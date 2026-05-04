# DDR Report Generator

An AI-powered system that converts raw building inspection documents into structured, client-ready Detailed Diagnostic Reports (DDR).

Built for the AI Generalist | Applied AI Builder assignment.

## Live Links

- Live App: https://ddr-report-generator-zeta.vercel.app
- Backend API: https://ddr-backend-5ter.onrender.com
- Health Check: https://ddr-backend-5ter.onrender.com/health
- GitHub: https://github.com/SandeshS2410/ddr-report-generator

Note for evaluator: Backend is on Render free tier and sleeps after 15 min inactivity. Visit the health check URL first, wait for ok, then open the live app.

## What It Does

Upload two documents and get a complete DDR in under 60 seconds.

- Accepts Inspection Report and Thermal Report as PDF or image
- Extracts all text and all embedded images from both PDFs using PyMuPDF
- Merges data from both documents intelligently with no duplication
- Generates a structured 7-section DDR using Llama 4 via Groq API
- Displays extracted images in a gallery with lightbox viewer
- Handles missing data with explicit Not Available - never hallucinates
- Flags conflicting data with [CONFLICT:] markers

Real Performance on Sample Documents:
- 1926 total images extracted (126 from Inspection, 1800 from Thermal)
- Full DDR generated in under 60 seconds

## Architecture

User uploads 2 PDFs
Backend: PyMuPDF extracts text and images page by page
Smart truncation: prioritises key inspection keywords
Groq API Llama 4: receives content and generates DDR
Frontend: renders structured report and image gallery

Tech Stack:
- Frontend: React 18 deployed on Vercel
- Backend: FastAPI Python deployed on Render
- PDF Parsing: PyMuPDF
- AI Engine: Llama 4 Scout via Groq API (free)

## DDR Output - 7 Sections

1. Property Issue Summary
2. Area-wise Observations with thermal data and image references
3. Probable Root Cause
4. Severity Assessment - Critical / High / Medium / Low
5. Recommended Actions - Urgent / Short-term / Long-term
6. Additional Notes
7. Missing or Unclear Information

## Run Locally

Backend:
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

Frontend:
cd frontend
npm install
npm start

Get a free Groq API key at console.groq.com (starts with gsk_)

## Limitations

- Large PDFs are smart-truncated - key inspection keywords are prioritised
- Images referenced by ID in report text - direct embedding needs a future Word/PDF export step
- Render free tier sleeps after 15 min - first request takes around 30 seconds to wake

## How I Would Improve It

- Export DDR as Word or PDF with images physically embedded in correct sections
- Streaming output for real-time report generation
- OCR support for scanned or handwritten documents
- Multi-language report output
- Batch processing for multiple properties

Built by Sandesh Singh - AI Generalist Applied AI Builder Assignment