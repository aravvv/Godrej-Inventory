import os
import tempfile
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gsheets_db import gsheets_db
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


@app.on_event("startup")
def startup_event():
    try:
        info = gsheets_db.sync_from_sheets()
        if not os.getenv("GROQ_API_KEY"):
            sheet_key = gsheets_db.get_setting("groq_api_key", "")
            if sheet_key:
                os.environ["GROQ_API_KEY"] = sheet_key.strip()
        print(f"[APP STARTUP] Google Sheets Primary Ready: {info}")
    except Exception as e:
        print(f"[APP STARTUP WARNING] {e}")


# ----------------- SCHEMAS -----------------
class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: str = "employee"


class ChangePasswordRequest(BaseModel):
    new_password: str


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
    action: str
    source: str
    items: List[BatchItem]
    invoice_no: Optional[str] = None
    notes: Optional[str] = None


class SettingRequest(BaseModel):
    key: str
    value: str


class RestoreRequest(BaseModel):
    username: Optional[str] = "admin"


class DeleteInventoryBatchRequest(BaseModel):
    ln_codes: List[str]
    username: Optional[str] = "admin"


class HistoricalImportItem(BaseModel):
    product_name: Optional[str] = None
    description: Optional[str] = None
    ln_code: Optional[str] = None
    action: str = "IN"
    quantity: int = 1
    timestamp: Optional[str] = None
    date: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None


class HistoricalImportRequest(BaseModel):
    items: List[HistoricalImportItem]
    username: Optional[str] = "admin"


class MatchPreviewRequest(BaseModel):
    names: List[str]


# ----------------- AUTH ENDPOINTS -----------------
@app.post("/api/login")
def login(req: LoginRequest):
    try:
        user = gsheets_db.authenticate_user(req.username, req.password)
    except RuntimeError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Database connection unavailable: {str(e)}. Configure GOOGLE_SERVICE_ACCOUNT_JSON in Vercel Environment Variables."
        )

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Auto-sync inventory & metadata from Google Sheets on every login
    sync_info = {}
    try:
        sync_info = gsheets_db.sync_from_sheets()
    except Exception as e:
        print(f"[LOGIN SYNC WARNING] {e}")

    return {
        "success": True,
        "user": user,
        "sync_info": sync_info
    }


@app.get("/api/users")
def list_users(refresh: int = Query(0)):
    return {"users": gsheets_db.get_all_users(force_refresh=bool(refresh))}


@app.post("/api/users")
def add_user(req: CreateUserRequest):
    ok, msg = gsheets_db.create_user(req.username, req.password, req.full_name, req.role)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.delete("/api/users/{user_id}")
def remove_user(user_id: int):
    ok, msg = gsheets_db.delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.put("/api/users/{user_id}/password")
