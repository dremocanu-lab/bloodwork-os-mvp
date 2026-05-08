from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


MODEL_NAME = os.getenv("OPENAI_DISCHARGE_MODEL", "gpt-4.1")


DISCHARGE_SYSTEM_PROMPT = """
You are reading a Romanian hospital discharge summary PDF.

Your job:
- Read the document directly.
- Do not use OCR output.
- Do not summarize away medical detail.
- Preserve Romanian medical wording.
- Extract patient/document metadata when visible.
- Build structured major sections for the discharge reader.
- Preserve long EPICRIZA chronology as much as possible.
- Do not invent missing values.
- Do not translate.
- Return strict JSON only.

Important:
- EPICRIZA / evolutie / clinical course should stay together as one section when it is a long chronological history.
- Do not split every "Hemograma", "Biochimie", "Consult", "Ecografie" line into separate top-level sections.
- Keep lab values, dates, diagnoses, medications, units, and transfusion details exactly as written when possible.
"""


DISCHARGE_JSON_SCHEMA = {
    "name": "discharge_summary_structured_output",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "patient_name": {"type": ["string", "null"]},
            "date_of_birth": {"type": ["string", "null"]},
            "age": {"type": ["string", "null"]},
            "sex": {"type": ["string", "null"]},
            "cnp": {"type": ["string", "null"]},
            "patient_identifier": {"type": ["string", "null"]},
            "lab_name": {"type": ["string", "null"]},
            "referring_doctor": {"type": ["string", "null"]},
            "report_name": {"type": ["string", "null"]},
            "source_language": {"type": ["string", "null"]},
            "collected_on": {"type": ["string", "null"]},
            "reported_on": {"type": ["string", "null"]},
            "registered_on": {"type": ["string", "null"]},
            "generated_on": {"type": ["string", "null"]},
            "extracted_text": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "title": {"type": "string"},
                        "original_titles": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "body": {"type": "string"},
                        "formatted_body": {"type": ["string", "null"]},
                        "formatting_method": {"type": ["string", "null"]},
                        "formatting_confidence": {"type": ["number", "null"]},
                        "confidence": {"type": "number"},
                    },
                    "required": [
                        "key",
                        "title",
                        "original_titles",
                        "body",
                        "formatted_body",
                        "formatting_method",
                        "formatting_confidence",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "patient_name",
            "date_of_birth",
            "age",
            "sex",
            "cnp",
            "patient_identifier",
            "lab_name",
            "referring_doctor",
            "report_name",
            "source_language",
            "collected_on",
            "reported_on",
            "registered_on",
            "generated_on",
            "extracted_text",
            "sections",
            "warnings",
        ],
        "additionalProperties": False,
    },
}


ALLOWED_SECTION_KEYS = {
    "administrative_information",
    "diagnoses",
    "discharge_status",
    "epicriza",
    "investigations",
    "laboratory_normal",
    "laboratory_abnormal",
    "treatment_in_hospital",
    "recommended_treatment",
    "recommendations",
    "other",
}


