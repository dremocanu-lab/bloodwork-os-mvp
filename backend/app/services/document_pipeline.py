from pathlib import Path

from app.parsers.bloodwork_parser import parse_bloodwork_text
from app.services.ocr_service import extract_text, score_ocr_quality


def process_uploaded_document(file_path: Path, filename: str, section: str, temp_dir: Path) -> dict:
    extraction = extract_text(file_path=file_path, filename=filename, temp_dir=temp_dir)

    extracted_text = extraction.get("text") or ""
    ocr_quality = score_ocr_quality(extracted_text)

    warnings: list[str] = []
    warnings.extend(extraction.get("warnings", []))
    warnings.extend(ocr_quality.get("warnings", []))

    if section == "bloodwork":
        parsed_data = parse_bloodwork_text(extracted_text)
    else:
        parsed_data = {
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

    warnings.extend(parsed_data.get("warnings", []))

    return {
        "extracted_text": extracted_text,
        "parsed_data": parsed_data,
        "ocr_method": extraction.get("method"),
        "ocr_quality": ocr_quality,
        "warnings": warnings,
    }