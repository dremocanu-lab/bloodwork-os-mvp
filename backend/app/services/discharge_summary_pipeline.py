from __future__ import annotations

import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import fitz
from openai import OpenAI


MODEL = os.getenv("OPENAI_DISCHARGE_LAYOUT_MODEL", "gpt-4.1")
PAGE_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_DISCHARGE_PAGE_MAX_OUTPUT_TOKENS", "32000"))
PDF_RENDER_ZOOM = float(os.getenv("OPENAI_DISCHARGE_RENDER_ZOOM", "2.6"))
MAX_PAGES = int(os.getenv("OPENAI_DISCHARGE_MAX_PAGES", "90"))
MAX_PARALLEL_PAGES = int(os.getenv("OPENAI_DISCHARGE_MAX_PARALLEL_PAGES", "6"))


ALLOWED_SECTION_KEYS = {
    "administrative_information",
    "diagnoses",
    "discharge_status",
    "epicriza",
    "investigations",
    "consults",
    "laboratory_normal",
    "laboratory_abnormal",
    "treatment_in_hospital",
    "recommended_treatment",
    "prescriptions_released",
    "recommendations",
    "other",
}


SECTION_TITLE_BY_KEY = {
    "administrative_information": "Administrative information",
    "diagnoses": "Diagnoses",
    "discharge_status": "Discharge status",
    "epicriza": "EPICRIZA",
    "investigations": "Investigations / imaging",
    "consults": "Consults",
    "laboratory_normal": "Examen de laborator cu valori normale",
    "laboratory_abnormal": "Examen de laborator cu valori patologice",
    "treatment_in_hospital": "Tratament administrat in timpul internarii",
    "recommended_treatment": "Tratament recomandat",
    "prescriptions_released": "Retete eliberate",
    "recommendations": "Recomandari",
    "other": "Other",
}


SYSTEM_PROMPT = """
You are a Romanian hospital discharge document verbatim transcription engine.

YOUR ONLY JOB IS TO COPY TEXT. NOT TO SUMMARIZE. NOT TO EXPLAIN. NOT TO REWRITE.

ABSOLUTE RULES — NEVER BREAK THESE:
1. Copy every single word visible on the page, exactly as written.
2. If a laboratory table has 60 rows, you write all 60 rows. If it has 100 rows, you write all 100 rows. Never stop partway through a table.
3. If the EPICRIZA section is 3 pages long, you write the entire EPICRIZA for the current page — every sentence, every date, every lab value, every medication name and dose.
4. NEVER truncate, shorten, compress, abbreviate, or omit any content.
5. NEVER replace multiple lines with "[...]", "...", "see above", "same as previous", "continues", "omitted", "abbreviated", or any similar placeholder.
6. NEVER decide a piece of text is "redundant", "repetitive", or "already captured". Copy it anyway.
7. Do NOT summarize. Do NOT paraphrase. Do NOT rewrite. Copy verbatim.
8. Do NOT fix Romanian spelling, medical abbreviations, OCR artifacts, typos, odd spacing, or unusual punctuation.
9. If a word is completely unreadable, write [?] for that word only.
10. LENGTH OF YOUR OUTPUT DOES NOT MATTER. A 30,000-token verbatim transcript is correct. A 2,000-token "summary" is a failure.

FORMATTING RULES:
- Preserve original line breaks exactly.
- Preserve indentation and leading spaces.
- Preserve bullets, dashes, arrows (→, ->, —), parentheses.
- For table-like areas: keep each label/value pair on its own line, aligned with spaces as best you can.
- Do NOT merge separate lines into one paragraph.
- Do NOT convert tables into flowing prose.
- Do NOT collapse multiple entries onto one line.

SECTION ASSIGNMENT RULES:
- administrative_information: hospital/patient/admin table on page 1 (provider, doctor, FO, section, compartment, CNP, address, insurance, occupation, admission/discharge dates).
- diagnoses: DRG boxes, diagnostic boxes, secondary diagnoses, diagnosis lists.
- discharge_status: stare la externare / discharge status field.
- epicriza: the EPICRIZA narrative and everything under its heading — chronological medical history, old labs, previous admissions, imaging results, transfusions, consultations, treatments described in the narrative.
- investigations: imaging, ultrasound, radiology, ECG, echo, CT, MRI — when under a separate heading outside epicriza.
- consults: consultations under a separate heading outside epicriza.
- laboratory_normal: section titled "Examen de laborator cu valori normale" or equivalent.
- laboratory_abnormal: section titled "Examen de laborator cu valori patologice" or equivalent.
- treatment_in_hospital: medications and treatments administered during the admission, transfusions given — under a separate heading.
- recommended_treatment: "Tratament recomandat" section.
- prescriptions_released: "Retete eliberate" / "Rp." section.
- recommendations: recommendations, follow-up, discharge instructions.
- other: any visible text that does not fit the above.

METADATA FIELDS (extract from the document — null if not visible):
- patient_name: full name
- cnp: 13-digit Romanian CNP
- date_of_birth: date of birth
- sex: M/F or masculin/feminin
- admission_date: data internarii
- discharge_date: data externarii
- hospital_name: full hospital name

Return ONLY valid JSON. No markdown. No explanations before or after. Start with { and end with }.

Required JSON shape:
{
  "page_number": <integer>,
  "printed_page_label": <string or null>,
  "document_page_count_visible": <string or null>,
  "patient_name": <string or null>,
  "cnp": <string or null>,
  "date_of_birth": <string or null>,
  "sex": <string or null>,
  "admission_date": <string or null>,
  "discharge_date": <string or null>,
  "hospital_name": <string or null>,
  "sections": [
    {
      "key": "<one of the allowed section keys>",
      "title": "<heading as it appears on this page>",
      "original_titles": ["<heading as it appears on this page>"],
      "body": "<complete verbatim text from this section on this page, with original line breaks and indentation>"
    }
  ],
  "warnings": []
}
"""


