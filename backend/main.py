"""
DDR Report Generator - Backend
Reads inspection + thermal PDFs, extracts all images with metadata,
sends structured context to LLM, returns report + images for frontend rendering.
Works generically on any similar inspection/thermal PDF pair.
"""

import base64
import re
import fitz  # PyMuPDF
import httpx
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="DDR Report Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "meta-llama/llama-4-scout-17b-16e-instruct"

SYSTEM_PROMPT = """You are a senior building inspection analyst writing a professional DDR (Detailed Diagnostic Report) for a client.

STRICT RULES:
1. NEVER invent facts. Only use information from the documents provided.
2. If information is missing write: Not Available
3. If information conflicts write: [CONFLICT: explain here]
4. Use simple, client-friendly language. Avoid unnecessary technical jargon.
5. Do NOT duplicate observations across sections.

IMAGE PLACEMENT RULES:
- You will receive an IMAGE MANIFEST listing every extracted image with its ID, type, page, and source.
- Place image references in your report using EXACTLY this format: {IMAGE:image_id}
- For each area observation, place the relevant images UNDER that specific area — not all together.
- For each area: place inspection_photo first, then thermal_scan, then visual_photo.
- Only reference images relevant to the observation being described.
- If no image exists for an area write: Image Not Available

OUTPUT FORMAT — use EXACTLY these section headers with ## prefix:

## 1. PROPERTY ISSUE SUMMARY
2-3 sentence executive summary of overall property condition.

## 2. AREA-WISE OBSERVATIONS
For EACH impacted area found in the documents create a subsection like this:

### Area: [Area Name]
**Observations:** what was found on the negative/impacted side
**Thermal Data:** temperature readings, hotspot/coldspot values if available, or Not Available
**Visual Evidence:**
{IMAGE:image_id_inspection_photo}
{IMAGE:image_id_thermal_scan}
{IMAGE:image_id_visual_photo}
**Condition:** Good / Fair / Poor / Critical

## 3. PROBABLE ROOT CAUSE
Explain the likely causes logically based on evidence only.

## 4. SEVERITY ASSESSMENT
| Area | Issue | Severity | Reasoning |
|------|-------|----------|-----------|
Fill one row per issue found.

## 5. RECOMMENDED ACTIONS
**URGENT (Immediate action required):**
- action item

**SHORT-TERM (Within 1-3 months):**
- action item

**LONG-TERM (Preventive/structural):**
- action item

## 6. ADDITIONAL NOTES
Any other relevant observations, checklist results, structural notes.

## 7. MISSING OR UNCLEAR INFORMATION
List any data that was absent or ambiguous. Write None if everything was clear.
"""


# ─── PDF Extraction ────────────────────────────────────────────────────────────

def extract_pdf_content(file_bytes: bytes, source_label: str):
    """
    Extract full text and all images from a PDF.

    Thermal PDFs have 2 images per page:
      img index 0 = thermal_scan (heat map)
      img index 1 = visual_photo (regular camera photo)

    Inspection PDFs: all images = inspection_photo
    """
    text   = ""
    images = []
    is_thermal = "thermal" in source_label.lower()

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")

        # Extract full text from every page
        for page in doc:
            text += page.get_text() + "\n"

        # Extract images from every page
        for page_num, page in enumerate(doc):
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                try:
                    xref       = img_info[0]
                    base_image = doc.extract_image(xref)
                    img_bytes  = base_image["image"]
                    img_ext    = base_image["ext"]

                    # Skip tiny icons/logos (under 8 KB)
                    if len(img_bytes) < 8_000:
                        continue

                    # Only allow jpeg and png
                    mime = "image/jpeg" if img_ext in ("jpg", "jpeg") else f"image/{img_ext}"
                    if mime not in ("image/jpeg", "image/png"):
                        continue

                    # Determine type:
                    # Thermal page: first image = heat map scan, second = visual photo
                    # Inspection page: all photos are inspection photos
                    if is_thermal:
                        img_type = "thermal_scan" if img_index == 0 else "visual_photo"
                    else:
                        img_type = "inspection_photo"

                    img_id = f"{source_label}_p{page_num + 1}_img{img_index + 1}"

                    images.append({
                        "id":        img_id,
                        "data":      base64.b64encode(img_bytes).decode(),
                        "mime_type": mime,
                        "source":    source_label,
                        "page":      page_num + 1,
                        "img_index": img_index + 1,
                        "img_type":  img_type,
                        "size_kb":   round(len(img_bytes) / 1024, 1),
                    })

                except Exception:
                    continue

        doc.close()

    except Exception as e:
        text = f"[PDF extraction error: {e}]"

    return text, images


