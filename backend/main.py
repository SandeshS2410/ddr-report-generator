"""
DDR Report Generator - Backend (v3, restructured)

Key design change from v2:
  - Inspection PDF is parsed into structured Area objects (name, negative/positive
    description, and the photos that belong to each side) using the document's own
    "Impacted Area N" / "Negative side Description" / "Photo N" structure, instead of
    treating every image as an undifferentiated blob.
  - Thermal PDF is parsed into one ThermalReading per page (thermal image, visual
    image, hotspot, coldspot) using the document's own per-page caption text.
  - Images are identified by their printed "Photo N" caption (matched by spatial
    proximity), not by raw extraction index. This is what actually fixes duplicate/
    mislabeled images: repeated "recap" thumbnails that PDFs sometimes render at the
    top of a new page have no caption near them, so they're correctly excluded,
    and decorative elements like a logo are excluded the same way.
  - There is no deterministic key linking thermal pages to inspection areas (verified:
    thermal pages carry no room label, and the file's internal photo order is not in
    the same order as the room order). So the link is established with a vision model
    call that compares each area's negative-side photo(s) against all thermal visual
    photos and returns an explicit confidence + reasoning, rather than being guessed
    by page position. Low-confidence matches are surfaced as "Not Available" rather
    than silently assigned, per the report's own "Not Available" / "[CONFLICT]" rules.
"""

import asyncio
import base64
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

import fitz  # PyMuPDF
import httpx
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="DDR Report Generator v3")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TEXT_MODEL   = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # multimodal capable

MIN_IMAGE_BYTES = 5_000          # filters genuinely tiny icons
MATCH_CONFIDENCE_THRESHOLD = 0.55  # below this, thermal data is "Not Available" for that area


# ─── Data model ─────────────────────────────────────────────────────────────

@dataclass
class ExtractedImage:
    id: str
    data: str            # base64
    mime_type: str
    page: int
    caption: Optional[str] = None   # e.g. "Photo 7", or None if uncaptioned/excluded
    size_kb: float = 0.0


@dataclass
class InspectionArea:
    area_index: int
    name: str                       # short room/area label parsed from the description
    negative_description: str
    negative_photos: list = field(default_factory=list)   # list[ExtractedImage]
    positive_description: str = ""
    positive_photos: list = field(default_factory=list)


@dataclass
class ThermalReading:
    page: int
    source_filename: Optional[str]
    thermal_image: Optional[ExtractedImage]
    visual_image: Optional[ExtractedImage]
    hotspot_c: Optional[float]
    coldspot_c: Optional[float]
    emissivity: Optional[float] = None
    reflected_temp_c: Optional[float] = None


# ─── Inspection PDF parsing ─────────────────────────────────────────────────

def _caption_for_image(page, img_bbox, caption_spans):
    """
    Find a 'Photo N' text span that sits directly below this image (same column,
    just beneath it). Returns the caption string or None if no caption is close
    enough — uncaptioned images (recap thumbnails, logos) are deliberately excluded
    by this returning None.
    """
    x0, y0, x1, y1 = img_bbox
    best = None
    best_dy = 999
    for span_text, (sx0, sy0, sx1, sy1) in caption_spans:
        # caption should start just below the image bottom, roughly aligned in x
        x_overlap = min(x1, sx1) - max(x0, sx0)
        if x_overlap < (x1 - x0) * 0.3:
            continue
        dy = sy0 - y1
        if -2 <= dy < 15 and dy < best_dy:
            best = span_text
            best_dy = dy
    return best


_LABEL_X_MAX = 250          # left-column label text starts left of this
_VALUE_GATHER_Y_WINDOW = 30  # vertical window (pts) around a label's y to gather wrapped value text