USER_PROMPT_TEMPLATE = """
Transcribe page {page_number} of this Romanian hospital discharge document.

RAW TEXT EXTRACTED FROM PDF (GROUND TRUTH):
===
{raw_text}
===

The raw text block above is extracted directly from the PDF's text layer — it is character-perfect.
Every word, number, date, lab value, medical term, name, and abbreviation in that block is exactly correct.

YOUR RULES:
1. Use the raw text as your authoritative source for ALL content. Copy it exactly.
2. Use the image ONLY to understand layout: which text belongs to which section heading.
3. Do NOT alter any character from the raw text. Do NOT fix spelling, do NOT "correct" medical abbreviations.
4. Do NOT skip any line present in the raw text.
5. If the raw text has a number like "11.690" do NOT change it to "1.690" or "11,690".
6. Preserve the exact line breaks, spacing, and order from the raw text within each section.
7. If a table appears, include every row exactly as it appears in the raw text.
8. Do NOT truncate, summarize, or abbreviate. If the section is 2000 words, write all 2000 words.

SECTION ASSIGNMENT (use the image to determine section boundaries):
- Assign each block of raw text to the correct section key based on where it visually appears under each heading.
- If a section continues from a previous page (no new heading visible), use the same section key.
- Do NOT merge two different sections into one.

For page 1 specifically:
- The hospital/patient/admin table → administrative_information
- DRG/diagnosis boxes → diagnoses
- If the EPICRIZA heading appears, start the epicriza section

Output complete JSON only. No notes, no explanations.
"""


def _client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    return OpenAI(api_key=api_key)


def _extract_response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)

    if isinstance(text, str) and text.strip():
        return text.strip()

    chunks: list[str] = []

    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            value = getattr(content, "text", None)

            if isinstance(value, str):
                chunks.append(value)

    return "\n".join(chunks).strip()


def _strip_json_fences(text: str) -> str:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]

    return cleaned


def _safe_json_loads(text: str) -> dict[str, Any]:
    cleaned = _strip_json_fences(text)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"OpenAI returned invalid JSON: {exc}. First 1000 chars: {cleaned[:1000]}"
        ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("OpenAI returned JSON, but it was not an object.")

    return parsed


