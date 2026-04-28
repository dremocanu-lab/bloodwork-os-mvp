from pathlib import Path

from app.parsers.bloodwork_parser import parse_bloodwork_text
from app.parsers.ocr_table_parser import parse_labs_from_ocr_words
from app.services.ocr_service import extract_text, score_ocr_quality


def merge_lab_results(*lab_lists: list[dict]) -> list[dict]:
    merged: list[dict] = []

    for lab_list in lab_lists:
        for lab in lab_list or []:
            key = lab.get("canonical_name") or lab.get("display_name") or lab.get("raw_test_name")

            if not key:
                continue

            key = str(key).lower()

            existing_index = None
            for index, existing in enumerate(merged):
                existing_key = (
                    existing.get("canonical_name")
                    or existing.get("display_name")
                    or existing.get("raw_test_name")
                )

                if existing_key and str(existing_key).lower() == key:
                    existing_index = index
                    break

            if existing_index is None:
                merged.append(lab)
                continue

            existing = merged[existing_index]

            existing_score = float(existing.get("confidence") or 0)
            new_score = float(lab.get("confidence") or 0)

            if existing.get("reference_range"):
                existing_score += 0.12
            if existing.get("unit"):
                existing_score += 0.06
            if existing.get("flag") and existing.get("flag") != "Normal":
                existing_score += 0.03

            if lab.get("reference_range"):
                new_score += 0.12
            if lab.get("unit"):
                new_score += 0.06
            if lab.get("flag") and lab.get("flag") != "Normal":
                new_score += 0.03

            # Prefer coordinate OCR when it is better, because it preserves table rows.
            if new_score >= existing_score:
                merged[existing_index] = lab

    return merged


def empty_parsed_document(section: str) -> dict:
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
        "report_name": section.title(),
        "report_type": section,
        "source_language": None,
        "test_date": None,
        "collected_on": None,
        "reported_on": None,
        "registered_on": None,
        "generated_on": None,
        "labs": [],
        "warnings": [],
    }


def process_uploaded_document(file_path: Path, filename: str, section: str, temp_dir: Path) -> dict:
    extraction = extract_text(file_path=file_path, filename=filename, temp_dir=temp_dir)

    extracted_text = extraction.get("text") or ""
    ocr_words = extraction.get("words") or []

    ocr_quality = score_ocr_quality(extracted_text)

    warnings: list[str] = []
    warnings.extend(extraction.get("warnings", []))
    warnings.extend(ocr_quality.get("warnings", []))

    if section == "bloodwork":
        parsed_data = parse_bloodwork_text(extracted_text)

        text_labs = parsed_data.get("labs", []) or []
        table_labs = parse_labs_from_ocr_words(ocr_words)

        merged_labs = merge_lab_results(table_labs, text_labs)
        parsed_data["labs"] = merged_labs

        if table_labs:
            warnings.append(f"Coordinate OCR table parser extracted {len(table_labs)} candidate lab rows.")

        if len(merged_labs) < 10:
            warnings.append("Fewer than 10 structured lab rows were extracted. Manual review is recommended.")

    else:
        parsed_data = empty_parsed_document(section)

    warnings.extend(parsed_data.get("warnings", []))

    # Remove duplicate warning strings while preserving order.
    deduped_warnings = []
    seen_warnings = set()

    for warning in warnings:
        if warning not in seen_warnings:
            deduped_warnings.append(warning)
            seen_warnings.add(warning)

    return {
        "extracted_text": extracted_text,
        "parsed_data": parsed_data,
        "ocr_method": extraction.get("method"),
        "ocr_quality": ocr_quality,
        "warnings": deduped_warnings,
    }