"""Conservative structured extraction for the Phase 4 clinical readers.

Only `discharge_summary` and `bloodwork` have dedicated pipelines today
(see `discharge_summary_pipeline.py`, `document_pipeline.py`). This
module gives the other narrative document types — imaging, operative,
pathology, prescription/medication list, specialist consultation — a
type-aware structured extraction, following the exact same conservative
convention as `openai_discharge_service.py`: read the source file
directly (not a re-OCR'd text proxy), temperature 0, JSON-only output,
and an explicit "do not invent missing data" instruction. No Reducto
Parse/Extract exists yet (see BRAGI_REDUCTO_PLAN.md §3) — this is the
legacy/OpenAI equivalent, and is expected to be superseded by a Reducto
Extract call once that integration exists.

If OPENAI_API_KEY is not configured, or the call fails, this returns an
empty result rather than raising — a missing "structured summary" must
never fail the whole upload; the Reader always still has the raw
extracted text as a fallback.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.services.openai_discharge_service import _guess_mime_type, _read_as_data_url

READER_MODEL = os.getenv("OPENAI_READER_MODEL", "gpt-4.1")

# Per-type section keys, in display order. Keys are stable identifiers
# used by the frontend Reader to look up labels — see
# frontend/lib/reader-sections.ts for the EN/RO label mapping.
SECTION_KEYS: dict[str, list[str]] = {
    "imaging_report": [
        "modality", "body_region", "exam_date", "indication", "technique",
        "comparison", "findings", "impression", "recommendations", "incidental_findings",
    ],
    "operative_report": [
        "procedure", "date", "indication", "surgeon", "assistants", "anesthesia",
        "findings", "procedural_steps", "complications", "blood_loss",
        "specimens", "postoperative_plan",
    ],
    "pathology_report": [
        "specimen", "gross_description", "microscopic_description", "final_diagnosis",
        "histologic_grade", "margins", "biomarkers", "comments",
    ],
    "prescription": ["medications", "prescriber", "date", "instructions"],
    "medication_list": ["medications", "instructions"],
    "specialist_consultation": [
        "specialty", "clinician", "date", "reason", "history", "exam",
        "assessment", "diagnoses", "investigations", "plan", "recommendations", "follow_up",
    ],
}

_SYSTEM_PROMPT_TEMPLATE = """
You are a medical document extraction engine. Read the uploaded {doc_type_label}
directly and extract it into structured JSON.

Rules:
1. Extract ONLY what is explicitly present in the source document.
2. Do NOT infer, diagnose, summarize into new medical conclusions, or add
   any clinical information that is not written in the document.
3. If a section is not present in the source, set its value to null —
   never fabricate content for a missing section.
4. Preserve source wording (including Romanian) rather than rewriting it;
   light cleanup of obvious OCR spacing errors is fine.
5. Do not use markdown. Return JSON only, no explanation.

Return this exact JSON shape:
{{
  "language": "ro" | "en" | "mixed",
  "sections": {{
{section_lines}
  }}
}}

Each section value must be a string (the extracted text for that
section, preserving source wording) or null if not present in the
document.
"""


def _build_prompt(document_type: str) -> str:
    keys = SECTION_KEYS.get(document_type, [])
    section_lines = ",\n".join(f'    "{key}": string|null' for key in keys)
    doc_type_label = document_type.replace("_", " ")
    return _SYSTEM_PROMPT_TEMPLATE.format(doc_type_label=doc_type_label, section_lines=section_lines)


def _extract_json_from_text(raw_text: str) -> dict[str, Any]:
    cleaned = (raw_text or "").strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass

    return {}


def extract_structured_sections(
    document_type: str,
    file_path: Path,
    filename: str,
    content_type: str | None,
) -> dict[str, Any]:
    """Returns {"language": str|None, "sections": {key: text|None}, "warnings": [...]}.

    Never raises for missing config/failure — callers should treat an
    empty `sections` dict as "no structured summary available", not an
    error.
    """
    section_keys = SECTION_KEYS.get(document_type)

    if not section_keys:
        return {"language": None, "sections": {}, "warnings": [f"No section schema for {document_type}."]}

    if not os.getenv("OPENAI_API_KEY"):
        return {"language": None, "sections": {}, "warnings": ["OPENAI_API_KEY not configured."]}

    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  # OPENAI_API_KEY already verified present above
        mime_type = _guess_mime_type(file_path, filename, content_type)
        data_url = _read_as_data_url(file_path, mime_type)

        if mime_type == "application/pdf":
            file_content = {"type": "input_file", "filename": filename, "file_data": data_url}
        elif mime_type.startswith("image/"):
            file_content = {"type": "input_image", "image_url": data_url}
        else:
            return {"language": None, "sections": {}, "warnings": [f"Unsupported file type for reader extraction: {mime_type}"]}

        response = client.responses.create(
            model=READER_MODEL,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": _build_prompt(document_type)}],
                },
                {
                    "role": "user",
                    "content": [
                        file_content,
                        {"type": "input_text", "text": "Extract this document as instructed."},
                    ],
                },
            ],
            temperature=0,
            max_output_tokens=8000,
        )

        raw_text = getattr(response, "output_text", None) or str(response)
        payload = _extract_json_from_text(raw_text)
        raw_sections = payload.get("sections") or {}

        # Only keep keys we actually asked for, and only string/None values —
        # never trust the model to have followed the shape exactly.
        sections = {}
        for key in section_keys:
            value = raw_sections.get(key)
            if isinstance(value, str) and value.strip():
                sections[key] = value.strip()
            elif isinstance(value, (list, dict)) and value:
                # e.g. a medications list the model returned as an array —
                # render as readable text rather than discarding it.
                sections[key] = json.dumps(value, ensure_ascii=False)

        return {
            "language": payload.get("language"),
            "sections": sections,
            "warnings": [] if sections else ["No structured sections were extracted from this document."],
        }
    except Exception as error:
        return {"language": None, "sections": {}, "warnings": [f"Structured extraction failed: {error}"]}
