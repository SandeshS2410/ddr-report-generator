from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import base64

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DDR_PROMPT = "You are an expert building inspection analyst. Read the provided documents and generate a professional DDR. STRICT RULES: Never invent facts. Write [CONFLICT:] for conflicts. Write Not Available for missing data. Use client-friendly language. Generate EXACTLY this structure:\n\n1. PROPERTY ISSUE SUMMARY\n2. AREA-WISE OBSERVATIONS (for each area: Observations, Thermal Data, Visual Evidence, Condition)\n3. PROBABLE ROOT CAUSE\n4. SEVERITY ASSESSMENT - Issue | Location | Severity | Reasoning\n5. RECOMMENDED ACTIONS - URGENT / SHORT-TERM / LONG-TERM\n6. ADDITIONAL NOTES\n7. MISSING OR UNCLEAR INFORMATION"

def get_mime(filename):
    ext = filename.lower().split(".")[-1]
    if ext in ("jpg", "jpeg"): return "image/jpeg"
    if ext == "png": return "image/png"
    return "application/pdf"

@app.post("/generate-ddr")
async def generate_ddr(
    inspection_report: UploadFile = File(...),
    thermal_report: UploadFile = File(...),
    api_key: str = Form(...)
):
    if not api_key.startswith("gsk_"):
        raise HTTPException(status_code=400, detail="Invalid Groq API key. It should start with 'gsk_'")

    insp = await inspection_report.read()
    thermal = await thermal_report.read()

    insp_b64 = base64.b64encode(insp).decode()
    thermal_b64 = base64.b64encode(thermal).decode()

    insp_mime = get_mime(inspection_report.filename)
    thermal_mime = get_mime(thermal_report.filename)

    # Build message with images if image files, else describe as docs
    content = []

    if "image" in insp_mime:
        content.append({"type": "text", "text": "DOCUMENT: Inspection Report"})
        content.append({"type": "image_url", "image_url": {"url": f"data:{insp_mime};base64,{insp_b64}"}})
    else:
        content.append({"type": "text", "text": f"DOCUMENT: Inspection Report\n[PDF file uploaded - please analyze based on filename: {inspection_report.filename}]"})

    if "image" in thermal_mime:
        content.append({"type": "text", "text": "DOCUMENT: Thermal Report"})
        content.append({"type": "image_url", "image_url": {"url": f"data:{thermal_mime};base64,{thermal_b64}"}})
    else:
        content.append({"type": "text", "text": f"DOCUMENT: Thermal Report\n[PDF file uploaded - please analyze based on filename: {thermal_report.filename}]"})

    content.append({"type": "text", "text": "Generate the complete DDR report based on the provided documents."})

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                    "messages": [
                        {"role": "system", "content": DDR_PROMPT},
                        {"role": "user", "content": content}
                    ],
                    "max_tokens": 4096
                }
            )
            response.raise_for_status()
            data = response.json()
            report = data["choices"][0]["message"]["content"]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse({
        "report": report,
        "images": [],
        "stats": {"total_images": 0, "inspection_images": 0, "thermal_images": 0}
    })

@app.get("/health")
def health():
    return {"status": "ok", "service": "DDR Report Generator"}
