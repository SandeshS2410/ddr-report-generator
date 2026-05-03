# Deployment Guide — DDR Report Generator

## Step 1: Push to GitHub

```bash
cd ddr-report-generator
git init
git add .
git commit -m "Initial commit: DDR Report Generator"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/ddr-report-generator.git
git push -u origin main
```

---

## Step 2: Deploy Backend to Render

1. Go to https://render.com and sign up / log in
2. Click **New +** → **Web Service**
3. Connect your GitHub account → select `ddr-report-generator`
4. Fill in settings:
   - **Name:** `ddr-backend`
   - **Root Directory:** `backend`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Click **Create Web Service**
6. Wait ~3 minutes for deployment
7. Copy your live URL: `https://ddr-backend.onrender.com`

Test it: `https://ddr-backend.onrender.com/health` → should return `{"status":"ok"}`

---

## Step 3: Deploy Frontend to Vercel

1. Go to https://vercel.com and sign up / log in
2. Click **Add New Project** → Import `ddr-report-generator`
3. Settings:
   - **Framework Preset:** Create React App
   - **Root Directory:** `frontend`
   - **Environment Variables:**
     - Key: `REACT_APP_API_URL`
     - Value: `https://ddr-backend.onrender.com`  ← your Render URL
4. Click **Deploy**
5. Wait ~2 minutes
6. Your live URL: `https://ddr-report-generator.vercel.app`

---

## Done!

Your live links:
- **Frontend (app):** https://ddr-report-generator.vercel.app
- **Backend (API):** https://ddr-backend.onrender.com
- **Health check:** https://ddr-backend.onrender.com/health

---

## Local Development (no Docker)

```bash
# Terminal 1 — Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm start
```

App runs at http://localhost:3000

---

## Notes

- Render free tier spins down after 15 min inactivity — first request may take ~30 sec to wake
- Vercel free tier is always-on for frontend
- Never commit your API key — users enter it at runtime
