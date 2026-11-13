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

An iPhone-optimized, AI-powered warehouse scanning and inventory management application.

## Features
- **IN Mode:** Instant bill scanning (multi-item table extraction) & cardboard packaging slip multi-scan batching.
- **OUT Mode:** Single & multi-slip barcode/product-code scanning with live catalog resolution.
- **CAME IN & WENT OUT Mode:** Real-time pass-through / transit tracking with zero net inventory discrepancy.
- **Live Google Sheets Synchronization:** Every batch is synchronized automatically with your Google Sheet `Live_Inventory` and `Audit_Log` tabs.
- **Role-Based Access:** Admin dashboard with employee account creation, audit trail, and 1-click Excel export.

## Environment Secrets Required
Set these in your Hugging Face Space **Settings -> Variables and secrets**:
- `GROQ_API_KEY`: Your Groq API key (`gsk_...`)
- `GOOGLE_SHEET_ID`: The ID of your Google Sheet from its URL (`https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`)
- `GOOGLE_SERVICE_ACCOUNT_JSON`: The raw JSON string of your Google Cloud Service Account
