# Deploying to Hugging Face Spaces (100% Free Forever)

This repository is already configured with a `Dockerfile`, `requirements.txt`, and Hugging Face metadata. Follow these 4 simple steps to deploy it live to the cloud:

---

### Step 1: Create a Free Hugging Face Account
1. Go to [huggingface.co](https://huggingface.co/join) and create a free account if you don't have one.

---

### Step 2: Create a New Space
1. Click on your profile icon (top right) ➔ Select **New Space**.
2. **Space name:** e.g. `godrej-inventory`
3. **License:** `mit` or `apache-2.0`
4. **Select the Space SDK:** Choose **Docker** ➔ Select **Blank**.
5. **Space Hardware:** Leave as **CPU basic • 2 vCPU • 16 GB • Free**.
6. Click **Create Space**.

---

### Step 3: Upload the Project Files
You can either upload the files via the web UI or Git:

#### Method A: Direct Web Upload (Easiest)
In your newly created Space:
1. Click on the **Files** tab ➔ Click **+ Add file** ➔ **Upload files**.
2. Drag and drop all the files from this folder (`c:\Users\aravg\Downloads\inventory_automation\`):
   - `Dockerfile`
   - `README.md`
   - `requirements.txt`
   - `app.py`
   - `catalog.py`
   - `database.py`
   - `vision.py`
   - `gsheets_sync.py`
   - `newList_with_dealer_price_deduplicated.csv`
   - `static/` (upload the entire folder with `index.html`, `app.js`, `styles.css`)
3. Click **Commit changes to main**.

#### Method B: Git Push (For Developers)
```bash
git init
git remote add origin https://huggingface.co/spaces/<YOUR-USERNAME>/godrej-inventory
git add .
git commit -m "Deploy Godrej inventory system"
git push -u origin main
```

---

### Step 4: Add Your Secret Variables
In your Hugging Face Space:
1. Go to **Settings** (top right of the space).
2. Scroll down to **Variables and secrets**.
3. Under **Secrets**, click **New secret**:
   - Name: `GROQ_API_KEY`
   - Value: *(Your Groq API key: `gsk_...`)*
4. If connecting Google Sheets (see `GOOGLE_SHEETS_SETUP.md`):
   - Add Secret: `GOOGLE_SHEET_ID` = `your_sheet_id`
   - Add Secret: `GOOGLE_SERVICE_ACCOUNT_JSON` = *(Contents of your downloaded Google service account JSON)*

---

### Step 5: You're Live!
Hugging Face will automatically build your Docker container in ~2 minutes and display:
**`Running` (Green badge)**.

Your permanent public URL will be:
`https://<YOUR-USERNAME>-godrej-inventory.hf.space`

You and your warehouse staff can now open this URL from any phone, iPhone, tablet, or desktop anywhere in the world!