def dedupe_warnings(warnings: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    for warning in warnings:
        clean_warning = str(warning).strip()
        if not clean_warning or clean_warning in seen:
            continue
        deduped.append(clean_warning)
        seen.add(clean_warning)

    return deduped


def _client_available() -> bool:
    return OpenAI is not None and bool(os.getenv("OPENAI_API_KEY"))


def _file_to_data_url(file_path: Path, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    mime_type = "application/pdf"

    if suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    elif suffix == ".png":
        mime_type = "image/png"
    elif suffix == ".webp":
        mime_type = "image/webp"
    elif suffix == ".pdf":
        mime_type = "application/pdf"

    encoded = base64.b64encode(file_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)

    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []

    try:
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if isinstance(text, str) and text.strip():
                    parts.append(text)
    except Exception:
        return ""

    return "\n".join(parts).strip()


def _safe_json_loads(value: str) -> dict[str, Any]:
    try:
        return json.loads(value)
    except Exception:
        start = value.find("{")
        end = value.rfind("}")

        if start >= 0 and end > start:
            return json.loads(value[start : end + 1])

        raise


def _normalize_section(section: dict[str, Any], index: int) -> dict[str, Any]:
    key = str(section.get("key") or "").strip() or "other"

    if key not in ALLOWED_SECTION_KEYS:
        key = "other"

    title = str(section.get("title") or key.replace("_", " ").title()).strip()
    body = str(section.get("body") or "").strip()
    formatted_body = section.get("formatted_body")

    if formatted_body is None:
        formatted_body = body
    else:
        formatted_body = str(formatted_body).strip()

    original_titles_raw = section.get("original_titles") or []
    if not isinstance(original_titles_raw, list):
        original_titles_raw = [str(original_titles_raw)]

    original_titles = [str(item).strip() for item in original_titles_raw if str(item).strip()]

    confidence = section.get("confidence")
    try:
        confidence_number = float(confidence)
    except Exception:
        confidence_number = 0.75

    formatting_confidence = section.get("formatting_confidence")
    try:
        formatting_confidence_number = float(formatting_confidence) if formatting_confidence is not None else None
    except Exception:
        formatting_confidence_number = None

    return {
        "key": key,
        "title": title,
        "original_titles": original_titles,
        "body": body,
        "formatted_body": formatted_body,
        "formatting_method": section.get("formatting_method") or "openai_document_read",
        "formatting_confidence": formatting_confidence_number,
        "confidence": max(0.0, min(confidence_number, 1.0)),
    }


def _build_note_body(sections: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "document_type": "discharge_summary",
            "sections": sections,
        },
        ensure_ascii=False,
    )


def process_uploaded_discharge_summary(
    file_path: Path,
    filename: str,
    temp_dir: Path | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []

    if not _client_available():
        raise RuntimeError("OPENAI_API_KEY is not configured, so discharge summary processing cannot run.")

    if not file_path.exists():
        raise RuntimeError(f"Discharge file does not exist: {file_path}")

    client = OpenAI()
    file_data_url = _file_to_data_url(file_path, filename)

    user_prompt = {
        "filename": filename,
        "instructions": [
            "Read this discharge summary document directly.",
            "Create one structured discharge_summary payload.",
            "Keep the EPICRIZA section long and detailed.",
            "Do not use OCR text.",
            "Do not summarize clinically important chronology.",
            "Do not translate Romanian.",
            "Use null for missing metadata.",
            "The extracted_text field should be the best full plain-text reconstruction you can produce from the document.",
            "The sections array should contain major document sections only.",
        ],
        "allowed_section_keys": sorted(ALLOWED_SECTION_KEYS),
    }

    response = client.responses.create(
        model=MODEL_NAME,
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": DISCHARGE_SYSTEM_PROMPT,
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(user_prompt, ensure_ascii=False),
                    },
                    {
                        "type": "input_file",
                        "filename": filename,
                        "file_data": file_data_url,
                    },
                ],
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": DISCHARGE_JSON_SCHEMA["name"],
                "strict": True,
                "schema": DISCHARGE_JSON_SCHEMA["schema"],
            }
        },
    )

    output_text = _extract_output_text(response)

    if not output_text:
        raise RuntimeError("OpenAI returned empty output for discharge summary.")

    parsed = _safe_json_loads(output_text)

    sections_raw = parsed.get("sections") or []
    if not isinstance(sections_raw, list):
        sections_raw = []

    sections = [
        _normalize_section(section, index)
        for index, section in enumerate(sections_raw)
        if isinstance(section, dict) and str(section.get("body") or section.get("formatted_body") or "").strip()
    ]

    if not sections:
        warnings.append("OpenAI did not return any discharge sections.")

    warnings.extend(parsed.get("warnings") or [])

    extracted_text = str(parsed.get("extracted_text") or "").strip()

    if not extracted_text:
        extracted_text = "\n\n".join(section["body"] for section in sections).strip()
        warnings.append("OpenAI did not return extracted_text; rebuilt it from sections.")

    report_name = parsed.get("report_name") or "Fișă de externare"
    reported_on = parsed.get("reported_on")
    if report_name == "Fișă de externare" and reported_on:
        report_name = f"Fișă de externare {reported_on}"

    parsed_data = {
        "patient_name": parsed.get("patient_name"),
        "date_of_birth": parsed.get("date_of_birth"),
        "age": parsed.get("age"),
        "sex": parsed.get("sex"),
        "cnp": parsed.get("cnp"),
        "patient_identifier": parsed.get("patient_identifier"),
        "lab_name": parsed.get("lab_name"),
        "sample_type": None,
        "referring_doctor": parsed.get("referring_doctor"),
        "report_name": report_name,
        "report_type": "Discharge summary",
        "source_language": parsed.get("source_language") or "ro",
        "test_date": None,
        "collected_on": parsed.get("collected_on"),
        "reported_on": reported_on,
        "registered_on": parsed.get("registered_on"),
        "generated_on": parsed.get("generated_on"),
        "note_body": _build_note_body(sections),
        "labs": [],
        "warnings": dedupe_warnings(warnings),
    }

    return {
        "extracted_text": extracted_text,
        "parsed_data": parsed_data,
        "ocr_method": "none_openai_direct_document_read",
        "ocr_quality": None,
        "warnings": dedupe_warnings(warnings),
    }