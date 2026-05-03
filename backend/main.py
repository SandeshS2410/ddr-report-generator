import base64
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google import genai
from google.genai import types

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DDR_PROMPT = "You are an expert building inspection analyst. Read the provided documents and generate a professional DDR. STRICT RULES: Never invent facts. Write [CONFLICT:] for conflicts. Write Not Available for missing data. Use client-friendly language. Generate EXACTLY this structure:\n\n1. PROPERTY ISSUE SUMMARY\n2. AREA-WISE OBSERVATIONS (for each area: Observations, Thermal Data, Visual Evidence, Condition)\n3. PROBABLE ROOT CAUSE\n4. SEVERITY ASSESSMENT - Issue | Location | Severity | Reasoning\n5. RECOMMENDED ACTIONS - URGENT / SHORT-TERM / LONG-TERM\n6. ADDITIONAL NOTES\n7. MISSING OR UNCLEAR INFORMATION"

@app.post("/generate-ddr")
async def generate_ddr(
    inspection_report: UploadFile = File(...),
    thermal_report: UploadFile = File(...),
    api_key: str = Form(...)
):
    if not api_key.startswith("AIza"):
        raise HTTPException(status_code=400, detail="Invalid Gemini API key.")

    insp = await inspection_report.read()
    thermal = await thermal_report.read()

    def get_mime(filename):
        ext = filename.lower().split(".")[-1]
        if ext in ("jpg", "jpeg"): return "image/jpeg"
        if ext == "png": return "image/png"
        return "application/pdf"

    try:
        client = genai.Client(api_key=api_key)

        contents = [
            types.Part(text="DOCUMENT: Inspection Report"),
            types.Part(inline_data=types.Blob(mime_type=get_mime(inspection_report.filename), data=insp)),
            types.Part(text="DOCUMENT: Thermal Report"),
            types.Part(inline_data=types.Blob(mime_type=get_mime(thermal_report.filename), data=thermal)),
            types.Part(text="Generate the complete DDR report.")
        ]

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=DDR_PROMPT,
                max_output_tokens=4096
            )
        )

        report = response.text

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