_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif"}
_IMAGE_MIME = {
    ".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png",
    ".webp": "webp", ".tiff": "tiff", ".tif": "tiff",
    ".bmp": "bmp", ".gif": "gif",
}


def _render_pdf_pages_as_data_urls(path: Path) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []

    with fitz.open(path) as pdf:
        page_count = min(len(pdf), MAX_PAGES)

        for index in range(page_count):
            page = pdf.load_page(index)
            matrix = fitz.Matrix(PDF_RENDER_ZOOM, PDF_RENDER_ZOOM)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pixmap.tobytes("png")
            encoded = base64.b64encode(png_bytes).decode("ascii")
            native_text = page.get_text("text").strip()

            pages.append(
                {
                    "page_number": index + 1,
                    "width": page.rect.width,
                    "height": page.rect.height,
                    "image_url": f"data:image/png;base64,{encoded}",
                    "native_text": native_text,
                }
            )

    return pages


def _render_image_as_single_page(path: Path) -> list[dict[str, Any]]:
    mime = _IMAGE_MIME.get(path.suffix.lower(), "jpeg")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")

    return [
        {
            "page_number": 1,
            "width": 0,
            "height": 0,
            "image_url": f"data:image/{mime};base64,{encoded}",
            "native_text": "",
        }
    ]


