import os
import json
import gspread
from google.oauth2.service_account import Credentials
from database import get_setting

# Google Sheets Scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

class GoogleSheetsSync:
    def __init__(self):
        self.client = None
        self.sheet = None
        self.spreadsheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()

    def get_credentials(self):
        # 1. Check raw JSON string in environment (ideal for Hugging Face Secrets)
        json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if json_env:
            try:
                info = json.loads(json_env)
                return Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception as e:
                print(f"[GSHEET] Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

        # 2. Check local file (e.g. credentials.json)
        file_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
        if os.path.exists(file_path):
            return Credentials.from_service_account_file(file_path, scopes=SCOPES)

        return None

    def connect(self):
        if not self.spreadsheet_id:
            self.spreadsheet_id = get_setting("google_sheet_id", "")

        if not self.spreadsheet_id:
            return False, "GOOGLE_SHEET_ID not configured"

        try:
            creds = self.get_credentials()
            if not creds:
                return False, "Google Service Account credentials not found"

            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.spreadsheet_id)
            self._ensure_sheets_exist()
            return True, "Connected to Google Sheet successfully"
        except Exception as e:
            return False, str(e)

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

    def sync_batch(self, employee_username, action, source, processed_items, invoice_no=None, notes=None):
        """
        Syncs a committed batch to both Live_Inventory and Audit_Log sheets.
        Runs asynchronously/safely without blocking the user.
        """
        ok, msg = self.connect()
        if not ok:
            print(f"[GSHEET SYNC SKIPPED] {msg}")
            return False

        try:
            inv_ws = self.sheet.worksheet("Live_Inventory")
            log_ws = self.sheet.worksheet("Audit_Log")

            # Load all existing LN codes from column A
            ln_codes = inv_ws.col_values(1)

            now_str = str(os.popen("date /t").read().strip()) if os.name == 'nt' else ""

            for it in processed_items:
                ln = it["ln_code"]
                qty = it["quantity"]
                stock_after = it["stock_after"]
                stock_before = it["stock_before"]

                # Check if LN code exists in Live_Inventory
                if ln in ln_codes:
                    row_idx = ln_codes.index(ln) + 1
                    # Update Current Stock (Col 6), Last Updated (Col 9), Modified By (Col 10)
                    inv_ws.update_cell(row_idx, 6, stock_after)
                    inv_ws.update_cell(row_idx, 9, "Just Now")
                    inv_ws.update_cell(row_idx, 10, employee_username)
                else:
                    # Append new row
                    inv_ws.append_row([
                        ln,
                        it.get("description", ""),
                        it.get("sku", ""),
                        it.get("category", ""),
                        it.get("sub_cat", ""),
                        stock_after,
                        it.get("dealer_price", 0.0),
                        it.get("consumer_price", 0.0),
                        "Just Now",
                        employee_username
                    ])
                    ln_codes.append(ln)

                # Append to Audit Log
                log_ws.append_row([
                    "",  # Auto ID
                    "Now",
                    employee_username,
                    action,
                    source,
                    ln,
                    it.get("description", ""),
                    qty,
                    stock_before,
                    stock_after,
                    invoice_no or "",
                    notes or ""
                ])

            print(f"[GSHEET SYNC] Successfully synced {len(processed_items)} items to Google Sheets.")
            return True
        except Exception as e:
            print(f"[GSHEET SYNC ERROR] {e}")
            return False

# Singleton instance
gsheets = GoogleSheetsSync()
