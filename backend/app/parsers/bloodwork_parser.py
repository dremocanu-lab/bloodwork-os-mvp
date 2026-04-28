import re

from app.report_fields import extract_report_metadata
from app.synonyms import normalize_test_name


KNOWN_TEST_ALIASES = {
    "WBC": "White Blood Cells",
    "RBC": "Red Blood Cell Count",
    "HGB": "Hemoglobin",
    "HB": "Hemoglobin",
    "HCT": "Hematocrit",
    "MCV": "MCV",
    "MCH": "MCH",
    "MCHC": "MCHC",
    "PLT": "Platelets",
    "RDW-SD": "RDW-SD",
    "RDW SD": "RDW-SD",
    "RDW_CV": "RDW-CV",
    "RDW-CV": "RDW-CV",
    "RDW CV": "RDW-CV",
    "PDW": "PDW",
    "MPV": "MPV",
    "P-LCR": "P-LCR",
    "P LCR": "P-LCR",
    "P_LCR": "P-LCR",
    "PCT": "Plateletcrit",
    "NRBC#": "NRBC Absolute",
    "NRBC": "NRBC Absolute",
    "NRBC%": "NRBC Percent",
    "NEUT#": "Neutrophils Absolute",
    "NEUT": "Neutrophils Absolute",
    "NEUT%": "Neutrophils Percent",
    "LYMPH#": "Lymphocytes Absolute",
    "LYMPH": "Lymphocytes Absolute",
    "LYMPH%": "Lymphocytes Percent",
    "MONO#": "Monocytes Absolute",
    "MONO": "Monocytes Absolute",
    "MONO%": "Monocytes Percent",
    "EO#": "Eosinophils Absolute",
    "EO": "Eosinophils Absolute",
    "EO%": "Eosinophils Percent",
    "EOS#": "Eosinophils Absolute",
    "EOS": "Eosinophils Absolute",
    "EOS%": "Eosinophils Percent",
    "BASO#": "Basophils Absolute",
    "BASO": "Basophils Absolute",
    "BASO%": "Basophils Percent",
    "IG#": "Immature Granulocytes Absolute",
    "IG": "Immature Granulocytes Absolute",
    "IG%": "Immature Granulocytes Percent",
    "GLU": "Glucose",
    "GLUCOSE": "Glucose",
    "GLUCOZA": "Glucose",
    "GLICEMIE": "Glucose",
    "CREATININA": "Creatinine",
    "CREATININĂ": "Creatinine",
    "CREATININE": "Creatinine",
    "UREE": "Urea",
    "UREA": "Urea",
    "BUN": "Urea",
    "ALT": "ALT",
    "ALAT": "ALT",
    "TGP": "ALT",
    "AST": "AST",
    "ASAT": "AST",
    "TGO": "AST",
    "GGT": "GGT",
    "TSH": "TSH",
    "CRP": "CRP",
    "HDL": "HDL Cholesterol",
    "LDL": "LDL Cholesterol",
}


SKIP_LINE_KEYWORDS = [
    "denumire",
    "analiza",
    "analiză",
    "rezultat",
    "interval",
    "biologic",
    "referinta",
    "referință",
    "citomorfologie",
    "hematograma",
    "hemogram",
    "starea probei",
    "conforma",
    "data validare",
    "nota",
    "buletin",
    "nume",
    "cnp",
    "telefon",
    "varsta",
    "vârsta",
    "cod pacient",
    "sex",
    "sectie",
    "medic",
]


