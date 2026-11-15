# PROJECT CONTEXT & HANDOVER CHECKPOINT
**Project Name:** Godrej Interio - Warehouse Inventory Automation System  
**Last Updated:** 2026-11-16  
**Production URL:** [https://godrej-inventory.vercel.app/](https://godrej-inventory.vercel.app/)  
**GitHub Repository:** `https://github.com/aravvv/Godrej-Inventory.git` (Branch: `main`)  
**Target Platform:** Mobile (iPhone/Android warehouse floor scanning) & Desktop (Admin & Operations)

---

## 1. Quick Orientation for AI Agents

This document is the **single source of truth** for the architecture, business logic, design decisions, and active state of this repository. Any AI agent reading this file can immediately continue building, debugging, or deploying without needing prior conversation context.

### Essential Rules & Invariants:
1. **Google Sheets is the Primary Production Database** (`gsheets_db.py`). There is NO PostgreSQL or MySQL. Do NOT introduce an external DB unless requested. Local SQLite (`inventory.db`) was only used during early prototyping and has been migrated into the Google Sheet `Users` tab.
2. **Timezone is Indian Standard Time (IST, UTC+05:30)**: Vercel serverless containers run in UTC. Never use raw `datetime.now()` without timezone conversion. Always use `get_ist_now()` or `get_ist_now_str()` in `gsheets_db.py`.
3. **0-Stock Preservation**: Products whose stock drops to `0` via `OUT` or `CAME_IN_AND_WENT_OUT` must **remain in the Google Sheet `Live_Inventory`** with `Current Stock = 0`. They are NEVER deleted automatically. Rows are removed ONLY when an admin explicitly executes a deletion.
4. **No Inline Delete Buttons**: Do not add individual "Delete" buttons to product cards or table rows. Deletion is done via **Hold / Long-Press (~420ms)** or **Right-Click** multi-selection with the floating Selection Action Bar and confirmation modal.
5. **Audit Logs are Admin-Only**: The `GET /api/logs` endpoint and `#logsTab` in the frontend are **strictly restricted to admin users**. Non-admin requests receive `403 Forbidden`.
6. **Price Visibility**: Dealer Price is visible ONLY to admins in the Admin Panel and in Excel exports requested by admins. Employees see neither Dealer Price nor Consumer Price on their default views.
7. **Invoice/Bill Extraction (`vision.py`)**: The AI vision parser must read ONLY the **`QUANTITY` (`ECH`)** column from supplier invoices. It must **NEVER extract from the `No of Pkg` (Packages)** column.

---

## 2. System Architecture & Tech Stack

```mermaid
flowchart TD
    Client["Mobile Web / Desktop (SPA)\nstatic/index.html + app.js + styles.css"] -->|REST API| FastAPI["FastAPI Backend\napp.py (Vercel Serverless: api/index.py)"]
    FastAPI -->|Catalog Lookup (In-Memory)| Catalog["Godrej Catalog (9,458 SKUs)\ncatalog.py + CSV"]
    FastAPI -->|Vision OCR Extraction| Groq["Groq Vision API\nllama-3.2-11b-vision-preview\nvision.py"]
    FastAPI -->|Primary Storage & Sync| GSheets["Google Sheets Primary DB\ngsheets_db.py\nService Account Auth"]
    GSheets --> Tab1[("Live_Inventory")]
    GSheets --> Tab2[("Audit_Log")]
    GSheets --> Tab3[("Users")]
    GSheets --> Tab4[("Settings")]
    GSheets --> Tab5[("Backup_Latest & History")]
```

- **Backend**: Python 3.11+, FastAPI, Uvicorn, Gspread, OpenPyXL, Requests.
- **Frontend**: Vanilla JavaScript (Modern AI Workspace UI styling with glassmorphism/neumorphism accents), HTML5, CSS3, native device camera integration (`<input type="file" capture="environment">`).
- **Vision Model**: Groq API (`llama-3.2-11b-vision-preview`) via `vision.py`.
- **Hosting / CI/CD**: Vercel Serverless Functions (`vercel.json`, `api/index.py`). Commits pushed to `origin/main` automatically build and deploy.

---

## 3. Google Sheets Database Specification (`gsheets_db.py`)

**Spreadsheet ID:** `1BF1RgdQVmffReUPSHnKoE-N_jQqmx02OOVXtNlxQ2sc`  
**Authentication:** Service account credentials stored in `service_account.json` (or passed as base64/JSON string via `GSHEETS_SERVICE_ACCOUNT_JSON` environment variable on Vercel).

### Worksheets & Schemas:
1. **`Live_Inventory`**:
   - Columns: `LN Code`, `Product Description`, `Category`, `Sub Cat`, `Current Stock`, `Consumer Price (Rs)`, `Last Updated`, `Last Modified By`.
   - *Note*: SKU and Dealer Price columns were removed from the Google Sheet as requested.
   - In-place row updates use Google Sheets `batch_update` ranges. New items are appended. Rows with `0` stock remain in the sheet.
2. **`Audit_Log`**:
   - Append-only immutable ledger.
   - Columns: `Log ID`, `Timestamp`, `Employee`, `Action`, `Source`, `LN Code`, `Product Description`, `Quantity`, `Stock Before`, `Stock After`, `Invoice No`, `Notes`.
   - Actions: `IN`, `OUT`, `CAME_IN_AND_WENT_OUT`, `DELETE`, `SYSTEM_RESTORE`.
3. **`Users`**:
   - Columns: `ID`, `Username`, `Password Hash`, `Full Name`, `Role`, `Is Active`, `Created At`.
   - Default seeded accounts: `admin` (role: `admin`), default password `admin123`.
4. **`Settings`**:
   - Key-value config store (`groq_api_key`, `last_backup_at`, `last_auto_backup_date`).
5. **`Backup_Latest` & `Backup_History`**:
   - `Backup_Latest`: Exact mirror snapshot of `Live_Inventory` for quick rollback.
   - `Backup_History`: Append-only historical log of backup snapshots.

---

## 4. Key Feature Implementation Details

### A. Hold / Right-Click Multi-Selection & Batch Deletion
- **Touch / Mobile**: User presses and holds any product card for ~420ms (`handleItemPointerDown` / `handleItemPointerUp`). The app enters Selection Mode and plays haptic feedback if available.
- **Desktop**: Right-clicking (`oncontextmenu="App.handleItemContextMenu(event, ...)"`) or long-pressing enters Selection Mode.
- **Selection Mode State (`App.state.selectionMode`)**:
  - Cards and table rows display selection check circles.
  - Tapping any card or row toggles selection on/off.
  - Floating bar `#selectionActionBar` appears at the bottom with:
    - Selected counter badge: `X Selected`
    - `Select All` / `Deselect All` button (acts on currently visible/filtered items)
    - `Cancel` button (exits selection mode)
    - `Delete (X)` button (opens `#deleteStockModal`)
- **Deletion Execution (`POST /api/inventory/delete-batch`)**:
  - Calls `db.delete_inventory_batch(ln_codes, employee_username)`.
  - Deletes contiguous row ranges from **bottom to top** (`reversed(ranges)`) so row index shifting is completely avoided.
  - Writes `DELETE` audit entries to `Audit_Log` in a single batch.

### B. 0-Stock Handling & Live Pill Counters
- When a product reaches `0` stock:
  - Google Sheets retains the row with `Current Stock = 0`.
  - In the UI, product shows red `0 stock` badge.
  - Filter pills dynamically calculate live item counts:
    - `All Items (N)`
    - `In Stock (>0) (M)`
    - `Out of Stock (0) (K)`
  - Available on both Employee Live Inventory screen and Admin Live Inventory tab.

### C. Admin Security & Role Enforcement
- **Authentication**: JWT/Session stored in `localStorage` under `godrej_user`.
- **API Guard**: `GET /api/logs` explicitly checks `role == "admin"`. Returns `403 Forbidden` for non-admin accounts.
- **UI Guard**: Admin Panel button (`#adminShortcut`) is hidden for non-admins. Admin screen (`#adminScreen`) has 4 tabs:
  1. *Live Inventory*: Full inventory table with Dealer Price & Consumer Price.
  2. *Audit Logs*: Live searchable and filterable table with IST timestamps.
  3. *Staff & Employees*: User list with "+ Add Employee", Delete user, and **"Change Password"** modal (allows admin to update password for any employee account).
  4. *Backups & Recovery*: Point-in-time snapshot generator and 1-click restore.

### D. Vision & Invoice Slip Extraction (`vision.py`)
- Supported image sources:
  1. Cardboard Packaging Barcode Slips (scans 14-char alphanumeric Godrej codes, e.g. `56121403SD00226`).
  2. Multi-item Supplier Tax Invoices / Delivery Challans.
- **Critical Extraction Rule**: The prompt specifically instructs Groq Vision to extract the `QUANTITY` (`ECH`) column and ignore the `No of Pkg` column. If 1 package contains 3 items, the quantity is 3.

---

## 5. API Endpoints Map (`app.py`)

| Endpoint | Method | Role Required | Description |
|---|---|---|---|
| `/` | `GET` | Public | Serves `static/index.html` (SPA) |
| `/api/login` | `POST` | Public | Authenticates username/password against `Users` sheet |
| `/api/scan/slip` | `POST` | Any | Uploads slip image -> Groq Vision extraction |
| `/api/scan/bill` | `POST` | Any | Uploads bill image -> Multi-row item table extraction |
| `/api/lookup/{ln_code}` | `GET` | Any | Resolves 14-char code in 9,458-item memory catalog |
| `/api/process-batch` | `POST` | Any | Commits `IN`, `OUT`, or `CAME_IN_AND_WENT_OUT` stock batch to Google Sheets |
| `/api/inventory` | `GET` | Any | Returns live inventory list. Prices included only if `role=admin` |
| `/api/inventory/delete-batch` | `POST` | Admin/Staff | Deletes batch of selected LN codes from Google Sheets |
| `/api/inventory/{ln_code}` | `DELETE` | Admin/Staff | Deletes single LN code from Google Sheets |
| `/api/logs` | `GET` | **Admin Only** | Returns audit logs from `Audit_Log` tab. Returns 403 for non-admins |
| `/api/users` | `GET` | Admin | Lists all user accounts |
| `/api/users` | `POST` | Admin | Creates new employee account |
| `/api/users/{id}` | `DELETE` | Admin | Deletes employee account |
| `/api/users/{id}/password` | `PUT` | Admin | Resets/updates password for any account |
| `/api/backups` | `GET` | Admin | Lists backup history and snapshot metadata |
| `/api/backup-now` | `POST` | Admin | Takes immediate snapshot into `Backup_Latest` |
| `/api/restore-backup` | `POST` | Admin | Restores `Live_Inventory` from `Backup_Latest` |
| `/api/export-excel` | `GET` | Any | Generates styled `.xlsx` file. Includes prices only if `role=admin` |
| `/api/settings` | `GET` / `POST` | Admin | Reads/writes app settings |

---

## 6. Directory Structure

```text
inventory_automation/
├── api/
│   └── index.py                           # Vercel serverless entrypoint
├── static/
│   ├── index.html                         # SPA markup with Interio logo & modals
│   ├── styles.css                         # Modern AI UI with neumorphism/glassmorphism
│   ├── app.js                             # Frontend state machine & UI controller
│   └── interio_logo.svg                   # Official "interio by Godrej" SVG branding
├── app.py                                 # FastAPI application & API routers
├── catalog.py                             # In-memory CSV catalog indexing
├── gsheets_db.py                          # Primary Google Sheets ORM & transaction engine
├── vision.py                              # Groq Vision AI slip and invoice parser
├── newList_with_dealer_price_deduplicated.csv # 9,458 pre-indexed Godrej products
├── service_account.json                   # Google Service Account credentials (keep secure)
├── vercel.json                            # Vercel deployment & routing config
├── requirements.txt                       # Python dependencies
├── PROJECT_CONTEXT.md                     # THIS FILE (handover context checkpoint)
└── README.md                              # Project overview
```

---

## 7. How to Run Locally & How to Deploy

### Local Development:
```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run local development server
python -m uvicorn app:app --port 8000 --reload

# 3. Open in browser
http://localhost:8000
```

### Deploying Changes to Production:
The repository is hooked to Vercel via GitHub. Pushing to `origin/main` automatically triggers a production build:
```powershell
git add .
git commit -m "your descriptive commit message"
git push origin main
```
To verify the deployment:
```powershell
# Check HTTP status of live site
python -c "import requests; print(requests.get('https://godrej-inventory.vercel.app/').status_code)"
```

---

## 8. Summary of Recent Changes (Changelog)

- **Audit Logs Admin-Only Access**: Strictly restricted `GET /api/logs` to `role=admin` (403 Forbidden for others) and removed the public activity log card from staff screens.
- **Timezone Fix (IST)**: Converted all datetime logic in `gsheets_db.py` to use `timezone(timedelta(hours=5, minutes=30))` and batch-updated all existing 94 audit log timestamps and inventory timestamps in Google Sheets from UTC to IST.
- **Audit Logs View Restored**: Re-implemented `loadAuditLogs`, `filterAuditLogs`, and `renderAuditLogsTable` in `static/app.js` with live search and action filtering.
- **Hold / Right-Click Multi-Select Deletion**: Implemented pointer-events hold timer (~420ms) and desktop `contextmenu` listener with floating selection bar (`#selectionActionBar`), "Select All / Deselect All", and modal confirmation.
- **Batch Deletion Backend**: Added `delete_inventory_batch` in `gsheets_db.py` with bottom-up row deletion to prevent row index shifting.
- **0-Stock Preservation**: Ensured `Live_Inventory` keeps products when current stock drops to 0, and added live filter pill counts for `All Items`, `In Stock (>0)`, and `Out of Stock (0)`.
- **Supplier Invoice Quantity Fix**: Updated `vision.py` prompt and parser to strictly extract the `QUANTITY` (`ECH`) column and disregard `No of Pkg`.
- **Branding**: Added official `interio by Godrej` SVG logo in header and login screens.
- **Admin Password Reset**: Added modal and endpoint `PUT /api/users/{user_id}/password` enabling admins to change any user's password.
- **Column Cleanup**: Removed `SKU` and `Dealer Price` columns from Google Sheets `Live_Inventory`.
