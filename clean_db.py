import sqlite3
import os

db_path = "inventory.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM settings WHERE key = 'groq_api_key'")
    conn.commit()
    conn.close()
    print("Database settings table cleared.")
