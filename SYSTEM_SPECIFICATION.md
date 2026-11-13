# Godrej Warehouse Inventory Automation - System Specification & Blueprint

## 1. Executive Summary

This document specifies the end-to-end architecture, user workflows, data models, and technical requirements for automating inventory tracking (IN, OUT, and CAME IN & WENT OUT) for the Godrej firm.

The system will be delivered as an **iPhone-optimized Mobile Progressive Web App (PWA)** backed by a secure backend, integrating the master **Super Price List (CSV / Google Sheets)** and providing complete employee tracking and audit logs for the Admin.

---

## 2. Google Sheets API Pricing & Feasibility

> [!NOTE]
> **Google Sheets API is 100% FREE.**
> - Google Cloud does not charge for Google Sheets API calls.
> - Default free quotas:
>   - **300 requests per minute per project**
>   - **60 requests per minute per user**
> - For a warehouse setup (even with multiple staff members scanning concurrently), requests are batched and will easily stay well within the free limits.
> - **Verdict:** We will use **Google Sheets** as the primary live database, giving live visibility to managers and seamless export to Excel (`.xlsx`) at any moment.

---

## 3. Data Schema & Super Price List Mapping

Based on the verified master catalog (`newList_with_dealer_price_deduplicated.csv`, 9,462 Godrej items):

### Master Price List Columns
| Field Name | Description | Example Value |
| :--- | :--- | :--- |
| `Ln Code` | Primary Key / Unique identifier scanned on slips/bills | `56101522SD01909` |
| `Ln Description` | Product Name & Variant description | `Virtue FB Black Black Study` |
| `SKU` | Internal SKU reference | `SKUHO1803` |
| `Category` | Main category | `HOME CASUAL_GAMING_ SEATING` |
| `Sub Cat` | Sub-category | `HOME SEATING` |
| `HSN Code` | Tax / HSN code | `94013000` |
| `No. Of Packets` | Packets per unit | `1` |
| `Consumer Price` | Retail MRP / Consumer Price (₹) | `11504` |
| `Dealer price` | Purchase / Dealer Price (₹) | `8858` |

### Target Google Sheets Structure
1. **Sheet 1: `Master_Catalog`** (Read-only lookup from the CSV)
2. **Sheet 2: `Live_Inventory`**
   - `Ln Code`, `SKU`, `Product Description`, `Category`, `Sub Cat`, `Current Stock`, `Dealer Price`, `Consumer Price`, `Last Updated`, `Last Modified By`
3. **Sheet 3: `Audit_Log`**
   - `Log ID`, `Timestamp`, `Employee Username`, `Action (IN / OUT / CAME_IN_AND_WENT_OUT)`, `Source (BILL / SLIP_BATCH)`, `Ln Code`, `Product Description`, `Quantity`, `Notes`

---

## 4. User Roles & Access Control

### A. Admin Account
- **Authentication:** Admin username & password.
- **Features:**
  - Create, view, reset passwords, or deactivate employee accounts.
  - View real-time **Audit Logs** filtered by date, employee, product, or action type.
  - View & export live inventory to Excel (`.xlsx`).
  - Reload / sync updated Super Price List.

### B. Employee Accounts
- **Authentication:** Unique employee username/PIN created by Admin.
- **Interface:** Mobile-first, high-contrast, clean 3-button launcher:
  1. **IN** (Incoming stock)
  2. **OUT** (Outgoing stock)
  3. **CAME IN AND WENT OUT** (Cross-docking / Direct pass-through)

---

## 5. Detailed Functional Workflows

### 5.1 Mode 1: IN (Incoming Stock)
Allows two input options:
* **Option A: Bill Photo**
  1. Worker snaps a photo of the vendor invoice.
  2. System extracts all `Ln Code` values and quantities from the bill tables.
  3. Queries the Master Catalog to resolve item descriptions and details.
  4. Displays a structured preview of all detected items.
  5. Upon confirmation:
     - If the `Ln Code` exists in `Live_Inventory`: **Increments quantity**.
     - If the `Ln Code` is new: **Creates a new row** with product details and quantity.
     - Writes detailed entries to `Audit_Log`.
* **Option B: Cardboard Slip Photo (Multi-Slip Batch Queue)**
  1. Worker snaps a photo of a box slip.
  2. Image engine normalizes orientation (handles 90°/180°/270° rotation and iPhone EXIF data), isolates the `Ln Code` region, and extracts the code.
  3. Resolves product name from the Master Catalog.
  4. **Live Staging Queue:** The product name, LN code, and thumbnail appear instantly in a live list on screen.
  5. Worker snaps subsequent slips (#2, #3, etc.) — list expands live.
  6. Worker reviews the staged batch (can delete any accidental scan).
  7. Worker taps **"Process Batch"**: all items are committed to `Live_Inventory` and `Audit_Log`.

---

### 5.2 Mode 2: OUT (Outgoing Stock)
* Works via **Cardboard Slip Multi-Scan Batch** (no combined bill exists for outgoing goods).
* Same smart rotation, crop, and extraction pipeline.
* **Live Staging Queue:** Displays what product is being removed with visual confirmation.
* Checks available stock; alerts worker if an item has zero/low recorded stock.
* Upon batch confirmation: **Decrements quantity** in `Live_Inventory` and logs outgoing transaction in `Audit_Log`.

---

### 5.3 Mode 3: CAME IN AND WENT OUT (Direct Pass-through / Transit)
For inventory arriving at the warehouse that is dispatched immediately without staying in stock:
* Supports both **Bill Photo** and **Cardboard Slip Batch**.
* Shows live preview of matched products.
* Upon confirmation:
  - Records both an `IN` and `OUT` record in `Audit_Log`.
  - Maintains net-zero inventory count change while preserving complete serial/LN history.

---

## 6. iPhone (iOS Safari) Implementation Blueprint

1. **Camera Capture:**
   - HTML5 environment capture: `<input type="file" accept="image/*" capture="environment">` alongside optional live viewfinder.
   - Guaranteed compatibility across Safari on iOS 15, 16, 17, and 18 without canvas memory crashes.
2. **EXIF & Orientation Correction:**
   - Client/server EXIF reader to automatically re-orient photos taken sideways or upside-down.
   - Multi-rotation AI OCR parsing so warehouse staff do not have to hold the phone at a perfect angle.
3. **PWA Standalone Mode:**
   - Web App Manifest configured for full-screen display (`display: standalone`).
   - "Add to Home Screen" enabled with custom Godrej-themed app icon.

---

## 7. Next Milestones

1. **Step 1:** Ingest sample slip and bill images provided by the user.
2. **Step 2:** Fine-tune the LN code extraction logic (pattern matching `56101522SDxxxxx` and Godrej slip layout).
3. **Step 3:** Build the full-stack Mobile PWA (Backend + Frontend + Google Sheets connector).
