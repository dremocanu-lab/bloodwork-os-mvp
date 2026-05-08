import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI


DISCHARGE_MODEL = os.getenv("OPENAI_DISCHARGE_MODEL", "gpt-4.1")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


DISCHARGE_JSON_SCHEMA = {
    "document_type": "discharge_summary",
    "language": "ro",
    "patient": {
        "name": None,
        "cnp": None,
        "date_of_birth": None,
        "age": None,
        "sex": None,
    },
    "document_metadata": {
        "hospital": None,
        "department": None,
        "admission_date": None,
        "discharge_date": None,
        "generated_at": None,
        "attending_doctor": None,
        "report_name": None,
    },
    "sections": [
        {
            "key": "epicriza",
            "title": "Epicriză / Clinical course",
            "original_titles": ["EPICRIZA"],
            "body": "",
            "formatted_body": "",
            "confidence": 0.95,
        }
    ],
}


SYSTEM_PROMPT = """
You are a medical document extraction engine for Romanian hospital discharge summaries.

Your job:
Read the uploaded discharge document directly.
Extract the document into structured JSON.
Preserve clinically important text.
Do NOT summarize away clinical details.
Do NOT invent missing data.
Do NOT use markdown.
Do NOT return explanations.
Return JSON only.

Critical requirements:
1. The EPICRIZA section must include the very first line under the EPICRIZA heading.
2. Preserve chronological entries.
3. Preserve lab values, dates, medication names, transfusion units, diagnoses, and procedure details.
4. Keep Romanian text as Romanian.
5. Clean obvious OCR spacing errors only when safe.
6. Do not convert this into a short summary.
7. Section bodies should be readable, but clinically faithful.
8. If a heading is unclear, keep it under the closest useful section.
9. Never omit severe abnormal values such as Hb 3.4, Hb 2.9, platelets, leukocytes, ferritin, LDH, INR, APTT, etc.
10. For discharge summaries, the output should be structured for display in a patient portal, not rewritten as a doctor letter.

Required JSON shape:
{
  "document_type": "discharge_summary",
  "language": "ro" | "en" | "mixed",
  "patient": {
    "name": string|null,
    "cnp": string|null,
    "date_of_birth": string|null,
    "age": string|null,
    "sex": string|null
  },
  "document_metadata": {
    "hospital": string|null,
    "department": string|null,
    "admission_date": string|null,
    "discharge_date": string|null,
    "generated_at": string|null,
    "attending_doctor": string|null,
    "report_name": string|null
  },
  "sections": [
    {
      "key": string,
      "title": string,
      "original_titles": string[],
      "body": string,
      "formatted_body": string,
      "confidence": number
    }
  ]
}

Use these preferred section keys when possible:
- administrative_information
- diagnoses
- epicriza
- investigations
- laboratory_values
- treatment_in_hospital
- recommended_treatment
- recommendations
- discharge_status
- other

For EPICRIZA:
- key must be "epicriza"
- title should be "Epicriză / Clinical course"
- original_titles should include "EPICRIZA" if seen
"""


USER_PROMPT = """
Extract this hospital discharge document.

Important:
- Preserve the full EPICRIZA narrative.
- The first line after the EPICRIZA heading must not be dropped.
- Keep the long clinical chronology.
- Return JSON only.
"""


def _guess_mime_type(file_path: str, filename: Optional[str] = None, content_type: Optional[str] = None) -> str:
    if content_type:
        return content_type

    guessed, _ = mimetypes.guess_type(filename or file_path)
    if guessed:
        return guessed

    suffix = Path(filename or file_path).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"

    return "application/octet-stream"