def _gather_value_near_label(label_bbox, all_spans, used_indices):
    """
    Given a label span's bbox (e.g. 'Negative side Description' at x<250), collect
    nearby right-column text (x>=_LABEL_X_MAX) within a vertical window of the label,
    ordered top-to-bottom then left-to-right, to reconstruct wrapped multi-line values.
    Marks consumed spans in used_indices so they aren't reused as something else.
    """
    label_y = label_bbox[1]
    candidates = []
    for i, (text, bbox) in enumerate(all_spans):
        if i in used_indices:
            continue
        if bbox[0] < _LABEL_X_MAX:
            continue  # left column = another label, not a value
        if re.match(r"^Photo\s+\d+$", text):
            continue  # never sweep up photo captions as description text
        if abs(bbox[1] - label_y) <= _VALUE_GATHER_Y_WINDOW:
            candidates.append((i, text, bbox))
    candidates.sort(key=lambda c: (round(c[2][1], 1), c[2][0]))
    for i, _, _ in candidates:
        used_indices.add(i)
    return " ".join(c[1] for c in candidates).strip()


def extract_inspection_areas(file_bytes: bytes):
    """
    Walks the inspection PDF page by page. This document family uses a two-column
    layout where each 'Negative/Positive side Description' label (left column) has
    its actual value text sitting in the right column at roughly the same height,
    sometimes wrapped across 2 lines straddling the label's y-position. Strict
    top-to-bottom reading order does NOT reliably reconstruct these values (verified
    against the real file), so labels and values are paired by spatial proximity
    instead. Photos are assigned to the side whose marker ('Negative/Positive side
    photographs') most recently appeared above them in y-order, which IS reliable
    since photo grids consistently follow their marker line directly.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    areas: list[InspectionArea] = []
    current_area: Optional[InspectionArea] = None
    current_side = None  # "negative" | "positive" | None

    summary_table_text = ""

    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]

        all_spans = []  # (text, bbox)
        for b in blocks:
            if "lines" in b:
                for line in b["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if text:
                            all_spans.append((text, span["bbox"]))

        caption_spans = [(t, bb) for t, bb in all_spans if re.match(r"^Photo\s+\d+$", t)]
        used_indices = set()

        page_text_lower = page.get_text()
        if "SUMMARY TABLE" in page_text_lower:
            summary_table_text += page.get_text() + "\n"

        # Build ordered list of structural markers (area headers, side labels, photo markers)
        # plus images, sorted by y position, to drive the area/side state machine.
        markers = []
        for i, (text, bbox) in enumerate(all_spans):
            if bbox[0] >= _LABEL_X_MAX:
                continue  # right-column value text, handled via label pairing, not as a marker
            if re.match(r"^Impacted Area\s+\d+$", text):
                markers.append(("area_header", text, bbox, i))
            elif text == "Negative side Description":
                markers.append(("neg_label", text, bbox, i))
            elif text == "Positive side Description":
                markers.append(("pos_label", text, bbox, i))
            elif text in ("Negative side photographs", "Positive side photographs"):
                markers.append(("photo_marker", text, bbox, i))

        image_infos = page.get_image_info(xrefs=True)
        for info in image_infos:
            markers.append(("image", info, info["bbox"], None))

        markers.sort(key=lambda m: (round(m[2][1], 1), m[2][0]))

        for kind, payload, bbox, span_idx in markers:
            if kind == "area_header":
                m = re.match(r"^Impacted Area\s+(\d+)$", payload)
                current_area = InspectionArea(
                    area_index=int(m.group(1)), name="", negative_description="",
                )
                areas.append(current_area)
                current_side = None

            elif kind == "neg_label":
                current_side = "negative"
                if current_area is not None:
                    value = _gather_value_near_label(bbox, all_spans, used_indices)
                    if value:
                        current_area.negative_description = (
                            (current_area.negative_description + " " + value).strip()
                        )
                        if not current_area.name:
                            current_area.name = _guess_area_name(current_area.negative_description)

            elif kind == "pos_label":
                current_side = "positive"
                if current_area is not None:
                    value = _gather_value_near_label(bbox, all_spans, used_indices)
                    if value:
                        current_area.positive_description = (
                            (current_area.positive_description + " " + value).strip()
                        )

            elif kind == "photo_marker":
                current_side = "negative" if "Negative" in payload else "positive"

            elif kind == "image":
                info = payload
                if current_area is None or current_side is None:
                    continue
                caption = _caption_for_image(page, info["bbox"], caption_spans)
                if caption is None:
                    continue  # uncaptioned -> recap thumbnail or decorative element (e.g. logo)

                try:
                    base_img = doc.extract_image(info["xref"])
                except Exception:
                    continue
                img_bytes = base_img["image"]
                ext = base_img["ext"]
                mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
                if mime not in ("image/jpeg", "image/png"):
                    continue

                img_obj = ExtractedImage(
                    id=f"insp_{caption.replace(' ', '_').lower()}",
                    data=base64.b64encode(img_bytes).decode(),
                    mime_type=mime,
                    page=page_num + 1,
                    caption=caption,
                    size_kb=round(len(img_bytes) / 1024, 1),
                )
                # avoid double-adding the same caption if it was already captured
                # (e.g. an uncaptioned recap render elsewhere wrongly matched twice)
                existing_ids = {p.id for p in (current_area.negative_photos + current_area.positive_photos)}
                if img_obj.id in existing_ids:
                    continue
                if current_side == "negative":
                    current_area.negative_photos.append(img_obj)
                else:
                    current_area.positive_photos.append(img_obj)

    doc.close()
    return areas, summary_table_text


def _guess_area_name(description: str) -> str:
    """Pull a short room name out of a free-text negative-side description."""
    known_rooms = [
        "Master Bedroom", "Master bedroom", "Common Bedroom", "Bedroom",
        "Common Bathroom", "Bathroom", "Hall", "Kitchen", "Parking Area",
        "Parking", "External wall", "WC",
    ]
    for room in known_rooms:
        if room.lower() in description.lower():
            return room
    # fallback: first few words
    return description.split(".")[0][:40].strip() or "Unnamed Area"


# ─── Thermal PDF parsing ────────────────────────────────────────────────────

_HOTSPOT_RE = re.compile(r"Hotspot\s*:\s*~?(\d+\.?\d*)\s*°?C", re.IGNORECASE)
_COLDSPOT_RE = re.compile(r"Coldspot\s*:\s*~?(\d+\.?\d*)\s*°?C", re.IGNORECASE)
_EMISSIVITY_RE = re.compile(r"Emissivity\s*:\s*(\d+\.?\d*)", re.IGNORECASE)
_REFLECTED_RE = re.compile(r"Reflected temperature\s*:\s*(\d+\.?\d*)\s*°?C", re.IGNORECASE)
_FILENAME_RE = re.compile(r"Thermal image\s*:\s*(\S+)", re.IGNORECASE)


def extract_thermal_readings(file_bytes: bytes):
    """
    One ThermalReading per page. Each thermal-report page in this format contains
    exactly two images (heatmap on top, camera photo below) plus caption text with
    hotspot/coldspot/emissivity/reflected-temperature and a source filename. We use
    vertical position to distinguish heatmap (top) from photo (bottom) rather than
    raw extraction index, since that's robust to extraction-order quirks; the heatmap
    is further confirmed by checking it sits in the same row as a temperature-scale
    color bar that appears immediately to its right (consistent in this report family).
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    readings: list[ThermalReading] = []

    for page_num, page in enumerate(doc):
        text = page.get_text()
        hotspot = _HOTSPOT_RE.search(text)
        coldspot = _COLDSPOT_RE.search(text)
        emissivity = _EMISSIVITY_RE.search(text)
        reflected = _REFLECTED_RE.search(text)
        filename = _FILENAME_RE.search(text)

        image_infos = page.get_image_info(xrefs=True)
        # filter out tiny decorative elements (e.g. small icons), keep substantive images
        substantive = [i for i in image_infos if i["size"] >= MIN_IMAGE_BYTES]
        # sort top-to-bottom
        substantive.sort(key=lambda i: i["bbox"][1])

        def _to_extracted(info, role):
            try:
                base_img = doc.extract_image(info["xref"])
            except Exception:
                return None
            img_bytes = base_img["image"]
            ext = base_img["ext"]
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            if mime not in ("image/jpeg", "image/png"):
                return None
            return ExtractedImage(
                id=f"thermal_p{page_num + 1}_{role}",
                data=base64.b64encode(img_bytes).decode(),
                mime_type=mime,
                page=page_num + 1,
                caption=role,
                size_kb=round(len(img_bytes) / 1024, 1),
            )

        thermal_img = _to_extracted(substantive[0], "thermal_scan") if len(substantive) >= 1 else None
        visual_img = _to_extracted(substantive[1], "visual_photo") if len(substantive) >= 2 else None

        if thermal_img is None and visual_img is None and hotspot is None:
            continue  # genuinely empty / non-data page

        readings.append(ThermalReading(
            page=page_num + 1,
            source_filename=filename.group(1) if filename else None,
            thermal_image=thermal_img,
            visual_image=visual_img,
            hotspot_c=float(hotspot.group(1)) if hotspot else None,
            coldspot_c=float(coldspot.group(1)) if coldspot else None,
            emissivity=float(emissivity.group(1)) if emissivity else None,
            reflected_temp_c=float(reflected.group(1)) if reflected else None,
        ))

    doc.close()
    return readings


