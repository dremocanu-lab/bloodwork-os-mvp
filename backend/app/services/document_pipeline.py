from __future__ import annotations

from pathlib import Path
from typing import Any

from app.parsers.bloodwork_parser import parse_bloodwork_text
from app.parsers.ocr_table_parser import parse_labs_from_ocr_words
from app.services.lab_catalog import build_report_name_from_categories, normalize_lab_rows
from app.services.ocr_service import extract_text, score_ocr_quality

try:
    from app.services.ai_lab_organizer import organize_labs_with_ai
except Exception:
    organize_labs_with_ai = None


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


def clean_string(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).replace("\u00a0", " ").strip()
    cleaned = " ".join(cleaned.split())

    return cleaned or None


def normalize_value(value: Any) -> str | None:
    cleaned = clean_string(value)

    if not cleaned:
        return None

    lowered = cleaned.lower()
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")

    if lowered in {"nil", "null", "none", "n/a", "na", "-", "--", "---", "----", "—", "–"}:
        return None

    # Keep decimals exactly as OCR found them. Do not round.
    cleaned = cleaned.replace(",", ".")

    return cleaned


def normalize_flag(value: Any) -> str | None:
    cleaned = clean_string(value)

    if not cleaned:
        return None

    lowered = cleaned.lower()

    if lowered in {"high", "h", "crescut", "mare"}:
        return "High"

    if lowered in {"low", "l", "scazut", "mic"}:
        return "Low"

    if lowered in {"normal", "n"}:
        return "Normal"

    return None


def numeric_float(value: Any) -> float | None:
    cleaned = normalize_value(value)

    if not cleaned:
        return None

    try:
        return float(cleaned)
    except Exception:
        return None


def infer_flag(value: Any, reference_range: Any) -> str | None:
    numeric = numeric_float(value)

    if numeric is None:
        return None

    reference = clean_string(reference_range)

    if not reference:
        # Safety rule: no range means no automatic normal/high/low.
        return None

    import re

    nums = re.findall(r"[-+]?\d+(?:[.,]\d+)?", reference)

    if len(nums) < 2:
        return None

    low = numeric_float(nums[0])
    high = numeric_float(nums[1])

    if low is None or high is None:
        return None

    if high < low:
        low, high = high, low

    if numeric < low:
        return "Low"

    if numeric > high:
        return "High"

    return "Normal"


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

    value = normalize_value(lab.get("value"))
    reference_range = clean_string(lab.get("reference_range"))
    unit = clean_string(lab.get("unit"))

    flag = normalize_flag(lab.get("flag"))

    if value is not None and flag is None:
        flag = infer_flag(value, reference_range)

    if value is None:
        flag = None

    # Safety rule: never say Normal if no reference range exists.
    if value is not None and not reference_range and flag == "Normal":
        flag = None

    confidence = lab.get("confidence")

    try:
        confidence = float(confidence) if confidence is not None else None
    except Exception:
        confidence = None

    return {
        "raw_test_name": clean_string(raw_name),
        "canonical_name": clean_string(canonical_name),
        "display_name": clean_string(display_name),
        "category": clean_string(lab.get("category")) or "Alte analize",
        "value": value,
        "flag": flag,
        "reference_range": reference_range,
        "unit": unit,
        "confidence": confidence,
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
    row = standardize_lab_row_shape(lab)

    score = float(row.get("confidence") or 0)

    if row.get("value") is not None:
        score += 0.40

    if row.get("reference_range"):
        score += 0.35

    if row.get("unit"):
        score += 0.15

    if row.get("flag") in {"High", "Low"}:
        score += 0.10

    if row.get("canonical_name"):
        score += 0.05

    return score


def merge_lab_results(*lab_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []

    for lab_list in lab_lists:
        for lab in lab_list or []:
            row = standardize_lab_row_shape(lab)
            key = get_lab_identity(row)

            if not key:
                continue

            existing_index = None

            for index, existing in enumerate(merged):
                if get_lab_identity(existing) == key:
                    existing_index = index
                    break

            if existing_index is None:
                merged.append(row)
                continue

            existing = merged[existing_index]

            if lab_quality_score(row) >= lab_quality_score(existing):
                merged[existing_index] = row

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
        created_at=None,
        fallback_name=parsed_data.get("report_name") or "Analize medicale",
    )


def lab_rows_need_ai_help(labs: list[dict[str, Any]], parsed_data: dict[str, Any]) -> bool:
    if not labs:
        return True

    if not parsed_data.get("collected_on") and not parsed_data.get("test_date"):
        return True

    rows_with_values = [row for row in labs if row.get("value") is not None]

    if not rows_with_values:
        return True

    rows_with_refs = [row for row in rows_with_values if row.get("reference_range")]

    # If most values have no reference ranges, ask AI organizer for help.
    if len(rows_with_refs) < max(3, int(len(rows_with_values) * 0.55)):
        return True

    return False


def merge_metadata(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)

    for key in [
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
    ]:
        if not merged.get(key) and fallback.get(key):
            merged[key] = fallback.get(key)

    return merged


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
            warnings.append(f"Coordinate OCR parser extracted {len(table_labs)} candidate lab rows.")

        normalized_table_labs = normalize_lab_rows(table_labs, context_text=extracted_text)
        normalized_text_labs = normalize_lab_rows(text_labs, context_text=extracted_text)

        merged_labs = merge_lab_results(normalized_table_labs, normalized_text_labs)
        merged_labs = normalize_lab_rows(merged_labs, context_text=extracted_text)
        merged_labs = [standardize_lab_row_shape(row) for row in merged_labs]

        if lab_rows_need_ai_help(merged_labs, parsed_data) and organize_labs_with_ai is not None:
            ai_result = organize_labs_with_ai(extracted_text=extracted_text, deterministic_labs=merged_labs)

            if ai_result.get("ok"):
                warnings.append("OpenAI organizer fallback improved or validated structured extraction.")

                ai_metadata = ai_result.get("metadata") or {}
                ai_labs = ai_result.get("labs") or []

                parsed_data = merge_metadata(parsed_data, ai_metadata)

                normalized_ai_labs = normalize_lab_rows(ai_labs, context_text=extracted_text)
                merged_labs = merge_lab_results(merged_labs, normalized_ai_labs)
                merged_labs = normalize_lab_rows(merged_labs, context_text=extracted_text)
                merged_labs = [standardize_lab_row_shape(row) for row in merged_labs]
            else:
                if ai_result.get("warning"):
                    warnings.append(str(ai_result["warning"]))

        parsed_data["labs"] = merged_labs
        parsed_data["report_type"] = "Bloodwork"
        parsed_data["report_name"] = build_category_report_name(parsed_data, merged_labs)

        if not parsed_data.get("collected_on") and not parsed_data.get("test_date"):
            warnings.append("No clinical collection/test date was extracted. Timeline will show this as undated.")

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