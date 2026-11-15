---
title: Godrej Inventory Automation
emoji: 📦
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Godrej Interio - Warehouse Inventory Automation System

An iPhone & Android-optimized, AI-powered warehouse scanning and inventory management application deployed on Vercel with Google Sheets as the primary real-time database.

> [!NOTE]
> **For AI Agents & Developers:** See [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) for the complete system architecture, business rules, API reference, database schema, and checkpoint handover details.

## Quick Links
- **Production URL:** [https://godrej-inventory.vercel.app/](https://godrej-inventory.vercel.app/)
- **Architecture & Handover Docs:** [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)
- **Google Sheet ID:** `1BF1RgdQVmffReUPSHnKoE-N_jQqmx02OOVXtNlxQ2sc`

## Features
- **IN Mode:** Instant bill scanning (multi-item table extraction) & cardboard packaging slip multi-scan batching.
- **OUT Mode:** Single & multi-slip barcode/product-code scanning with live catalog resolution. Preserves 0-stock products.
- **CAME IN & WENT OUT Mode:** Real-time pass-through / transit tracking with zero net inventory discrepancy.
- **Hold / Right-Click Multi-Select Deletion:** Safe deletion via hold or right-click, "Select All", and modal confirmation.
- **Live Google Sheets Primary DB:** Real-time transactions directly update `Live_Inventory` and `Audit_Log` in Indian Standard Time (IST).
- **Role-Based Access Control:** Admin dashboard with employee management, password reset for all accounts, audit trail (strictly restricted to admins), and 1-click Excel export.

## Environment Secrets Required (Vercel)
- `GROQ_API_KEY`: Your Groq API key (`gsk_...`)
- `GSHEETS_SERVICE_ACCOUNT_JSON`: The raw JSON string or base64 of your Google Cloud Service Account
- `GSHEETS_SPREADSHEET_ID`: `1BF1RgdQVmffReUPSHnKoE-N_jQqmx02OOVXtNlxQ2sc`