# ─── Vision-based area <-> thermal matching ─────────────────────────────────

CANDIDATES_PER_BATCH = 4  # Groq vision API caps requests at 5 images total; 1 area photo + 4 candidates


async def _match_area_against_batch(client, api_key, area, batch_readings, batch_offset):
    """Single Groq vision call comparing one area photo against up to 4 thermal candidates."""
    area_photo = area.negative_photos[0]

    content = [
        {
            "type": "text",
            "text": (
                f"You are matching a building inspection photo to one of several thermal-camera "
                f"site photos, to find which thermal scan was taken at the same physical location.\n\n"
                f"AREA NAME: {area.name}\n"
                f"AREA DESCRIPTION: {area.negative_description}\n\n"
                f"The first image below is the inspection photo for this area. "
                f"The following images are candidate thermal-report site photos, each labeled "
                f"with an index number. Compare wall surfaces, damp/stain patterns, fixtures, "
                f"flooring, windows, doors, and camera angle.\n\n"
                f"Respond with ONLY a JSON object, no other text:\n"
                f'{{"best_match_index": <int or null>, "confidence": <float 0-1>, '
                f'"reasoning": "<one sentence>"}}\n'
                f"Use null for best_match_index if none of these candidates plausibly match."
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:{area_photo.mime_type};base64,{area_photo.data}"},
        },
    ]
    valid_local_indices = []
    for local_idx, reading in enumerate(batch_readings):
        if reading.visual_image is None:
            continue
        valid_local_indices.append(local_idx)
        content.append({"type": "text", "text": f"Candidate index {local_idx}:"})
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{reading.visual_image.mime_type};base64,{reading.visual_image.data}"
            },
        })

    if not valid_local_indices:
        return None

    resp = await client.post(
        GROQ_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"},
        json={
            "model": GROQ_VISION_MODEL,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 300,
            "temperature": 0.0,
        },
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    cleaned = re.sub(r"```json|```", "", raw).strip()
    parsed = json.loads(cleaned)

    local_best = parsed.get("best_match_index")
    confidence = float(parsed.get("confidence", 0))
    if local_best is None or local_best not in valid_local_indices:
        return None

    return {
        "reading": batch_readings[local_best],
        "confidence": confidence,
        "reasoning": parsed.get("reasoning", ""),
    }


class GroqAuthError(Exception):
    """Raised when Groq rejects the API key outright (401) — distinct from a
    rate limit or a transient failure, since it should abort immediately rather
    than be retried or silently treated as 'no match found' for every area."""
    pass


async def _call_with_retry(client, api_key, area, batch, batch_offset, max_retries=3):
    """Wraps a single batch match call with 429 backoff. A 401 (invalid/revoked key)
    is NOT retried and is raised immediately, since retrying or silently swallowing
    it would make every area look unmatched while actually burning ~2 minutes on a
    key that will never work."""
    for attempt in range(max_retries):
        try:
            return await _match_area_against_batch(client, api_key, area, batch, batch_offset)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise GroqAuthError(
                    f"Groq API rejected the request ({e.response.status_code}). "
                    f"Check that the API key is valid, active, and not blocked."
                ) from e
            if e.response.status_code == 429 and attempt < max_retries - 1:
                retry_after = float(e.response.headers.get("retry-after", 2 ** (attempt + 1)))
                await asyncio.sleep(retry_after)
                continue
            return None
        except Exception:
            return None
    return None


EARLY_EXIT_CONFIDENCE = 0.85  # stop searching further batches once a match this strong is found


async def match_areas_to_thermal(areas: list[InspectionArea], readings: list[ThermalReading], api_key: str):
    """
    There is no text/metadata key linking thermal pages to inspection areas in this
    document family, so the link must be established visually. Groq's vision API
    caps requests at 5 total images, so each area's negative-side photo is compared
    against thermal candidates in batches of 4 (1 area photo + 4 candidates = 5).
    Batches stop early once a sufficiently confident match is found (no need to
    exhaust all 30 thermal pages once a clear match shows up), which keeps the
    typical case fast; otherwise all batches are tried and the best result kept.

    Two efficiency/correctness measures, given real free-tier rate limits (30 req/min):
      - A small delay between calls avoids bursting past the per-minute cap.
      - Once a thermal reading is confidently claimed by one area, it's excluded from
        later areas' candidate pools — in this report family each scan corresponds to
        one physical location, so the same reading should not be assigned twice.

    Matches below MATCH_CONFIDENCE_THRESHOLD are discarded — that area's thermal data
    is then surfaced as "Not Available" rather than guessed.
    """
    if not readings:
        return {a.area_index: None for a in areas}

    matches = {}
    remaining_readings = list(readings)

    async with httpx.AsyncClient(timeout=120) as client:
        for area in areas:
            if not area.negative_photos or not remaining_readings:
                matches[area.area_index] = None
                continue

            best_overall = None
            for i in range(0, len(remaining_readings), CANDIDATES_PER_BATCH):
                batch = remaining_readings[i:i + CANDIDATES_PER_BATCH]
                result = await _call_with_retry(client, api_key, area, batch, i)
                # GroqAuthError raised inside _call_with_retry propagates immediately,
                # skipping this sleep — no point throttling after a key that's already dead.
                await asyncio.sleep(2.1)  # ~28 req/min, under the 30 RPM free-tier cap

                if result is not None:
                    if best_overall is None or result["confidence"] > best_overall["confidence"]:
                        best_overall = result
                    if best_overall["confidence"] >= EARLY_EXIT_CONFIDENCE:
                        break

            if best_overall is not None and best_overall["confidence"] >= MATCH_CONFIDENCE_THRESHOLD:
                matches[area.area_index] = best_overall
                remaining_readings = [r for r in remaining_readings if r.page != best_overall["reading"].page]
            else:
                matches[area.area_index] = None

    return matches


# ─── Building the structured payload for the LLM ───────────────────────────

def build_structured_context(areas: list[InspectionArea], matches: dict, summary_table_text: str) -> str:
    """
    Produces a single unambiguous JSON-like text block describing, per area: its
    name, descriptions, image IDs (already correctly assigned, not guessed), and
    its matched thermal reading (if any, with confidence) or explicit absence.
    The LLM's job becomes writing prose around fixed facts, not deciding which
    image belongs where.
    """
    lines = ["STRUCTURED AREA DATA (use this exactly — do not reassign images):", ""]

    for area in areas:
        match = matches.get(area.area_index)
        lines.append(f"=== Area {area.area_index}: {area.name} ===")
        lines.append(f"Negative side description: {area.negative_description or 'Not Available'}")
        lines.append(
            "Negative side image IDs: "
            + (", ".join(p.id for p in area.negative_photos) if area.negative_photos else "Image Not Available")
        )
        lines.append(f"Positive side description: {area.positive_description or 'Not Available'}")
        lines.append(
            "Positive side image IDs: "
            + (", ".join(p.id for p in area.positive_photos) if area.positive_photos else "Image Not Available")
        )

        if match:
            reading = match["reading"]
            lines.append(
                f"Matched thermal reading (confidence {match['confidence']:.2f}): "
                f"hotspot={reading.hotspot_c}°C, coldspot={reading.coldspot_c}°C, "
                f"emissivity={reading.emissivity}, reflected_temp={reading.reflected_temp_c}°C"
            )
            if reading.thermal_image:
                lines.append(f"Thermal scan image ID: {reading.thermal_image.id}")
            if reading.visual_image:
                lines.append(f"Thermal visual photo image ID: {reading.visual_image.id}")
            lines.append(f"Match reasoning: {match['reasoning']}")
        else:
            lines.append(
                "Matched thermal reading: Not Available "
                "(no thermal scan could be confidently linked to this area — "
                "write 'Not Available' for Thermal Data, do not guess)"
            )
        lines.append("")

    if summary_table_text.strip():
        lines.append("=== SUMMARY TABLE FROM INSPECTION REPORT (for cross-reference) ===")
        lines.append(summary_table_text.strip())

    return "\n".join(lines)


# ─── System prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior building inspection analyst writing a professional DDR (Detailed Diagnostic Report) for a client.

STRICT RULES:
1. NEVER invent facts. Only use information from the STRUCTURED AREA DATA provided. Do not reassign, swap, or invent image IDs.
2. If information is missing write: Not Available
3. If information conflicts write: [CONFLICT: explain here]
4. Use simple, client-friendly language. Avoid unnecessary technical jargon.
5. Do NOT duplicate observations across sections.
6. The STRUCTURED AREA DATA already tells you exactly which images belong to which area, and whether a thermal reading was confidently matched. Trust it completely — do not try to re-derive or second-guess image placement yourself.

IMAGE PLACEMENT RULES:
- Place image references using EXACTLY this format: {IMAGE:image_id} using the image IDs given in STRUCTURED AREA DATA.
- For each area, place negative-side images, then the matched thermal scan + visual photo (if any), then positive-side images.
- If an area has "Image Not Available" or "Matched thermal reading: Not Available", write that text plainly instead of an image tag.

OUTPUT FORMAT — use EXACTLY these section headers with ## prefix:

## 1. PROPERTY ISSUE SUMMARY
2-3 sentence executive summary of overall property condition.

## 2. AREA-WISE OBSERVATIONS
For EACH area in STRUCTURED AREA DATA create a subsection:

### Area: [Area Name]
**Observations:** what was found on the negative/impacted side
**Thermal Data:** hotspot/coldspot values if matched, otherwise "Not Available"
**Visual Evidence:**
{IMAGE:...} (negative side photos)
{IMAGE:...} (thermal scan, if matched)
{IMAGE:...} (thermal visual photo, if matched)
{IMAGE:...} (positive side photos)
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
List any data that was absent or ambiguous, including any area where the thermal reading could not be confidently matched. Write None if everything was clear.
"""


def cap_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text.rfind("\n\n", 0, max_chars)
    if cut == -1:
        cut = max_chars
    return text[:cut] + "\n\n[... truncated for length ...]"


# ─── Main endpoint ──────────────────────────────────────────────────────────

@app.post("/generate-ddr")
async def generate_ddr(
    inspection_report: UploadFile = File(...),
    thermal_report: UploadFile = File(...),
    api_key: str = Form(...),
):
    if not api_key.strip().startswith("gsk_"):
        raise HTTPException(status_code=400, detail="Invalid Groq API key format.")

    insp_bytes = await inspection_report.read()
    thermal_bytes = await thermal_report.read()

    try:
        areas, summary_table_text = extract_inspection_areas(insp_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse inspection report: {e}")

    try:
        readings = extract_thermal_readings(thermal_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse thermal report: {e}")

    if not areas:
        raise HTTPException(
            status_code=422,
            detail="No 'Impacted Area' sections were found in the inspection report. "
                   "This parser expects the UrbanRoof-style 'Impacted Area N' format; "
                   "a differently formatted report would need an adapted parser.",
        )

    try:
        matches = await match_areas_to_thermal(areas, readings, api_key)
    except GroqAuthError:
        raise HTTPException(
            status_code=401,
            detail="Groq rejected the provided API key. Check that it is valid and not revoked.",
        )

    structured_context = build_structured_context(areas, matches, summary_table_text)
    structured_context = cap_text(structured_context, 8000)

    user_message = f"""{structured_context}

=== YOUR TASK ===
Generate a complete, accurate DDR report using ONLY the STRUCTURED AREA DATA above.
Follow the system instructions exactly for structure, image placement, and rules.
Every area listed above must have its own subsection in Section 2.
"""

    report = None
    last_error_detail = None
    max_report_retries = 4
    for attempt in range(max_report_retries):
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    GROQ_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {api_key.strip()}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROQ_TEXT_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_message},
                        ],
                        "max_tokens": 4096,
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                report = resp.json()["choices"][0]["message"]["content"]
                break
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise HTTPException(
                    status_code=401,
                    detail="Groq rejected the provided API key. Check that it is valid and not revoked.",
                )
            if e.response.status_code == 429 and attempt < max_report_retries - 1:
                retry_after = float(e.response.headers.get("retry-after", 2 ** (attempt + 1)))
                await asyncio.sleep(retry_after + 0.5)
                continue
            last_error_detail = f"Groq API error {e.response.status_code}: {e.response.text[:400]}"
            break
        except Exception as e:
            last_error_detail = str(e)
            break

    if report is None:
        raise HTTPException(status_code=500, detail=last_error_detail or "Failed to generate report after retries.")

    # Flatten all images for the frontend, with metadata about match confidence
    all_images = []
    for area in areas:
        for p in area.negative_photos + area.positive_photos:
            all_images.append({
                "id": p.id, "data": p.data, "mime_type": p.mime_type,
                "source": "Inspection", "page": p.page, "img_type": "inspection_photo",
                "caption": p.caption, "size_kb": p.size_kb,
            })
    matched_reading_pages = set()
    for area in areas:
        match = matches.get(area.area_index)
        if match:
            reading = match["reading"]
            matched_reading_pages.add(reading.page)
            if reading.thermal_image:
                all_images.append({
                    "id": reading.thermal_image.id, "data": reading.thermal_image.data,
                    "mime_type": reading.thermal_image.mime_type, "source": "Thermal",
                    "page": reading.page, "img_type": "thermal_scan",
                    "matched_area": area.name, "match_confidence": match["confidence"],
                    "size_kb": reading.thermal_image.size_kb,
                })
            if reading.visual_image:
                all_images.append({
                    "id": reading.visual_image.id, "data": reading.visual_image.data,
                    "mime_type": reading.visual_image.mime_type, "source": "Thermal",
                    "page": reading.page, "img_type": "visual_photo",
                    "matched_area": area.name, "match_confidence": match["confidence"],
                    "size_kb": reading.visual_image.size_kb,
                })

    unmatched_count = sum(1 for a in areas if matches.get(a.area_index) is None)

    return JSONResponse({
        "report": report,
        "images": all_images,
        "stats": {
            "total_areas": len(areas),
            "areas_with_thermal_match": len(areas) - unmatched_count,
            "areas_without_thermal_match": unmatched_count,
            "total_thermal_readings": len(readings),
            "total_inspection_images": sum(len(a.negative_photos) + len(a.positive_photos) for a in areas),
        },
    })


@app.get("/health")
def health():
    return {"status": "ok", "service": "DDR Report Generator v3"}
