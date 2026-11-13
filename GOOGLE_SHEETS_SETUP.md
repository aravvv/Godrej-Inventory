# Connecting Your App to Google Sheets (Step-by-Step)

This guide shows you how to connect your inventory app to a live Google Sheet in 3 minutes so every scan (`IN`, `OUT`, `TRANSIT`) automatically updates your spreadsheet in real time.

---

### Step 1: Create a Google Sheet
1. Open [Google Sheets](https://sheets.new) and create a new blank spreadsheet.
2. Name it: **`Godrej_Inventory_Master`**
3. Look at your browser URL bar:
   `https://docs.google.com/spreadsheets/d/`**`1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms`**`/edit`
4. Copy the long code between `/d/` and `/edit`. That is your **`GOOGLE_SHEET_ID`**.

---

### Step 2: Get a Free Google Service Account Key
1. Go to **[Google Cloud Console](https://console.cloud.google.com/)**.
2. Create a new project (e.g. `godrej-inventory-sync`).
3. In the search bar at the top, search for **"Google Sheets API"** and click **Enable**.
4. In the left navigation, go to **APIs & Services** ➔ **Credentials**.
5. Click **+ CREATE CREDENTIALS** at the top ➔ Select **Service account**.
6. Give it a name (e.g. `inventory-sync`) and click **Create and Continue**, then click **Done**.
7. In the Service Accounts list, click on the email you just created (looks like `inventory-sync@godrej-inventory-12345.iam.gserviceaccount.com`).
8. Go to the **Keys** tab ➔ Click **Add Key** ➔ **Create new key** ➔ Select **JSON** ➔ Click **Create**.
9. A `.json` file will automatically download to your computer.

---

### Step 3: Share the Google Sheet with the Service Account
1. Open the downloaded `.json` file in Notepad and copy the `client_email` address.
2. Open your Google Sheet from Step 1.
3. Click the green **Share** button in the top right.
4. Paste the service account email and grant it **Editor** permissions.
5. Click **Send** (uncheck "Notify people").

---

### Step 4: Configure the App
#### For Local Testing:
1. Move the downloaded `.json` file into this folder (`c:\Users\aravg\Downloads\inventory_automation\`) and rename it to **`service_account.json`**.
2. Add your Sheet ID to your [`.env`](file:///c:/Users/aravg/Downloads/inventory_automation/.env) file:
   ```env
   GOOGLE_SHEET_ID=your_copied_sheet_id_here
   ```

#### For Hugging Face Spaces (Cloud Hosting):
In your Hugging Face Space ➔ **Settings** ➔ **Variables and secrets**:
* Add Secret: `GOOGLE_SHEET_ID` = `your_sheet_id`
* Add Secret: `GOOGLE_SERVICE_ACCOUNT_JSON` = *Paste the entire contents of the downloaded `.json` file*
* Add Secret: `GROQ_API_KEY` = `your_groq_key`

---

### What Happens Automatically:
Whenever any employee processes a batch:
- **`Live_Inventory` tab:** Automatically updates current stock counts by LN code (or creates a new row if new).
- **`Audit_Log` tab:** Appends a new timestamped row recording Employee Name, Action (`IN`/`OUT`/`TRANSIT`), LN code, Description, and Quantities.
