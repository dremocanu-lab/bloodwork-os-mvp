from __future__ import annotations

from pathlib import Path

from app.services.google_document_ai_service import (
    get_document_ai_debug_config,
    is_google_document_ai_configured,
    process_with_google_document_ai,
)


def ocr_failed_response(method: str, warnings: list[str]) -> dict:
    return {
        "text": "",
        "plain_text": "",
        "lines_text": "",
        "table_text": "",
        "tables": [],
        "lines": [],
        "words": [],
        "method": method,
        "warnings": [
            *warnings,
            "No OCR text could be extracted. Manual review is required.",
        ],
    }


def extract_text(file_path: Path, filename: str, temp_dir: Path | None = None) -> dict:
    if not is_google_document_ai_configured():
        return ocr_failed_response(
            method="google_document_ai_not_configured",
            warnings=[
                "Google Document AI is required, but environment variables are missing.",
                f"Current config: {get_document_ai_debug_config()}",
            ],
        )

    try:
        return process_with_google_document_ai(file_path=file_path, filename=filename)
    except Exception as error:
        return ocr_failed_response(
            method="google_document_ai_failed",
            warnings=[
                f"Google Document AI failed. Error: {str(error)}",
                f"Current config: {get_document_ai_debug_config()}",
            ],
        )


def score_ocr_quality(text: str) -> dict:
    cleaned = (text or "").strip()

    if not cleaned:
        return {
            "score": 0.0,
            "level": "empty",
            "warnings": ["No text could be extracted from this document."],
        }

    letters = sum(ch.isalpha() for ch in cleaned)
    digits = sum(ch.isdigit() for ch in cleaned)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    lab_keywords = [
        "hemoglobin",
        "hemoglobina",
        "hemoglobină",
        "leucocyte",
        "leukocyte",
        "leucocite",
        "eritrocite",
        "creatinina",
        "creatinine",
        "glucoza",
        "glucose",
        "colesterol",
        "cholesterol",
        "trigliceride",
        "triglycerides",
        "tsh",
        "alt",
        "ast",
        "wbc",
        "rbc",
        "hgb",
        "hct",
        "plt",
        "mcv",
        "mch",
        "mchc",
        "neut",
        "lymph",
        "mono",
    ]

    lowered = cleaned.lower()
    keyword_hits = sum(1 for keyword in lab_keywords if keyword in lowered)

    score = 0.0

    if len(cleaned) >= 200:
        score += 0.25
    elif len(cleaned) >= 80:
        score += 0.15

    if letters >= 80:
        score += 0.2

    if digits >= 10:
        score += 0.2

    if len(lines) >= 5:
        score += 0.15

    if keyword_hits >= 3:
        score += 0.2
    elif keyword_hits >= 1:
        score += 0.1

    score = min(round(score, 2), 1.0)

    warnings = []

    if score < 0.4:
        warnings.append("Google Document AI text quality appears low. Manual review is recommended.")
    elif score < 0.7:
        warnings.append("Google Document AI text quality is moderate. Some fields may need review.")

    level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"

    return {
        "score": score,
        "level": level,
        "warnings": warnings,
    }