def _render_pages_from_file(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in _IMAGE_EXTENSIONS:
        return _render_image_as_single_page(path)
    return _render_pdf_pages_as_data_urls(path)


def _try_document_ai_ocr_per_page(path: Path) -> dict[int, str]:
    """
    Runs Google Document AI on the whole file and returns per-page OCR text.
    Keys are 0-based page indices. Returns empty dict if not configured or fails.
    Used when the PDF has no native text layer (scanned) or the upload is an image.
    """
    try:
        from app.services.google_document_ai_service import (
            is_google_document_ai_configured,
            process_with_google_document_ai,
        )

        if not is_google_document_ai_configured():
            return {}

        result = process_with_google_document_ai(path, path.name)
        lines = result.get("lines") or []

        pages_text: dict[int, list[str]] = {}

        for line in sorted(
            lines,
            key=lambda ln: (int(ln.get("page", 0)), float(ln.get("top", 0)), float(ln.get("left", 0))),
        ):
            page_idx = int(line.get("page", 0))
            text = (line.get("text") or "").strip()

            if text:
                pages_text.setdefault(page_idx, []).append(text)

        return {idx: "\n".join(lines) for idx, lines in pages_text.items()}

    except Exception:
        return {}


def _call_openai_for_page(client: OpenAI, page: dict[str, Any]) -> dict[str, Any]:
    page_number = page["page_number"]
    native_text = page.get("native_text") or ""

    # If the PDF has a native text layer (digital PDFs like Hipocrate), use it as
    # ground truth so the model doesn't hallucinate characters from the image.
    # For scanned PDFs with no text layer, fall back to vision-only mode.
    has_native_text = len(native_text) > 80

    if has_native_text:
        raw_text_block = native_text
    else:
        raw_text_block = "(No native text layer — use the image only)"

    response = client.responses.create(
        model=MODEL,
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": SYSTEM_PROMPT,
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": page["image_url"],
                    },
                    {
                        "type": "input_text",
                        "text": USER_PROMPT_TEMPLATE.format(
                            page_number=page_number,
                            raw_text=raw_text_block,
                        ),
                    },
                ],
            },
        ],
        temperature=0,
        max_output_tokens=PAGE_MAX_OUTPUT_TOKENS,
    )

    raw_text = _extract_response_text(response)
    parsed = _safe_json_loads(raw_text)
    parsed["page_number"] = int(parsed.get("page_number") or page_number)

    return parsed


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("﻿", "")
    text = text.replace(" ", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Only collapse truly absurd vertical gaps (5+ blank lines → 4).
    text = re.sub(r"\n{5,}", "\n\n\n\n", text)

    return text.strip("\n")


def _normalize_for_matching(value: str) -> str:
    normalized = value.lower()
    normalized = normalized.replace("ă", "a").replace("â", "a").replace("î", "i")
    normalized = normalized.replace("ș", "s").replace("ş", "s")
    normalized = normalized.replace("ț", "t").replace("ţ", "t")
    normalized = normalized.replace("-", " ")
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def _normalize_section_key(value: Any) -> str:
    key = str(value or "other").strip().lower()
    key = key.replace(" ", "_").replace("-", "_")

    aliases = {
        "administrative": "administrative_information",
        "admin": "administrative_information",
        "administrative_info": "administrative_information",
        "administrative_data": "administrative_information",
        "date_administrative": "administrative_information",
        "diagnosis": "diagnoses",
        "diagnostic": "diagnoses",
        "diagnostice": "diagnoses",
        "diagnostice_drg": "diagnoses",
        "stare_la_externare": "discharge_status",
        "investigatii": "investigations",
        "investigații": "investigations",
        "ecografie": "investigations",
        "radiologie": "investigations",
        "consulturi": "consults",
        "consultatii": "consults",
        "consultații": "consults",
        "laborator_normal": "laboratory_normal",
        "examen_de_laborator_cu_valori_normale": "laboratory_normal",
        "valori_normale": "laboratory_normal",
        "laborator_patologic": "laboratory_abnormal",
        "laborator_patologice": "laboratory_abnormal",
        "examen_de_laborator_cu_valori_patologice": "laboratory_abnormal",
        "valori_patologice": "laboratory_abnormal",
        "tratament_in_spital": "treatment_in_hospital",
        "tratament_administrat": "treatment_in_hospital",
        "tratament_administrat_in_timpul_internarii": "treatment_in_hospital",
        "tratament_recomandat": "recommended_treatment",
        "retete_eliberate": "prescriptions_released",
        "rețete_eliberate": "prescriptions_released",
        "rp": "prescriptions_released",
        "rp.": "prescriptions_released",
        "recomandari": "recommendations",
        "recomandări": "recommendations",
    }

    key = aliases.get(key, key)

    if key not in ALLOWED_SECTION_KEYS:
        return "other"

    return key


def _infer_section_key_from_title(title: str, fallback_key: str) -> str:
    normalized = _normalize_for_matching(title)

    if "bilet de iesire" in normalized or "scrisoare medicala" in normalized:
        return "administrative_information"

    if "diagnostic" in normalized:
        return "diagnoses"

    if "stare la externare" in normalized:
        return "discharge_status"

    if "epicriza" in normalized:
        return "epicriza"

    if "examen de laborator" in normalized and "normal" in normalized:
        return "laboratory_normal"

    if "examen de laborator" in normalized and (
        "patologic" in normalized or "modificat" in normalized
    ):
        return "laboratory_abnormal"

    if "valori normale" in normalized:
        return "laboratory_normal"

    if "valori patologice" in normalized:
        return "laboratory_abnormal"

    if "tratament recomandat" in normalized:
        return "recommended_treatment"

    if "retete eliberate" in normalized:
        return "prescriptions_released"

    if normalized.strip() in {"rp", "rp.", "reteta", "retete"}:
        return "prescriptions_released"

    if "tratament administrat" in normalized:
        return "treatment_in_hospital"

    if "pe parcursul internarii" in normalized:
        return "treatment_in_hospital"

    if "recomandari" in normalized:
        return "recommendations"

    if "consult" in normalized:
        return "consults"

    if (
        "ecografie" in normalized
        or "radiografie" in normalized
        or normalized.startswith("rx")
        or " rx " in f" {normalized} "
        or "ekg" in normalized
        or "ecg" in normalized
    ):
        return "investigations"

    return fallback_key


def _clean_section(section: dict[str, Any], page_number: int, index: int) -> dict[str, Any]:
    original_key = _normalize_section_key(section.get("key"))

    title = _clean_text(section.get("title")) or SECTION_TITLE_BY_KEY.get(
        original_key, original_key.replace("_", " ").title()
    )

    key = _infer_section_key_from_title(title, original_key)
    body = _clean_text(section.get("body"))

    original_titles = section.get("original_titles")

    if not isinstance(original_titles, list):
        original_titles = [title]

    cleaned_original_titles = [
        _clean_text(item)
        for item in original_titles
        if _clean_text(item)
    ]

    if not cleaned_original_titles:
        cleaned_original_titles = [title]

    return {
        "key": key,
        "title": title or SECTION_TITLE_BY_KEY.get(key, key.replace("_", " ").title()),
        "original_titles": cleaned_original_titles,
        "body": body,
        "formatted_body": body,
        "formatting_method": "openai_pdf_page_vision_verbatim_layout",
        "formatting_confidence": 0.82,
        "confidence": 0.82,
        "page_start": page_number,
        "page_end": page_number,
        "source_pages": [page_number],
        "section_order": index,
    }


def _page_to_sections(page_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sections = page_payload.get("sections")
    page_number = int(page_payload.get("page_number") or 0)

    if not isinstance(raw_sections, list):
        raw_sections = []

    sections: list[dict[str, Any]] = []

    for index, raw_section in enumerate(raw_sections):
        if not isinstance(raw_section, dict):
            continue

        cleaned = _clean_section(raw_section, page_number=page_number, index=index)

        if cleaned["body"]:
            sections.append(cleaned)

    return sections


def _should_merge_with_previous(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False

    if previous["key"] != current["key"]:
        return False

    previous_title = _normalize_for_matching(previous.get("title") or "")
    current_title = _normalize_for_matching(current.get("title") or "")

    if previous_title == current_title:
        return True

    # EPICRIZA and lab sections often continue across many pages.
    if previous["key"] in {
        "epicriza",
        "laboratory_normal",
        "laboratory_abnormal",
        "treatment_in_hospital",
        "recommended_treatment",
        "recommendations",
        "prescriptions_released",
    }:
        return True

    return False


def _merge_sections(page_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []

    for page_payload in page_payloads:
        for section in _page_to_sections(page_payload):
            previous = merged[-1] if merged else None

            if _should_merge_with_previous(previous, section):
                previous["body"] = f"{previous['body']}\n\n{section['body']}".strip("\n")
                previous["formatted_body"] = previous["body"]
                previous["page_end"] = section["page_end"]
                previous["source_pages"] = sorted(
                    set(previous.get("source_pages", []) + section.get("source_pages", []))
                )
                previous["original_titles"] = list(
                    dict.fromkeys(
                        previous.get("original_titles", []) + section.get("original_titles", [])
                    )
                )
            else:
                merged.append(section)

    return merged


def _first_non_empty(page_payloads: list[dict[str, Any]], key: str) -> Any:
    for payload in page_payloads:
        value = payload.get(key)

        if value not in (None, ""):
            return value

    return None


def _payload_to_text(payload: dict[str, Any]) -> str:
    sections = payload.get("sections") or []

    parts: list[str] = []

    for section in sections:
        title = _clean_text(section.get("title"))
        body = _clean_text(section.get("body"))
        pages = section.get("source_pages") or []
        page_label = f" [pages {', '.join(str(page) for page in pages)}]" if pages else ""

        if title and body:
            parts.append(f"{title}{page_label}\n\n{body}")
        elif body:
            parts.append(body)

    return "\n\n---\n\n".join(parts).strip()


def _build_warnings(
    page_payloads: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    actual_page_count: int,
) -> list[str]:
    warnings: list[str] = []

    extracted_pages = sorted(
        {
            int(payload.get("page_number") or 0)
            for payload in page_payloads
            if payload.get("page_number")
        }
    )

    if len(extracted_pages) != actual_page_count:
        warnings.append(
            f"Expected {actual_page_count} rendered pages, extracted {len(extracted_pages)} page payloads."
        )

    if not any(section.get("key") == "administrative_information" for section in sections):
        warnings.append("No administrative_information section was extracted. Check page 1 manually.")

    if not any(section.get("key") == "diagnoses" for section in sections):
        warnings.append("No diagnoses section was extracted. Check page 1 manually.")

    if not any(section.get("key") == "epicriza" for section in sections):
        warnings.append("No epicriza section was extracted. Check discharge summary manually.")

    for payload in page_payloads:
        for warning in payload.get("warnings") or []:
            if warning:
                warnings.append(str(warning))

    deduped: list[str] = []
    seen: set[str] = set()

    for warning in warnings:
        clean = warning.strip()

        if clean and clean not in seen:
            deduped.append(clean)
            seen.add(clean)

    return deduped


def _normalize_payload(page_payloads: list[dict[str, Any]], actual_page_count: int) -> dict[str, Any]:
    sections = _merge_sections(page_payloads)
    warnings = _build_warnings(page_payloads, sections, actual_page_count)

    return {
        "document_type": "discharge_summary",
        "extraction_mode": "page_vision_verbatim_layout_sections",
        "patient_name": _first_non_empty(page_payloads, "patient_name"),
        "cnp": _first_non_empty(page_payloads, "cnp"),
        "date_of_birth": _first_non_empty(page_payloads, "date_of_birth"),
        "sex": _first_non_empty(page_payloads, "sex"),
        "admission_date": _first_non_empty(page_payloads, "admission_date"),
        "discharge_date": _first_non_empty(page_payloads, "discharge_date"),
        "hospital_name": _first_non_empty(page_payloads, "hospital_name"),
        "page_count": actual_page_count,
        "page_payloads": page_payloads,
        "sections": sections,
        "warnings": warnings,
    }


def process_uploaded_discharge_summary(
    file_path: str | Path,
    filename: str | None = None,
) -> dict[str, Any]:
    """
    Verbatim, layout-preserving discharge summary extraction.

    Each PDF page is rendered as a high-resolution image and sent separately
    to the OpenAI vision model, which extracts the complete visible text
    verbatim into named sections. Sections that continue across pages are
    merged. Nothing is summarized or omitted.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Discharge PDF not found: {path}")

    client = _client()
    rendered_pages = _render_pages_from_file(path)

    if not rendered_pages:
        raise RuntimeError("No pages could be rendered for discharge extraction.")

    # Enrich pages that have no native text layer with Google Document AI OCR.
    # Digital PDFs (Hipocrate etc.) already have native_text so this is skipped.
    # For scanned PDFs and image uploads, Document AI gives character-accurate OCR
    # which we then pass to OpenAI as ground truth instead of relying on vision alone.
    pages_needing_ocr = [p for p in rendered_pages if len(p.get("native_text") or "") <= 80]

    if pages_needing_ocr:
        doc_ai_text = _try_document_ai_ocr_per_page(path)

        if doc_ai_text:
            for page in pages_needing_ocr:
                page_idx = page["page_number"] - 1
                ocr_text = doc_ai_text.get(page_idx, "")

                if len(ocr_text) > 80:
                    page["native_text"] = ocr_text

    page_payloads: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_PAGES) as executor:
        futures = {executor.submit(_call_openai_for_page, client, page): page for page in rendered_pages}
        for future in as_completed(futures):
            page_payloads.append(future.result())

    page_payloads.sort(key=lambda p: int(p.get("page_number") or 0))

    payload = _normalize_payload(page_payloads, actual_page_count=len(rendered_pages))
    extracted_text = _payload_to_text(payload)

    return {
        "document_type": "discharge_summary",
        "payload": payload,
        "parsed_payload": payload,
        "note_body": json.dumps(payload, ensure_ascii=False),
        "extracted_text": extracted_text,
        "patient_name": payload.get("patient_name"),
        "cnp": payload.get("cnp"),
        "date_of_birth": payload.get("date_of_birth"),
        "sex": payload.get("sex"),
        "collected_on": payload.get("admission_date"),
        "reported_on": payload.get("discharge_date"),
        "hospital_name": payload.get("hospital_name"),
        "report_name": "Bilet de iesire din spital / Scrisoare medicala",
        "report_type": "discharge_summary",
        "source_language": "ro",
        "formatting_method": "openai_pdf_page_vision_verbatim_layout_sections",
        "warnings": payload.get("warnings") or [],
    }
