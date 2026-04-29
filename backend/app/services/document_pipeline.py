from __future__ import annotations

from pathlib import Path
from typing import Any

from app.parsers.bloodwork_parser import parse_bloodwork_text
from app.parsers.ocr_table_parser import parse_labs_from_ocr_words
from app.services.lab_catalog import build_report_name_from_categories, normalize_lab_rows
from app.services.ocr_service import extract_text, score_ocr_quality


def empty_parsed_document(section: str) -> dict[str, Any]:
    clean_section = section or "document"

    return {
        "patient_name": None,
        "date_of_birth": None,
        "age": None,
        "sex": None,
        "cnp": None,
        "patient_identifier": None,
        "lab_name": None,
        "sample_type": None,
        "referring_doctor": None,
        "report_name": clean_section.replace("_", " ").title(),
        "report_type": clean_section,
        "source_language": None,
        "test_date": None,
        "collected_on": None,
        "reported_on": None,
        "registered_on": None,
        "generated_on": None,
        "labs": [],
        "warnings": [],
    }


def get_lab_identity(lab: dict[str, Any]) -> str:
    value = (
        lab.get("canonical_name")
        or lab.get("display_name")
        or lab.get("raw_test_name")
        or lab.get("raw_name")
        or lab.get("test_name")
        or lab.get("name")
        or ""
    )

    return str(value).strip().lower()


def lab_quality_score(lab: dict[str, Any]) -> float:
    score = float(lab.get("confidence") or 0)

    if lab.get("value"):
        score += 0.35
    if lab.get("reference_range"):
        score += 0.20
    if lab.get("unit"):
        score += 0.10
    if lab.get("flag") and str(lab.get("flag")).lower() != "normal":
        score += 0.05
    if lab.get("category") and lab.get("category") != "Alte analize":
        score += 0.05
    if lab.get("canonical_name"):
        score += 0.05

    return score


def standardize_lab_row_shape(lab: dict[str, Any]) -> dict[str, Any]:
    raw_name = (
        lab.get("raw_test_name")
        or lab.get("raw_name")
        or lab.get("test_name")
        or lab.get("name")
        or lab.get("display_name")
        or lab.get("canonical_name")
        or ""
    )

    canonical_name = lab.get("canonical_name") or lab.get("test_name") or lab.get("display_name") or raw_name
    display_name = lab.get("display_name") or canonical_name or raw_name

    return {
        "raw_test_name": str(raw_name).strip() if raw_name is not None else None,
        "canonical_name": str(canonical_name).strip() if canonical_name is not None else None,
        "display_name": str(display_name).strip() if display_name is not None else None,
        "category": lab.get("category") or "Alte analize",
        "value": lab.get("value"),
        "flag": lab.get("flag") or "Normal",
        "reference_range": lab.get("reference_range"),
        "unit": lab.get("unit"),
        "confidence": lab.get("confidence"),
    }


def merge_lab_results(*lab_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []

    for lab_list in lab_lists:
        for lab in lab_list or []:
            key = get_lab_identity(lab)

            if not key:
                continue

            existing_index = None

            for index, existing in enumerate(merged):
                if get_lab_identity(existing) == key:
                    existing_index = index
                    break

            if existing_index is None:
                merged.append(lab)
                continue

            existing = merged[existing_index]

            if lab_quality_score(lab) >= lab_quality_score(existing):
                merged[existing_index] = lab

    return [standardize_lab_row_shape(row) for row in merged]


def dedupe_warnings(warnings: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    for warning in warnings:
        clean_warning = str(warning).strip()

        if not clean_warning:
            continue

        if clean_warning in seen:
            continue

        deduped.append(clean_warning)
        seen.add(clean_warning)

    return deduped


def build_category_report_name(parsed_data: dict[str, Any], labs: list[dict[str, Any]]) -> str:
    return build_report_name_from_categories(
        labs,
        collected_on=parsed_data.get("collected_on"),
        test_date=parsed_data.get("test_date"),
        reported_on=parsed_data.get("reported_on"),
        registered_on=parsed_data.get("registered_on"),
        generated_on=parsed_data.get("generated_on"),
        created_at=parsed_data.get("created_at"),
        fallback_name="Analize medicale",
    )


def process_uploaded_document(file_path: Path, filename: str, section: str, temp_dir: Path) -> dict[str, Any]:
    extraction = extract_text(file_path=file_path, filename=filename, temp_dir=temp_dir)

    extracted_text = extraction.get("text") or ""
    ocr_words = extraction.get("words") or []
    ocr_quality = score_ocr_quality(extracted_text)

    warnings: list[str] = []
    warnings.extend(extraction.get("warnings", []) or [])
    warnings.extend(ocr_quality.get("warnings", []) or [])

    if section == "bloodwork":
        parsed_data = parse_bloodwork_text(extracted_text)

        text_labs = parsed_data.get("labs", []) or []
        table_labs = parse_labs_from_ocr_words(ocr_words) or []

        if table_labs:
            warnings.append(f"Coordinate OCR table parser extracted {len(table_labs)} candidate lab rows.")

        normalized_table_labs = normalize_lab_rows(table_labs, context_text=extracted_text)
        normalized_text_labs = normalize_lab_rows(text_labs, context_text=extracted_text)

        merged_labs = merge_lab_results(normalized_table_labs, normalized_text_labs)
        merged_labs = normalize_lab_rows(merged_labs, context_text=extracted_text)

        parsed_data["labs"] = merged_labs
        parsed_data["report_type"] = "Bloodwork"

        parsed_data["report_name"] = build_category_report_name(parsed_data, merged_labs)

        if len(merged_labs) < 10:
            warnings.append("Fewer than 10 structured lab rows were extracted. Manual review is recommended.")

    else:
        parsed_data = empty_parsed_document(section)

    warnings.extend(parsed_data.get("warnings", []) or [])

    return {
        "extracted_text": extracted_text,
        "parsed_data": parsed_data,
        "ocr_method": extraction.get("method"),
        "ocr_quality": ocr_quality,
        "warnings": dedupe_warnings(warnings),
    }