from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


MODEL_NAME = os.getenv("OPENAI_DISCHARGE_MODEL", "gpt-4.1")

# Keep this high because discharge summaries can be huge.
# If the API rejects this number, set OPENAI_DISCHARGE_MAX_OUTPUT_TOKENS=32000 on Render.
MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_DISCHARGE_MAX_OUTPUT_TOKENS", "60000"))

MIN_DISCHARGE_TEXT_CHARS = int(os.getenv("OPENAI_DISCHARGE_MIN_TEXT_CHARS", "8000"))


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


DISCHARGE_SYSTEM_PROMPT = """
You are reading a Romanian hospital discharge summary PDF.

CRITICAL RULES:
- You must return the actual text from the document.
- Do NOT summarize the EPICRIZA.
- Do NOT replace the EPICRIZA with a placeholder.
- Do NOT say "the full text was inserted into extracted_text".
- Do NOT say "text omitted".
- Do NOT say "see extracted_text".
- The section body itself must contain the full actual Romanian text for that section.
- Preserve Romanian medical wording.
- Preserve dates, lab values, diagnoses, medications, units, transfusions, consults, imaging findings, and chronology.
- Do not translate.
- Do not invent missing values.
- If a field is not visible, use null.
- Return strict JSON only.

The most important section is EPICRIZA.
For EPICRIZA:
- Include the actual chronological text.
- Include the beginning lines under the EPICRIZA heading.
- Include the historical diagnosis, treatment history, visit-by-visit evolution, transfusions, labs, imaging, and final hospitalizations.
- Do not compress it into a summary.

You are allowed to structure the document into sections, but the content must be the actual document content.
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


BAD_PLACEHOLDER_PHRASES = [
    "textul complet",
    "a fost inserat",
    "a fost introdus",
    "in extracted_text",
    "în extracted_text",
    "see extracted_text",
    "vezi extracted_text",
    "omitted",
    "omis",
    "placeholder",
    "cronologia prezentărilor",
    "nu este inclus",
]


def _client_available() -> bool:
    return OpenAI is not None and bool(os.getenv("OPENAI_API_KEY"))


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


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)

    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

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

    formatted_body_raw = section.get("formatted_body")
    formatted_body = body if formatted_body_raw is None else str(formatted_body_raw).strip()

    original_titles_raw = section.get("original_titles") or []
    if not isinstance(original_titles_raw, list):
        original_titles_raw = [str(original_titles_raw)]

    original_titles = [str(item).strip() for item in original_titles_raw if str(item).strip()]

    try:
        confidence_number = float(section.get("confidence"))
    except Exception:
        confidence_number = 0.75

    formatting_confidence = section.get("formatting_confidence")
    try:
        formatting_confidence_number = (
            float(formatting_confidence) if formatting_confidence is not None else None
        )
    except Exception:
        formatting_confidence_number = None

    return {
        "key": key,
        "title": title,
        "original_titles": original_titles,
        "body": body,
        "formatted_body": formatted_body,
        "formatting_method": section.get("formatting_method") or "openai_pdf_file_read",
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


def _looks_like_placeholder(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(phrase in normalized for phrase in BAD_PLACEHOLDER_PHRASES)


def _validate_discharge_output(parsed: dict[str, Any], sections: list[dict[str, Any]]) -> None:
    extracted_text = str(parsed.get("extracted_text") or "").strip()
    combined_sections = "\n\n".join(
        str(section.get("body") or section.get("formatted_body") or "") for section in sections
    ).strip()

    combined = f"{extracted_text}\n\n{combined_sections}".strip()

    if _looks_like_placeholder(combined):
        raise RuntimeError(
            "OpenAI returned a placeholder instead of the actual discharge text. "
            "The document was not saved. Retry after the stricter discharge prompt is deployed."
        )

    if len(combined) < MIN_DISCHARGE_TEXT_CHARS:
        raise RuntimeError(
            f"OpenAI returned too little discharge text ({len(combined)} characters). "
            f"Expected at least {MIN_DISCHARGE_TEXT_CHARS}. The document was not saved."
        )

    epicriza_sections = [
        section for section in sections if section.get("key") == "epicriza"
    ]

    if not epicriza_sections:
        raise RuntimeError(
            "OpenAI did not return an EPICRIZA section. The document was not saved."
        )

    epicriza_text = "\n\n".join(
        str(section.get("body") or section.get("formatted_body") or "")
        for section in epicriza_sections
    ).strip()

    if len(epicriza_text) < 3000:
        raise RuntimeError(
            f"OpenAI returned an EPICRIZA section that is too short ({len(epicriza_text)} characters). "
            "The document was not saved."
        )


def _call_openai_with_file(client: Any, file_id: str, filename: str, retry: bool = False) -> dict[str, Any]:
    user_prompt = {
        "filename": filename,
        "instructions": [
            "Read the attached PDF directly.",
            "Return the real full Romanian text, not a placeholder.",
            "The extracted_text field must contain the best full plain-text reconstruction of the document.",
            "The EPICRIZA section body must contain the actual EPICRIZA text.",
            "Do not summarize the EPICRIZA.",
            "Do not refer to extracted_text instead of writing the section body.",
            "Preserve long chronology, lab values, dates, diagnoses, medications, imaging, transfusions, consults, and recommendations.",
            "Use major sections only.",
            "Use null for missing metadata.",
        ],
        "required_quality_bar": {
            "bad_output_examples": [
                "[Textul complet a fost inserat in extracted_text]",
                "[Full text omitted]",
                "The detailed chronology is in extracted_text",
                "Summary of clinical course",
            ],
            "good_output": "The actual visible Romanian medical text from the PDF.",
        },
        "allowed_section_keys": sorted(ALLOWED_SECTION_KEYS),
    }

    if retry:
        user_prompt["retry_reason"] = (
            "Previous output was too short or placeholder-like. "
            "This time output the actual text. Do not use placeholders."
        )

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
                        "type": "input_file",
                        "file_id": file_id,
                    },
                    {
                        "type": "input_text",
                        "text": json.dumps(user_prompt, ensure_ascii=False),
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
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    output_text = _extract_output_text(response)

    if not output_text:
        raise RuntimeError("OpenAI returned empty output for discharge summary.")

    return _safe_json_loads(output_text)


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

    uploaded_file = None

    try:
        with open(file_path, "rb") as file_handle:
            uploaded_file = client.files.create(
                file=file_handle,
                purpose="user_data",
            )

        file_id = uploaded_file.id

        try:
            parsed = _call_openai_with_file(
                client=client,
                file_id=file_id,
                filename=filename,
                retry=False,
            )
        except Exception as first_error:
            # Retry once only if the first output was bad/short/placeholder.
            parsed = _call_openai_with_file(
                client=client,
                file_id=file_id,
                filename=filename,
                retry=True,
            )
            warnings.append(f"OpenAI discharge extraction required retry: {first_error}")

        sections_raw = parsed.get("sections") or []
        if not isinstance(sections_raw, list):
            sections_raw = []

        sections = [
            _normalize_section(section, index)
            for index, section in enumerate(sections_raw)
            if isinstance(section, dict)
            and str(section.get("body") or section.get("formatted_body") or "").strip()
        ]

        _validate_discharge_output(parsed, sections)

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
            "ocr_method": "none_openai_direct_pdf_file_id",
            "ocr_quality": None,
            "warnings": dedupe_warnings(warnings),
        }

    finally:
        # Optional cleanup. If deletion fails, ignore it.
        if uploaded_file is not None:
            try:
                client.files.delete(uploaded_file.id)
            except Exception:
                pass