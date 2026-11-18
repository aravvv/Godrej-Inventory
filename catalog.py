import csv
import os
import re
import difflib

LOCAL_CSV = os.path.join(os.path.dirname(__file__), "newList_with_dealer_price_deduplicated.csv")
FALLBACK_CSV = r"C:\Users\aravg\Downloads\priceListSync\newList_with_dealer_price_deduplicated.csv"
DEFAULT_CSV_PATH = LOCAL_CSV if os.path.exists(LOCAL_CSV) else FALLBACK_CSV

class Catalog:
    def __init__(self, csv_path=DEFAULT_CSV_PATH):
        self.csv_path = csv_path
        self.items = {}
        self._desc_tokens = [] # List of (ln_code, description, set_of_tokens, lower_clean_desc)
        self.load()

    def load(self):
        if not os.path.exists(self.csv_path):
            print(f"[CATALOG WARNING] CSV file not found at: {self.csv_path}")
            return

        with open(self.csv_path, mode="r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_code = row.get("Ln Code", "")
                if not raw_code:
                    continue
                code = raw_code.strip()
                if not code or code == "XXXXX":
                    continue
                
                desc = row.get("Ln Description", "").strip()
                code_up = code.upper()

                # Standardize key (uppercase)
                item_dict = {
                    "ln_code": code,
                    "description": desc,
                    "sku": row.get("SKU ", row.get("SKU", "")).strip(),
                    "category": row.get("Category", "").strip(),
                    "sub_cat": row.get("Sub Cat", "").strip(),
                    "hsn_code": row.get("HSN Code", "").strip(),
                    "no_of_packets": row.get("No. Of Packets", "").strip(),
                    "consumer_price": self._parse_price(row.get("Consumer Price", "0")),
                    "dealer_price": self._parse_price(row.get("Dealer price", "0"))
                }
                self.items[code_up] = item_dict

                if desc:
                    desc_clean = re.sub(r"[^a-z0-9 ]", " ", desc.lower())
                    tokens = set(desc_clean.split())
                    self._desc_tokens.append((code_up, desc, tokens, desc_clean))

        print(f"[CATALOG] Loaded {len(self.items)} products into memory.")

    def _parse_price(self, val):
        try:
            cleaned = re.sub(r"[^\d\.]", "", str(val))
            return float(cleaned) if cleaned else 0.0
        except Exception:
            return 0.0

    def lookup(self, code_or_name):
        if not code_or_name:
            return None
        cleaned = str(code_or_name).strip().upper()
        # 1. Direct LN code match
        if cleaned in self.items:
            return self.items[cleaned]
        # 2. Substring LN match
        for k, v in self.items.items():
            if k == cleaned or cleaned in k:
                return v
        # 3. Fallback to name matching if code not found
        match_res = self.match_name(code_or_name, min_score=0.55)
        if match_res:
            return match_res["item"]
        return None

    def match_name(self, query: str, min_score: float = 0.45) -> dict:
        """
        Intelligently maps an un-coded product name or invoice description
        to the best matching official Godrej LN code and catalog record.
        """
        if not query:
            return None
        q_raw = str(query).strip()
        q_clean = re.sub(r"[^a-z0-9 ]", " ", q_raw.lower())
        q_tokens = set(q_clean.split())
        if not q_tokens:
            return None

        best_code = None
        best_desc = None
        best_score = 0.0

        for code_up, desc, d_tokens, desc_clean in self._desc_tokens:
            if not d_tokens:
                continue
            common = q_tokens.intersection(d_tokens)
            if not common:
                continue

            token_match = len(common) / len(q_tokens)
            ratio = difflib.SequenceMatcher(None, q_clean, desc_clean).ratio()

            if token_match >= 0.95:
                score = 0.6 + 0.4 * ratio
            elif token_match >= 0.5:
                score = 0.4 * token_match + 0.6 * ratio
            else:
                score = 0.3 * token_match + 0.7 * ratio

            if score > best_score:
                best_score = score
                best_code = code_up
                best_desc = desc
                if best_score >= 0.98:
                    break

        if best_code and best_score >= min_score:
            return {
                "item": self.items[best_code],
                "score": round(best_score, 3),
                "matched_desc": best_desc,
                "input_query": q_raw
            }
        return None

# Singleton instance
catalog = Catalog()
