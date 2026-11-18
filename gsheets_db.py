import os
import json
import base64
import hashlib
import sqlite3
import threading
import time
import re
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# India Standard Time (IST, UTC+05:30) for Godrej India operations
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now() -> datetime:
    return datetime.now(IST)

def get_ist_now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now(IST).strftime(fmt)

import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from catalog import catalog

# Load .env from project root if present
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

DEFAULT_SHEET_ID = "1BF1RgdQVmffReUPSHnKoE-N_jQqmx02OOVXtNlxQ2sc"
CACHE_TTL_SECONDS = 60
MAX_BACKUP_HISTORY_ROWS = 3000

# Exact worksheet schemas
INVENTORY_HEADERS = [
    "LN Code", "Product Description", "Category", "Sub Cat",
    "Current Stock", "Consumer Price (Rs)",
    "Last Updated", "Last Modified By"
]

AUDIT_HEADERS = [
    "Log ID", "Timestamp", "Employee", "Action", "Source",
    "LN Code", "Product Description", "Quantity",
    "Stock Before", "Stock After", "Invoice No", "Notes"
]

USERS_HEADERS = [
    "ID", "Username", "Password Hash", "Full Name", "Role", "Is Active", "Created At"
]

SETTINGS_HEADERS = [
    "Key", "Value", "Updated At"
]

BACKUP_HISTORY_HEADERS = [
    "Backup ID", "Backup Date", "LN Code", "Product Description",
    "Category", "Sub Cat", "Current Stock",
    "Consumer Price (Rs)", "Last Updated By"
]


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _to_int(val, default=0) -> int:
    try:
        if val is None or val == "":
            return default
        cleaned = re.sub(r"[^\d\-]", "", str(val))
        return int(cleaned) if cleaned else default
    except Exception:
        return default


def _to_float(val, default=0.0) -> float:
    try:
        if val is None or val == "":
            return default
        cleaned = re.sub(r"[^\d\.\-]", "", str(val))
        return float(cleaned) if cleaned else default
    except Exception:
        return default