def change_user_password(user_id: int, req: ChangePasswordRequest):
    ok, msg = gsheets_db.update_user_password(user_id, req.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


# ----------------- VISION & SCANNING ENDPOINTS -----------------
@app.post("/api/scan-slip")
async def scan_slip(file: UploadFile = File(...)):
    image_bytes = await file.read()
    return parse_slip_image(image_bytes)


@app.post("/api/scan-bill")
async def scan_bill(file: UploadFile = File(...)):
    image_bytes = await file.read()
    return parse_bill_image(image_bytes)


@app.get("/api/lookup/{ln_code}")
def lookup_code(ln_code: str):
    res = catalog.lookup(ln_code)
    if res:
        return {"found": True, "item": res}
    return {"found": False, "message": f"Code {ln_code} not found in catalog"}


# ----------------- INVENTORY, SYNC & BACKUP ENDPOINTS -----------------
@app.post("/api/process-batch")
def process_batch(req: ProcessBatchRequest):
    if req.action not in ["IN", "OUT", "CAME_IN_AND_WENT_OUT"]:
        raise HTTPException(status_code=400, detail="Invalid action type")

    items_dict = [it.dict() for it in req.items]
    ok, details = gsheets_db.process_stock_batch(
        employee_username=req.username,
        action=req.action,
        source=req.source,
        items=items_dict,
        invoice_no=req.invoice_no,
        notes=req.notes
    )
    if not ok:
        raise HTTPException(status_code=500, detail=str(details))

    return {
        "success": True,
        "processed": details,
        "gsheet_synced": True,
        "gsheet_message": "Saved permanently to Google Sheets",
        "synced_at": gsheets_db.get_last_synced_at()
    }


@app.post("/api/sync-from-sheets")
def sync_from_sheets():
    try:
        info = gsheets_db.sync_from_sheets(include_logs=True)
        return {
            "success": True,
            "message": f"Synced {info['inventory_count']} items ({info['total_units']} units) from Google Sheet",
            "sync_info": info
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@app.get("/api/inventory")
def get_inventory(search: str = "", refresh: int = Query(0), role: str = Query("employee")):
    include_prices = (role or "").strip().lower() == "admin"
    items = gsheets_db.get_inventory_list(
        search=search,
        force_refresh=bool(refresh),
        include_prices=include_prices
    )
    return {
        "inventory": items,
        "synced_at": gsheets_db.get_last_synced_at(),
        "sheet_id": gsheets_db.spreadsheet_id,
        "storage_mode": "google_sheets_primary"
    }


@app.post("/api/inventory/delete-batch")
def delete_inventory_batch(req: DeleteInventoryBatchRequest):
    ok, msg, deleted = gsheets_db.delete_inventory_batch(req.ln_codes, employee_username=req.username or "admin")
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {
        "success": True,
        "message": msg,
        "deleted": deleted,
        "synced_at": gsheets_db.get_last_synced_at()
    }


@app.delete("/api/inventory/{ln_code}")
def delete_inventory_item(ln_code: str, username: str = Query("admin")):
    ok, msg, deleted = gsheets_db.delete_inventory_item(ln_code, employee_username=username)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {
        "success": True,
        "message": msg,
        "deleted": deleted,
        "synced_at": gsheets_db.get_last_synced_at()
    }


@app.get("/api/logs")
def get_logs(limit: int = 150, action: Optional[str] = None, employee: Optional[str] = None, refresh: int = Query(0), role: str = Query("")):
    if (role or "").strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Audit logs are strictly restricted to admin users.")
    return {
        "logs": gsheets_db.get_audit_logs(
            limit=limit, action=action, employee=employee, force_refresh=bool(refresh)
        )
    }


@app.post("/api/admin/match-preview")
def match_names_preview(req: MatchPreviewRequest):
    results = []
    for raw in req.names:
        clean = (raw or "").strip()
        if not clean:
            continue
        match = catalog.match_name(clean)
        if match:
            it = match["item"]
            results.append({
                "input_name": clean,
                "matched": True,
                "ln_code": it["ln_code"],
                "description": it["description"],
                "category": it["category"],
                "consumer_price": it["consumer_price"],
                "score": match["score"]
            })
        else:
            results.append({
                "input_name": clean,
                "matched": False,
                "ln_code": None,
                "description": clean,
                "category": "",
                "consumer_price": 0.0,
                "score": 0.0
            })
    return {"results": results}


@app.post("/api/admin/reconcile-ledger")
def reconcile_ledger(role: str = Query("admin"), username: str = Query("admin")):
    if (role or "").strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admins can reconcile ledger.")
    ok, msg, summary = gsheets_db.reconcile_and_reorganize_ledger(employee_username=username)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg, "summary": summary}


@app.post("/api/admin/import-historical")
def import_historical(req: HistoricalImportRequest, role: str = Query("admin")):
    if (role or "").strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admins can import historical data.")
    items_dict = [it.dict() for it in req.items]
    ok, msg, summary = gsheets_db.import_historical_batch(items_dict, employee_username=req.username or "admin")
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg, "summary": summary}


@app.get("/api/backups")
def list_backups():
    try:
        return {"success": True, **gsheets_db.get_backup_summary()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backup-now")
def backup_now():
    ok, msg, details = gsheets_db.create_backup_snapshot(trigger="MANUAL")
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg, "backup": details}


@app.post("/api/restore-backup")
def restore_backup(req: RestoreRequest):
    ok, msg = gsheets_db.restore_from_backup_latest(restored_by=req.username or "admin")
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}


@app.get("/api/export-excel")
def download_excel(role: str = Query("employee")):
    include_prices = (role or "").strip().lower() == "admin"
    temp_dir = tempfile.gettempdir()
    suffix = "Admin" if include_prices else "Staff"
    excel_path = os.path.join(temp_dir, f"Godrej_Inventory_Export_{suffix}.xlsx")
    gsheets_db.export_inventory_excel(excel_path, include_prices=include_prices)
    return FileResponse(
        excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Godrej_Inventory_Live.xlsx"
    )


# ----------------- SETTINGS ENDPOINTS -----------------
@app.get("/api/settings")
def get_app_settings():
    is_groq_configured = bool(os.getenv("GROQ_API_KEY") or gsheets_db.get_setting("groq_api_key"))
    gsheet_ok, gsheet_msg = gsheets_db.connect()
    last_backup = gsheets_db.get_setting("last_backup_at", "Never") if gsheet_ok else "Unavailable"
    return {
        "is_groq_configured": is_groq_configured,
        "groq_status": "Active & Secured" if is_groq_configured else "Not Set",
        "is_gsheet_configured": gsheet_ok,
        "gsheet_status": gsheet_msg,
        "gsheet_id": gsheets_db.spreadsheet_id,
        "storage_mode": "Google Sheets Primary (Persistent)",
        "synced_at": gsheets_db.get_last_synced_at(),
        "last_backup_at": last_backup,
        "total_catalog_items": len(catalog.items)
    }


@app.post("/api/settings")
def update_app_settings(req: SettingRequest):
    gsheets_db.set_setting(req.key, req.value.strip())
    return {"success": True, "message": f"Setting {req.key} saved permanently to Google Sheets"}


# ----------------- STATIC ASSETS -----------------
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Godrej Inventory API is running."}