def _read_as_data_url(file_path: str, mime_type: str) -> str:
    with open(file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("OpenAI returned an empty response.")

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _normalize_section_key(title: str, fallback: str) -> str:
    lower = (title or "").lower()

    if "epicriz" in lower or "clinical course" in lower:
        return "epicriza"
    if "diagn" in lower:
        return "diagnoses"
    if "invest" in lower or "imagistic" in lower or "ecografie" in lower or "ct" in lower or "rx" in lower:
        return "investigations"
    if "laborator" in lower or "hemogram" in lower or "biochim" in lower:
        return "laboratory_values"
    if "tratament" in lower and ("recomand" in lower or "externare" in lower):
        return "recommended_treatment"
    if "tratament" in lower:
        return "treatment_in_hospital"
    if "recomand" in lower:
        return "recommendations"
    if "externare" in lower or "status" in lower:
        return "discharge_status"

    return fallback or "other"


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("OpenAI discharge payload was not a JSON object.")

    payload.setdefault("document_type", "discharge_summary")
    payload.setdefault("language", "ro")
    payload.setdefault("patient", {})
    payload.setdefault("document_metadata", {})
    payload.setdefault("sections", [])

    if not isinstance(payload["patient"], dict):
        payload["patient"] = {}

    if not isinstance(payload["document_metadata"], dict):
        payload["document_metadata"] = {}

    if not isinstance(payload["sections"], list):
        payload["sections"] = []

    normalized_sections: List[Dict[str, Any]] = []

    for index, section in enumerate(payload["sections"]):
        if not isinstance(section, dict):
            continue

        title = str(section.get("title") or section.get("key") or f"Section {index + 1}").strip()
        key = str(section.get("key") or "").strip()
        key = _normalize_section_key(title, key)

        body = section.get("body")
        formatted_body = section.get("formatted_body")

        if body is None:
            body = formatted_body or ""

        if formatted_body is None:
            formatted_body = body or ""

        original_titles = section.get("original_titles")
        if not isinstance(original_titles, list):
            original_titles = [title]

        try:
            confidence = float(section.get("confidence", 0.9))
        except Exception:
            confidence = 0.9

        normalized_sections.append(
            {
                "key": key,
                "title": title,
                "original_titles": [str(item) for item in original_titles if item],
                "body": str(body or "").strip(),
                "formatted_body": str(formatted_body or body or "").strip(),
                "formatting_method": "openai_direct_document_read",
                "formatting_confidence": confidence,
                "confidence": confidence,
            }
        )

    payload["sections"] = normalized_sections

    return payload


def _build_extracted_text(payload: Dict[str, Any]) -> str:
    sections = payload.get("sections") or []
    chunks = []

    for section in sections:
        title = section.get("title") or section.get("key") or "Section"
        body = section.get("formatted_body") or section.get("body") or ""
        if body:
            chunks.append(f"{title}\n\n{body}")

    return "\n\n---\n\n".join(chunks).strip()


def process_discharge_with_openai(
    file_path: str,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    OpenAI-only discharge extraction.

    No Google Document AI.
    No OCR.
    No PyMuPDF.
    No Tesseract.

    Returns a normalized payload compatible with the existing Document.note_body flow.
    """

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to Render environment variables.")

    actual_filename = filename or Path(file_path).name
    mime_type = _guess_mime_type(file_path, actual_filename, content_type)
    data_url = _read_as_data_url(file_path, mime_type)

    if mime_type == "application/pdf":
        file_content = {
            "type": "input_file",
            "filename": actual_filename,
            "file_data": data_url,
        }
    elif mime_type.startswith("image/"):
        file_content = {
            "type": "input_image",
            "image_url": data_url,
        }
    else:
        raise ValueError(f"Unsupported discharge file type for OpenAI direct reading: {mime_type}")

    response = client.responses.create(
        model=DISCHARGE_MODEL,
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
                    file_content,
                    {
                        "type": "input_text",
                        "text": USER_PROMPT,
                    },
                ],
            },
        ],
        temperature=0,
        max_output_tokens=16000,
    )

    raw_text = getattr(response, "output_text", None)
    if not raw_text:
        raw_text = str(response)

    payload = _extract_json_from_text(raw_text)
    payload = _normalize_payload(payload)

    extracted_text = _build_extracted_text(payload)
    patient = payload.get("patient") or {}
    metadata = payload.get("document_metadata") or {}

    report_name = metadata.get("report_name") or "Fișă de externare"
    admission = metadata.get("admission_date")
    discharge = metadata.get("discharge_date")

    return {
        "document_type": "discharge_summary",
        "report_type": "Discharge summary",
        "report_name": report_name,
        "source_language": payload.get("language") or "ro",
        "patient_name": patient.get("name"),
        "cnp": patient.get("cnp"),
        "date_of_birth": patient.get("date_of_birth"),
        "age": patient.get("age"),
        "sex": patient.get("sex"),
        "lab_name": metadata.get("hospital"),
        "referring_doctor": metadata.get("attending_doctor"),
        "collected_on": admission,
        "reported_on": discharge,
        "generated_on": metadata.get("generated_at"),
        "extracted_text": extracted_text,
        "note_body": json.dumps(payload, ensure_ascii=False),
        "openai_model": DISCHARGE_MODEL,
    }


# Compatibility aliases in case older code imports these names.
def process_discharge_summary_with_openai(
    file_path: str,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    return process_discharge_with_openai(file_path, filename, content_type)


def process_discharge_summary_document(
    file_path: str,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    return process_discharge_with_openai(file_path, filename, content_type)