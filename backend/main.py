import base64
import io
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import fitz  

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DDR_PROMPT = "You are an expert building inspection analyst. Read the provided documents and generate a professional DDR. STRICT RULES: Never invent facts. Write [CONFLICT:] for conflicts. Write Not Available for missing data. Use client-friendly language. Generate EXACTLY this structure:\n\n1. PROPERTY ISSUE SUMMARY\n2. AREA-WISE OBSERVATIONS (for each area: Observations, Thermal Data, Visual Evidence, Condition)\n3. PROBABLE ROOT CAUSE\n4. SEVERITY ASSESSMENT - Issue | Location | Severity | Reasoning\n5. RECOMMENDED ACTIONS - URGENT / SHORT-TERM / LONG-TERM\n6. ADDITIONAL NOTES\n7. MISSING OR UNCLEAR INFORMATION"

def get_mime(filename):
    ext = filename.lower().split(".")[-1]
    if ext in ("jpg", "jpeg"): return "image/jpeg"
    if ext == "png": return "image/png"
    return "application/pdf"

def extract_from_pdf(file_bytes, source_label):
    """Extract text and images from PDF using PyMuPDF"""
    text = ""
    images = []
    
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        
        # Extract text
        for page in doc:
            text += page.get_text()
        
        # Extract images
        for page_num, page in enumerate(doc):
            image_list = page.get_images(full=True)
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                mime_type = f"image/{image_ext}" if image_ext != "jpg" else "image/jpeg"
                b64_image = base64.b64encode(image_bytes).decode()
                images.append({
                    "id": f"{source_label}_p{page_num+1}_img{img_index+1}",
                    "data": b64_image,
                    "mime_type": mime_type,
                    "source": source_label,
                    "page": page_num + 1
                })
        
        doc.close()
    except Exception as e:
        text = f"[Could not extract text from PDF: {str(e)}]"
    
    return text, images

@app.post("/generate-ddr")
async def generate_ddr(
    inspection_report: UploadFile = File(...),
    thermal_report: UploadFile = File(...),
    api_key: str = Form(...)
):
    if not api_key.startswith("gsk_"):
        raise HTTPException(status_code=400, detail="Invalid Groq API key.")

    insp_bytes = await inspection_report.read()
    thermal_bytes = await thermal_report.read()

    insp_mime = get_mime(inspection_report.filename)
    thermal_mime = get_mime(thermal_report.filename)

    all_images = []
    content = []

    # ── Process Inspection Report ──
    if "pdf" in insp_mime:
        insp_text, insp_images = extract_from_pdf(insp_bytes, "Inspection")
        all_images.extend(insp_images)
        content.append({"type": "text", "text": f"DOCUMENT: Inspection Report\n\n{insp_text}"})
        # Add extracted images to content
        for img in insp_images[:3]:  # max 3 images per doc
            content.append({"type": "text", "text": f"[Image from Inspection Report - Page {img['page']}]"})
            content.append({"type": "image_url", "image_url": {"url": f"data:{img['mime_type']};base64,{img['data']}"}})
    else:
        insp_b64 = base64.b64encode(insp_bytes).decode()
        content.append({"type": "text", "text": "DOCUMENT: Inspection Report"})
        content.append({"type": "image_url", "image_url": {"url": f"data:{insp_mime};base64,{insp_b64}"}})
        all_images.append({
            "id": "inspection_img1",
            "data": insp_b64,
            "mime_type": insp_mime,
            "source": "Inspection",
            "page": 1
        })

    # ── Process Thermal Report ──
    if "pdf" in thermal_mime:
        thermal_text, thermal_images = extract_from_pdf(thermal_bytes, "Thermal")
        all_images.extend(thermal_images)
        content.append({"type": "text", "text": f"DOCUMENT: Thermal Report\n\n{thermal_text}"})
        for img in thermal_images[:3]:  # max 3 images per doc
            content.append({"type": "text", "text": f"[Image from Thermal Report - Page {img['page']}]"})
            content.append({"type": "image_url", "image_url": {"url": f"data:{img['mime_type']};base64,{img['data']}"}})
    else:
        thermal_b64 = base64.b64encode(thermal_bytes).decode()
        content.append({"type": "text", "text": "DOCUMENT: Thermal Report"})
        content.append({"type": "image_url", "image_url": {"url": f"data:{thermal_mime};base64,{thermal_b64}"}})
        all_images.append({
            "id": "thermal_img1",
            "data": thermal_b64,
            "mime_type": thermal_mime,
            "source": "Thermal",
            "page": 1
        })

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
        "images": all_images,
        "stats": {
            "total_images": len(all_images),
            "inspection_images": len([i for i in all_images if i["source"] == "Inspection"]),
            "thermal_images": len([i for i in all_images if i["source"] == "Thermal"])
        }
    })

@app.get("/health")
def health():
    return {"status": "ok", "service": "DDR Report Generator"}
