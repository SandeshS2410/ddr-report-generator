"""
DDR Report Generator - FastAPI Backend
Extracts text + images from uploaded PDFs/images and generates DDR via Claude API
"""

import os
import io
import base64
import json
import asyncio
from typing import Optional
from datetime import date

import anthropic
import fitz  # PyMuPDF
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image

app = FastAPI(title="DDR Report Generator API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── DDR System Prompt ───────────────────────────────────────────────────────

DDR_SYSTEM_PROMPT = f"""You are an expert building inspection analyst. Your task is to read provided inspection and thermal documents and generate a professional Detailed Diagnostic Report (DDR) for the client.

Today's date: {date.today().strftime('%B %d, %Y')}

STRICT RULES:
- NEVER invent facts not present in the documents
- If data conflicts between documents, explicitly mention the conflict with: [CONFLICT: describe it]
- If information is missing or not found, write "Not Available"
- Use simple, client-friendly language — avoid unnecessary jargon
- Do not duplicate observations across sections
- Be concise and precise
- For each area observation, if images were extracted from that section, reference them as [Image-X] where X is the image number

Generate the DDR with EXACTLY this structure:

═══════════════════════════════════════════════════════
DETAILED DIAGNOSTIC REPORT (DDR)
Date: {date.today().strftime('%B %d, %Y')}
═══════════════════════════════════════════════════════

1. PROPERTY ISSUE SUMMARY
─────────────────────────
[2–4 sentence executive overview: total issues found, severity distribution, property type/location if mentioned]

2. AREA-WISE OBSERVATIONS
──────────────────────────
[For each distinct area/zone/component identified:]

■ [Area Name]
  Observations: [detailed findings]
  Thermal Data: [temperature readings or anomalies, or "Not Available"]
  Visual Evidence: [reference image numbers if applicable, e.g. [Image-1], [Image-2], or "Not Available"]
  Condition: [Critical / Poor / Fair / Good]

3. PROBABLE ROOT CAUSE
───────────────────────
[For each identified issue, state the most likely cause based only on document evidence]
• [Issue]: [Root cause analysis]

4. SEVERITY ASSESSMENT
───────────────────────
Issue | Location | Severity | Reasoning
[List each issue with severity: Critical / High / Medium / Low and brief reasoning]

5. RECOMMENDED ACTIONS
───────────────────────
[URGENT — Immediate action required]
• [action items]

[SHORT-TERM — Within 1–3 months]
• [action items]

[LONG-TERM — Planned maintenance]
• [action items]

6. ADDITIONAL NOTES
────────────────────
[Any anomalies, contextual observations, or secondary findings not captured above]

7. MISSING OR UNCLEAR INFORMATION
───────────────────────────────────
[Explicitly list expected but absent data. Use "Not Available" for each item]
• Property address: [value or "Not Available"]
• Inspection date: [value or "Not Available"]
• Inspector name/credentials: [value or "Not Available"]
• [Any other expected but missing fields]

═══════════════════════════════════════════════════════
END OF REPORT
═══════════════════════════════════════════════════════"""


# ─── Document Processing ─────────────────────────────────────────────────────

def pdf_to_content_blocks(pdf_bytes: bytes, label: str) -> tuple[list, list[dict]]:
    """
    Extract text pages + images from a PDF.
    Returns (api_content_blocks, extracted_images_metadata)
    """
    blocks = []
    images_meta = []
    img_counter = [0]

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        blocks.append({
            "type": "text",
            "text": f"\n\n{'='*60}\nDOCUMENT: {label}\n{'='*60}\n"
        })

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Extract text
            text = page.get_text("text").strip()
            if text:
                blocks.append({
                    "type": "text",
                    "text": f"\n[Page {page_num + 1}]\n{text}\n"
                })

            # Extract images
            image_list = page.get_images(full=True)
            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    img_bytes = base_image["image"]
                    img_ext = base_image["ext"]

                    # Convert to JPEG for API efficiency
                    pil_img = Image.open(io.BytesIO(img_bytes))
                    if pil_img.mode in ("RGBA", "P", "LA"):
                        pil_img = pil_img.convert("RGB")

                    # Resize if too large
                    max_dim = 1024
                    if max(pil_img.size) > max_dim:
                        pil_img.thumbnail((max_dim, max_dim), Image.LANCZOS)

                    buf = io.BytesIO()
                    pil_img.save(buf, format="JPEG", quality=85)
                    img_b64 = base64.b64encode(buf.getvalue()).decode()

                    img_counter[0] += 1
                    img_num = img_counter[0]

                    blocks.append({
                        "type": "text",
                        "text": f"\n[Image-{img_num} from {label}, Page {page_num + 1}]\n"
                    })
                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64
                        }
                    })

                    images_meta.append({
                        "id": f"Image-{img_num}",
                        "source": label,
                        "page": page_num + 1,
                        "data": img_b64
                    })
                except Exception:
                    pass

        doc.close()
    except Exception as e:
        blocks.append({"type": "text", "text": f"[Could not fully parse {label}: {str(e)}]"})

    return blocks, images_meta