# ─── Text Helpers ──────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Strip excess whitespace while keeping structure."""
    lines   = [l.strip() for l in text.split("\n") if l.strip()]
    result  = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                result.append("")
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False
    return "\n".join(result)


def cap_text(text: str, max_chars: int) -> str:
    """Trim text at a natural paragraph boundary near max_chars."""
    if len(text) <= max_chars:
        return text
    cut = text.rfind("\n\n", 0, max_chars)
    if cut == -1:
        cut = max_chars
    return text[:cut] + "\n\n[... truncated for length ...]"


def build_image_manifest(all_images: list) -> str:
    """
    Build a clear structured manifest for the AI so it knows
    exactly which image ID maps to which type and which area/page.
    Groups thermal images by page so the AI sees scan+photo pairs clearly.
    """
    if not all_images:
        return "No images extracted from documents."

    lines = [
        f"TOTAL IMAGES: {len(all_images)}",
        "Use EXACTLY this format to embed images: {IMAGE:image_id}",
        "Distribute images under their matching area section — do NOT group them all together.",
        "",
    ]

    # Inspection photos
    insp = [i for i in all_images if i["source"] == "Inspection"]
    if insp:
        lines.append(f"INSPECTION PHOTOS ({len(insp)}) — site photos showing visible damage/dampness/cracks:")
        for img in insp:
            lines.append(f"  {img['id']} | page {img['page']} | type: {img['img_type']} | {img['size_kb']} KB")
        lines.append("")

    # Thermal images grouped by page
    thermal = [i for i in all_images if i["source"] == "Thermal"]
    if thermal:
        lines.append(f"THERMAL IMAGES ({len(thermal)}) — each page = one scan location:")
        lines.append("  Rule: img1 on each page = thermal_scan (heat map), img2 = visual_photo (camera)")
        lines.append("")

        pages = {}
        for img in thermal:
            pages.setdefault(img["page"], []).append(img)

        for pg in sorted(pages.keys()):
            lines.append(f"  [Thermal Page {pg}]")
            for img in pages[pg]:
                lines.append(f"    {img['id']} | type: {img['img_type']} | {img['size_kb']} KB")

        lines.append("")

    
    return "\n".join(lines)


# ─── Main Endpoint ─────────────────────────────────────────────────────────────

@app.post("/generate-ddr")
async def generate_ddr(
    inspection_report: UploadFile = File(...),
    thermal_report:    UploadFile = File(...),
    api_key:           str        = Form(...),
):
    if not api_key.strip().startswith("gsk_"):
        raise HTTPException(status_code=400, detail="Invalid Groq API key format.")

    # Read files
    insp_bytes    = await inspection_report.read()
    thermal_bytes = await thermal_report.read()

    # Extract text + images
    insp_text,    insp_images    = extract_pdf_content(insp_bytes,    "Inspection")
    thermal_text, thermal_images = extract_pdf_content(thermal_bytes, "Thermal")

    insp_text    = clean_text(insp_text)
    thermal_text = clean_text(thermal_text)

    all_images     = insp_images + thermal_images
    image_manifest = build_image_manifest(all_images)

    # Cap text to stay within token limits — keep most useful content
    insp_text_capped    = cap_text(insp_text,    6000)
    thermal_text_capped = cap_text(thermal_text, 5000)

    user_message = f"""=== DOCUMENT 1: INSPECTION REPORT ===
{insp_text_capped}

=== DOCUMENT 2: THERMAL REPORT ===
{thermal_text_capped}

=== IMAGE MANIFEST ===
{image_manifest}

=== YOUR TASK ===
Generate a complete, accurate DDR report using ALL information above.
Follow the system instructions exactly for structure, image placement, and rules.
Place images using {{IMAGE:image_id}} under the correct area observation.
Every impacted area in the inspection report must have its own subsection in Section 2.
"""

    # Call Groq
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                GROQ_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key.strip()}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": user_message},
                    ],
                    "max_tokens":  4096,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            report = resp.json()["choices"][0]["message"]["content"]

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Groq API error {e.response.status_code}: {e.response.text[:400]}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse({
        "report": report,
        "images": [
            {
                "id":        img["id"],
                "data":      img["data"],
                "mime_type": img["mime_type"],
                "source":    img["source"],
                "page":      img["page"],
                "img_type":  img["img_type"],
                "size_kb":   img["size_kb"],
            }
            for img in all_images
        ],
        "stats": {
            "total_images":      len(all_images),
            "inspection_images": len(insp_images),
            "thermal_images":    len(thermal_images),
            "thermal_scans":     len([i for i in thermal_images if i["img_type"] == "thermal_scan"]),
            "visual_photos":     len([i for i in thermal_images if i["img_type"] == "visual_photo"]),
        },
    })


@app.get("/health")
def health():
    return {"status": "ok", "service": "DDR Report Generator v2"}
