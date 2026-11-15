import requests
import base64
import json
import re
import time
import io
from PIL import Image, ImageOps, ImageFilter
from catalog import catalog
from gsheets_db import get_setting

import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "qwen/qwen3.8-27b"

# Persistent HTTP session for connection pooling (saves ~150-300ms TLS handshake per scan)
_http_session = requests.Session()

def get_groq_api_key():
    # 1. Check process environment (from .env or server config)
    key = os.getenv("GROQ_API_KEY")
    if key:
        return key.strip()
    # 2. Check database settings
    db_key = get_setting("groq_api_key", None)
    if db_key:
        return db_key.strip()
    raise ValueError("GROQ_API_KEY not configured. Please set it in .env or environment variables.")

def _normalize_ln_code(raw_code: str) -> str:
    """
    Cleans and normalizes a 15-character Godrej LN / Item Code (8 digits + SD + 5 digits).
    Fixes common OCR confusions (O->0, I/L->1) in the numeric prefix/suffix.
    """
    cleaned = re.sub(r"[^A-Z0-9]", "", str(raw_code or "").upper())
    m = re.search(r"(\d{8}SD\d{5})", cleaned)
    if m:
        return m.group(1)

    # Fix OCR letter-to-digit confusions around 'SD'
    m_sd = re.search(r"([A-Z0-9]{8})SD([A-Z0-9]{5})", cleaned)
    if m_sd:
        trans = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8"})
        prefix = m_sd.group(1).translate(trans)
        suffix = m_sd.group(2).translate(trans)
        candidate = f"{prefix}SD{suffix}"
        if re.match(r"^\d{8}SD\d{5}$", candidate):
            return candidate

    m2 = re.search(r"(\d{8}[A-Z]{2}\d{5})", cleaned)
    return m2.group(1) if m2 else cleaned

def prepare_image(image_bytes, max_dimension=600, quality=75, skip_thumb=False, sharpen=False):
    """
    Fixes EXIF orientation (crucial for iPhones), resizes to save tokens,
    and returns (base64_str, thumbnail_base64).
    """
    img = Image.open(io.BytesIO(image_bytes))
    # Correct EXIF rotation from iPhone Safari
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Generate normalized image for OCR
    ocr_img = img.copy()
    ocr_img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    if sharpen:
        ocr_img = ImageOps.autocontrast(ocr_img, cutoff=1)
        ocr_img = ocr_img.filter(ImageFilter.SHARPEN)
    buf = io.BytesIO()
    ocr_img.save(buf, format="JPEG", quality=quality, optimize=True)
    b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")

    if skip_thumb:
        return b64_str, ""

    # Generate small thumbnail for UI (150x150)
    thumb = img.copy()
    thumb.thumbnail((150, 150), Image.Resampling.LANCZOS)
    t_buf = io.BytesIO()
    thumb.save(t_buf, format="JPEG", quality=65)
    thumb_b64 = "data:image/jpeg;base64," + base64.b64encode(t_buf.getvalue()).decode("utf-8")

    return b64_str, thumb_b64

def call_groq_vision(prompt, b64_image, max_retries=2, timeout=12):
    api_key = get_groq_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL_NAME,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
            ]
        }],
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }

    for attempt in range(max_retries):
        try:
            res = _http_session.post(GROQ_API_URL, headers=headers, json=payload, timeout=timeout)
            if res.status_code == 200:
                data = res.json()
                return True, json.loads(data["choices"][0]["message"]["content"])
            elif res.status_code == 429:
                wait_time = 2 + attempt
                print(f"[GROQ 429] Rate limited. Waiting {wait_time}s before retry {attempt+1}/{max_retries}...")
                time.sleep(wait_time)
            else:
                return False, f"Groq Error ({res.status_code}): {res.text}"
        except Exception as e:
            if attempt == max_retries - 1:
                return False, str(e)
            time.sleep(1)

    return False, "Groq API busy. Please tap scan once again."

