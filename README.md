# DDR Report Generator

An AI-powered system that converts raw building inspection documents into structured, client-ready **Detailed Diagnostic Reports (DDR)** using Claude AI.

![DDR Report Generator](docs/screenshot.png)

## 🏗️ Architecture

```
ddr-report-generator/
├── frontend/          # React 18 web application
│   └── src/
│       ├── App.js     # Main UI — upload, generate, view report
│       └── App.css    # Dark industrial theme
├── backend/           # FastAPI Python backend
│   ├── main.py        # API server + PDF parsing + Claude integration
│   └── requirements.txt
└── README.md
```

**Flow:**
```
[User uploads 2 PDFs/images]
        ↓
[Backend: PyMuPDF extracts text + images from each document]
        ↓
[Claude API: receives all content, generates structured DDR]
        ↓
[Frontend: renders report in structured or raw view + image gallery]
```

## ✨ Features

- **Real image extraction** from PDFs using PyMuPDF — images are placed inline in the report
- **Dual document fusion** — merges Inspection Report + Thermal Report logically
- **7-section DDR output**: Property Summary → Area Observations → Root Cause → Severity Assessment → Recommended Actions → Notes → Missing Info
- **Conflict detection** — explicitly flags contradictions between documents
- **Missing data handling** — writes "Not Available" rather than hallucinating
- **Image gallery** — extracted images shown as thumbnails with lightbox viewer
- **Download / Copy** — export report as plain text
- **Generalises** to any similar inspection + thermal document pair

## 🚀 Deployment

### Option A: Local Development

**Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm start        # runs on http://localhost:3000
```

The frontend proxies `/generate-ddr` to `localhost:8000` via `package.json → proxy`.

---

### Option B: Deploy to Render (Backend) + Vercel (Frontend)

#### Backend → Render.com

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Settings:
   - **Root Directory:** `backend`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Environment:** Python 3.11
5. Deploy → copy your Render URL (e.g. `https://ddr-backend.onrender.com`)

#### Frontend → Vercel

1. Go to [vercel.com](https://vercel.com) → New Project → Import your repo
2. Settings:
   - **Root Directory:** `frontend`
   - **Framework Preset:** Create React App
   - **Environment Variable:** `REACT_APP_API_URL=https://ddr-backend.onrender.com`
3. Deploy → your live URL is ready

---

### Option C: Docker Compose (self-hosted)

```bash
docker-compose up --build
```
Frontend: http://localhost:3000  |  Backend: http://localhost:8000

---

## 🔑 API Key

Users provide their own Anthropic API key at runtime — it's sent directly to the Anthropic API and **never stored**. Get a key at [console.anthropic.com](https://console.anthropic.com).

## 📋 Input Document Requirements

| Field | Accepted Formats |
|-------|-----------------|
| Inspection Report | PDF, JPG, PNG |
| Thermal Report | PDF, JPG, PNG |

The system handles:
- Multi-page PDFs
- Embedded images at any position
- Handwritten notes (partially — depends on document quality)
- Missing sections (writes "Not Available")
- Conflicting data between documents (flags with `[CONFLICT: ...]`)

## 🔧 Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `REACT_APP_API_URL` | `""` (uses proxy) | Backend URL for production |
| `PORT` | `8000` | Backend listen port (set by Render automatically) |

## ⚠️ Known Limitations

1. **Image extraction is positional** — images are tagged by page number and referenced in the report by `[Image-X]` IDs; the AI places references where relevant but doesn't embed them directly inside text
2. **Handwritten or scanned PDFs** — text extraction quality depends on PDF type; use text-based PDFs for best results
3. **Very large PDFs (>50 pages)** — may approach Claude's context limit; trim to relevant sections if needed
4. **Report language** — currently English only

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Lucide icons |
| Backend | FastAPI, Python 3.11 |
| PDF Parsing | PyMuPDF (fitz) |
| Image Processing | Pillow |
| AI | Anthropic Claude claude-sonnet-4-20250514 |
| Deployment | Vercel (frontend) + Render (backend) |

## 📁 Project Structure

```
backend/
  main.py              # FastAPI app, PDF parsing, Claude integration
  requirements.txt     # Python dependencies

frontend/
  public/
    index.html         # HTML shell
  src/
    App.js             # Full React app (upload UI + report viewer)
    App.css            # Dark industrial CSS theme
  package.json         # Node dependencies + proxy config
```

## 🧪 Testing the System

Use any two of:
- A building inspection PDF with area-wise observations
- A thermal imaging report with temperature data

The system generalises — it doesn't require a specific template format. It reads whatever is provided and maps it to the DDR structure.

---

Built for the **AI Generalist | Applied AI Builder** assignment.  
Demonstrates: document parsing, multi-source fusion, structured AI output, missing/conflict handling, image extraction.
