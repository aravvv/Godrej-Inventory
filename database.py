import sqlite3
import os
import hashlib
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

if os.getenv("VERCEL"):
    DB_PATH = "/tmp/inventory.db"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'employee')),
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Inventory Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            ln_code TEXT PRIMARY KEY,
            description TEXT,
            sku TEXT,
            category TEXT,
            sub_cat TEXT,
            current_stock INTEGER DEFAULT 0,
            dealer_price REAL DEFAULT 0.0,
            consumer_price REAL DEFAULT 0.0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated_by TEXT
        )
    """)

    # Audit Logs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            employee_username TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('IN', 'OUT', 'CAME_IN_AND_WENT_OUT')),
            source TEXT NOT NULL CHECK(source IN ('SLIP_BATCH', 'BILL_PHOTO', 'MANUAL')),
            ln_code TEXT NOT NULL,
            description TEXT,
            quantity INTEGER NOT NULL,
            stock_before INTEGER,
            stock_after INTEGER,
            invoice_no TEXT,
            notes TEXT
        )
    """)

    # Settings Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Ensure default admin account exists
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role)
            VALUES (?, ?, ?, ?)
        """, ('admin', hash_password('admin123'), 'Administrator', 'admin'))

    conn.commit()
    conn.close()
    print("[DB] Database initialized successfully.")

def get_setting(key: str, default=None):
    conn = get_connection()
    row = conn.cursor().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_connection()
    conn.cursor().execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# User Management
def authenticate_user(username, password):
    conn = get_connection()
    hashed = hash_password(password)
    user = conn.cursor().execute("""
        SELECT id, username, full_name, role, is_active 
        FROM users 
        WHERE username = ? AND password_hash = ? AND is_active = 1
    """, (username, hashed)).fetchone()
    conn.close()
    return dict(user) if user else None

def get_all_users():
    conn = get_connection()
    rows = conn.cursor().execute("SELECT id, username, full_name, role, is_active, created_at FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_user(username, password, full_name, role="employee"):
    conn = get_connection()
    try:
        conn.cursor().execute("""
            INSERT INTO users (username, password_hash, full_name, role)
            VALUES (?, ?, ?, ?)
        """, (username.strip().lower(), hash_password(password), full_name.strip(), role))
        conn.commit()
        return True, "User created successfully"
    except sqlite3.IntegrityError:
        return False, "Username already exists"
    finally:
        conn.close()

def delete_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    # Prevent deleting primary admin
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row["username"] == "admin":
        conn.close()
        return False, "Cannot delete primary admin account"
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True, "User deleted"

# Stock Processing
def process_stock_batch(employee_username, action, source, items, invoice_no=None, notes=None):
    """
    items: list of dicts: [{"ln_code": ..., "description": ..., "sku": ..., "category": ..., "sub_cat": ..., "quantity": 1, "dealer_price": 0, "consumer_price": 0}]
    action: 'IN', 'OUT', 'CAME_IN_AND_WENT_OUT'
    """
    conn = get_connection()
    cursor = conn.cursor()
    results = []

    try:
        for item in items:
            ln = item["ln_code"].strip().upper()
            qty = int(item.get("quantity", 1))
            if qty <= 0:
                continue

            # Fetch current stock
            cursor.execute("SELECT current_stock, description FROM inventory WHERE ln_code = ?", (ln,))
            existing = cursor.fetchone()

            stock_before = existing["current_stock"] if existing else 0

            if action == "IN":
                stock_after = stock_before + qty
            elif action == "OUT":
                stock_after = stock_before - qty
            elif action == "CAME_IN_AND_WENT_OUT":
                stock_after = stock_before # net zero

            # Upsert into inventory
            if existing:
                cursor.execute("""
                    UPDATE inventory 
                    SET current_stock = ?, last_updated = CURRENT_TIMESTAMP, last_updated_by = ?
                    WHERE ln_code = ?
                """, (stock_after, employee_username, ln))
            else:
                cursor.execute("""
                    INSERT INTO inventory (ln_code, description, sku, category, sub_cat, current_stock, dealer_price, consumer_price, last_updated_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ln,
                    item.get("description", "Unknown Product"),
                    item.get("sku", ""),
                    item.get("category", ""),
                    item.get("sub_cat", ""),
                    stock_after,
                    item.get("dealer_price", 0.0),
                    item.get("consumer_price", 0.0),
                    employee_username
                ))

            # Record Audit Log
            cursor.execute("""
                INSERT INTO audit_logs (employee_username, action, source, ln_code, description, quantity, stock_before, stock_after, invoice_no, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                employee_username,
                action,
                source,
                ln,
                item.get("description", existing["description"] if existing else ""),
                qty,
                stock_before,
                stock_after,
                invoice_no,
                notes
            ))

            results.append({
                "ln_code": ln,
                "description": item.get("description", ""),
                "quantity": qty,
                "stock_before": stock_before,
                "stock_after": stock_after
            })

        conn.commit()
        return True, results
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_inventory_list(search=""):
    conn = get_connection()
    cursor = conn.cursor()
    if search:
        s = f"%{search.strip()}%"
        cursor.execute("""
            SELECT * FROM inventory 
            WHERE ln_code LIKE ? OR description LIKE ? OR sku LIKE ? OR category LIKE ?
            ORDER BY last_updated DESC
        """, (s, s, s, s))
    else:
        cursor.execute("SELECT * FROM inventory ORDER BY last_updated DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_audit_logs(limit=200, action=None, employee=None):
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM audit_logs WHERE 1=1"
    params = []
    if action:
        query += " AND action = ?"
        params.append(action)
    if employee:
        query += " AND employee_username = ?"
        params.append(employee)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def export_inventory_excel(filepath):
    """Generates a styled Excel sheet with current inventory and audit history."""
    items = get_inventory_list()
    logs = get_audit_logs(limit=500)

    wb = openpyxl.Workbook()
    
    # Sheet 1: Live Inventory
    ws1 = wb.active
    ws1.title = "Live Inventory"
    
    headers1 = ["LN Code", "Description", "SKU", "Category", "Sub Cat", "Current Stock", "Dealer Price (₹)", "Consumer Price (₹)", "Last Updated", "Last Modified By"]
    ws1.append(headers1)
    
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

    for col_num in range(1, len(headers1) + 1):
        cell = ws1.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, item in enumerate(items, start=2):
        ws1.append([
            item["ln_code"],
            item["description"],
            item["sku"],
            item["category"],
            item["sub_cat"],
            item["current_stock"],
            item["dealer_price"],
            item["consumer_price"],
            item["last_updated"],
            item["last_updated_by"]
        ])

    # Sheet 2: Audit Trail
    ws2 = wb.create_sheet(title="Audit Logs")
    headers2 = ["Log ID", "Timestamp", "Employee", "Action", "Source", "LN Code", "Product Description", "Quantity", "Stock Before", "Stock After", "Invoice No", "Notes"]
    ws2.append(headers2)

    for col_num in range(1, len(headers2) + 1):
        cell = ws2.cell(row=1, column=col_num)
        cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for log in logs:
        ws2.append([
            log["id"],
            log["timestamp"],
            log["employee_username"],
            log["action"],
            log["source"],
            log["ln_code"],
            log["description"],
            log["quantity"],
            log["stock_before"],
            log["stock_after"],
            log["invoice_no"],
            log["notes"]
        ])

    # Auto-adjust column widths
    for ws in [ws1, ws2]:
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    wb.save(filepath)
    return filepath