def normalize_decimal(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    cleaned = cleaned.replace(",", ".")

    if cleaned.startswith("."):
        cleaned = "0" + cleaned

    return cleaned


def to_float(value: str | None) -> float | None:
    try:
        cleaned = normalize_decimal(value)
        if cleaned is None:
            return None
        return float(cleaned)
    except Exception:
        return None


def infer_flag(value: str | None, reference_range: str | None) -> str:
    numeric_value = to_float(value)

    if numeric_value is None or not reference_range:
        return "Normal"

    matches = re.findall(r"[-+]?\d+(?:[.,]\d+)?", str(reference_range))

    if len(matches) >= 2:
        low = to_float(matches[0])
        high = to_float(matches[1])

        if low is not None and high is not None:
            if numeric_value < low:
                return "Low"
            if numeric_value > high:
                return "High"

    return "Normal"


def clean_reference_range(reference_range: str | None) -> str | None:
    if not reference_range:
        return None

    cleaned = str(reference_range)
    cleaned = cleaned.replace("—", "-").replace("–", "-")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned or None


def clean_unit(unit: str | None) -> str | None:
    if not unit:
        return None

    cleaned = str(unit).strip()
    cleaned = cleaned.replace("µ", "u").replace("μ", "u")
    cleaned = cleaned.replace(" ", "")
    cleaned = cleaned.replace("l", "L") if cleaned.endswith("/l") else cleaned

    return cleaned or None


def normalize_raw_test_name(raw_name: str) -> str:
    cleaned = raw_name.strip()
    cleaned = cleaned.replace("↑", "").replace("↓", "")
    cleaned = cleaned.replace("▲", "").replace("▼", "")
    cleaned = re.sub(r"\s+", " ", cleaned)

    upper = cleaned.upper()

    # OCR sometimes separates symbols.
    upper = upper.replace(" #", "#").replace(" %", "%")

    return KNOWN_TEST_ALIASES.get(upper, cleaned)


def build_lab_result(
    raw_test_name: str,
    value: str | None,
    flag: str | None,
    reference_range: str | None,
    unit: str | None,
    confidence: float = 0.85,
) -> dict:
    display_candidate = normalize_raw_test_name(raw_test_name)
    normalized = normalize_test_name(display_candidate)

    final_reference_range = clean_reference_range(reference_range)
    final_unit = clean_unit(unit)

    final_flag = flag or infer_flag(value, final_reference_range)

    return {
        "raw_test_name": raw_test_name.strip() if raw_test_name else display_candidate,
        "canonical_name": normalized["canonical_name"],
        "display_name": normalized["display_name"],
        "category": normalized["category"],
        "value": normalize_decimal(value),
        "flag": final_flag,
        "reference_range": final_reference_range,
        "unit": final_unit,
        "confidence": confidence,
    }


def should_skip_line(line: str) -> bool:
    lowered = line.lower()

    if not lowered.strip():
        return True

    return any(keyword in lowered for keyword in SKIP_LINE_KEYWORDS)


def split_possible_table_line(line: str) -> list[str]:
    cleaned = line.strip()

    # Remove visual flag arrows but remember they may imply abnormality elsewhere.
    cleaned = cleaned.replace("↗", " ").replace("↘", " ")
    cleaned = cleaned.replace("↑", " ").replace("↓", " ")
    cleaned = cleaned.replace("▲", " ").replace("▼", " ")

    cleaned = re.sub(r"\s+", " ", cleaned)

    return cleaned.split(" ")


def extract_flag_from_line(line: str, value: str | None, reference_range: str | None) -> str:
    lowered = line.lower()

    if any(marker in line for marker in ["↑", "▲", "↗"]) or " high " in f" {lowered} ":
        return "High"

    if any(marker in line for marker in ["↓", "▼", "↘"]) or " low " in f" {lowered} ":
        return "Low"

    return infer_flag(value, reference_range)


def parse_generic_table_rows(text: str) -> list[dict]:
    labs: list[dict] = []
    seen: set[str] = set()

    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]

    # This catches rows such as:
    # WBC 11.44 3.98 - 10.00 10^3/ul
    # RBC 5.75 3.93 - 6.08 10^6/ul
    # HGB 14.4 11.2 - 17.5 g/dL
    row_pattern = re.compile(
        r"""
        ^\s*
        (?P<name>[A-Za-zĂÂÎȘȚăâîșț][A-Za-zĂÂÎȘȚăâîșț0-9#%_\-\/\.]{0,24})
        \s+
        (?P<value>[-+]?\d+(?:[.,]\d+)?)
        \s+
        (?P<low>[-+]?\d+(?:[.,]\d+)?)
        \s*[-–—]\s*
        (?P<high>[-+]?\d+(?:[.,]\d+)?)
        (?P<tail>.*?)
        \s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # This catches rows where OCR loses the dash but leaves enough numeric structure:
    # WBC 11.44 3.98 10.00 10^3/ul
    row_no_dash_pattern = re.compile(
        r"""
        ^\s*
        (?P<name>[A-Za-zĂÂÎȘȚăâîșț][A-Za-zĂÂÎȘȚăâîșț0-9#%_\-\/\.]{0,24})
        \s+
        (?P<value>[-+]?\d+(?:[.,]\d+)?)
        \s+
        (?P<low>[-+]?\d+(?:[.,]\d+)?)
        \s+
        (?P<high>[-+]?\d+(?:[.,]\d+)?)
        (?P<tail>.*?)
        \s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    for original_line in lines:
        if should_skip_line(original_line):
            continue

        line = original_line.strip()
        line = line.replace("|", " ")
        line = re.sub(r"\s+", " ", line)

        match = row_pattern.match(line) or row_no_dash_pattern.match(line)

        if not match:
            continue

        raw_name = match.group("name").strip()
        raw_name_upper = raw_name.upper().replace("_", "-")

        # Avoid capturing random words as tests.
        if raw_name_upper not in KNOWN_TEST_ALIASES and len(raw_name_upper) <= 2 and raw_name_upper not in {"EO", "IG"}:
            continue

        value = match.group("value")
        low = match.group("low")
        high = match.group("high")
        tail = (match.group("tail") or "").strip()

        reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"

        # Unit is usually the remaining non-empty tail after the reference range.
        unit = tail.strip()
        unit = re.sub(r"^[^\w%µμ\/]+", "", unit)
        unit = unit or None

        flag = extract_flag_from_line(original_line, value, reference_range)

        result = build_lab_result(
            raw_test_name=raw_name,
            value=value,
            flag=flag,
            reference_range=reference_range,
            unit=unit,
            confidence=0.9,
        )

        dedupe_key = result["canonical_name"] or result["display_name"] or raw_name_upper

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        labs.append(result)

    return labs


def parse_wrapped_table_rows(text: str) -> list[dict]:
    """
    Tesseract sometimes splits a visual table row into multiple lines:
    WBC
    11.44
    3.98 - 10.00 10^3/ul

    This pass tries to recover those cases.
    """
    labs: list[dict] = []
    seen: set[str] = set()

    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    cleaned_lines = [re.sub(r"\s+", " ", line.replace("|", " ")).strip() for line in lines]

    for idx, line in enumerate(cleaned_lines):
        name = line.strip()
        name_upper = name.upper().replace("_", "-")

        if name_upper not in KNOWN_TEST_ALIASES:
            continue

        window = " ".join(cleaned_lines[idx + 1 : idx + 5])
        numbers = re.findall(r"[-+]?\d+(?:[.,]\d+)?", window)

        if len(numbers) < 3:
            continue

        value = numbers[0]
        low = numbers[1]
        high = numbers[2]

        unit_match = re.search(
            r"(10\^?\d+\s*/?\s*[uµμ]?[lL]|[a-zA-Zµμ%\/]+(?:\/[a-zA-Zµμ]+)?)",
            window,
        )
        unit = unit_match.group(1) if unit_match else None

        reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"
        flag = extract_flag_from_line(window, value, reference_range)

        result = build_lab_result(
            raw_test_name=name,
            value=value,
            flag=flag,
            reference_range=reference_range,
            unit=unit,
            confidence=0.72,
        )

        dedupe_key = result["canonical_name"] or result["display_name"] or name_upper

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        labs.append(result)

    return labs


def extract_known_inline_labs(text: str) -> list[dict]:
    labs: list[dict] = []
    seen: set[str] = set()

    inline_patterns = [
        (r"\b(Haemoglobin|Hemoglobin|Hemoglobina|Hemoglobină|HGB|Hb)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?", "Hemoglobin"),
        (r"\b(Leucocite|Leukocite|WBC|White Blood Cells)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?", "White Blood Cells"),
        (r"\b(Eritrocite|RBC|Red Blood Cells)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?", "Red Blood Cell Count"),
        (r"\b(Hematocrit|Hematocritul|HCT)\b\s*[:\-]?\s*([\d.,]+)\s*(%)?", "Hematocrit"),
        (r"\b(Platelets|Trombocite|PLT)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?", "Platelets"),
        (r"\b(Creatinine|Creatinina|Creatinină)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?", "Creatinine"),
        (r"\b(Glucose|Glucoza|Glicemie|Glicemia)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?", "Glucose"),
        (r"\b(TSH)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?", "TSH"),
        (r"\b(CRP|Proteina C reactiva|Proteina C reactivă)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?", "CRP"),
    ]

    for pattern, fallback_name in inline_patterns:
        for match in re.finditer(pattern, text or "", re.IGNORECASE):
            raw_name = match.group(1) or fallback_name
            value = match.group(2)
            unit = match.group(3) if len(match.groups()) >= 3 else None

            result = build_lab_result(
                raw_test_name=raw_name,
                value=value,
                flag=None,
                reference_range=None,
                unit=unit,
                confidence=0.6,
            )

            dedupe_key = result["canonical_name"] or result["display_name"] or raw_name.lower()

            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            labs.append(result)

    return labs


def merge_labs(*lab_lists: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()

    for lab_list in lab_lists:
        for lab in lab_list:
            key = lab.get("canonical_name") or lab.get("display_name") or lab.get("raw_test_name")

            if not key:
                continue

            key = str(key).lower()

            if key in seen:
                continue

            seen.add(key)
            merged.append(lab)

    return merged


def parse_bloodwork_text(text: str) -> dict:
    safe_text = text or ""

    metadata = extract_report_metadata(safe_text)

    table_labs = parse_generic_table_rows(safe_text)
    wrapped_labs = parse_wrapped_table_rows(safe_text)
    inline_labs = extract_known_inline_labs(safe_text)

    labs = merge_labs(table_labs, wrapped_labs, inline_labs)

    report_name = metadata.get("report_type") or "Bloodwork Report"

    warnings = []
    if not labs:
        warnings.append("No structured lab results were confidently extracted. Manual review is recommended.")
    elif len(labs) < 5:
        warnings.append("Only a small number of lab rows were extracted. Manual review is recommended.")

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
        "report_type": metadata.get("report_type") or "Bloodwork",
        "source_language": metadata.get("source_language"),
        "test_date": metadata.get("collected_on") or metadata.get("reported_on") or metadata.get("generated_on"),
        "collected_on": metadata.get("collected_on"),
        "reported_on": metadata.get("reported_on"),
        "registered_on": metadata.get("registered_on"),
        "generated_on": metadata.get("generated_on"),
        "labs": labs,
        "warnings": warnings,
    }