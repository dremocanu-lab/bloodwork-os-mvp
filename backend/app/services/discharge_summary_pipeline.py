from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI


MODEL = os.getenv("OPENAI_DISCHARGE_LAYOUT_MODEL", "gpt-4.1")
MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_DISCHARGE_MAX_OUTPUT_TOKENS", "32768"))


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


SYSTEM_PROMPT = """
You are a Romanian medical document extraction engine.

You receive a user-provided hospital discharge PDF.
Your job is to extract the complete discharge summary text into structured JSON.

CRITICAL RULES:
- Do NOT summarize.
- Do NOT shorten.
- Do NOT omit repeated follow-up entries.
- Do NOT omit old dates, repeated admissions, transfusions, lab values, imaging, consultations, treatments, or recommendations.
- Do NOT write placeholders such as "[...]", "[continues]", "[full text inserted]", "[text omitted]", or similar.
- Preserve the complete clinical chronology.
- Preserve all numbers, dates, medications, lab values, units, diagnoses, doctor names, hospital names, and recommendations.
- Lightly normalize spacing only when it improves readability.
- If a section is very long, still include the full text.
- Output valid JSON only. No markdown.

You must return this JSON shape exactly:

{
  "document_type": "discharge_summary",
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
      "body": "complete verbatim text"
    }
  ]
}

Allowed section keys:
- administrative_information
- diagnoses
- discharge_status
- epicriza
- investigations
- laboratory_normal
- laboratory_abnormal
- treatment_in_hospital
- recommended_treatment
- recommendations
- other

If the document has one huge EPICRIZA section, keep it as one huge epicriza section.
If there are clear separate headings, split them into separate sections.
The EPICRIZA section must include the complete body, not a short summary.
"""


USER_PROMPT = """
Extract this Romanian discharge summary.

Return the full document content as JSON.

Most important:
- Give me EVERYTHING.
- The EPICRIZA section must be complete and verbatim.
- Do not stop early.
- Do not use ellipses.
- Do not use placeholders.
- Do not summarize.
- Preserve the entire chronological medical history.
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
        raise RuntimeError(f"OpenAI returned invalid JSON: {exc}. First 1000 chars: {cleaned[:1000]}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("OpenAI returned JSON, but it was not an object.")

    return parsed


def _clean_section(section: dict[str, Any], index: int) -> dict[str, Any]:
    key = str(section.get("key") or "other").strip()

    if key not in ALLOWED_SECTION_KEYS:
        key = "other"

    title = str(section.get("title") or key.replace("_", " ").title()).strip()
    body = str(section.get("body") or "").strip()

    original_titles = section.get("original_titles")
    if not isinstance(original_titles, list):
        original_titles = [title]

    cleaned_original_titles = [
        str(item).strip()
        for item in original_titles
        if str(item).strip()
    ]

    if not cleaned_original_titles:
        cleaned_original_titles = [title]

    return {
        "key": key if index == 0 or key != "other" else f"other_{index}",
        "title": title,
        "original_titles": cleaned_original_titles,
        "body": body,
        "formatted_body": body,
        "formatting_method": "openai_pdf_single_pass",
        "formatting_confidence": 0.9,
        "confidence": 0.9,
    }


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sections = payload.get("sections")

    if not isinstance(sections, list):
        sections = []

    cleaned_sections = []
    for index, section in enumerate(sections):
        if isinstance(section, dict):
            cleaned = _clean_section(section, index)
            if cleaned["body"]:
                cleaned_sections.append(cleaned)

    if not cleaned_sections:
        fallback_text = json.dumps(payload, ensure_ascii=False, indent=2)
        cleaned_sections = [
            {
                "key": "epicriza",
                "title": "EPICRIZA",
                "original_titles": ["EPICRIZA"],
                "body": fallback_text,
                "formatted_body": fallback_text,
                "formatting_method": "openai_pdf_single_pass_fallback",
                "formatting_confidence": 0.4,
                "confidence": 0.4,
            }
        ]

    return {
        "document_type": "discharge_summary",
        "patient_name": payload.get("patient_name"),
        "cnp": payload.get("cnp"),
        "date_of_birth": payload.get("date_of_birth"),
        "sex": payload.get("sex"),
        "admission_date": payload.get("admission_date"),
        "discharge_date": payload.get("discharge_date"),
        "hospital_name": payload.get("hospital_name"),
        "sections": cleaned_sections,
    }


def _payload_to_text(payload: dict[str, Any]) -> str:
    sections = payload.get("sections") or []

    parts: list[str] = []

    for section in sections:
        title = str(section.get("title") or "").strip()
        body = str(section.get("body") or "").strip()

        if title and body:
            parts.append(f"{title}\n\n{body}")
        elif body:
            parts.append(body)

    return "\n\n---\n\n".join(parts).strip()


def process_uploaded_discharge_summary(file_path: str | Path, filename: str | None = None) -> dict[str, Any]:
    """
    Single-pass discharge summary pipeline.

    No OCR.
    No Google Document AI.
    No page chunks.
    Sends the full PDF to OpenAI and asks for complete JSON extraction.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Discharge PDF not found: {path}")

    client = _client()

    uploaded_file = None

    try:
        with path.open("rb") as file_handle:
            uploaded_file = client.files.create(
                file=file_handle,
                purpose="user_data",
            )

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
                            "type": "input_file",
                            "file_id": uploaded_file.id,
                        },
                        {
                            "type": "input_text",
                            "text": USER_PROMPT,
                        },
                    ],
                },
            ],
            temperature=0,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )

        raw_text = _extract_response_text(response)
        parsed = _safe_json_loads(raw_text)
        payload = _normalize_payload(parsed)
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
            "report_type": "discharge_summary",
            "source_language": "ro",
            "formatting_method": "openai_pdf_single_pass",
        }

    finally:
        if uploaded_file is not None:
            try:
                client.files.delete(uploaded_file.id)
            except Exception:
                pass