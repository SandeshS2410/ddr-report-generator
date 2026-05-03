import base64
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import google.generativeai as genai

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DDR_PROMPT = "You are an expert building inspection analyst. Read the provided documents and generate a professional DDR. STRICT RULES: Never invent facts. Write [CONFLICT:] for conflicts. Write Not Available for missing data. Use client-friendly language. Generate EXACTLY this structure:\n\n1. PROPERTY ISSUE SUMMARY\n2. AREA-WISE OBSERVATIONS (for each area: Observations, Thermal Data, Visual Evidence, Condition)\n3. PROBABLE ROOT CAUSE\n4. SEVERITY ASSESSMENT - Issue | Location | Severity | Reasoning\n5. RECOMMENDED ACTIONS - URGENT / SHORT-TERM / LONG-TERM\n6. ADDITIONAL NOTES\n7. MISSING OR UNCLEAR INFORMATION"

def build_parts(file_bytes, filename):
    ext = filename.lower().split(".")[-1]
    if ext in ("jpg", "jpeg"):
        return [{"mime_type": "image/jpeg", "data": file_bytes}]
    elif ext == "png":
        return [{"mime_type": "image/png", "data": file_bytes}]
    else:
        return [{"mime_type": "application/pdf", "data": file_bytes}]

@app.post("/generate-ddr")
async def generate_ddr(
    inspection_report: UploadFile = File(...),
    thermal_report: UploadFile = File(...),
    api_key: str = Form(...)
):
    if not api_key.startswith("AIza"):
        raise HTTPException(status_code=400, detail="Invalid Gemini API key. It should start with 'AIza'")

    insp = await inspection_report.read()
    thermal = await thermal_report.read()

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=DDR_PROMPT
        )

        parts = []
        parts.append("DOCUMENT: Inspection Report\n")
        for p in build_parts(insp, inspection_report.filename):
            parts.append(genai.protos.Part(inline_data=genai.protos.Blob(mime_type=p["mime_type"], data=p["data"])))

        parts.append("DOCUMENT: Thermal Report\n")
        for p in build_parts(thermal, thermal_report.filename):
            parts.append(genai.protos.Part(inline_data=genai.protos.Blob(mime_type=p["mime_type"], data=p["data"])))

        parts.append("Generate the complete DDR report.")

        response = model.generate_content(parts)
        report = response.text

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse({
        "report": report,
        "images": [],
        "stats": {
            "total_images": 0,
            "inspection_images": 0,
            "thermal_images": 0
        }
    })

@app.get("/health")
def health():
    return {"status": "ok", "service": "DDR Report Generator"}
    
