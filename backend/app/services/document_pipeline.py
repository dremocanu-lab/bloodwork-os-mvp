from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.parsers.google_table_parser import parse_labs_from_google_extraction
from app.report_fields import extract_report_metadata
from app.services.lab_catalog import build_report_name_from_categories, normalize_lab_rows
from app.services.ocr_service import extract_text, score_ocr_quality

try:
    from app.services.ai_lab_organizer import organize_labs_with_ai
except Exception:
    organize_labs_with_ai = None


NULL_VALUE_TOKENS = {
    "",
    "-",
    "--",
    "---",
    "----",
    "—",
    "–",
    "nil",
    "null",
    "none",
    "n/a",
    "na",
    "absent",
}

CBC_EXACT_LABELS = {
    "WBC": "White Blood Cell Count",
    "RBC": "Red Blood Cell Count",
    "HGB": "Hemoglobin",
    "HCT": "Hematocrit",
    "MCV": "Mean Corpuscular Volume",
    "MCH": "Mean Corpuscular Hemoglobin",
    "MCHC": "Mean Corpuscular Hemoglobin Concentration",
    "PLT": "Platelet Count",
    "RDW-SD": "Red Cell Distribution Width - SD",
    "RDW-CV": "Red Cell Distribution Width - CV",
    "PDW": "Platelet Distribution Width",
    "MPV": "Mean Platelet Volume",
    "P-LCR": "P-LCR",
    "PCT": "Plateletcrit",
    "NRBC#": "Nucleated Red Blood Cells Absolute",
    "NRBC%": "NRBC Percent",
    "NEUT#": "Neutrophils Absolute",
    "NEUT%": "Neutrophils Percent",
    "LYMPH#": "Lymphocytes Absolute",
    "LYMPH%": "Lymphocytes Percent",
    "MONO#": "Monocytes Absolute",
    "MONO%": "Monocytes Percent",
    "EO#": "Eosinophils Absolute",
    "EO%": "Eosinophils Percent",
    "BASO#": "Basophils Absolute",
    "BASO%": "Basophils Percent",
    "IG#": "Immature Granulocytes Absolute",
    "IG%": "Immature Granulocytes Percent",
}