class GSheetsPrimaryDB:
    """
    Google Sheets Primary Database with In-Memory Cache and Automated Backup Snapshots.
    Designed for serverless deployments (Vercel) where local disk (/tmp) is ephemeral.
    """

    def __init__(self, spreadsheet_id: str = None):
        self._lock = threading.RLock()
        self.client = None
        self.sheet = None
        self._sheets_verified = False
        self._ws_cache = {}
        self.spreadsheet_id = (
            spreadsheet_id
            or os.getenv("GOOGLE_SHEET_ID", "").strip()
            or DEFAULT_SHEET_ID
        )

        # In-memory TTL cache
        self._cache = {
            "inventory": {"data": [], "by_ln": {}, "ts": 0.0, "synced_at": None},
            "audit_logs": {"data": [], "ts": 0.0},
            "users": {"data": [], "ts": 0.0},
            "settings": {"data": {}, "ts": 0.0},
        }

    # ----------------- CREDENTIALS & CONNECTION -----------------
    def _get_credentials(self):
        # 1. Environment variable (raw JSON or Base64) - ideal for Vercel
        json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if json_env:
            try:
                info = json.loads(json_env)
                return Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception:
                try:
                    decoded = base64.b64decode(json_env).decode("utf-8")
                    info = json.loads(decoded)
                    return Credentials.from_service_account_info(info, scopes=SCOPES)
                except Exception as e:
                    print(f"[GSHEET DB] Invalid GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

        # 2. Local JSON files in project root or current dir
        for base in [ROOT_DIR, os.path.dirname(os.path.abspath(__file__))]:
            for fname in ["service_account.json", "credentials.json"]:
                fpath = os.path.join(base, fname)
                if os.path.exists(fpath):
                    try:
                        return Credentials.from_service_account_file(fpath, scopes=SCOPES)
                    except Exception as e:
                        print(f"[GSHEET DB] Failed loading {fpath}: {e}")

        return None

    def connect(self, force_reconnect: bool = False):
        with self._lock:
            if not force_reconnect and self.client and self.sheet and self._sheets_verified:
                return True, f"Connected to {self.sheet.title}"

            self.spreadsheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip() or DEFAULT_SHEET_ID
            if not self.spreadsheet_id:
                return False, "GOOGLE_SHEET_ID not configured"

            try:
                creds = self._get_credentials()
                if not creds:
                    return False, "Google Service Account credentials not found"

                self.client = gspread.authorize(creds)
                self.sheet = self.client.open_by_key(self.spreadsheet_id)
                self._ensure_worksheets_exist()
                self._sheets_verified = True
                return True, f"Connected to {self.sheet.title}"
            except Exception as e:
                self.client = None
                self.sheet = None
                self._ws_cache = {}
                self._sheets_verified = False
                return False, f"Google Sheets connection failed: {str(e)}"

    def _get_ws(self, title: str):
        with self._lock:
            ok, msg = self.connect()
            if not ok:
                raise RuntimeError(msg)
            if title not in self._ws_cache:
                self._ws_cache[title] = self.sheet.worksheet(title)
            return self._ws_cache[title]

    # ----------------- RETRY & WORKSHEET MIGRATION -----------------
    def _is_transient_error(self, exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
        if status in (429, 500, 502, 503):
            return True
        msg = str(exc).lower()
        return any(
            tok in msg
            for tok in (
                "429", "500", "502", "503",
                "quota", "rate limit", "timed out", "timeout",
                "connection reset", "temporarily unavailable"
            )
        )

    def _retry_api(self, fn, *args, **kwargs):
        last_exc = None
        for attempt in range(3):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and self._is_transient_error(exc):
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise
        raise last_exc

    def _ensure_worksheets_exist(self):
        worksheets = {ws.title: ws for ws in self._retry_api(self.sheet.worksheets)}
        self._ws_cache = worksheets.copy()

        def ensure_tab(title, headers, rows=1000):
            created_now = False
            if title not in worksheets:
                ws = self._retry_api(self.sheet.add_worksheet, title=title, rows=rows, cols=len(headers))
                self._retry_api(ws.append_row, headers)
                worksheets[title] = ws
                self._ws_cache[title] = ws
                created_now = True
            return worksheets[title], created_now

        def migrate_tab_schema(ws, target_headers):
            """Non-destructively migrates worksheet columns by header name to target_headers."""
            raw = self._retry_api(ws.get_all_values)
            if not raw:
                self._retry_api(ws.append_row, target_headers)
                return
            current_headers = [str(h).strip() for h in raw[0]]
            if current_headers == target_headers:
                return

            header_map = {}
            for idx, h in enumerate(current_headers):
                key = h.lower()
                if key and key not in header_map:
                    header_map[key] = idx

            alias_map = {
                "ln code": ["ln_code"],
                "product description": ["description"],
                "sub cat": ["sub_cat"],
                "current stock": ["stock", "current_stock"],
                "consumer price (rs)": ["consumer price", "consumer_price"],
                "last updated": ["last_updated"],
                "last modified by": ["last updated by", "last_updated_by"],
                "last updated by": ["last modified by", "last_updated_by"],
            }

            col_sources = []
            for th in target_headers:
                key = th.lower()
                src_idx = header_map.get(key)
                if src_idx is None:
                    for alias in alias_map.get(key, []):
                        if alias in header_map:
                            src_idx = header_map[alias]
                            break
                col_sources.append(src_idx)

            migrated_rows = [target_headers]
            for r in raw[1:]:
                if not r or not any(str(c).strip() for c in r):
                    continue
                new_row = [
                    r[src_idx] if (src_idx is not None and src_idx < len(r)) else ""
                    for src_idx in col_sources
                ]
                migrated_rows.append(new_row)

            self._retry_api(ws.clear)
            self._retry_api(ws.update, migrated_rows, "A1")
            try:
                if getattr(ws, "col_count", len(target_headers)) != len(target_headers):
                    ws.resize(cols=len(target_headers))
            except Exception:
                pass

        inv_ws, inv_created = ensure_tab("Live_Inventory", INVENTORY_HEADERS, rows=2000)
        ensure_tab("Audit_Log", AUDIT_HEADERS, rows=5000)
        users_ws, users_created = ensure_tab("Users", USERS_HEADERS, rows=200)
        ensure_tab("Settings", SETTINGS_HEADERS, rows=100)
        latest_ws, latest_created = ensure_tab("Backup_Latest", INVENTORY_HEADERS, rows=2000)
        hist_ws, hist_created = ensure_tab("Backup_History", BACKUP_HISTORY_HEADERS, rows=5000)

        if not inv_created:
            migrate_tab_schema(inv_ws, INVENTORY_HEADERS)
        if not latest_created:
            migrate_tab_schema(latest_ws, INVENTORY_HEADERS)
        if not hist_created:
            migrate_tab_schema(hist_ws, BACKUP_HISTORY_HEADERS)

        # Ensure Users sheet has at least admin seeded (or migrated from local sqlite once)
        existing_users = self._retry_api(users_ws.get_all_values)
        if users_created or len(existing_users) <= 1:
            self._seed_initial_users(users_ws)

    def _seed_initial_users(self, users_ws):
        seed_rows = []
        now_str = get_ist_now_str()
        local_sqlite = os.path.join(ROOT_DIR, "inventory.db")
        seen_usernames = set()

        # Migrate any existing local SQLite accounts smoothly on initial Users tab creation
        if os.path.exists(local_sqlite):
            try:
                conn = sqlite3.connect(local_sqlite)
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT id, username, password_hash, full_name, role, is_active, created_at FROM users ORDER BY id ASC").fetchall()
                conn.close()
                for r in rows:
                    uname = r["username"].strip().lower()
                    seen_usernames.add(uname)
                    seed_rows.append([
                        r["id"], uname, r["password_hash"], r["full_name"],
                        r["role"], r["is_active"], r["created_at"] or now_str
                    ])
            except Exception as e:
                print(f"[GSHEET DB] Local user migration skipped: {e}")

        if "admin" not in seen_usernames:
            next_id = len(seed_rows) + 1
            seed_rows.insert(0, [
                next_id, "admin", hash_password("admin123"), "Administrator", "admin", 1, now_str
            ])

        if seed_rows:
            self._retry_api(users_ws.append_rows, seed_rows)

    def _invalidate_cache(self, *keys):
        if not keys:
            keys = ("inventory", "audit_logs", "users", "settings")
        for k in keys:
            if k in self._cache:
                self._cache[k]["ts"] = 0.0

    # ----------------- SYNC ENGINE -----------------
    def sync_from_sheets(self, include_logs: bool = False):
        """
        Pulls fresh state directly from Google Sheets into memory cache.
        Called automatically on every login, app refresh, and manual refresh.
        """
        with self._lock:
            self._invalidate_cache()
            inv = self.get_inventory_list(force_refresh=True)
            users = self.get_all_users(force_refresh=True)
            settings = self.get_all_settings(force_refresh=True)
            if include_logs:
                self.get_audit_logs(force_refresh=True)

            # Check if automatic daily backup needs to run
            try:
                self.maybe_run_daily_backup()
            except Exception as e:
                print(f"[AUTO BACKUP WARNING] {e}")

            return {
                "synced_at": self._cache["inventory"]["synced_at"],
                "inventory_count": len(inv),
                "total_units": sum(max(0, x["current_stock"]) for x in inv),
                "users_count": len(users),
                "sheet_title": self.sheet.title if self.sheet else "",
                "sheet_id": self.spreadsheet_id,
                "last_backup_at": settings.get("last_backup_at", "Never")
            }

    # ----------------- SETTINGS -----------------
    def get_all_settings(self, force_refresh: bool = False) -> dict:
        with self._lock:
            now = time.time()
            cached = self._cache["settings"]
            if not force_refresh and cached["ts"] > 0 and (now - cached["ts"]) < CACHE_TTL_SECONDS:
                return dict(cached["data"])

            ws = self._get_ws("Settings")
            rows = self._retry_api(ws.get_all_values)
            data = {}
            for r in rows[1:]:
                if len(r) >= 2 and r[0].strip():
                    data[r[0].strip()] = r[1]

            self._cache["settings"] = {"data": data, "ts": now}
            return dict(data)

    def get_setting(self, key: str, default=None):
        try:
            settings = self.get_all_settings()
            return settings.get(key, default)
        except Exception:
            return default

    def set_setting(self, key: str, value: str):
        with self._lock:
            ws = self._get_ws("Settings")
            rows = self._retry_api(ws.get_all_values)
            now_str = get_ist_now_str()
            key_clean = key.strip()

            found_row = None
            for idx, r in enumerate(rows[1:], start=2):
                if r and r[0].strip() == key_clean:
                    found_row = idx
                    break

            if found_row:
                self._retry_api(ws.update, [[key_clean, value, now_str]], f"A{found_row}:C{found_row}")
            else:
                self._retry_api(ws.append_row, [key_clean, value, now_str])

            self._cache["settings"]["data"][key_clean] = value
            self._cache["settings"]["ts"] = time.time()

            # Propagate Groq key immediately to process env if updated via UI
            if key_clean == "groq_api_key" and value:
                os.environ["GROQ_API_KEY"] = value.strip()

    # ----------------- USER MANAGEMENT -----------------
    def get_all_users(self, force_refresh: bool = False) -> list:
        with self._lock:
            now = time.time()
            cached = self._cache["users"]
            if not force_refresh and cached["ts"] > 0 and (now - cached["ts"]) < 60:
                return list(cached["data"])

            ws = self._get_ws("Users")
            rows = self._retry_api(ws.get_all_values)
            users = []
            for row_idx, r in enumerate(rows[1:], start=2):
                if not r or len(r) < 5 or not r[1].strip():
                    continue
                users.append({
                    "id": _to_int(r[0], row_idx - 1),
                    "username": r[1].strip().lower(),
                    "password_hash": r[2].strip(),
                    "full_name": r[3].strip(),
                    "role": r[4].strip().lower() or "employee",
                    "is_active": _to_int(r[5] if len(r) > 5 else 1, 1),
                    "created_at": r[6].strip() if len(r) > 6 else "",
                    "_row_idx": row_idx
                })

            users.sort(key=lambda u: u["id"], reverse=True)
            self._cache["users"] = {"data": users, "ts": now}
            return list(users)

    def authenticate_user(self, username: str, password: str):
        uname = (username or "").strip().lower()
        hashed = hash_password(password or "")
        # Always pull fresh Users from Google Sheet on login
        users = self.get_all_users(force_refresh=True)
        for u in users:
            if u["username"] == uname and u["password_hash"] == hashed and u["is_active"] == 1:
                return {
                    "id": u["id"],
                    "username": u["username"],
                    "full_name": u["full_name"],
                    "role": u["role"],
                    "is_active": u["is_active"]
                }
        return None

    def create_user(self, username: str, password: str, full_name: str, role: str = "employee"):
        with self._lock:
            uname = username.strip().lower()
            if not uname or not password or not full_name:
                return False, "All user fields are required"
            if role not in ("admin", "employee"):
                return False, "Invalid role"

            users = self.get_all_users(force_refresh=True)
            if any(u["username"] == uname for u in users):
                return False, "Username already exists"

            next_id = max((u["id"] for u in users), default=0) + 1
            now_str = get_ist_now_str()
            ws = self._get_ws("Users")
            self._retry_api(ws.append_row, [
                next_id, uname, hash_password(password), full_name.strip(), role, 1, now_str
            ])
            self._invalidate_cache("users")
            return True, "User created permanently in Google Sheets"

    def delete_user(self, user_id: int):
        with self._lock:
            users = self.get_all_users(force_refresh=True)
            target = next((u for u in users if u["id"] == int(user_id)), None)
            if not target:
                return False, "User not found"
            if target["username"] == "admin":
                return False, "Cannot delete primary admin account"

            ws = self._get_ws("Users")
            self._retry_api(ws.delete_rows, target["_row_idx"])
            self._invalidate_cache("users")
            return True, "User deleted permanently from Google Sheets"

    def update_user_password(self, user_id: int, new_password: str):
        with self._lock:
            pwd = (new_password or "").strip()
            if len(pwd) < 4:
                return False, "Password must be at least 4 characters"

            users = self.get_all_users(force_refresh=True)
            target = next((u for u in users if u["id"] == int(user_id)), None)
            if not target:
                return False, "User account not found"

            ws = self._get_ws("Users")
            new_hash = hash_password(pwd)
            self._retry_api(ws.update, [[new_hash]], f"C{target['_row_idx']}")
            self._invalidate_cache("users")
            return True, f"Password updated for @{target['username']} in Google Sheets"

    # ----------------- INVENTORY -----------------
    def get_inventory_list(self, search: str = "", force_refresh: bool = False, include_prices: bool = True) -> list:
        with self._lock:
            now = time.time()
            cached = self._cache["inventory"]

            if force_refresh or cached["ts"] == 0 or (now - cached["ts"]) >= CACHE_TTL_SECONDS:
                ws = self._get_ws("Live_Inventory")
                raw = self._retry_api(ws.get_all_values)
                items = []
                by_ln = {}

                if len(raw) > 1:
                    headers = [h.strip().lower() for h in raw[0]]
                    # Resolve column positions safely from header names
                    def col_idx(candidates, fallback):
                        for cand in candidates:
                            if cand in headers:
                                return headers.index(cand)
                        return fallback

                    c_ln = col_idx(["ln code", "ln_code"], 0)
                    c_desc = col_idx(["product description", "description"], 1)
                    c_cat = col_idx(["category"], 2)
                    c_sub = col_idx(["sub cat", "sub_cat"], 3)
                    c_stock = col_idx(["current stock", "stock", "current_stock"], 4)
                    c_cp = col_idx(["consumer price (rs)", "consumer price", "consumer_price"], 5)
                    c_upd = col_idx(["last updated", "last_updated"], 6)
                    c_by = col_idx(["last modified by", "last_updated_by"], 7)

                    def cell(row, idx, default=""):
                        return str(row[idx]).strip() if idx < len(row) and row[idx] is not None else default

                    for row_num, r in enumerate(raw[1:], start=2):
                        ln = cell(r, c_ln).upper()
                        if not ln:
                            continue
                        cat_entry = catalog.lookup(ln)
                        dealer_price = _to_float(cat_entry.get("dealer_price"), 0.0) if cat_entry else 0.0
                        consumer_price = _to_float(cell(r, c_cp, "0"), 0.0)
                        if consumer_price <= 0 and cat_entry:
                            consumer_price = _to_float(cat_entry.get("consumer_price"), 0.0)

                        item = {
                            "ln_code": ln,
                            "description": cell(r, c_desc),
                            "category": cell(r, c_cat),
                            "sub_cat": cell(r, c_sub),
                            "current_stock": _to_int(cell(r, c_stock, "0"), 0),
                            "dealer_price": dealer_price,
                            "consumer_price": consumer_price,
                            "last_updated": cell(r, c_upd),
                            "last_updated_by": cell(r, c_by),
                            "_row_idx": row_num
                        }
                        items.append(item)
                        by_ln[ln] = item

                # Sort newest updated first cleanly
                items.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
                self._cache["inventory"] = {
                    "data": items,
                    "by_ln": by_ln,
                    "ts": now,
                    "synced_at": get_ist_now_str()
                }

            result = list(self._cache["inventory"]["data"])
            if search and search.strip():
                q = search.strip().lower()
                result = [
                    it for it in result
                    if q in it["ln_code"].lower()
                    or q in (it["description"] or "").lower()
                    or q in (it["category"] or "").lower()
                    or q in (it["sub_cat"] or "").lower()
                ]
            if include_prices:
                return [dict(it) for it in result]

            stripped = []
            for it in result:
                copy_it = dict(it)
                copy_it["dealer_price"] = None
                copy_it["consumer_price"] = None
                stripped.append(copy_it)
            return stripped

    def get_last_synced_at(self):
        return self._cache["inventory"].get("synced_at")

    # ----------------- ATOMIC STOCK PROCESSING -----------------
    def process_stock_batch(self, employee_username, action, source, items, invoice_no=None, notes=None):
        """
        Concurrency-safe write directly to Google Sheets (Live_Inventory + Audit_Log):
        1. Force-reads latest Live_Inventory so concurrent employees don't overwrite each other.
        2. Updates modified existing rows in-place via batch_update (NEVER clears Live_Inventory!).
        3. Appends new LN codes via append_rows.
        4. Appends immutable ledger entries to Audit_Log.
        5. Runs daily auto-backup snapshot if one hasn't run today.
        """
        if action not in ("IN", "OUT", "CAME_IN_AND_WENT_OUT"):
            return False, "Invalid action type"

        with self._lock:
            try:
                inv_ws = self._get_ws("Live_Inventory")
                log_ws = self._get_ws("Audit_Log")

                # Always pull fresh inventory from Google Sheet before computing deltas
                self.get_inventory_list(force_refresh=True)
                by_ln = {ln: dict(it) for ln, it in self._cache["inventory"]["by_ln"].items()}
                next_row_idx = max(
                    (it.get("_row_idx") or 1 for it in self._cache["inventory"]["data"]),
                    default=1
                ) + 1

                now_str = get_ist_now_str()
                batch_updates = []  # For existing rows updated in-place
                new_rows = []       # For newly seen LN codes
                audit_rows = []
                results = []

                for item in items:
                    ln = (item.get("ln_code") or "").strip().upper()
                    qty = _to_int(item.get("quantity", 1), 1)
                    if not ln or qty <= 0:
                        continue

                    existing = by_ln.get(ln)
                    stock_before = existing["current_stock"] if existing else 0

                    if action == "IN":
                        stock_after = stock_before + qty
                    elif action == "OUT":
                        stock_after = stock_before - qty
                    else:  # CAME_IN_AND_WENT_OUT
                        stock_after = stock_before

                    cat_entry = catalog.lookup(ln) if ln else None
                    desc = (item.get("description") or (existing["description"] if existing else "") or (cat_entry.get("description") if cat_entry else "") or "Unknown Product").strip()

                    if existing and existing.get("_row_idx"):
                        row_num = existing["_row_idx"]
                        # Update Current Stock (E=5), Last Updated (G=7), Last Modified By (H=8) in exact row
                        batch_updates.append({
                            "range": f"{rowcol_to_a1(row_num, 5)}",
                            "values": [[stock_after]]
                        })
                        batch_updates.append({
                            "range": f"{rowcol_to_a1(row_num, 7)}:{rowcol_to_a1(row_num, 8)}",
                            "values": [[now_str, employee_username]]
                        })
                        # Keep working map consistent if same LN appears twice in one batch
                        existing["current_stock"] = stock_after
                        existing["last_updated"] = now_str
                        existing["last_updated_by"] = employee_username
                    elif existing:
                        # New LN already staged earlier in this same batch
                        existing["current_stock"] = stock_after
                        existing["last_updated"] = now_str
                        existing["last_updated_by"] = employee_username
                    else:
                        cat_entry = catalog.lookup(ln)
                        cat = (item.get("category") or (cat_entry.get("category") if cat_entry else "") or "").strip()
                        sub_cat = (item.get("sub_cat") or (cat_entry.get("sub_cat") if cat_entry else "") or "").strip()
                        dp = _to_float(item.get("dealer_price", 0.0), 0.0)
                        if dp <= 0 and cat_entry:
                            dp = _to_float(cat_entry.get("dealer_price"), 0.0)
                        cp = _to_float(item.get("consumer_price", 0.0), 0.0)
                        if cp <= 0 and cat_entry:
                            cp = _to_float(cat_entry.get("consumer_price"), 0.0)

                        new_row = [
                            ln, desc, cat, sub_cat, stock_after, cp, now_str, employee_username
                        ]
                        new_rows.append(new_row)
                        # Track in working map in case same new LN appears twice in same batch
                        by_ln[ln] = {
                            "ln_code": ln,
                            "description": desc,
                            "category": cat,
                            "sub_cat": sub_cat,
                            "current_stock": stock_after,
                            "dealer_price": dp,
                            "consumer_price": cp,
                            "last_updated": now_str,
                            "last_updated_by": employee_username,
                            "_row_idx": None
                        }

                    log_id = f"LOG-{int(time.time() * 1000)}"
                    audit_rows.append([
                        log_id,
                        now_str,
                        employee_username,
                        action,
                        source,
                        ln,
                        desc,
                        qty,
                        stock_before,
                        stock_after,
                        invoice_no or "",
                        notes or ""
                    ])

                    results.append({
                        "ln_code": ln,
                        "description": desc,
                        "quantity": qty,
                        "stock_before": stock_before,
                        "stock_after": stock_after
                    })

                if not results:
                    return False, "No valid items in batch"

                # Update existing rows first (while row indices match), then append new items
                if batch_updates:
                    self._retry_api(inv_ws.batch_update, batch_updates)

                if new_rows:
                    dedup_new = {}
                    for nr in new_rows:
                        dedup_new[nr[0]] = nr
                        dedup_new[nr[0]][4] = by_ln[nr[0]]["current_stock"]
                    append_list = list(dedup_new.values())
                    self._retry_api(inv_ws.append_rows, append_list)
                    for nr in append_list:
                        by_ln[nr[0]]["_row_idx"] = next_row_idx
                        next_row_idx += 1

                if audit_rows:
                    self._retry_api(log_ws.append_rows, audit_rows)

                # O(k) write-through cache update without re-reading entire sheet
                updated_items = list(by_ln.values())
                updated_items.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
                self._cache["inventory"] = {
                    "data": updated_items,
                    "by_ln": by_ln,
                    "ts": time.time(),
                    "synced_at": now_str
                }
                self._invalidate_cache("audit_logs")

                # Check lazy daily backup after transaction
                try:
                    self.maybe_run_daily_backup()
                except Exception as be:
                    print(f"[AUTO BACKUP WARNING] {be}")

                return True, results
            except Exception as e:
                return False, f"Google Sheets write error: {str(e)}"

    def delete_inventory_batch(self, ln_codes: list, employee_username: str = "admin"):
        """
        Permanently deletes one or more item rows from Live_Inventory in Google Sheets
        (deleting contiguous row ranges from bottom to top so row indices never shift)
        and records immutable DELETE audit entries in Audit_Log.
        """
        cleaned_lns = []
        seen = set()
        for raw_ln in (ln_codes or []):
            ln = (raw_ln or "").strip().upper()
            if ln and ln not in seen:
                seen.add(ln)
                cleaned_lns.append(ln)

        if not cleaned_lns:
            return False, "No LN Codes selected for deletion", []

        with self._lock:
            try:
                inv_ws = self._get_ws("Live_Inventory")
                log_ws = self._get_ws("Audit_Log")

                # Force-refresh to guarantee exact _row_idx before deleting rows in Google Sheets
                self.get_inventory_list(force_refresh=True)
                by_ln = self._cache["inventory"]["by_ln"]

                targets = []
                for ln in cleaned_lns:
                    t = by_ln.get(ln)
                    if t and t.get("_row_idx"):
                        targets.append(t)

                if not targets:
                    return False, "Selected items were not found in Google Sheet", []

                # Sort ascending to group contiguous row ranges, then delete ranges from bottom to top
                targets.sort(key=lambda x: x["_row_idx"])
                ranges = []
                for t in targets:
                    r_idx = t["_row_idx"]
                    if ranges and r_idx == ranges[-1][1] + 1:
                        ranges[-1] = (ranges[-1][0], r_idx)
                    else:
                        ranges.append((r_idx, r_idx))

                for start_row, end_row in reversed(ranges):
                    pass

                # Execute all row deletions in a single batchUpdate API call for maximum speed
                try:
                    delete_requests = [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": inv_ws.id,
                                    "dimension": "ROWS",
                                    "startIndex": start_row - 1,
                                    "endIndex": end_row
                                }
                            }
                        }
                        for start_row, end_row in reversed(ranges)
                    ]
                    self._retry_api(self.sheet.batch_update, {"requests": delete_requests})
                except Exception:
                    for start_row, end_row in reversed(ranges):
                        self._retry_api(inv_ws.delete_rows, start_row, end_row)

                now_str = get_ist_now_str()
                actor = (employee_username or "admin").strip()
                base_ts = int(time.time() * 1000)

                audit_rows = []
                deleted_summary = []
                for idx, t in enumerate(targets):
                    ln = t["ln_code"]
                    stock_before = _to_int(t.get("current_stock", 0), 0)
                    desc = t.get("description") or "Godrej Item"
                    audit_rows.append([
                        f"LOG-{base_ts + idx}",
                        now_str,
                        actor,
                        "DELETE",
                        "APP_DELETE",
                        ln,
                        desc,
                        stock_before,
                        stock_before,
                        0,
                        "",
                        "Confirmed stock deletion from app"
                    ])
                    deleted_summary.append({
                        "ln_code": ln,
                        "description": desc,
                        "deleted_stock": stock_before
                    })

                if audit_rows:
                    self._retry_api(log_ws.append_rows, audit_rows)

                # O(N) in-memory cache update without a redundant network round-trip
                deleted_lns_set = {t["ln_code"] for t in targets}
                deleted_row_indices = sorted(t["_row_idx"] for t in targets)
                remaining_items = []
                new_by_ln = {}
                for it in self._cache["inventory"]["data"]:
                    if it["ln_code"] in deleted_lns_set:
                        continue
                    old_r = it.get("_row_idx", 0)
                    shift = sum(1 for dr in deleted_row_indices if dr < old_r)
                    updated_it = dict(it)
                    updated_it["_row_idx"] = old_r - shift
                    remaining_items.append(updated_it)
                    new_by_ln[updated_it["ln_code"]] = updated_it

                self._cache["inventory"] = {
                    "data": remaining_items,
                    "by_ln": new_by_ln,
                    "ts": time.time(),
                    "synced_at": now_str
                }
                self._invalidate_cache("audit_logs")

                if len(deleted_summary) == 1:
                    d0 = deleted_summary[0]
                    msg = f"Deleted {d0['ln_code']} ({d0['description']}) from Google Sheet"
                else:
                    msg = f"Deleted {len(deleted_summary)} products from Google Sheet"

                return True, msg, deleted_summary
            except Exception as e:
                return False, f"Google Sheets delete error: {str(e)}", []

    def delete_inventory_item(self, ln_code: str, employee_username: str = "admin"):
        ok, msg, deleted_list = self.delete_inventory_batch([ln_code], employee_username=employee_username)
        return ok, msg, (deleted_list[0] if deleted_list else None)

    # ----------------- AUDIT LOGS -----------------
    def get_audit_logs(self, limit: int = 5000, action: str = None, employee: str = None, force_refresh: bool = False) -> list:
        with self._lock:
            now = time.time()
            cached = self._cache["audit_logs"]
            if force_refresh or cached["ts"] == 0 or (now - cached["ts"]) >= CACHE_TTL_SECONDS:
                ws = self._get_ws("Audit_Log")
                raw = self._retry_api(ws.get_all_values)
                logs = []
                for row_num, r in enumerate(raw[1:], start=2):
                    if not r or len(r) < 6:
                        continue
                    def c(i, d=""):
                        return str(r[i]).strip() if i < len(r) and r[i] is not None else d
                    log_id = c(0) or f"ROW-{row_num}"
                    logs.append({
                        "id": log_id,
                        "timestamp": c(1),
                        "employee_username": c(2),
                        "action": c(3),
                        "source": c(4),
                        "ln_code": c(5),
                        "description": c(6),
                        "quantity": _to_int(c(7, "0"), 0),
                        "stock_before": _to_int(c(8, "0"), 0),
                        "stock_after": _to_int(c(9, "0"), 0),
                        "invoice_no": c(10),
                        "notes": c(11),
                        "_row_idx": row_num
                    })
                # Reverse chronological order
                logs.reverse()
                self._cache["audit_logs"] = {"data": logs, "ts": now}

            result = list(self._cache["audit_logs"]["data"])
            if action:
                result = [l for l in result if l["action"] == action]
            if employee:
                emp_low = employee.strip().lower()
                result = [l for l in result if (l["employee_username"] or "").lower() == emp_low]
            return result[:limit]

    def delete_audit_logs_batch(self, log_ids: list, employee_username: str = "admin") -> tuple[bool, str, list]:
        """
        Permanently deletes one or more audit log rows from Audit_Log in Google Sheets
        using a single batchUpdate DeleteDimension call from bottom to top.
        """
        cleaned_ids = []
        seen = set()
        for raw_id in (log_ids or []):
            lid = str(raw_id or "").strip()
            if lid and lid not in seen:
                seen.add(lid)
                cleaned_ids.append(lid)

        if not cleaned_ids:
            return False, "No audit logs selected for deletion", []

        target_id_set = set(cleaned_ids)

        with self._lock:
            try:
                log_ws = self._get_ws("Audit_Log")

                # Force-refresh to guarantee exact 1-based _row_idx before deleting rows
                self.get_audit_logs(limit=100000, force_refresh=True)
                all_logs = self._cache["audit_logs"]["data"]

                targets = [l for l in all_logs if l.get("id") in target_id_set and l.get("_row_idx")]
                if not targets:
                    return False, "Selected audit log entries were not found in Google Sheet", []

                # Sort ascending by _row_idx to merge contiguous ranges
                targets.sort(key=lambda x: x["_row_idx"])
                ranges = []
                for t in targets:
                    r_idx = t["_row_idx"]
                    if ranges and r_idx == ranges[-1][1] + 1:
                        ranges[-1] = (ranges[-1][0], r_idx)
                    else:
                        ranges.append((r_idx, r_idx))

                # Delete ranges from bottom to top in a single batch_update call
                try:
                    delete_requests = [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": log_ws.id,
                                    "dimension": "ROWS",
                                    "startIndex": start_row - 1,
                                    "endIndex": end_row
                                }
                            }
                        }
                        for start_row, end_row in reversed(ranges)
                    ]
                    self._retry_api(self.sheet.batch_update, {"requests": delete_requests})
                except Exception:
                    for start_row, end_row in reversed(ranges):
                        self._retry_api(log_ws.delete_rows, start_row, end_row)

                deleted_row_set = {t["_row_idx"] for t in targets}
                deleted_row_indices = sorted(deleted_row_set)
                remaining_logs = []
                for l in all_logs:
                    old_r = l.get("_row_idx", 0)
                    if old_r in deleted_row_set:
                        continue
                    shift = sum(1 for dr in deleted_row_indices if dr < old_r)
                    updated_l = dict(l)
                    updated_l["_row_idx"] = old_r - shift
                    remaining_logs.append(updated_l)

                self._cache["audit_logs"] = {
                    "data": remaining_logs,
                    "ts": time.time()
                }

                deleted_summary = [
                    {
                        "id": t["id"],
                        "ln_code": t.get("ln_code", ""),
                        "description": t.get("description", ""),
                        "action": t.get("action", ""),
                        "timestamp": t.get("timestamp", "")
                    }
                    for t in targets
                ]

                if len(deleted_summary) == 1:
                    d0 = deleted_summary[0]
                    msg = f"Deleted audit log {d0['id']} ({d0['action']} {d0['ln_code']}) from Google Sheet"
                else:
                    msg = f"Deleted {len(deleted_summary)} audit log records from Google Sheet"

                return True, msg, deleted_summary
            except Exception as e:
                return False, f"Google Sheets audit log delete error: {str(e)}", []

    def reconcile_and_reorganize_ledger(self, employee_username: str = "admin") -> tuple[bool, str, dict]:
        """
        Reconciles the entire historical ledger across Audit_Log and Live_Inventory:
        1. Reads all transactions from Audit_Log.
        2. Resolves any missing/unknown LN codes from descriptions via Catalog fuzzy match.
        3. Sorts all transactions in strict chronological order by Timestamp.
        4. Replays running stock from row 1 to the end:
           - Recalculates stock_before and stock_after for every transaction.
           - IN: +qty
           - OUT: -qty (no clamping, allows negative deficits)
           - CAME_IN_AND_WENT_OUT: unchanged (0 -> 0)
        5. Updates Audit_Log in Google Sheets with the sorted, calculated rows.
        6. Rebuilds Live_Inventory in Google Sheets with the final net stock for all active items,
           populating descriptions, categories, and consumer prices from the catalog.
        7. Invalidates cache.
        """
        with self._lock:
            try:
                log_ws = self._get_ws("Audit_Log")
                inv_ws = self._get_ws("Live_Inventory")

                raw_logs = self._retry_api(log_ws.get_all_values)
                if len(raw_logs) <= 1:
                    return False, "Audit_Log has no transaction rows to reconcile.", {}

                headers = raw_logs[0]
                rows = raw_logs[1:]

                parsed_records = []
                for idx, r in enumerate(rows):
                    if not r or len(r) < 6:
                        continue
                    def c(i, d=""):
                        return str(r[i]).strip() if i < len(r) and r[i] is not None else d

                    log_id = c(0) or f"LOG-{idx+1}"
                    ts_str = c(1) or get_ist_now_str()
                    emp = c(2) or "system"
                    action = c(3).upper() or "IN"
                    src = c(4) or "MANUAL"
                    ln = c(5).upper()
                    desc = c(6)
                    qty = _to_int(c(7, "1"), 1)
                    inv_no = c(10)
                    notes = c(11)

                    # If LN code is missing or placeholder, attempt fuzzy match from description
                    if (not ln or ln in ("UNKNOWN", "NONE", "XXXXX", "NULL")) and desc:
                        match = catalog.match_name(desc)
                        if match:
                            ln = match["item"]["ln_code"]
                            if not desc or desc == "Unknown Product":
                                desc = match["item"]["description"]

                    # If description is missing or generic, lookup from catalog
                    if ln and (not desc or desc == "Unknown Product"):
                        cat_item = catalog.lookup(ln)
                        if cat_item:
                            desc = cat_item["description"]

                    parsed_records.append({
                        "id": log_id,
                        "timestamp": ts_str,
                        "employee": emp,
                        "action": action,
                        "source": src,
                        "ln_code": ln,
                        "description": desc or "Godrej Item",
                        "quantity": qty,
                        "invoice_no": inv_no,
                        "notes": notes
                    })

                # Sort chronologically by timestamp
                def parse_sort_key(rec):
                    ts = rec["timestamp"]
                    cleaned_ts = re.sub(r"[^\d]", "", ts)
                    return cleaned_ts.ljust(14, "0")

                parsed_records.sort(key=parse_sort_key)

                # Replay running stock across all SKUs
                from collections import defaultdict
                running_stock = defaultdict(int)
                last_activity = {}

                reconciled_audit_rows = []
                for rec in parsed_records:
                    ln = rec["ln_code"]
                    qty = rec["quantity"]
                    action = rec["action"]
                    sb = running_stock[ln]

                    if action == "IN":
                        sa = sb + qty
                    elif action == "OUT":
                        sa = sb - qty
                    else:  # CAME_IN_AND_WENT_OUT or other pass-through
                        sa = sb

                    running_stock[ln] = sa
                    last_activity[ln] = {
                        "timestamp": rec["timestamp"],
                        "employee": rec["employee"],
                        "description": rec["description"]
                    }

                    reconciled_audit_rows.append([
                        rec["id"],
                        rec["timestamp"],
                        rec["employee"],
                        rec["action"],
                        rec["source"],
                        rec["ln_code"],
                        rec["description"],
                        rec["quantity"],
                        sb,
                        sa,
                        rec["invoice_no"],
                        rec["notes"]
                    ])

                # 1. Update Audit_Log tab with sorted, reconciled ledger
                self._retry_api(log_ws.clear)
                self._retry_api(log_ws.update, [AUDIT_HEADERS] + reconciled_audit_rows, "A1")

                # 2. Rebuild Live_Inventory tab from reconciled running stock
                new_inventory_rows = []
                for ln, current_qty in running_stock.items():
                    if not ln:
                        continue
                    cat_item = catalog.lookup(ln)
                    desc = (cat_item.get("description") if cat_item else None) or last_activity.get(ln, {}).get("description") or "Godrej Item"
                    cat = cat_item.get("category", "") if cat_item else ""
                    sub_cat = cat_item.get("sub_cat", "") if cat_item else ""
                    cp = cat_item.get("consumer_price", 0.0) if cat_item else 0.0
                    last_ts = last_activity.get(ln, {}).get("timestamp", get_ist_now_str())
                    last_emp = last_activity.get(ln, {}).get("employee", employee_username)

                    new_inventory_rows.append([
                        ln, desc, cat, sub_cat, current_qty, cp, last_ts, last_emp
                    ])

                # Sort inventory items: positive stock first, then deficit items, by newest updated
                new_inventory_rows.sort(key=lambda r: (r[4] > 0, r[6]), reverse=True)

                self._retry_api(inv_ws.clear)
                self._retry_api(inv_ws.update, [INVENTORY_HEADERS] + new_inventory_rows, "A1")

                self._invalidate_cache()

                summary = {
                    "total_transactions": len(reconciled_audit_rows),
                    "total_skus": len(new_inventory_rows),
                    "in_stock_skus": sum(1 for r in new_inventory_rows if r[4] > 0),
                    "deficit_skus": sum(1 for r in new_inventory_rows if r[4] < 0),
                    "zero_stock_skus": sum(1 for r in new_inventory_rows if r[4] == 0)
                }

                return True, f"Ledger reconciled: {summary['total_transactions']} transactions organized across {summary['total_skus']} SKUs.", summary

            except Exception as e:
                return False, f"Reconciliation failed: {str(e)}", {}

    def import_historical_batch(self, items: list, employee_username: str = "admin") -> tuple[bool, str, dict]:
        """
        Imports historical records with or without LN codes:
        Resolves product descriptions to Godrej catalog LN codes, writes to Audit_Log,
        and re-organizes and reconciles the entire ledger.
        """
        if not items:
            return False, "No items provided for historical import.", {}

        with self._lock:
            try:
                log_ws = self._get_ws("Audit_Log")
                now_str = get_ist_now_str()
                base_ts = int(time.time() * 1000)

                new_rows = []
                mapped_details = []

                for idx, it in enumerate(items):
                    raw_name = (it.get("product_name") or it.get("description") or "").strip()
                    code = (it.get("ln_code") or "").strip().upper()
                    action = (it.get("action") or "IN").strip().upper()
                    if action not in ("IN", "OUT", "CAME_IN_AND_WENT_OUT"):
                        action = "IN"
                    qty = _to_int(it.get("quantity", 1), 1)
                    if qty <= 0:
                        qty = 1

                    ts = (it.get("timestamp") or it.get("date") or now_str).strip()
                    if len(ts) == 10:  # e.g. YYYY-MM-DD
                        ts = f"{ts} 12:00:00"

                    ref = (it.get("reference") or it.get("invoice_no") or "HISTORICAL_IMPORT").strip()
                    notes = (it.get("notes") or "Imported historical record").strip()

                    # Match LN code from name if missing
                    cat_item = None
                    if code:
                        cat_item = catalog.lookup(code)
                    if not cat_item and raw_name:
                        match = catalog.match_name(raw_name)
                        if match:
                            cat_item = match["item"]
                            code = cat_item["ln_code"]

                    desc = (cat_item.get("description") if cat_item else raw_name) or "Godrej Item"
                    final_code = code or "UNKNOWN"

                    new_rows.append([
                        f"LOG-HIST-{base_ts + idx}",
                        ts,
                        employee_username or "admin",
                        action,
                        "HISTORICAL_IMPORT",
                        final_code,
                        desc,
                        qty,
                        0,  # Temporary; reconcile will compute exact chronological stock_before
                        0,  # Temporary; reconcile will compute exact chronological stock_after
                        ref,
                        notes
                    ])

                    mapped_details.append({
                        "raw_name": raw_name,
                        "ln_code": final_code,
                        "description": desc,
                        "action": action,
                        "quantity": qty,
                        "timestamp": ts,
                        "matched": bool(cat_item)
                    })

                # Append raw rows to Audit_Log
                self._retry_api(log_ws.append_rows, new_rows)

                # Reconcile, re-sort chronologically, and cascade stock
                ok, msg, summary = self.reconcile_and_reorganize_ledger(employee_username=employee_username)
                if not ok:
                    return False, f"Rows imported but reconciliation failed: {msg}", {"mapped": mapped_details}

                summary["mapped_items"] = mapped_details
                return True, f"Successfully imported and organized {len(new_rows)} historical items! {msg}", summary

            except Exception as e:
                return False, f"Historical import failed: {str(e)}", {}

    # ----------------- BACKUPS & RECOVERY -----------------
    def maybe_run_daily_backup(self):
        """
        Serverless-friendly automatic daily backup:
        On the first login or write of a new day, snapshots Live_Inventory to Backup_Latest & Backup_History.
        """
        today = get_ist_now_str("%Y-%m-%d")
        last_auto = self.get_setting("last_auto_backup_date", "")
        if last_auto == today:
            return False, "Already backed up today"

        items = self.get_inventory_list()
        if not items:
            return False, "Skipping empty backup"

        ok, msg, _ = self.create_backup_snapshot(trigger="DAILY_AUTO")
        if ok:
            self.set_setting("last_auto_backup_date", today)
        return ok, msg

    def create_backup_snapshot(self, trigger: str = "MANUAL"):
        """
        Writes a verified point-in-time snapshot into:
        1. Backup_Latest (clean single-table snapshot)
        2. Backup_History (append-only historical snapshots)
        """
        with self._lock:
            items = self.get_inventory_list(force_refresh=True)
            now_dt = get_ist_now()
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            date_str = now_dt.strftime("%Y-%m-%d")
            backup_id = f"{trigger}-{now_dt.strftime('%Y%m%d-%H%M%S')}"

            try:
                latest_ws = self._get_ws("Backup_Latest")
                history_ws = self._get_ws("Backup_History")

                latest_rows = [INVENTORY_HEADERS] + [[
                    it["ln_code"],
                    it["description"],
                    it["category"],
                    it["sub_cat"],
                    it["current_stock"],
                    it["consumer_price"],
                    it["last_updated"],
                    it["last_updated_by"]
                ] for it in items]

                self._retry_api(latest_ws.clear)
                self._retry_api(latest_ws.update, latest_rows, "A1")

                if items:
                    hist_rows = [[
                        backup_id,
                        now_str,
                        it["ln_code"],
                        it["description"],
                        it["category"],
                        it["sub_cat"],
                        it["current_stock"],
                        it["consumer_price"],
                        it["last_updated_by"]
                    ] for it in items]
                    self._retry_api(history_ws.append_rows, hist_rows)

                    # Cap Backup_History to newest MAX_BACKUP_HISTORY_ROWS data rows
                    all_hist = self._retry_api(history_ws.get_all_values)
                    if len(all_hist) > MAX_BACKUP_HISTORY_ROWS + 1:
                        trimmed_hist = [BACKUP_HISTORY_HEADERS] + all_hist[1:][-MAX_BACKUP_HISTORY_ROWS:]
                        self._retry_api(history_ws.clear)
                        self._retry_api(history_ws.update, trimmed_hist, "A1")

                self.set_setting("last_backup_at", now_str)
                if trigger == "DAILY_AUTO":
                    self.set_setting("last_auto_backup_date", date_str)

                total_units = sum(max(0, x["current_stock"]) for x in items)
                return True, f"Backup {backup_id} saved ({len(items)} items, {total_units} units)", {
                    "backup_id": backup_id,
                    "timestamp": now_str,
                    "item_count": len(items),
                    "total_units": total_units
                }
            except Exception as e:
                return False, f"Backup failed: {str(e)}", None

    def get_backup_summary(self):
        with self._lock:
            ws = self._get_ws("Backup_History")
            raw = self._retry_api(ws.get_all_values)
            settings = self.get_all_settings()

            stock_col = 6
            if raw and raw[0]:
                hdrs = [h.strip().lower() for h in raw[0]]
                if "current stock" in hdrs:
                    stock_col = hdrs.index("current stock")

            grouped = {}
            for r in raw[1:]:
                if not r or len(r) < 7 or not r[0].strip():
                    continue
                bid = r[0].strip()
                bdate = r[1].strip()
                qty = _to_int(r[stock_col] if stock_col < len(r) else "0", 0)
                if bid not in grouped:
                    grouped[bid] = {
                        "backup_id": bid,
                        "timestamp": bdate,
                        "item_count": 0,
                        "total_units": 0
                    }
                grouped[bid]["item_count"] += 1
                grouped[bid]["total_units"] += max(0, qty)

            snapshots = list(grouped.values())
            snapshots.sort(key=lambda x: x["timestamp"], reverse=True)
            return {
                "last_backup_at": settings.get("last_backup_at", "Never"),
                "last_auto_backup_date": settings.get("last_auto_backup_date", "Pending"),
                "snapshots": snapshots[:20]
            }

    def restore_from_backup_latest(self, restored_by: str = "admin"):
        """Restores Live_Inventory safely from Backup_Latest worksheet."""
        with self._lock:
            try:
                latest_ws = self._get_ws("Backup_Latest")
                inv_ws = self._get_ws("Live_Inventory")
                log_ws = self._get_ws("Audit_Log")

                rows = self._retry_api(latest_ws.get_all_values)
                if len(rows) <= 1:
                    return False, "Backup_Latest has no inventory rows to restore."

                self._retry_api(inv_ws.clear)
                self._retry_api(inv_ws.update, rows, "A1")

                now_str = get_ist_now_str()
                self._retry_api(log_ws.append_row, [
                    f"RESTORE-{int(time.time())}",
                    now_str,
                    restored_by,
                    "SYSTEM_RESTORE",
                    "BACKUP_LATEST",
                    "ALL",
                    f"Restored {len(rows) - 1} items from Backup_Latest",
                    len(rows) - 1,
                    0,
                    0,
                    "",
                    "Admin triggered snapshot restore"
                ])
                self._invalidate_cache("inventory", "audit_logs")
                self.get_inventory_list(force_refresh=True)
                return True, f"Restored {len(rows) - 1} items from Backup_Latest"
            except Exception as e:
                return False, f"Restore failed: {str(e)}"

    # ----------------- EXCEL EXPORT -----------------
    def export_inventory_excel(self, filepath: str, include_prices: bool = True):
        """Generates a clean Excel workbook directly from Google Sheets Primary data."""
        items = self.get_inventory_list(force_refresh=True, include_prices=include_prices)
        logs = self.get_audit_logs(limit=500, force_refresh=True)

        wb = openpyxl.Workbook()
        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

        # Sheet 1: Live Inventory
        ws1 = wb.active
        ws1.title = "Live Inventory"
        if include_prices:
            export_headers = [
                "LN Code", "Product Description", "Category", "Sub Cat",
                "Current Stock", "Dealer Price (Rs)", "Consumer Price (Rs)",
                "Last Updated", "Last Modified By"
            ]
        else:
            export_headers = [
                "LN Code", "Product Description", "Category", "Sub Cat",
                "Current Stock", "Last Updated", "Last Modified By"
            ]
        ws1.append(export_headers)
        for col_num in range(1, len(export_headers) + 1):
            cell = ws1.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for item in items:
            if include_prices:
                ws1.append([
                    item["ln_code"], item["description"], item["category"],
                    item["sub_cat"], item["current_stock"], item["dealer_price"],
                    item["consumer_price"], item["last_updated"], item["last_updated_by"]
                ])
            else:
                ws1.append([
                    item["ln_code"], item["description"], item["category"],
                    item["sub_cat"], item["current_stock"],
                    item["last_updated"], item["last_updated_by"]
                ])

        # Sheet 2: Audit Log
        ws2 = wb.create_sheet("Audit History")
        ws2.append(AUDIT_HEADERS)
        for col_num in range(1, len(AUDIT_HEADERS) + 1):
            cell = ws2.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for l in logs:
            ws2.append([
                l["id"], l["timestamp"], l["employee_username"], l["action"], l["source"],
                l["ln_code"], l["description"], l["quantity"], l["stock_before"],
                l["stock_after"], l["invoice_no"], l["notes"]
            ])

        wb.save(filepath)
        return filepath


# Singleton instance
gsheets_db = GSheetsPrimaryDB()
get_setting = gsheets_db.get_setting
