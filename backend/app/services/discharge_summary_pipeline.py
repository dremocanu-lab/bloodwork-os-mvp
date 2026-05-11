from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import fitz
from openai import OpenAI


MODEL = os.getenv("OPENAI_DISCHARGE_LAYOUT_MODEL", "gpt-4.1")
PAGE_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_DISCHARGE_PAGE_MAX_OUTPUT_TOKENS", "16000"))
PDF_RENDER_ZOOM = float(os.getenv("OPENAI_DISCHARGE_RENDER_ZOOM", "2.6"))
MAX_PAGES = int(os.getenv("OPENAI_DISCHARGE_MAX_PAGES", "90"))


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
You are a Romanian hospital discharge document layout transcription engine.

Your job is NOT to summarize and NOT to rewrite.
Your job is to transcribe one visible PDF page as faithfully as possible, preserving the visual layout of the paper.

CRITICAL RULES:
- Extract VERBATIM visible text from the page.
- Preserve line breaks exactly as much as possible.
- Preserve indentation, spacing, bullets, dashes, arrows, table-like alignment, and short line fragments.
- Preserve section order from top to bottom.
- Preserve repeated entries and repeated headings.
- Do NOT combine separate lines into one paragraph if they appear on separate lines.
- Do NOT turn tables into prose.
- Do NOT rewrite Romanian medical language.
- Do NOT fix typos, OCR-looking words, abbreviations, punctuation, dates, values, or units.
- Do NOT summarize, shorten, infer, normalize, or clinically clean anything.
- Do NOT omit old dates, repeated admissions, transfusions, lab values, imaging, treatments, consults, or recommendations.
- Never write placeholders such as "[...]", "continues", "omitted", "same as above", or "full text inserted".
- If a word is unreadable, write [?] only for that unreadable word.
- Keep Romanian text in Romanian.
- This is one page of a multi-page document.
- Return valid JSON only. No markdown.

Very important formatting rule:
Each section body must be a preformatted text block.
Use newline characters and leading spaces to mimic the original page layout.
For table-like areas, keep label/value pairs on separate lines and use spaces to preserve alignment.

Use these section keys only:
- administrative_information: first-page hospital/patient/admin table fields, provider, doctor, FO, dates, section, compartment, CNP, address, insurance, work/occupation, discharge/admission data.
- diagnoses: diagnostic boxes/lists, DRG diagnoses, secondary diagnoses, free-form diagnoses.
- discharge_status: status at discharge / stare la externare.
- epicriza: the EPICRIZA narrative and chronological medical history, including old labs, admissions, imaging, transfusions, consultations, and treatment history when they appear under EPICRIZA.
- investigations: imaging, ultrasound, radiology, ECG, echo, or other investigations outside epicriza when separately headed.
- consults: consultations outside epicriza when separately headed.
- laboratory_normal: section titled like "Examen de laborator cu valori normale" or equivalent.
- laboratory_abnormal: section titled like "Examen de laborator cu valori patologice" or equivalent.
- treatment_in_hospital: treatment administered during admission, transfusions, medications given in hospital, when separately headed.
- recommended_treatment: "Tratament recomandat".
- prescriptions_released: "Retete eliberate" / "Rețete eliberate" / "Rp."
- recommendations: recommendations/follow-up/discharge instructions.
- other: any visible text that does not fit above.

Return exactly this JSON shape:
{
  "page_number": number,
  "printed_page_label": string | null,
  "document_page_count_visible": string | null,
  "patient_name": string | null,
  "cnp": string | null,
  "date_of_birth": string | null,
  "sex": string | null,
  "admission_date": string | null,
  "discharge_date": string | null,
  "hospital_name": string | null,
  "sections": [
    {
      "key": "epicriza",
      "title": "EPICRIZA",
      "original_titles": ["EPICRIZA"],
      "body": "preformatted verbatim visible text from this page with original line breaks and indentation"
    }
  ],
  "warnings": []
}
"""


USER_PROMPT_TEMPLATE = """
Transcribe page {page_number} of this Romanian discharge document.

Put ALL visible text into sections.

Formatting requirements:
- Preserve the page layout as much as possible.
- Keep original line breaks.
- Keep indentation.
- Keep bullets, dashes, arrows, parentheses, and short line fragments.
- Keep table-like fields as table-like text.
- Do not merge separate lines into one paragraph.
- Do not convert the page into a summary.
- The section body must look like copied text from the paper.

Important sectioning rules:
- On page 1, put the hospital/patient/admin table into administrative_information.
- On page 1, put DRG/diagnosis boxes into diagnoses.
- Put the EPICRIZA narrative into epicriza.
- If the page has a separate heading such as "Tratament recomandat", "Retete eliberate", "Examen de laborator cu valori normale", "Examen de laborator cu valori patologice", "Recomandari", or similar, split that text into its own matching section.
- If a section starts on this page and continues from the previous page, still include the text visible on this page.

Return complete preformatted verbatim JSON for this page only.
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

            pages.append(
                {
                    "page_number": index + 1,
                    "width": page.rect.width,
                    "height": page.rect.height,
                    "image_url": f"data:image/png;base64,{encoded}",
                }
            )

    return pages


def _call_openai_for_page(client: OpenAI, page: dict[str, Any]) -> dict[str, Any]:
    page_number = page["page_number"]

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
                        "text": USER_PROMPT_TEMPLATE.format(page_number=page_number),
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
    text = text.replace("\ufeff", "")
    text = text.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Preserve indentation and table-like spacing.
    # Only reduce absurd blank vertical gaps.
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

    # EPICRIZA often continues across many pages. Keep it as one major section
    # even if the model labels continuation titles slightly differently.
    if previous["key"] == "epicriza":
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

    This pipeline:
    - renders every PDF page as an image
    - sends each page separately to OpenAI vision
    - asks for preformatted verbatim text
    - separates the text into document sections
    - merges section continuations across pages
    - stores the complete JSON in note_body

    It is intentionally not a summarizer.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Discharge PDF not found: {path}")

    client = _client()
    rendered_pages = _render_pdf_pages_as_data_urls(path)

    if not rendered_pages:
        raise RuntimeError("No PDF pages could be rendered for discharge extraction.")

    page_payloads: list[dict[str, Any]] = []

    for page in rendered_pages:
        page_payloads.append(_call_openai_for_page(client, page))

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