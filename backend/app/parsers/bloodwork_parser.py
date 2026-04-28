import re

from app.report_fields import extract_report_metadata
from app.synonyms import normalize_test_name


def infer_flag(value: str, reference_range: str) -> str:
    try:
        numeric_value = float(str(value).replace(",", "."))
        matches = re.findall(r"[-+]?\d*\.?\d+", str(reference_range).replace(",", "."))
        if len(matches) >= 2:
            low = float(matches[0])
            high = float(matches[1])
            if numeric_value < low:
                return "Low"
            if numeric_value > high:
                return "High"
    except Exception:
        pass

    return "Normal"


def build_lab_result(
    raw_test_name: str,
    value: str,
    flag: str | None,
    reference_range: str,
    unit: str,
    confidence: float = 0.85,
) -> dict:
    normalized = normalize_test_name(raw_test_name)

    final_flag = flag or infer_flag(value, reference_range)

    return {
        "raw_test_name": normalized["raw_test_name"],
        "canonical_name": normalized["canonical_name"],
        "display_name": normalized["display_name"],
        "category": normalized["category"],
        "value": value.strip() if value else None,
        "flag": final_flag,
        "reference_range": reference_range.strip() if reference_range else None,
        "unit": unit.strip() if unit else None,
        "confidence": confidence,
    }


def clean_reference_range(reference_range: str) -> str:
    return re.sub(r"\s+", " ", reference_range or "").strip()


def clean_unit(unit: str) -> str:
    return re.sub(r"\s+", "", unit or "").strip()


def extract_match_labs(text: str) -> list[dict]:
    labs: list[dict] = []
    seen: set[str] = set()

    lab_patterns = [
        # CBC
        (r"\b(Haemoglobin|Hemoglobin|Hemoglobina|Hemoglobină|HGB|Hb)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Hemoglobin"),
        (r"\b(Leucocite|Leukocite|WBC|White Blood Cells|Total Leucocyte Count|Total Leukocyte Count|Total WBC count)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "White Blood Cells"),
        (r"\b(Eritrocite|RBC|Red Blood Cells|RBC Count|Total RBC count)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Red Blood Cells"),
        (r"\b(Hematocrit|Hematocritul|HCT)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*(%)?", "Hematocrit"),
        (r"\b(Platelets|Trombocite|PLT)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Platelets"),
        (r"\b(MCV)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "MCV"),
        (r"\b(MCH)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "MCH"),
        (r"\b(MCHC)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "MCHC"),
        (r"\b(RDW)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "RDW"),

        # Differential
        (r"\b(Neutrophils|Neutrofile|NEUT)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*(%)?", "Neutrophils"),
        (r"\b(Lymphocytes|Limfocite|LYMPH)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*(%)?", "Lymphocytes"),
        (r"\b(Monocytes|Monocite|MONO)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*(%)?", "Monocytes"),
        (r"\b(Eosinophils|Eozinofile|EOS)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*(%)?", "Eosinophils"),
        (r"\b(Basophils|Bazofile|BASO)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*(%)?", "Basophils"),

        # Kidney / electrolytes
        (r"\b(Creatinine|Creatinina|Creatinină)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Creatinine"),
        (r"\b(Uree|Urea|BUN)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Urea"),
        (r"\b(eGFR|GFR|RFG)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "eGFR"),
        (r"\b(Sodium|Sodiu|Na)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Sodium"),
        (r"\b(Potassium|Potasiu|K)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Potassium"),

        # Metabolic
        (r"\b(Glucose|Glucoza|Glicemie|Glicemia)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Glucose"),
        (r"\b(HbA1c|Hemoglobina glicata|Hemoglobină glicată)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*(%)?", "HbA1c"),

        # Lipids
        (r"\b(Total Cholesterol|Cholesterol total|Colesterol total)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Total Cholesterol"),
        (r"\b(HDL|HDL Cholesterol|Colesterol HDL)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "HDL Cholesterol"),
        (r"\b(LDL|LDL Cholesterol|Colesterol LDL)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "LDL Cholesterol"),
        (r"\b(Triglycerides|Trigliceride)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Triglycerides"),

        # Liver
        (r"\b(ALT|ALAT|GPT|TGP)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "ALT"),
        (r"\b(AST|ASAT|GOT|TGO)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "AST"),
        (r"\b(GGT|Gamma GT)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "GGT"),
        (r"\b(Bilirubin|Bilirubina|Bilirubină)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Bilirubin"),

        # Thyroid / inflammation
        (r"\b(TSH)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "TSH"),
        (r"\b(Free T4|FT4|fT4)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "Free T4"),
        (r"\b(CRP|Proteina C reactiva|Proteina C reactivă)\b\s*[:\-]?\s*([\d.,]+)\s*(?:High|Low|H|L)?\s*([\d.,]+\s*[-–—]\s*[\d.,]+)?\s*([a-zA-Z/%µμ0-9^]+)?", "CRP"),
    ]

    for pattern, canonical_guess in lab_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            raw_name = match.group(1).strip() if match.group(1) else canonical_guess
            value = match.group(2).strip() if len(match.groups()) >= 2 and match.group(2) else ""
            reference_range = clean_reference_range(match.group(3)) if len(match.groups()) >= 3 and match.group(3) else ""
            unit = clean_unit(match.group(4)) if len(match.groups()) >= 4 and match.group(4) else ""

            if not value:
                continue

            normalized = normalize_test_name(canonical_guess)
            dedupe_key = normalized["canonical_name"] or normalized["display_name"].lower()

            # Preserve first match for each canonical test.
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)

            labs.append(
                build_lab_result(
                    raw_test_name=raw_name,
                    value=value,
                    flag=None,
                    reference_range=reference_range,
                    unit=unit,
                    confidence=0.85 if reference_range else 0.7,
                )
            )

    return labs


def parse_bloodwork_text(text: str) -> dict:
    metadata = extract_report_metadata(text or "")
    labs = extract_match_labs(text or "")

    report_name = metadata.get("report_type") or "Unknown Report"

    warnings = []
    if not labs:
        warnings.append("No structured lab results were confidently extracted. Manual review is recommended.")

    return {
        "patient_name": metadata.get("patient_name"),
        "date_of_birth": metadata.get("date_of_birth"),
        "age": metadata.get("age"),
        "sex": metadata.get("sex"),
        "cnp": metadata.get("cnp"),
        "patient_identifier": metadata.get("patient_identifier"),
        "lab_name": metadata.get("lab_name"),
        "sample_type": metadata.get("sample_type"),
        "referring_doctor": metadata.get("referring_doctor"),
        "report_name": report_name,
        "report_type": metadata.get("report_type"),
        "source_language": metadata.get("source_language"),
        "test_date": metadata.get("collected_on") or metadata.get("reported_on") or metadata.get("generated_on"),
        "collected_on": metadata.get("collected_on"),
        "reported_on": metadata.get("reported_on"),
        "registered_on": metadata.get("registered_on"),
        "generated_on": metadata.get("generated_on"),
        "labs": labs,
        "warnings": warnings,
    }