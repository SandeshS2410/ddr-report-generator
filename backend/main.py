import base64
from datetime import date
import anthropic
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DDR_PROMPT = "You are an expert building inspection analyst. Read the provided documents and generate a professional DDR. STRICT RULES: Never invent facts. Write [CONFLICT:] for conflicts. Write Not Available for missing data. Use client-friendly language. Generate EXACTLY this structure:\n\n1. PROPERTY ISSUE SUMMARY\n2. AREA-WISE OBSERVATIONS (for each area: Observations, Thermal Data, Visual Evidence, Condition)\n3. PROBABLE ROOT CAUSE\n4. SEVERITY ASSESSMENT - Issue | Location | Severity | Reasoning\n5. RECOMMENDED ACTIONS - URGENT / SHORT-TERM / LONG-TERM\n6. ADDITIONAL NOTES\n7. MISSING OR UNCLEAR INFORMATION"

def build_blocks(file_bytes, filename, label):
    b64 = base64.b64encode(file_bytes).decode()
    ext = filename.lower().split(".")[-1]
    blocks = [{"type": "text", "text": f"\n\nDOCUMENT: {label}\n"}]
    if ext in ("jpg", "jpeg"):
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    elif ext == "png":
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
    else:
        blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}})
    return blocks

@app.post("/generate-ddr")
async def generate_ddr(inspection_report: UploadFile = File(...), thermal_report: UploadFile = File(...), api_key: str = Form(...)):
    if not api_key.startswith("sk-"):
        raise HTTPException(status_code=400, detail="Invalid API key")
    insp = await inspection_report.read()
    thermal = await thermal_report.read()
    content = build_blocks(insp, inspection_report.filename, "Inspection Report") + build_blocks(thermal, thermal_report.filename, "Thermal Report") + [{"type": "text", "text": "Generate the complete DDR report."}]
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=4096, system=DDR_PROMPT, messages=[{"role": "user", "content": content}])
        report = "".join(b.text for b in response.content if hasattr(b, "text"))
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid API key")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse({"report": report, "images": [], "stats": {"total_images": 0, "inspection_images": 0, "thermal_images": 0}})

@app.get("/health")
def health():
    return {"status": "ok", "service": "DDR Report Generator"}