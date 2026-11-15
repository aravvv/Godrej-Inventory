import requests
import base64
import json
import re
import time
import io
from PIL import Image, ImageOps
from catalog import catalog
from gsheets_db import get_setting

import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "qwen/qwen3.8-27b"

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

def prepare_image(image_bytes, max_dimension=600, quality=75):
    """
    Fixes EXIF orientation (crucial for iPhones), resizes to save tokens,
    and returns (base64_str, thumbnail_base64).
    """
    img = Image.open(io.BytesIO(image_bytes))
    # Correct EXIF rotation from iPhone Safari
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Generate full-sized normalized image for OCR (max 600px for speed & token efficiency)
    ocr_img = img.copy()
    ocr_img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    ocr_img.save(buf, format="JPEG", quality=quality)
    b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")

    # Generate small thumbnail for UI (150x150)
    thumb = img.copy()
    thumb.thumbnail((150, 150), Image.Resampling.LANCZOS)
    t_buf = io.BytesIO()
    thumb.save(t_buf, format="JPEG", quality=65)
    thumb_b64 = "data:image/jpeg;base64," + base64.b64encode(t_buf.getvalue()).decode("utf-8")

    return b64_str, thumb_b64

def call_groq_vision(prompt, b64_image, max_retries=2):
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
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    for attempt in range(max_retries):
        try:
            res = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=8)
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

        raw_code = str(result.get("product_code", "")).strip().upper()
        # Clean with regex
        match = re.search(r"\b(\d{8}SD\d{5})\b", raw_code)
        if match:
            ln_code = match.group(1)
        else:
            # Fallback search anywhere in string
            m2 = re.search(r"(\d{8}[A-Z]{2}\d{5})", raw_code)
            ln_code = m2.group(1) if m2 else raw_code

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

def parse_bill_image(image_bytes):
    """
    Parses a photo of a Godrej Tax Invoice bill.
    Returns: {
        success: bool,
        invoice_no: str,
        date: str,
        items: list of resolved items with quantities,
        error: str
    }
    """
    try:
        b64_img, thumb_b64 = prepare_image(image_bytes, max_dimension=1024, quality=85)

        prompt = """You are an expert Godrej warehouse invoice parser.
Look at this photo of a Godrej Tax Invoice bill.
Extract:
1. Sales Invoice No (e.g. 10005TI11303977)
2. Invoice Date (e.g. 30-07-2026)
3. The table of products: For every line item, extract:
   - item_code (the 15-character code like 56121403SD00226, 30161803SD00835)
   - description (item name)
   - quantity (the number in the Quantity column, integer)

Respond strictly as JSON:
{
  "invoice_no": "...",
  "date": "...",
  "items": [
    {"item_code": "56121403SD00226", "quantity": 3},
    ...
  ]
}"""

        success, result = call_groq_vision(prompt, b64_img)
        if not success:
            return {"success": False, "error": result}

        inv_no = result.get("invoice_no", "UNKNOWN")
        date_str = result.get("date", "")
        raw_items = result.get("items", [])

        resolved_items = []
        for r in raw_items:
            raw_code = str(r.get("item_code", "")).strip().upper()
            m = re.search(r"\b(\d{8}SD\d{5})\b", raw_code)
            ln = m.group(1) if m else raw_code
            try:
                qty = int(float(r.get("quantity", 1)))
            except Exception:
                qty = 1

            cat_item = catalog.lookup(ln)
            if cat_item:
                resolved_items.append({
                    "ln_code": cat_item["ln_code"],
                    "description": cat_item["description"],
                    "sku": cat_item["sku"],
                    "category": cat_item["category"],
                    "sub_cat": cat_item["sub_cat"],
                    "quantity": qty,
                    "dealer_price": cat_item["dealer_price"],
                    "consumer_price": cat_item["consumer_price"],
                    "catalog_match": True
                })
            else:
                resolved_items.append({
                    "ln_code": ln,
                    "description": r.get("description", "Unlisted Item"),
                    "sku": "NEW_SKU",
                    "category": "General",
                    "sub_cat": "",
                    "quantity": qty,
                    "dealer_price": 0.0,
                    "consumer_price": 0.0,
                    "catalog_match": False
                })

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
