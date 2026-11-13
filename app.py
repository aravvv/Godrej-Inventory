import os
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status, BackgroundTasks
from gsheets_sync import gsheets
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import tempfile

from database import (
    init_db, authenticate_user, get_all_users, create_user, delete_user,
    process_stock_batch, get_inventory_list, get_audit_logs, export_inventory_excel,
    get_setting, set_setting
)
from catalog import catalog
from vision import parse_slip_image, parse_bill_image

app = FastAPI(title="Godrej Inventory Automation System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    init_db()

# Pydantic Schemas
class LoginRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: str = "employee"

class BatchItem(BaseModel):
    ln_code: str
    description: Optional[str] = ""
    sku: Optional[str] = ""
    category: Optional[str] = ""
    sub_cat: Optional[str] = ""
    quantity: int = 1
    dealer_price: Optional[float] = 0.0
    consumer_price: Optional[float] = 0.0

class ProcessBatchRequest(BaseModel):
    username: str
    action: str  # 'IN', 'OUT', 'CAME_IN_AND_WENT_OUT'
    source: str  # 'SLIP_BATCH', 'BILL_PHOTO', 'MANUAL'
    items: List[BatchItem]
    invoice_no: Optional[str] = None
    notes: Optional[str] = None

class SettingRequest(BaseModel):
    key: str
    value: str

# ----------------- AUTH ENDPOINTS -----------------
@app.post("/api/login")
def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {
        "success": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"]
        }
    }

@app.get("/api/users")
def list_users(role: str = "admin"):
    return {"users": get_all_users()}

@app.post("/api/users")
def add_user(req: CreateUserRequest):
    ok, msg = create_user(req.username, req.password, req.full_name, req.role)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.delete("/api/users/{user_id}")
def remove_user(user_id: int):
    ok, msg = delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

# ----------------- VISION & SCANNING ENDPOINTS -----------------
@app.post("/api/scan-slip")
async def scan_slip(file: UploadFile = File(...)):
    image_bytes = await file.read()
    result = parse_slip_image(image_bytes)
    return result

@app.post("/api/scan-bill")
async def scan_bill(file: UploadFile = File(...)):
    image_bytes = await file.read()
    result = parse_bill_image(image_bytes)
    return result

@app.get("/api/lookup/{ln_code}")
def lookup_code(ln_code: str):
    res = catalog.lookup(ln_code)
    if res:
        return {"found": True, "item": res}
    return {"found": False, "message": f"Code {ln_code} not found in catalog"}

# ----------------- INVENTORY & BATCH ENDPOINTS -----------------
@app.post("/api/process-batch")
def process_batch(req: ProcessBatchRequest, background_tasks: BackgroundTasks):
    if req.action not in ["IN", "OUT", "CAME_IN_AND_WENT_OUT"]:
        raise HTTPException(status_code=400, detail="Invalid action type")
    
    items_dict = [it.dict() for it in req.items]
    ok, details = process_stock_batch(
        employee_username=req.username,
        action=req.action,
        source=req.source,
        items=items_dict,
        invoice_no=req.invoice_no,
        notes=req.notes
    )
    if not ok:
        raise HTTPException(status_code=500, detail=str(details))

    # Real-time background sync to Google Sheets
    background_tasks.add_task(
        gsheets.sync_batch,
        employee_username=req.username,
        action=req.action,
        source=req.source,
        processed_items=details,
        invoice_no=req.invoice_no,
        notes=req.notes
    )

    return {"success": True, "processed": details}

@app.get("/api/inventory")
def get_inventory(search: str = ""):
    return {"inventory": get_inventory_list(search)}

@app.get("/api/logs")
def get_logs(limit: int = 150, action: Optional[str] = None, employee: Optional[str] = None):
    return {"logs": get_audit_logs(limit=limit, action=action, employee=employee)}

@app.get("/api/export-excel")
def download_excel():
    temp_dir = tempfile.gettempdir()
    excel_path = os.path.join(temp_dir, "Godrej_Inventory_Export.xlsx")
    export_inventory_excel(excel_path)
    return FileResponse(
        excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Godrej_Inventory_Live.xlsx"
    )

# ----------------- SETTINGS ENDPOINTS -----------------
@app.get("/api/settings")
def get_app_settings():
    is_configured = bool(os.getenv("GROQ_API_KEY") or get_setting("groq_api_key"))
    return {
        "is_groq_configured": is_configured,
        "groq_status": "Active & Encrypted in .env" if is_configured else "Not Set",
        "total_catalog_items": len(catalog.items)
    }

@app.post("/api/settings")
def update_app_settings(req: SettingRequest):
    set_setting(req.key, req.value.strip())
    return {"success": True, "message": f"Setting {req.key} updated successfully"}

# ----------------- STATIC ASSETS -----------------
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Godrej Inventory API is running. UI is initializing..."}