CBC_ORDER = [
    "WBC",
    "RBC",
    "HGB",
    "HCT",
    "MCV",
    "MCH",
    "MCHC",
    "PLT",
    "RDW-SD",
    "RDW-CV",
    "PDW",
    "MPV",
    "P-LCR",
    "PCT",
    "NRBC#",
    "NRBC%",
    "NEUT#",
    "NEUT%",
    "LYMPH#",
    "LYMPH%",
    "MONO#",
    "MONO%",
    "EO#",
    "EO%",
    "BASO#",
    "BASO%",
    "IG#",
    "IG%",
]


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

    cleaned = str(value)
    cleaned = cleaned.replace("\ufeff", "")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")
    cleaned = cleaned.replace("Â", "")
    cleaned = cleaned.replace("â€", "")
    cleaned = cleaned.replace("�", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n;:")

    return cleaned or None


def normalize_cbc_raw_key(value: Any) -> str | None:
    cleaned = clean_string(value)

    if cleaned is None:
        return None

    key = cleaned.upper()
    key = key.replace(" ", "")
    key = key.replace("_", "-")
    key = key.replace(".", "")
    key = key.replace("＃", "#").replace("％", "%")

    if key == "RDWSD":
        key = "RDW-SD"

    if key == "RDWCV":
        key = "RDW-CV"

    if key in {"PLCR", "P-LCR%"}:
        key = "P-LCR"

    if key in CBC_EXACT_LABELS:
        return key

    return None


def find_cbc_key_in_lab(lab: dict[str, Any]) -> str | None:
    for field in [
        "raw_test_name",
        "raw_name",
        "test_name",
        "name",
        "code",
        "abbreviation",
    ]:
        key = normalize_cbc_raw_key(lab.get(field))

        if key:
            return key

    return None


def normalize_value(value: Any) -> str | None:
    cleaned = clean_string(value)

    if cleaned is None:
        return None

    if cleaned.lower() in NULL_VALUE_TOKENS:
        return None

    cleaned = cleaned.replace(",", ".")
    cleaned = re.sub(r"[^0-9.+-]", "", cleaned)

    if cleaned.startswith("."):
        cleaned = "0" + cleaned

    if cleaned in NULL_VALUE_TOKENS or cleaned in {"+", "-", ".", "+.", "-."}:
        return None

    return cleaned


def numeric_float(value: Any) -> float | None:
    cleaned = normalize_value(value)

    if cleaned is None:
        return None

    try:
        return float(cleaned)
    except Exception:
        return None


def normalize_reference_range(value: Any) -> str | None:
    cleaned = clean_string(value)

    if cleaned is None:
        return None

    cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")

    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", cleaned)

    if len(nums) < 2:
        return None

    low_raw = nums[0]
    high_raw = nums[1]

    if high_raw.startswith("-") and not low_raw.startswith("-"):
        high_raw = high_raw[1:]

    low = normalize_value(low_raw)
    high = normalize_value(high_raw)

    if low is None or high is None:
        return None

    low_float = numeric_float(low)
    high_float = numeric_float(high)

    if low_float is None or high_float is None:
        return None

    if high_float < low_float:
        low, high = high, low

    return f"{low} - {high}"


def normalize_unit(value: Any) -> str | None:
    cleaned = clean_string(value)

    if cleaned is None:
        return None

    compact = cleaned.replace(" ", "")
    lowered = compact.lower()

    if re.search(r"10\^?3/?u?l", compact, re.IGNORECASE):
        return "10^3/uL"

    if re.search(r"10\^?6/?u?l", compact, re.IGNORECASE):
        return "10^6/uL"

    if re.search(r"10\^?9/?l", compact, re.IGNORECASE):
        return "10^9/L"

    if re.search(r"10\^?12/?l", compact, re.IGNORECASE):
        return "10^12/L"

    if lowered == "g/dl":
        return "g/dL"

    if lowered == "g/l":
        return "g/L"

    if lowered == "mg/dl":
        return "mg/dL"

    if lowered == "mg/l":
        return "mg/L"

    if lowered == "mmol/l":
        return "mmol/L"

    if lowered in {"umol/l", "µmol/l", "μmol/l"}:
        return "umol/L"

    if lowered in {"uiu/ml", "ui/ml"}:
        return "uIU/mL"

    if lowered == "miu/l":
        return "mIU/L"

    if lowered == "iu/l":
        return "IU/L"

    if lowered == "u/l":
        return "U/L"

    if lowered == "fl":
        return "fL"

    if lowered == "pg":
        return "pg"

    if compact == "%":
        return "%"

    return cleaned


def normalize_flag(value: Any) -> str | None:
    cleaned = clean_string(value)

    if cleaned is None:
        return None

    lowered = cleaned.lower()

    if lowered in {"high", "h", "crescut", "mare", "↑", "▲"}:
        return "High"

    if lowered in {"low", "l", "scazut", "scăzut", "mic", "↓", "▼"}:
        return "Low"

    if lowered in {"normal", "n"}:
        return "Normal"

    return None


def infer_flag(value: Any, reference_range: Any) -> str | None:
    numeric = numeric_float(value)

    if numeric is None:
        return None

    reference = normalize_reference_range(reference_range)

    if reference is None:
        return None

    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", reference)

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
    cbc_key = find_cbc_key_in_lab(lab)

    raw_name = (
        lab.get("raw_test_name")
        or lab.get("raw_name")
        or lab.get("test_name")
        or lab.get("name")
        or lab.get("display_name")
        or lab.get("canonical_name")
        or ""
    )

    value = normalize_value(lab.get("value"))
    reference_range = normalize_reference_range(lab.get("reference_range"))
    unit = normalize_unit(lab.get("unit"))
    flag = normalize_flag(lab.get("flag"))

    if value is not None and flag is None:
        flag = infer_flag(value, reference_range)

    if value is None:
        flag = None

    if value is not None and not reference_range and flag == "Normal":
        flag = None

    confidence = lab.get("confidence")

    try:
        confidence = float(confidence) if confidence is not None else None
    except Exception:
        confidence = None

    if cbc_key:
        display_name = CBC_EXACT_LABELS[cbc_key]

        return {
            "raw_test_name": cbc_key,
            "canonical_name": display_name,
            "display_name": display_name,
            "category": "Hematologie",
            "value": value,
            "flag": flag,
            "reference_range": reference_range,
            "unit": unit,
            "confidence": confidence,
        }

    canonical_name = lab.get("canonical_name") or lab.get("test_name") or lab.get("display_name") or raw_name
    display_name = lab.get("display_name") or canonical_name or raw_name
    category = lab.get("category") or "Alte analize"

    return {
        "raw_test_name": clean_string(raw_name),
        "canonical_name": clean_string(canonical_name),
        "display_name": clean_string(display_name),
        "category": clean_string(category) or "Alte analize",
        "value": value,
        "flag": flag,
        "reference_range": reference_range,
        "unit": unit,
        "confidence": confidence,
    }


def normalize_rows_preserving_cbc(
    labs: list[dict[str, Any]],
    context_text: str = "",
) -> list[dict[str, Any]]:
    cbc_rows: list[dict[str, Any]] = []
    non_cbc_rows: list[dict[str, Any]] = []

    for lab in labs or []:
        if find_cbc_key_in_lab(lab):
            cbc_rows.append(standardize_lab_row_shape(lab))
        else:
            non_cbc_rows.append(lab)

    normalized_non_cbc = normalize_lab_rows(non_cbc_rows, context_text=context_text) if non_cbc_rows else []
    standardized_non_cbc = [standardize_lab_row_shape(row) for row in normalized_non_cbc]

    return cbc_rows + standardized_non_cbc


def get_lab_identity(lab: dict[str, Any]) -> str:
    cbc_key = find_cbc_key_in_lab(lab)

    if cbc_key:
        return f"cbc:{cbc_key.lower()}"

    value = (
        lab.get("raw_test_name")
        or lab.get("canonical_name")
        or lab.get("display_name")
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
        score += 0.40

    if row.get("unit"):
        score += 0.15

    if row.get("flag") in {"High", "Low"}:
        score += 0.08

    if find_cbc_key_in_lab(row):
        score += 0.25

    if row.get("raw_test_name") or row.get("canonical_name"):
        score += 0.05

    return score


def merge_lab_results(*lab_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_by_key: dict[str, dict[str, Any]] = {}

    for lab_list in lab_lists:
        for lab in lab_list or []:
            row = standardize_lab_row_shape(lab)
            key = get_lab_identity(row)

            if not key:
                continue

            if key not in merged_by_key or lab_quality_score(row) >= lab_quality_score(merged_by_key[key]):
                merged_by_key[key] = row

    return order_lab_rows([standardize_lab_row_shape(row) for row in merged_by_key.values()])


def order_lab_rows(labs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cbc_by_key: dict[str, dict[str, Any]] = {}
    other_rows: list[dict[str, Any]] = []

    for row in labs or []:
        cbc_key = find_cbc_key_in_lab(row)

        if cbc_key:
            cbc_by_key[cbc_key] = row
        else:
            other_rows.append(row)

    ordered: list[dict[str, Any]] = []

    for key in CBC_ORDER:
        if key in cbc_by_key:
            ordered.append(cbc_by_key.pop(key))

    ordered.extend(cbc_by_key.values())
    ordered.extend(other_rows)

    return ordered


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

    cbc_count = len([row for row in labs if find_cbc_key_in_lab(row)])

    if 0 < cbc_count < 24:
        return True

    if len(labs) < 20:
        return True

    rows_with_values = [row for row in labs if row.get("value") is not None]

    if not rows_with_values:
        return True

    rows_with_refs = [row for row in rows_with_values if row.get("reference_range")]

    if len(rows_with_refs) < max(5, int(len(rows_with_values) * 0.65)):
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


def extract_google_labs(
    extraction: dict[str, Any],
    extracted_text: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    google_labs = parse_labs_from_google_extraction(extraction)
    standardized_labs = normalize_rows_preserving_cbc(google_labs, context_text=extracted_text)
    standardized_labs = order_lab_rows(standardized_labs)

    table_count = len(extraction.get("tables") or [])
    line_count = len(extraction.get("lines") or [])
    word_count = len(extraction.get("words") or [])

    warnings.append(
        f"Google Document AI parser extracted {len(standardized_labs)} structured lab rows "
        f"from {table_count} tables, {line_count} lines, and {word_count} tokens."
    )

    return standardized_labs


def apply_ai_fallback(
    extracted_text: str,
    parsed_data: dict[str, Any],
    current_labs: list[dict[str, Any]],
    warnings: list[str],
    file_path: Path,
    filename: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if organize_labs_with_ai is None:
        warnings.append("OpenAI vision organizer fallback is unavailable because the module could not be imported.")
        return parsed_data, current_labs

    ai_result = organize_labs_with_ai(
        extracted_text=extracted_text,
        deterministic_labs=current_labs,
        file_path=file_path,
        filename=filename,
    )

    if not ai_result.get("ok"):
        if ai_result.get("warning"):
            warnings.append(str(ai_result["warning"]))
        else:
            warnings.append("OpenAI vision organizer fallback did not return usable structured data.")
        return parsed_data, current_labs

    ai_metadata = ai_result.get("metadata") or {}
    ai_labs = ai_result.get("labs") or []

    warnings.append(f"OpenAI vision organizer extracted {len(ai_labs)} lab rows.")

    parsed_data = merge_metadata(parsed_data, ai_metadata)

    standardized_ai_labs = normalize_rows_preserving_cbc(ai_labs, context_text=extracted_text)
    merged_labs = merge_lab_results(current_labs, standardized_ai_labs)

    return parsed_data, merged_labs


def process_bloodwork_document(
    extraction: dict[str, Any],
    extracted_text: str,
    warnings: list[str],
    file_path: Path,
    filename: str,
) -> dict[str, Any]:
    parsed_data = extract_report_metadata(extracted_text)
    parsed_data["report_type"] = "Bloodwork"
    parsed_data.setdefault("labs", [])
    parsed_data.setdefault("warnings", [])

    google_labs = extract_google_labs(
        extraction=extraction,
        extracted_text=extracted_text,
        warnings=warnings,
    )

    merged_labs = google_labs

    if lab_rows_need_ai_help(merged_labs, parsed_data):
        parsed_data, merged_labs = apply_ai_fallback(
            extracted_text=extracted_text,
            parsed_data=parsed_data,
            current_labs=merged_labs,
            warnings=warnings,
            file_path=file_path,
            filename=filename,
        )

    merged_labs = normalize_rows_preserving_cbc(merged_labs, context_text=extracted_text)
    merged_labs = merge_lab_results(merged_labs)

    parsed_data["labs"] = merged_labs
    parsed_data["report_name"] = build_category_report_name(parsed_data, merged_labs)

    if not merged_labs:
        warnings.append("No structured lab rows were extracted after Google Document AI and OpenAI vision fallback.")

    rows_with_values = [row for row in merged_labs if row.get("value") is not None]
    rows_with_refs = [row for row in rows_with_values if row.get("reference_range")]

    if rows_with_values and len(rows_with_refs) < max(3, int(len(rows_with_values) * 0.60)):
        warnings.append("Many lab rows are missing reference ranges. Manual review is recommended.")

    return parsed_data


def process_uploaded_document(
    file_path: Path,
    filename: str,
    section: str,
    temp_dir: Path,
) -> dict[str, Any]:
    extraction = extract_text(file_path=file_path, filename=filename, temp_dir=temp_dir)

    extracted_text = extraction.get("text") or ""
    ocr_quality = score_ocr_quality(extracted_text)

    warnings: list[str] = []
    warnings.extend(extraction.get("warnings", []) or [])
    warnings.extend(ocr_quality.get("warnings", []) or [])

    if section == "bloodwork":
        parsed_data = process_bloodwork_document(
            extraction=extraction,
            extracted_text=extracted_text,
            warnings=warnings,
            file_path=file_path,
            filename=filename,
        )
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