def parse_slip_image(image_bytes):
    """
    Parses a single cardboard slip photo.
    Returns: {
        success: bool,
        ln_code: str,
        catalog_match: bool,
        product: dict,
        thumbnail: str,
        error: str
    }
    """
    try:
        b64_img, thumb_b64 = prepare_image(image_bytes, max_dimension=768)

        prompt = """You are an expert Godrej warehouse label reader.
The photo is of a cardboard box packaging slip or label.
The text might be rotated (90 deg, 180 deg upside-down, or horizontal). Read it carefully regardless of orientation.

Your task:
1. Extract the PRODUCT CODE / Item Code. It is almost always a 15-character code consisting of 8 digits, followed by 'SD', followed by 5 digits (e.g., 30161803SD00344, 56101515SD00661, 56121403SD00226, 46171591SD00573).
2. Extract the printed Product Name / Description.
3. Extract Package Info if mentioned (e.g., '1 OF 4').

Respond strictly in JSON:
{
  "product_code": "30161803SD00344",
  "product_name": "...",
  "package_info": "..."
}"""

        success, result = call_groq_vision(prompt, b64_img)
        if not success:
            return {"success": False, "error": result, "thumbnail": thumb_b64}

        ln_code = _normalize_ln_code(result.get("product_code", ""))

        # Lookup in Master Catalog
        catalog_item = catalog.lookup(ln_code)

        if catalog_item:
            product_info = {
                "ln_code": catalog_item["ln_code"],
                "description": catalog_item["description"],
                "sku": catalog_item["sku"],
                "category": catalog_item["category"],
                "sub_cat": catalog_item["sub_cat"],
                "dealer_price": catalog_item["dealer_price"],
                "consumer_price": catalog_item["consumer_price"],
                "no_of_packets": catalog_item["no_of_packets"]
            }
            catalog_match = True
        else:
            product_info = {
                "ln_code": ln_code,
                "description": result.get("product_name", "Unlisted Product"),
                "sku": "NEW_SKU",
                "category": "General",
                "sub_cat": "",
                "dealer_price": 0.0,
                "consumer_price": 0.0,
                "no_of_packets": result.get("package_info", "1")
            }
            catalog_match = False

        return {
            "success": True,
            "ln_code": ln_code,
            "catalog_match": catalog_match,
            "product": product_info,
            "package_info": result.get("package_info", ""),
            "thumbnail": thumb_b64
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def _parse_qty_value(val, default=1):
    """Safely parses a quantity value like '3.0000', '3.0000 ECH', 3, or '3' into an integer."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        q = int(round(float(val)))
        return q if q > 0 else default
    s = str(val).strip().upper().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if m:
        q = int(round(float(m.group(1))))
        return q if q > 0 else default
    return default

def parse_bill_image(image_bytes):
    """
    Parses a photo of a Godrej Tax Invoice bill.
    Strictly extracts item quantities ONLY from the 'Quantity' (UOM / ECH) column
    and NEVER from the adjacent 'No of Pkg' column.
    Returns: {
        success: bool,
        invoice_no: str,
        date: str,
        items: list of resolved items with quantities,
        error: str
    }
    """
    try:
        b64_img, _ = prepare_image(
            image_bytes,
            max_dimension=1280,
            quality=85,
            skip_thumb=True,
            sharpen=True
        )

        prompt = """You are an expert Godrej Tax Invoice table parser.
Examine the product table in this Godrej Tax Invoice photo carefully.

CRITICAL COLUMN RULE — READ ONLY 'Quantity', NEVER 'No of Pkg':
In a Godrej Tax Invoice table, the columns from left to right are:
1. Sr No. (e.g. 1, 2, 3...)
2. Item Code / Item Description (15-character code like 56121403SD00226 on top, description below)
3. Sales Order No / Line Item No / Shipment No
4. HSN Code
5. Quantity / UOM -> THIS IS THE ONLY QUANTITY COLUMN! It shows a 4-decimal number on the top line (e.g., "3.0000", "1.0000", "2.0000") with "ECH" (Each) directly below it.
6. No of Pkg -> The column immediately to the right of Quantity shows the number of cardboard packages/boxes (an integer like 6, 6, 1, 2, with a total like 18 at the bottom). DO NOT use 'No of Pkg' as 'quantity'! For example, if Quantity is "3.0000 ECH" and No of Pkg is "6", then quantity MUST be 3 (NOT 6).
7. Ignore the bottom "Total" summary row.

Extract:
1. "invoice_no": Sales Invoice No (e.g. "10005TI11303977")
2. "date": Invoice Date (e.g. "30-07-2026")
3. "items": Every numbered line item row in order, with:
   - "item_code": 15-character code (e.g. "56121403SD00226")
   - "description": Item description text
   - "quantity_raw": Exact decimal number printed in the "Quantity" column above "ECH" (e.g. "3.0000", "1.0000", "2.0000")
   - "quantity": Integer value of the "Quantity" column ONLY (e.g. 3, 1, 2)
   - "no_of_pkg": Integer value in the adjacent "No of Pkg" column (recorded separately so you never confuse it with quantity)

Respond strictly as JSON:
{
  "invoice_no": "10005TI11303977",
  "date": "30-07-2026",
  "items": [
    {
      "item_code": "56121403SD00226",
      "description": "Transpose V2 Coffee Table Br",
      "quantity_raw": "3.0000",
      "quantity": 3,
      "no_of_pkg": 6
    }
  ]
}"""

        success, result = call_groq_vision(prompt, b64_img, max_retries=2, timeout=18)
        if not success:
            return {"success": False, "error": result}

        inv_no = result.get("invoice_no", "UNKNOWN")
        date_str = result.get("date", "")
        raw_items = result.get("items", [])

        merged_by_ln = {}
        ordered_lns = []

        for r in raw_items:
            raw_code = str(r.get("item_code", "")).strip().upper()
            if not raw_code or raw_code in ("TOTAL", "SUBTOTAL", "NONE", "NULL"):
                continue

            ln = _normalize_ln_code(raw_code)
            if not ln:
                continue

            # Prefer parsing quantity_raw (e.g. "3.0000") from the Quantity/ECH column
            if r.get("quantity_raw") is not None and str(r.get("quantity_raw")).strip() != "":
                qty = _parse_qty_value(r.get("quantity_raw"), default=1)
            else:
                qty = _parse_qty_value(r.get("quantity"), default=1)

            cat_item = catalog.lookup(ln)
            if cat_item:
                canonical_ln = cat_item["ln_code"]
                item_entry = {
                    "ln_code": canonical_ln,
                    "description": cat_item["description"],
                    "sku": cat_item["sku"],
                    "category": cat_item["category"],
                    "sub_cat": cat_item["sub_cat"],
                    "quantity": qty,
                    "dealer_price": cat_item["dealer_price"],
                    "consumer_price": cat_item["consumer_price"],
                    "catalog_match": True
                }
            else:
                canonical_ln = ln
                item_entry = {
                    "ln_code": canonical_ln,
                    "description": r.get("description", "Unlisted Item"),
                    "sku": "NEW_SKU",
                    "category": "General",
                    "sub_cat": "",
                    "quantity": qty,
                    "dealer_price": 0.0,
                    "consumer_price": 0.0,
                    "catalog_match": False
                }

            if canonical_ln in merged_by_ln:
                merged_by_ln[canonical_ln]["quantity"] += qty
            else:
                merged_by_ln[canonical_ln] = item_entry
                ordered_lns.append(canonical_ln)

        resolved_items = [merged_by_ln[k] for k in ordered_lns]

        return {
            "success": True,
            "invoice_no": inv_no,
            "date": date_str,
            "items": resolved_items,
            "total_items": len(resolved_items),
            "total_units": sum(it["quantity"] for it in resolved_items)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
