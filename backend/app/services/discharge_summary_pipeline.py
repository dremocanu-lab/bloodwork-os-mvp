from __future__ import annotations

from pathlib import Path
from typing import Any

from app.parsers.discharge_summary_parser import parse_discharge_summary
from app.services.google_document_ai_service import (
    is_google_document_ai_configured,
    process_with_google_document_ai,
)
from app.services.ocr_service import extract_text, score_ocr_quality


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


def get_clean_discharge_text(extraction: dict[str, Any]) -> str:
    parts: list[str] = []

    for key in ["plain_text", "lines_text", "table_text", "tokens_text", "text"]:
        value = extraction.get(key)

        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    seen: set[str] = set()
    unique_parts: list[str] = []

    for part in parts:
        compact = " ".join(part.split())

        if not compact or compact in seen:
            continue

        seen.add(compact)
        unique_parts.append(part)

    return "\n\n".join(unique_parts).strip()


def process_uploaded_discharge_summary(
    file_path: Path,
    filename: str,
    temp_dir: Path,
) -> dict[str, Any]:
    warnings: list[str] = []

    if is_google_document_ai_configured():
        try:
            extraction = process_with_google_document_ai(file_path=file_path, filename=filename)
            warnings.append("Dedicated discharge summary pipeline used Google Document AI.")
        except Exception as error:
            warnings.append(f"Google Document AI failed for discharge summary, falling back to OCR: {error}")
            extraction = extract_text(file_path=file_path, filename=filename, temp_dir=temp_dir)
    else:
        warnings.append("Google Document AI is not configured, using OCR fallback for discharge summary.")
        extraction = extract_text(file_path=file_path, filename=filename, temp_dir=temp_dir)

    extracted_text = get_clean_discharge_text(extraction)

    if not extracted_text.strip():
        extracted_text = extraction.get("text") or ""

    ocr_quality = score_ocr_quality(extracted_text)

    warnings.extend(extraction.get("warnings", []) or [])
    warnings.extend(ocr_quality.get("warnings", []) or [])

    parsed_data = parse_discharge_summary(extraction if extracted_text else extracted_text)

    parsed_data["report_type"] = "Discharge summary"
    parsed_data["sample_type"] = None
    parsed_data["labs"] = []

    warnings.extend(parsed_data.get("warnings", []) or [])

    if not extracted_text.strip():
        warnings.append("No OCR text was extracted from this discharge summary.")

    note_body = parsed_data.get("note_body") or ""
    if '"sections": []' in note_body:
        warnings.append("No discharge sections were created from the extracted text.")

    return {
        "extracted_text": extracted_text,
        "parsed_data": parsed_data,
        "ocr_method": extraction.get("method") or "google_document_ai_discharge_summary",
        "ocr_quality": ocr_quality,
        "warnings": dedupe_warnings(warnings),
    }