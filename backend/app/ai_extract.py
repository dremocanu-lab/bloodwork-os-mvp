import json
import os
from typing import Any

from openai import OpenAI

from app.synonyms import normalize_test_name


AI_EXTRACTION_MODEL = os.getenv("AI_EXTRACTION_MODEL", "gpt-4.1-mini")


REPORT_SCHEMA = {
    "name": "medical_lab_report",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "patient_name": {"type": ["string", "null"]},
            "date_of_birth": {"type": ["string", "null"]},
            "age": {"type": ["string", "null"]},
            "sex": {"type": ["string", "null"]},
            "cnp": {"type": ["string", "null"]},
            "patient_identifier": {"type": ["string", "null"]},
            "lab_name": {"type": ["string", "null"]},
            "sample_type": {"type": ["string", "null"]},
            "referring_doctor": {"type": ["string", "null"]},
            "report_name": {"type": ["string", "null"]},
            "report_type": {"type": ["string", "null"]},
            "source_language": {"type": ["string", "null"]},
            "test_date": {"type": ["string", "null"]},
            "collected_on": {"type": ["string", "null"]},
            "reported_on": {"type": ["string", "null"]},
            "registered_on": {"type": ["string", "null"]},
            "generated_on": {"type": ["string", "null"]},
            "labs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "raw_test_name": {"type": ["string", "null"]},
                        "canonical_name": {"type": ["string", "null"]},
                        "display_name": {"type": ["string", "null"]},
                        "category": {"type": ["string", "null"]},
                        "value": {"type": ["string", "null"]},
                        "flag": {"type": ["string", "null"]},
                        "reference_range": {"type": ["string", "null"]},
                        "unit": {"type": ["string", "null"]},
                    },
                    "required": [
                        "raw_test_name",
                        "canonical_name",
                        "display_name",
                        "category",
                        "value",
                        "flag",
                        "reference_range",
                        "unit",
                    ],
                },
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
            "sample_type",
            "referring_doctor",
            "report_name",
            "report_type",
            "source_language",
            "test_date",
            "collected_on",
            "reported_on",
            "registered_on",
            "generated_on",
            "labs",
        ],
    },
}


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"none", "null", "n/a", "na", "-", "—"}:
        return None

    return cleaned


def _normalize_flag(flag: str | None) -> str | None:
    cleaned = _clean_string(flag)
    if not cleaned:
        return None

    lower = cleaned.lower()

    if lower in {"h", "high", "mare", "crescut", "increased", "above range"}:
        return "High"

    if lower in {"l", "low", "mic", "scazut", "scăzut", "decreased", "below range"}:
        return "Low"

    if lower in {"critical", "panic"}:
        return "Critical"

    if lower in {"borderline", "borderline high", "borderline low"}:
        return "Borderline"

    if lower in {"normal", "n", "within range", "in range"}:
        return "Normal"

    return cleaned


def _normalize_lab_item(item: dict[str, Any]) -> dict[str, str | None]:
    raw_name = _clean_string(item.get("raw_test_name") or item.get("display_name"))

    normalized = normalize_test_name(raw_name or "")

    display_name = (
        normalized.get("display_name")
        or _clean_string(item.get("display_name"))
        or raw_name
    )

    canonical_name = normalized.get("canonical_name") or _clean_string(item.get("canonical_name"))
    category = normalized.get("category") or _clean_string(item.get("category"))

    return {
        "raw_test_name": raw_name,
        "canonical_name": canonical_name,
        "display_name": display_name,
        "category": category,
        "value": _clean_string(item.get("value")),
        "flag": _normalize_flag(item.get("flag")),
        "reference_range": _clean_string(item.get("reference_range")),
        "unit": _clean_string(item.get("unit")),
    }


def validate_ai_report(data: dict[str, Any]) -> dict[str, Any]:
    labs = data.get("labs")
    if not isinstance(labs, list):
        labs = []

    clean_labs = []
    seen = set()

    for item in labs:
        if not isinstance(item, dict):
            continue

        lab = _normalize_lab_item(item)

        if not lab["raw_test_name"] or not lab["value"]:
            continue

        dedupe_key = (
            lab["canonical_name"]
            or lab["display_name"]
            or lab["raw_test_name"]
            or ""
        ).strip().lower()

        if not dedupe_key or dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        clean_labs.append(lab)

    return {
        "patient_name": _clean_string(data.get("patient_name")),
        "date_of_birth": _clean_string(data.get("date_of_birth")),
        "age": _clean_string(data.get("age")),
        "sex": _clean_string(data.get("sex")),
        "cnp": _clean_string(data.get("cnp")),
        "patient_identifier": _clean_string(data.get("patient_identifier")),
        "lab_name": _clean_string(data.get("lab_name")),
        "sample_type": _clean_string(data.get("sample_type")),
        "referring_doctor": _clean_string(data.get("referring_doctor")),
        "report_name": _clean_string(data.get("report_name")),
        "report_type": _clean_string(data.get("report_type")),
        "source_language": _clean_string(data.get("source_language")),
        "test_date": _clean_string(data.get("test_date")),
        "collected_on": _clean_string(data.get("collected_on")),
        "reported_on": _clean_string(data.get("reported_on")),
        "registered_on": _clean_string(data.get("registered_on")),
        "generated_on": _clean_string(data.get("generated_on")),
        "labs": clean_labs,
    }


def extract_report_with_ai(extracted_text: str) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    text = (extracted_text or "").strip()
    if len(text) < 40:
        return None

    text = text[:24000]

    client = OpenAI(api_key=api_key)

    system_prompt = """
You extract structured data from medical laboratory reports.

Return only fields that are visible or strongly implied in the text.
Do not invent patient data, dates, values, units, or reference ranges.
Preserve the original value strings and units.
For labs, extract each individual analyte/test row.
Use English display names when possible.
Set source_language to "ro", "en", or "mixed".
Flag should be High, Low, Normal, Critical, Borderline, or null.
If a value has H/L markers or is outside the reference range, infer the flag.
If a field is not present, use null.
""".strip()

    user_prompt = f"""
Extract structured data from this OCR/PDF text.

TEXT:
{text}
""".strip()

    try:
        response = client.responses.create(
            model=AI_EXTRACTION_MODEL,
            input=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": REPORT_SCHEMA,
            },
            temperature=0,
        )

        raw_json = response.output_text
        data = json.loads(raw_json)

        if not isinstance(data, dict):
            return None

        return validate_ai_report(data)

    except Exception:
        return None