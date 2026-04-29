from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


def env_value(name: str) -> str | None:
    value = os.getenv(name)

    if value is None:
        return None

    value = value.strip()

    return value or None


def is_openai_configured() -> bool:
    return bool(env_value("OPENAI_API_KEY"))


def safe_json_loads(value: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(value)

        if isinstance(loaded, dict):
            return loaded
    except Exception:
        return None

    return None


def compact_text_for_ai(text: str, max_chars: int = 24000) -> str:
    safe = text or ""

    # Prefer Google table/line sections if present.
    important_markers = [
        "--- GOOGLE DOCUMENT AI TABLE",
        "--- GOOGLE DOCUMENT AI LINES ---",
        "BULETIN ANALIZE MEDICALE",
        "Hemograma simpla",
        "Citomorfologie",
        "INTERVAL BIOLOGIC",
        "INTERVAL BIOLOGIC DE REFERINTA",
    ]

    chunks: list[str] = []

    for marker in important_markers:
        index = safe.lower().find(marker.lower())

        if index >= 0:
            chunks.append(safe[max(0, index - 800) : index + 9000])

    if chunks:
        combined = "\n\n".join(chunks)
    else:
        combined = safe

    combined = combined[:max_chars]

    return combined


def normalize_ai_lab_row(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("value")

    if value is not None:
        value = str(value).strip().replace(",", ".")

        if value.lower() in {"nil", "null", "none", "n/a", "na", "-", "--", "---", "—"}:
            value = None

    reference_range = row.get("reference_range")
    if reference_range is not None:
        reference_range = str(reference_range).replace("–", "-").replace("—", "-").strip() or None

    unit = row.get("unit")
    if unit is not None:
        unit = str(unit).strip() or None

    flag = row.get("flag")
    if flag is not None:
        flag_lower = str(flag).strip().lower()

        if flag_lower in {"high", "h", "crescut"}:
            flag = "High"
        elif flag_lower in {"low", "l", "scazut"}:
            flag = "Low"
        elif flag_lower == "normal":
            flag = "Normal"
        else:
            flag = None

    if value is None:
        flag = None

    if value is not None and not reference_range and flag == "Normal":
        flag = None

    return {
        "raw_test_name": row.get("raw_test_name") or row.get("test") or row.get("name"),
        "canonical_name": row.get("canonical_name") or row.get("test") or row.get("name"),
        "display_name": row.get("display_name") or row.get("test") or row.get("name"),
        "category": row.get("category") or "Hematologie",
        "value": value,
        "flag": flag,
        "reference_range": reference_range,
        "unit": unit,
        "confidence": float(row.get("confidence") or 0.82),
    }


def organize_labs_with_ai(extracted_text: str, deterministic_labs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    api_key = env_value("OPENAI_API_KEY")

    if not api_key:
        return {
            "ok": False,
            "warning": "OpenAI organizer skipped because OPENAI_API_KEY is not configured.",
            "metadata": {},
            "labs": [],
        }

    model = env_value("OPENAI_EXTRACTION_MODEL") or "gpt-4o-mini"

    deterministic_labs = deterministic_labs or []
    text = compact_text_for_ai(extracted_text)

    system_prompt = """
You are a medical lab report extraction engine.

Extract ONLY facts visible in the supplied OCR text.
Do not invent values.
Do not invent reference ranges.
Do not mark a result Normal unless a reference range is present and the value is inside it.
If a row has no numeric result, use null.
Preserve decimals exactly.
For Romanian Fundeni CBC reports, the clinical collection date is the line after:
"Data si ora recoltarii setului de analize".
Return JSON only.
"""

    user_prompt = {
        "task": "Extract structured lab report data from this OCR text.",
        "required_metadata": [
            "patient_name",
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
        ],
        "lab_row_schema": {
            "raw_test_name": "string",
            "canonical_name": "string",
            "display_name": "string",
            "category": "string",
            "value": "string|null",
            "unit": "string|null",
            "reference_range": "string|null",
            "flag": "High|Low|Normal|null",
            "confidence": "number 0-1",
        },
        "deterministic_labs_so_far": deterministic_labs,
        "ocr_text": text,
    }

    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
    }

    request = urllib.request.Request(
        OPENAI_CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "warning": f"OpenAI organizer HTTP error: {exc.code}. {body[:500]}",
            "metadata": {},
            "labs": [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "warning": f"OpenAI organizer failed: {exc}",
            "metadata": {},
            "labs": [],
        }

    outer = safe_json_loads(raw)

    if not outer:
        return {
            "ok": False,
            "warning": "OpenAI organizer returned non-JSON response.",
            "metadata": {},
            "labs": [],
        }

    try:
        content = outer["choices"][0]["message"]["content"]
    except Exception:
        return {
            "ok": False,
            "warning": "OpenAI organizer response did not include message content.",
            "metadata": {},
            "labs": [],
        }

    parsed = safe_json_loads(content)

    if not parsed:
        return {
            "ok": False,
            "warning": "OpenAI organizer message content was not valid JSON.",
            "metadata": {},
            "labs": [],
        }

    metadata = parsed.get("metadata") or parsed.get("report_metadata") or {}
    labs = parsed.get("labs") or parsed.get("lab_results") or []

    if not isinstance(metadata, dict):
        metadata = {}

    if not isinstance(labs, list):
        labs = []

    normalized_labs = []

    for row in labs:
        if isinstance(row, dict):
            normalized_labs.append(normalize_ai_lab_row(row))

    return {
        "ok": True,
        "metadata": metadata,
        "labs": normalized_labs,
    }