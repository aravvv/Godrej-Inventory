import csv
import os
import re

LOCAL_CSV = os.path.join(os.path.dirname(__file__), "newList_with_dealer_price_deduplicated.csv")
FALLBACK_CSV = r"C:\Users\aravg\Downloads\priceListSync\newList_with_dealer_price_deduplicated.csv"
DEFAULT_CSV_PATH = LOCAL_CSV if os.path.exists(LOCAL_CSV) else FALLBACK_CSV

class Catalog:
    def __init__(self, csv_path=DEFAULT_CSV_PATH):
        self.csv_path = csv_path
        self.items = {}
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
                
                # Standardize key (uppercase)
                self.items[code.upper()] = {
                    "ln_code": code,
                    "description": row.get("Ln Description", "").strip(),
                    "sku": row.get("SKU ", row.get("SKU", "")).strip(),
                    "category": row.get("Category", "").strip(),
                    "sub_cat": row.get("Sub Cat", "").strip(),
                    "hsn_code": row.get("HSN Code", "").strip(),
                    "no_of_packets": row.get("No. Of Packets", "").strip(),
                    "consumer_price": self._parse_price(row.get("Consumer Price", "0")),
                    "dealer_price": self._parse_price(row.get("Dealer price", "0"))
                }
        print(f"[CATALOG] Loaded {len(self.items)} products into memory.")

    def _parse_price(self, val):
        try:
            cleaned = re.sub(r"[^\d\.]", "", str(val))
            return float(cleaned) if cleaned else 0.0
        except Exception:
            return 0.0

    def lookup(self, code):
        if not code:
            return None
        cleaned = code.strip().upper()
        # Direct match
        if cleaned in self.items:
            return self.items[cleaned]
        # Partial / normalized match (sometimes SD has varying case or extra whitespace)
        for k, v in self.items.items():
            if k == cleaned or cleaned in k:
                return v
        return None

# Singleton instance
catalog = Catalog()
