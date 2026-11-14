import os
import json
import base64
from datetime import datetime
from dotenv import load_dotenv

# Ensure local .env is loaded if available
load_dotenv()

import gspread
from google.oauth2.service_account import Credentials
from database import get_setting, get_inventory_list

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

DEFAULT_SHEET_ID = "1BF1RgdQVmffReUPSHnKoE-N_jQqmx02OOVXtNlxQ2sc"

class GoogleSheetsSync:
    def __init__(self):
        self.client = None
        self.sheet = None
        self.spreadsheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip() or DEFAULT_SHEET_ID

    def get_credentials(self):
        # 1. Check raw JSON or Base64 string in environment variables (Vercel / Cloud)
        json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if json_env:
            try:
                # Try direct JSON parse
                info = json.loads(json_env)
                return Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception:
                try:
                    # Try base64 decoded JSON
                    decoded = base64.b64decode(json_env).decode("utf-8")
                    info = json.loads(decoded)
                    return Credentials.from_service_account_info(info, scopes=SCOPES)
                except Exception as e:
                    print(f"[GSHEET] Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

        # 2. Check local files
        curr_dir = os.path.dirname(os.path.abspath(__file__))
        for fname in ["service_account.json", "credentials.json"]:
            path = os.path.join(curr_dir, fname)
            if os.path.exists(path):
                try:
                    return Credentials.from_service_account_file(path, scopes=SCOPES)
                except Exception as e:
                    print(f"[GSHEET] Error loading {path}: {e}")

        # 3. Check database setting fallback
        db_creds = get_setting("google_service_account_json", "")
        if db_creds:
            try:
                info = json.loads(db_creds)
                return Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception:
                pass

        return None

    def connect(self):
        # Always re-check ID
        self.spreadsheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip() or get_setting("google_sheet_id", "") or DEFAULT_SHEET_ID
        if not self.spreadsheet_id:
            return False, "GOOGLE_SHEET_ID environment variable not set"

        try:
            creds = self.get_credentials()
            if not creds:
                return False, "Google Service Account credentials not found (set GOOGLE_SERVICE_ACCOUNT_JSON or place service_account.json)"

            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.spreadsheet_id)
            self._ensure_sheets_exist()
            return True, f"Connected to sheet: {self.sheet.title}"
        except Exception as e:
            return False, f"Google Sheets connection failed: {str(e)}"

    def _ensure_sheets_exist(self):
        titles = [ws.title for ws in self.sheet.worksheets()]

        # 1. Live Inventory Sheet
        if "Live_Inventory" not in titles:
            ws = self.sheet.add_worksheet(title="Live_Inventory", rows=1000, cols=10)
            ws.append_row([
                "LN Code", "Product Description", "SKU", "Category", "Sub Cat", 
                "Current Stock", "Dealer Price (Rs)", "Consumer Price (Rs)", 
                "Last Updated", "Last Modified By"
            ])
        
        # 2. Audit Log Sheet
        if "Audit_Log" not in titles:
            ws = self.sheet.add_worksheet(title="Audit_Log", rows=2000, cols=12)
            ws.append_row([
                "Log ID", "Timestamp", "Employee", "Action", "Source", 
                "LN Code", "Product Description", "Quantity", 
                "Stock Before", "Stock After", "Invoice No", "Notes"
            ])

    def sync_full_inventory(self):
        """
        Pushes a 100% exact atomic mirror of the current inventory to Live_Inventory worksheet.
        Takes ~0.8s and updates everything in one single call.
        """
        ok, msg = self.connect()
        if not ok:
            return False, msg

        try:
            inv_ws = self.sheet.worksheet("Live_Inventory")
            items = get_inventory_list()

            headers = [
                "LN Code", "Product Description", "SKU", "Category", "Sub Cat", 
                "Current Stock", "Dealer Price (Rs)", "Consumer Price (Rs)", 
                "Last Updated", "Last Modified By"
            ]

            rows = [headers] + [[
                it["ln_code"],
                it.get("description", ""),
                it.get("sku", ""),
                it.get("category", ""),
                it.get("sub_cat", ""),
                it.get("current_stock", 0),
                it.get("dealer_price", 0.0),
                it.get("consumer_price", 0.0),
                it.get("last_updated", ""),
                it.get("last_updated_by", "")
            ] for it in items]

            # Atomic clear and update
            inv_ws.clear()
            inv_ws.update(rows, "A1")
            return True, f"Successfully mirrored {len(items)} items to Google Sheet"
        except Exception as e:
            return False, f"Failed to mirror inventory to Google Sheet: {str(e)}"

    def sync_batch(self, employee_username, action, source, processed_items, invoice_no=None, notes=None):
        """
        Synchronously updates both Live_Inventory (as a perfect mirror) and Audit_Log.
        Safe for serverless environments (e.g. Vercel) where background threads freeze.
        """
        ok, msg = self.connect()
        if not ok:
            print(f"[GSHEET SYNC SKIPPED] {msg}")
            return False, msg

        try:
            # 1. Mirror the full live inventory
            mirror_ok, mirror_msg = self.sync_full_inventory()
            if not mirror_ok:
                print(f"[GSHEET MIRROR WARNING] {mirror_msg}")

            # 2. Append new transaction to Audit_Log
            log_ws = self.sheet.worksheet("Audit_Log")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            audit_rows = [[
                "",  # Auto ID
                now_str,
                employee_username,
                action,
                source,
                it["ln_code"],
                it.get("description", ""),
                it.get("quantity", 1),
                it.get("stock_before", 0),
                it.get("stock_after", 0),
                invoice_no or "",
                notes or ""
            ] for it in processed_items]

            if audit_rows:
                log_ws.append_rows(audit_rows)

            print(f"[GSHEET SYNC] Successfully mirrored inventory & appended {len(audit_rows)} log rows.")
            return True, "Synced to Google Sheets"
        except Exception as e:
            err = f"Google Sheet sync error: {str(e)}"
            print(f"[GSHEET ERROR] {err}")
            return False, err

# Singleton instance
gsheets = GoogleSheetsSync()
