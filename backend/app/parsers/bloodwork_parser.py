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
    "RDWSD": "RDW-SD",
    "RDW": "RDW",
    "RDW-CV": "RDW-CV",
    "RDWCV": "RDW-CV",
    "PDW": "PDW",
    "MPV": "MPV",
    "P-LCR": "P-LCR",
    "PLCR": "P-LCR",
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
    "spitalizare",
    "institutul",
    "laborator",
]

ARROW_HIGH_MARKERS = ["↑", "▲", "↗", "⬆", "➚", "7"]
ARROW_LOW_MARKERS = ["↓", "▼", "↘", "⬇", "➘"]

NULL_RESULT_TOKENS = {"", "-", "--", "---", "—", "–", "___", "____", "nil", "n/a", "na", "null"}

JUNK_TOKENS = {
    "",
    "-",
    "—",
    "–",
    "|",
    ":",
    ".",
    ",",
    "•",
    "·",
    "»",
    "«",
    ">",
    "<",
    "↑",
    "↓",
    "▲",
    "▼",
    "↗",
    "↘",
    "⬆",
    "⬇",
    "➚",
    "➘",
}


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


def fix_missing_decimal_for_percent_or_small_range(value: str | None, low: str | None, high: str | None) -> str | None:
    """
    OCR sometimes turns 7.2 into 72 or 4.7 - 12.5 into 47 - 125.
    This conservative correction only applies when the value is an integer
    and the reference range strongly suggests a decimal percentage-type field.
    """
    if value is None or low is None or high is None:
        return value

    raw = str(value).strip()
    low_f = to_float(low)
    high_f = to_float(high)

    if not raw.isdigit() or low_f is None or high_f is None:
        return value

    numeric = float(raw)

    if numeric > high_f and numeric / 10 <= high_f * 1.5:
        return str(numeric / 10).rstrip("0").rstrip(".")

    return value


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

    replacements = {
        "103/uL": "10^3/uL",
        "10^3/ul": "10^3/uL",
        "10^3/uL": "10^3/uL",
        "106/uL": "10^6/uL",
        "10^6/ul": "10^6/uL",
        "10^6/uL": "10^6/uL",
        "g/dl": "g/dL",
        "g/dL": "g/dL",
        "FL": "fL",
    }

    return replacements.get(cleaned, cleaned) or None


def normalize_test_token(token: str) -> str:
    cleaned = token.strip().upper()
    cleaned = cleaned.replace("_", "-")
    cleaned = cleaned.replace(" ", "")
    cleaned = cleaned.replace("＃", "#")
    cleaned = cleaned.replace("％", "%")
    cleaned = cleaned.replace("S", "S")

    # OCR often loses the dash in these.
    if cleaned == "RDWSD":
        return "RDW-SD"
    if cleaned == "RDWCV":
        return "RDW-CV"
    if cleaned == "PLCR":
        return "P-LCR"

    return cleaned


