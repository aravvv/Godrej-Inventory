# Deploying to Vercel (100% Free Forever)

Your project is now fully configured for **Vercel Serverless Python**. Follow these simple steps to deploy it live:

---

### Step 1: Push Project to GitHub
If you haven't initialized Git yet, run these commands in `c:\Users\aravg\Downloads\inventory_automation`:
```bash
git init
git add .
git commit -m "Initial commit for Godrej inventory system"
```
Then create a new repository on [github.com](https://github.com/new) and push your code:
```bash
git remote add origin https://github.com/<YOUR-USERNAME>/<REPO-NAME>.git
git branch -M main
git push -u origin main
```

---

### Step 2: Import into Vercel
1. Go to **[vercel.com](https://vercel.com)** and sign in with your GitHub account (100% free, no credit card).
2. Click **"Add New..."** ➔ **"Project"**.
3. Select your newly created GitHub repository and click **Import**.

---

### Step 3: Add Your Environment Variables
Before clicking Deploy, expand the **Environment Variables** section and add:

| Variable Name | Value |
| :--- | :--- |
| `GROQ_API_KEY` | *(Your Groq key: `gsk_...`)* |
| `GOOGLE_SHEET_ID` | *(Optional: your Google Sheet ID)* |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | *(Optional: contents of service account JSON)* |

---

### Step 4: Click Deploy!
Vercel will build and launch your application in ~45 seconds.

You will get an instant, permanent HTTPS production URL:
`https://<YOUR-PROJECT-NAME>.vercel.app`

### Why Vercel is Ideal:
- **Instant Response (Zero Sleep):** Never sleeps or goes inactive.
- **Global CDN:** Lightning fast on all iPhones and Android phones.
- **Automatic HTTPS:** Phone camera permissions work right out of the box.
- **Auto-Sync:** Every inventory update syncs to your live Google Sheet in real time.
