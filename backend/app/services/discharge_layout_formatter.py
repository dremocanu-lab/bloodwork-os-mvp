from __future__ import annotations

import json
import os
from typing import Any

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


MODEL_NAME = os.getenv("OPENAI_DISCHARGE_LAYOUT_MODEL", "gpt-4.1")


FORMATTER_SYSTEM_PROMPT = """
You are formatting OCR text from a Romanian hospital discharge summary.

Your job:
- Preserve the original medical content.
- Restore readable line breaks, indentation, bullets, and table-like spacing.
- Do NOT summarize.
- Do NOT translate.
- Do NOT add facts.
- Do NOT remove medical values.
- Do NOT change dates, lab values, diagnoses, medication names, doctor names, or hospital names.
- Only correct obvious OCR spacing/line-break damage.
- If uncertain, keep the raw OCR text.

Return strict JSON only.
"""


FORMATTER_JSON_SCHEMA = {
    "name": "discharge_layout_format",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "formatted_body": {
                "type": "string",
                "description": "The section text reformatted to look like the original document layout as closely as possible.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence from 0 to 1 that the formatted_body preserves the original text and layout.",
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Formatting warnings. Empty if no warnings.",
            },
        },
        "required": ["formatted_body", "confidence", "warnings"],
        "additionalProperties": False,
    },
}


def _client_available() -> bool:
    return OpenAI is not None and bool(os.getenv("OPENAI_API_KEY"))


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)

    if isinstance(output_text, str) and output_text.strip():
        return output_text

    try:
        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    except Exception:
        return ""


def format_discharge_section_with_ai(
    *,
    section_key: str,
    section_title: str,
    raw_body: str,
    original_titles: list[str] | None = None,
) -> dict[str, Any]:
    """
    Optional AI formatting layer for discharge summary sections.

    It returns:
      {
        "ok": bool,
        "formatted_body": str,
        "confidence": float,
        "warnings": list[str],
      }

    If unavailable or failed, it safely returns ok=False and keeps the raw body.
    """

    raw_body = str(raw_body or "").strip()

    if not raw_body:
        return {
            "ok": False,
            "formatted_body": "",
            "confidence": 0.0,
            "warnings": ["Empty section body; AI formatter skipped."],
        }

    if not _client_available():
        return {
            "ok": False,
            "formatted_body": raw_body,
            "confidence": 0.0,
            "warnings": ["OpenAI discharge layout formatter skipped because OPENAI_API_KEY is not configured."],
        }

    # Avoid wasting money on tiny sections.
    if len(raw_body) < 80:
        return {
            "ok": False,
            "formatted_body": raw_body,
            "confidence": 0.0,
            "warnings": ["Section too short for AI layout formatting; raw text kept."],
        }

    # Avoid oversized requests for now. We can later chunk by page.
    max_chars = int(os.getenv("OPENAI_DISCHARGE_LAYOUT_MAX_CHARS", "14000"))
    body_for_model = raw_body[:max_chars]
    truncated = len(raw_body) > max_chars

    client = OpenAI()

    user_payload = {
        "section_key": section_key,
        "section_title": section_title,
        "original_titles": original_titles or [],
        "raw_ocr_text": body_for_model,
        "instructions": [
            "Format this OCR text to visually resemble the original discharge document section.",
            "Preserve line breaks, indentation, bullets, date lines, lab lines, diagnosis lists, and medication lists.",
            "Do not summarize or rewrite clinically.",
            "Do not add or remove medical content.",
            "Keep Romanian text as Romanian.",
            "Return only the JSON object requested by the schema.",
        ],
    }

    try:
        response = client.responses.create(
            model=MODEL_NAME,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": FORMATTER_SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": FORMATTER_JSON_SCHEMA["name"],
                    "strict": True,
                    "schema": FORMATTER_JSON_SCHEMA["schema"],
                }
            },
        )

        output_text = _extract_output_text(response)

        if not output_text:
            return {
                "ok": False,
                "formatted_body": raw_body,
                "confidence": 0.0,
                "warnings": ["OpenAI formatter returned empty output."],
            }

        parsed = json.loads(output_text)
        formatted_body = str(parsed.get("formatted_body") or "").strip()
        confidence = float(parsed.get("confidence") or 0.0)
        warnings = [str(item) for item in parsed.get("warnings", []) if str(item).strip()]

        if truncated:
            warnings.append("Section was truncated before AI formatting because it exceeded max character limit.")

        if not formatted_body:
            return {
                "ok": False,
                "formatted_body": raw_body,
                "confidence": 0.0,
                "warnings": ["OpenAI formatter returned no formatted_body."],
            }

        return {
            "ok": True,
            "formatted_body": formatted_body,
            "confidence": max(0.0, min(confidence, 1.0)),
            "warnings": warnings,
        }

    except Exception as exc:
        return {
            "ok": False,
            "formatted_body": raw_body,
            "confidence": 0.0,
            "warnings": [f"OpenAI discharge layout formatter failed: {exc}"],
        }


def format_discharge_sections_with_ai(sections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Adds formatted_body to each discharge section when AI formatting succeeds.
    Returns updated sections and warnings.
    """

    updated_sections: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Format the sections where layout matters most first.
    allowed_keys = {
        "administrative_information",
        "pre_epicriza_summary",
        "diagnoses",
        "discharge_status",
        "epicriza",
        "investigations",
        "laboratory_normal",
        "laboratory_abnormal",
        "treatment_in_hospital",
        "recommended_treatment",
        "recommendations",
    }

    for section in sections or []:
        copied = dict(section)
        key = str(copied.get("key") or "")
        raw_body = str(copied.get("body") or "")

        if key not in allowed_keys:
            updated_sections.append(copied)
            continue

        result = format_discharge_section_with_ai(
            section_key=key,
            section_title=str(copied.get("title") or key),
            raw_body=raw_body,
            original_titles=list(copied.get("original_titles") or []),
        )

        warnings.extend(result.get("warnings", []) or [])

        if result.get("ok") and result.get("formatted_body"):
            copied["formatted_body"] = result["formatted_body"]
            copied["formatting_method"] = "openai_layout"
            copied["formatting_confidence"] = result.get("confidence", 0.0)
        else:
            copied["formatted_body"] = raw_body
            copied["formatting_method"] = "raw_ocr"
            copied["formatting_confidence"] = 0.0

        updated_sections.append(copied)

    return updated_sections, warnings