def normalize_raw_test_name(raw_name: str) -> str:
    cleaned = raw_name.strip()
    cleaned = cleaned.replace("↑", "").replace("↓", "")
    cleaned = cleaned.replace("▲", "").replace("▼", "")
    cleaned = cleaned.replace("↗", "").replace("↘", "")
    cleaned = cleaned.replace("⬆", "").replace("⬇", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    upper = normalize_test_token(cleaned)

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


def clean_ocr_text_for_rows(text: str) -> str:
    cleaned = text or ""

    # Remove visual abnormal arrows as separators. They should not block row parsing.
    for marker in ARROW_HIGH_MARKERS + ARROW_LOW_MARKERS:
        cleaned = cleaned.replace(marker, " ")

    cleaned = cleaned.replace("|", " ")
    cleaned = cleaned.replace("¦", " ")
    cleaned = cleaned.replace("│", " ")
    cleaned = cleaned.replace("€", " ")
    cleaned = cleaned.replace("®", " ")
    cleaned = cleaned.replace("™", " ")

    # Normalize table-like whitespace.
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    return cleaned


def extract_flag_from_line(original_line: str, value: str | None, reference_range: str | None) -> str:
    lowered = f" {original_line.lower()} "

    if any(marker in original_line for marker in ARROW_HIGH_MARKERS[:-1]) or " high " in lowered:
        return "High"

    if any(marker in original_line for marker in ARROW_LOW_MARKERS) or " low " in lowered:
        return "Low"

    return infer_flag(value, reference_range)


def parse_generic_table_rows(text: str) -> list[dict]:
    labs: list[dict] = []
    seen: set[str] = set()

    original_lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    cleaned_lines = [clean_ocr_text_for_rows(line).strip() for line in original_lines]

    # Allows junk between name and value:
    # WBC 18.52 3.98 - 10.00 10^3/ul
    # WBC arrow 18.52 3.98 - 10.00 10^3/ul
    row_pattern = re.compile(
        r"""
        ^\s*
        (?P<name>[A-Za-zĂÂÎȘȚăâîșț][A-Za-zĂÂÎȘȚăâîșț0-9#%_\-\/\.]{0,24})
        (?:\s+[^\d\s]{1,5}){0,3}
        \s+
        (?P<value>[-+]?\d+(?:[.,]\d+)?)
        \s+
        (?P<low>[-+]?\d+(?:[.,]\d+)?)
        \s*[-–—]?\s*
        (?P<high>[-+]?\d+(?:[.,]\d+)?)
        (?P<tail>.*?)
        \s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    for idx, line in enumerate(cleaned_lines):
        original_line = original_lines[idx]

        if should_skip_line(original_line):
            continue

        line = re.sub(r"\s+", " ", line).strip()
        match = row_pattern.match(line)

        if not match:
            continue

        raw_name = match.group("name").strip()
        raw_name_upper = normalize_test_token(raw_name)

        if raw_name_upper not in KNOWN_TEST_ALIASES:
            continue

        value = match.group("value")
        low = match.group("low")
        high = match.group("high")
        tail = (match.group("tail") or "").strip()

        fixed_value = fix_missing_decimal_for_percent_or_small_range(value, low, high)
        fixed_low = low
        fixed_high = high

        # If range was OCR'd as 47 - 125 for percent-style tests, make it 4.7 - 12.5.
        if raw_name_upper.endswith("%") or raw_name_upper in {"MONO", "NEUT", "LYMPH", "BASO", "EO", "EOS", "IG"}:
            low_f = to_float(low)
            high_f = to_float(high)
            if low_f is not None and high_f is not None and high_f > 100:
                fixed_low = str(low_f / 10).rstrip("0").rstrip(".")
                fixed_high = str(high_f / 10).rstrip("0").rstrip(".")

        reference_range = f"{normalize_decimal(fixed_low)} - {normalize_decimal(fixed_high)}"

        unit = tail.strip()
        unit = re.sub(r"^[^\w%µμ\/\^]+", "", unit)
        unit = unit or None

        if not unit:
            if raw_name_upper.endswith("%"):
                unit = "%"
            elif raw_name_upper.endswith("#"):
                unit = "10^3/uL"

        flag = extract_flag_from_line(original_line, fixed_value, reference_range)

        result = build_lab_result(
            raw_test_name=raw_name,
            value=fixed_value,
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


def tokenize_ocr_text(text: str) -> list[str]:
    cleaned = clean_ocr_text_for_rows(text or "")

    # Keep useful symbols inside tokens.
    cleaned = re.sub(r"([A-Za-zĂÂÎȘȚăâîșț]+)\s+([#%])", r"\1\2", cleaned)
    cleaned = cleaned.replace("RDW SD", "RDW-SD")
    cleaned = cleaned.replace("RDW CV", "RDW-CV")
    cleaned = cleaned.replace("P LCR", "P-LCR")

    tokens = re.findall(
        r"[A-Za-zĂÂÎȘȚăâîșț]+[#%]?"
        r"|[A-Za-zĂÂÎȘȚăâîșț]+-[A-Za-zĂÂÎȘȚăâîșț]+"
        r"|[A-Za-zĂÂÎȘȚăâîșț]+-[A-Za-zĂÂÎȘȚăâîșț]+[#%]?"
        r"|[A-Za-zĂÂÎȘȚăâîșț]+-[A-Za-zĂÂÎȘȚăâîșț]+"
        r"|[A-Za-zĂÂÎȘȚăâîșț]+-[A-Za-zĂÂÎȘȚăâîșț]+"
        r"|[A-Za-zĂÂÎȘȚăâîșț]+-[A-Z]+"
        r"|[A-Z]+-[A-Z]+[#%]?"
        r"|[-+]?\d+(?:[.,]\d+)?"
        r"|10\^?\d+/?[uµμ]?[lL]?"
        r"|[%]"
        r"|[A-Za-zµμ/%^0-9]+",
        cleaned,
    )

    return [token.strip() for token in tokens if token.strip() and token.strip() not in JUNK_TOKENS]


def is_number_token(token: str) -> bool:
    return re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", token.strip()) is not None


def is_null_result_token(token: str | None) -> bool:
    if token is None:
        return True

    cleaned = str(token).strip().lower()
    cleaned = cleaned.replace("−", "-")
    cleaned = cleaned.replace("—", "-").replace("–", "-")

    return cleaned in NULL_RESULT_TOKENS or re.fullmatch(r"-{2,}", cleaned) is not None


def build_nil_result(raw_test_name: str, reference_range: str | None = None, unit: str | None = None, confidence: float = 0.72) -> dict:
    result = build_lab_result(
        raw_test_name=raw_test_name,
        value=None,
        flag=None,
        reference_range=reference_range,
        unit=unit,
        confidence=confidence,
    )
    result["value"] = None
    result["flag"] = None
    return result


def looks_like_unit(token: str) -> bool:
    cleaned = token.strip()
    if not cleaned:
        return False

    lowered = cleaned.lower()

    return (
        "%" in cleaned
        or "/" in cleaned
        or "^" in cleaned
        or lowered in {"fl", "g/dl", "g/dl", "pg", "u/l", "mg/dl", "mmol/l"}
        or re.fullmatch(r"10\^?\d+/?[uµμ]?[lL]?", cleaned) is not None
        or re.fullmatch(r"10\d+/?[uµμ]?[lL]?", cleaned) is not None
    )


def parse_token_stream_rows(text: str) -> list[dict]:
    """
    Backup parser for OCR text where table rows are badly split.
    It scans token-by-token:
    TEST -> value -> low -> high -> optional unit
    and ignores arrow/junk artifacts.
    """
    labs: list[dict] = []
    seen: set[str] = set()

    tokens = tokenize_ocr_text(text)

    i = 0
    while i < len(tokens):
        token = tokens[i]
        test_key = normalize_test_token(token)

        # OCR sometimes sees "RDW" "SD" as two tokens.
        if test_key == "RDW" and i + 1 < len(tokens):
            nxt = normalize_test_token(tokens[i + 1])
            if nxt in {"SD", "CV"}:
                test_key = f"RDW-{nxt}"
                i += 1

        if test_key == "P" and i + 1 < len(tokens):
            nxt = normalize_test_token(tokens[i + 1])
            if nxt == "LCR":
                test_key = "P-LCR"
                i += 1

        if test_key not in KNOWN_TEST_ALIASES:
            i += 1
            continue

        # Look ahead for the next 3 numbers. They are usually value, low, high.
        # If the row starts with --- / nil / blank markers, do not steal reference-range
        # numbers and pretend they are measured values.
        lookahead = tokens[i + 1 : i + 12]

        first_non_arrow_token = None
        for candidate in lookahead:
            if candidate in ARROW_HIGH_MARKERS or candidate in ARROW_LOW_MARKERS:
                continue
            first_non_arrow_token = candidate
            break

        if is_null_result_token(first_non_arrow_token):
            unit = None
            if test_key.endswith("%"):
                unit = "%"
            elif test_key.endswith("#"):
                unit = "10^3/uL"

            result = build_nil_result(test_key, reference_range=None, unit=unit, confidence=0.76)
            dedupe_key = result["canonical_name"] or result["display_name"] or test_key

            if dedupe_key not in seen:
                seen.add(dedupe_key)
                labs.append(result)

            i += 1
            continue

        number_positions = []

        for offset, candidate in enumerate(lookahead):
            if is_number_token(candidate):
                number_positions.append((offset, candidate))
                if len(number_positions) >= 3:
                    break

        if len(number_positions) < 3:
            result = build_nil_result(test_key, reference_range=None, unit=None, confidence=0.68)
            dedupe_key = result["canonical_name"] or result["display_name"] or test_key

            if dedupe_key not in seen:
                seen.add(dedupe_key)
                labs.append(result)

            i += 1
            continue

        value = number_positions[0][1]
        low = number_positions[1][1]
        high = number_positions[2][1]

        fixed_value = fix_missing_decimal_for_percent_or_small_range(value, low, high)
        fixed_low = low
        fixed_high = high

        if test_key.endswith("%"):
            low_f = to_float(low)
            high_f = to_float(high)
            if low_f is not None and high_f is not None and high_f > 100:
                fixed_low = str(low_f / 10).rstrip("0").rstrip(".")
                fixed_high = str(high_f / 10).rstrip("0").rstrip(".")

        unit = None
        after_numbers_start = number_positions[2][0] + 1

        for candidate in lookahead[after_numbers_start : after_numbers_start + 4]:
            if looks_like_unit(candidate):
                unit = candidate
                break

        if not unit:
            if test_key.endswith("%"):
                unit = "%"
            elif test_key.endswith("#"):
                unit = "10^3/uL"

        reference_range = f"{normalize_decimal(fixed_low)} - {normalize_decimal(fixed_high)}"

        local_text = " ".join(lookahead[: after_numbers_start + 4])
        flag = extract_flag_from_line(local_text, fixed_value, reference_range)

        result = build_lab_result(
            raw_test_name=test_key,
            value=fixed_value,
            flag=flag,
            reference_range=reference_range,
            unit=unit,
            confidence=0.78,
        )

        dedupe_key = result["canonical_name"] or result["display_name"] or test_key

        if dedupe_key not in seen:
            seen.add(dedupe_key)
            labs.append(result)

        i += 1

    return labs


def parse_wrapped_table_rows(text: str) -> list[dict]:
    labs: list[dict] = []
    seen: set[str] = set()

    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    cleaned_lines = [clean_ocr_text_for_rows(line).strip() for line in lines]

    for idx, line in enumerate(cleaned_lines):
        name = normalize_test_token(line)

        if name not in KNOWN_TEST_ALIASES:
            continue

        following_lines = cleaned_lines[idx + 1 : idx + 6]
        first_following = following_lines[0] if following_lines else ""

        if is_null_result_token(first_following):
            result = build_nil_result(name, reference_range=None, unit=None, confidence=0.74)
            dedupe_key = result["canonical_name"] or result["display_name"] or name

            if dedupe_key not in seen:
                seen.add(dedupe_key)
                labs.append(result)

            continue

        window = " ".join(following_lines)
        numbers = re.findall(r"[-+]?\d+(?:[.,]\d+)?", window)

        if len(numbers) < 3:
            result = build_nil_result(name, reference_range=None, unit=None, confidence=0.66)
            dedupe_key = result["canonical_name"] or result["display_name"] or name

            if dedupe_key not in seen:
                seen.add(dedupe_key)
                labs.append(result)

            continue

        value = numbers[0]
        low = numbers[1]
        high = numbers[2]

        fixed_value = fix_missing_decimal_for_percent_or_small_range(value, low, high)
        fixed_low = low
        fixed_high = high

        if name.endswith("%"):
            low_f = to_float(low)
            high_f = to_float(high)
            if low_f is not None and high_f is not None and high_f > 100:
                fixed_low = str(low_f / 10).rstrip("0").rstrip(".")
                fixed_high = str(high_f / 10).rstrip("0").rstrip(".")

        unit_match = re.search(
            r"(10\^?\d+\s*/?\s*[uµμ]?[lL]|10\d+\s*/?\s*[uµμ]?[lL]|[a-zA-Zµμ%\/]+(?:\/[a-zA-Zµμ]+)?)",
            window,
        )
        unit = unit_match.group(1) if unit_match else None

        if not unit:
            if name.endswith("%"):
                unit = "%"
            elif name.endswith("#"):
                unit = "10^3/uL"

        reference_range = f"{normalize_decimal(fixed_low)} - {normalize_decimal(fixed_high)}"
        flag = extract_flag_from_line(window, fixed_value, reference_range)

        result = build_lab_result(
            raw_test_name=name,
            value=fixed_value,
            flag=flag,
            reference_range=reference_range,
            unit=unit,
            confidence=0.72,
        )

        dedupe_key = result["canonical_name"] or result["display_name"] or name

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

            existing_index = None
            for idx, existing in enumerate(merged):
                existing_key = existing.get("canonical_name") or existing.get("display_name") or existing.get("raw_test_name")
                if existing_key and str(existing_key).lower() == key:
                    existing_index = idx
                    break

            if existing_index is None:
                seen.add(key)
                merged.append(lab)
                continue

            # Prefer higher-confidence rows with reference range and unit.
            existing = merged[existing_index]
            existing_score = float(existing.get("confidence") or 0)
            new_score = float(lab.get("confidence") or 0)

            if lab.get("reference_range"):
                new_score += 0.1
            if lab.get("unit"):
                new_score += 0.05

            if existing.get("reference_range"):
                existing_score += 0.1
            if existing.get("unit"):
                existing_score += 0.05

            if new_score > existing_score:
                merged[existing_index] = lab

    return merged


def parse_bloodwork_text(text: str) -> dict:
    safe_text = text or ""

    metadata = extract_report_metadata(safe_text)

    table_labs = parse_generic_table_rows(safe_text)
    token_labs = parse_token_stream_rows(safe_text)
    wrapped_labs = parse_wrapped_table_rows(safe_text)
    inline_labs = extract_known_inline_labs(safe_text)

    labs = merge_labs(table_labs, token_labs, wrapped_labs, inline_labs)

    report_name = metadata.get("report_type") or "Bloodwork Report"

    warnings = []
    if not labs:
        warnings.append("No structured lab results were confidently extracted. Manual review is recommended.")
    elif len(labs) < 10:
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