def image_to_content_blocks(img_bytes: bytes, label: str, mime_type: str) -> tuple[list, list[dict]]:
    """Handle direct image uploads (non-PDF)."""
    try:
        pil_img = Image.open(io.BytesIO(img_bytes))
        if pil_img.mode in ("RGBA", "P", "LA"):
            pil_img = pil_img.convert("RGB")
        max_dim = 1200
        if max(pil_img.size) > max_dim:
            pil_img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=85)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        img_b64 = base64.b64encode(img_bytes).decode()

    blocks = [
        {"type": "text", "text": f"\n\n{'='*60}\nDOCUMENT: {label}\n{'='*60}\n[Image-1 from {label}]\n"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}}
    ]
    images_meta = [{"id": "Image-1", "source": label, "page": 1, "data": img_b64}]
    return blocks, images_meta


# ─── API Endpoint ─────────────────────────────────────────────────────────────

@app.post("/generate-ddr")
async def generate_ddr(
    inspection_report: UploadFile = File(...),
    thermal_report: UploadFile = File(...),
    api_key: str = Form(...)
):
    if not api_key.startswith("sk-"):
        raise HTTPException(status_code=400, detail="Invalid API key format")

    # Read both files
    inspection_bytes = await inspection_report.read()
    thermal_bytes = await thermal_report.read()

    # Process documents
    def process_file(file_bytes, filename, label):
        ext = filename.lower().split(".")[-1]
        if ext == "pdf":
            return pdf_to_content_blocks(file_bytes, label)
        else:
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            return image_to_content_blocks(file_bytes, label, mime)

    insp_blocks, insp_images = process_file(
        inspection_bytes, inspection_report.filename, "Inspection Report"
    )
    thermal_blocks, thermal_images = process_file(
        thermal_bytes, thermal_report.filename, "Thermal Report"
    )

    all_images = insp_images + thermal_images

    # Build API content
    user_content = (
        insp_blocks
        + thermal_blocks
        + [{
            "type": "text",
            "text": (
                f"\nTotal images extracted: {len(all_images)} "
                f"({len(insp_images)} from Inspection Report, {len(thermal_images)} from Thermal Report).\n"
                "Please generate the complete DDR report following your instructions exactly. "
                "Reference extracted images by their [Image-X] labels where relevant in Area-wise Observations."
            )
        }]
    )

    # Call Claude API
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=DDR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}]
        )
        report_text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid API key")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again shortly.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude API error: {str(e)}")

    return JSONResponse({
        "report": report_text,
        "images": [
            {"id": img["id"], "source": img["source"], "page": img["page"], "data": img["data"]}
            for img in all_images
        ],
        "stats": {
            "total_images": len(all_images),
            "inspection_images": len(insp_images),
            "thermal_images": len(thermal_images),
        }
    })


@app.get("/health")
def health():
    return {"status": "ok", "service": "DDR Report Generator"}
