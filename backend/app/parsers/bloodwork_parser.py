import re

from app.report_fields import extract_report_metadata
from app.synonyms import normalize_test_name


KNOWN_TEST_ALIASES = {
    "WBC": "White Blood Cells",
    "RBC": "Red Blood Cell Count",
    "HGB": "Hemoglobin",
    "HB": "Hemoglobin",
    "HCT": "Hematocrit",
    "MCV": "Mean Corpuscular Volume",
    "MCH": "Mean Corpuscular Hemoglobin",
    "MCHC": "Mean Corpuscular Hemoglobin Concentration",
    "PLT": "Platelet Count",
    "RDW": "Red Cell Distribution Width",
    "RDW-SD": "Red Cell Distribution Width - SD",
    "RDWSD": "Red Cell Distribution Width - SD",
    "RDW-CV": "Red Cell Distribution Width - CV",
    "RDWCV": "Red Cell Distribution Width - CV",
    "PDW": "Platelet Distribution Width",
    "MPV": "Mean Platelet Volume",
    "P-LCR": "P-LCR",
    "PLCR": "P-LCR",
    "PCT": "Plateletcrit",
    "NRBC#": "Nucleated Red Blood Cells Absolute",
    "NRBC": "Nucleated Red Blood Cells Absolute",
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
    "denumire analiza",
    "denumire analiză",
    "rezultat",
    "interval biologic",
    "interval de referinta",
    "interval de referință",
    "citomorfologie",
    "hematograma",
    "hemogram",
    "starea probei",
    "conforma",
    "data validare",
    "buletin analize",
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

ARROW_HIGH_MARKERS = {"↑", "▲", "↗", "⬆", "➚"}
ARROW_LOW_MARKERS = {"↓", "▼", "↘", "⬇", "➘"}

NULL_RESULT_TOKENS = {
    "",
    "-",
    "--",
    "---",
    "----",
    "-----",
    "------",
    "—",
    "–",
    "___",
    "____",
    "_____",
    "nil",
    "n/a",
    "na",
    "null",
}

BLANK_PRONE_TESTS = {
    "PDW",
    "MPV",
    "P-LCR",
    "PLCR",
    "PCT",
    "NRBC",
    "NRBC#",
    "NRBC%",
}

NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
NULL_MARKER_RE = re.compile(
    r"(^|[\s|:;])(?:-{2,}|_{2,}|—+|–+|nil|n/a|na|null)(?=$|[\s|:;])",
    re.IGNORECASE,
)


def normalize_decimal(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.replace("−", "-")
    cleaned = cleaned.replace("—", "-")
    cleaned = cleaned.replace("–", "-")

    if not cleaned:
        return None

    if is_null_result_token(cleaned):
        return None

    cleaned = re.sub(r"[^0-9.+-]", "", cleaned)

    if cleaned.startswith("."):
        cleaned = "0" + cleaned

    if cleaned in {"", "+", "-", ".", "+.", "-."}:
        return None

    return cleaned


def to_float(value: str | None) -> float | None:
    try:
        cleaned = normalize_decimal(value)
        if cleaned is None:
            return None
        return float(cleaned)
    except Exception:
        return None


def is_number_token(token: str | None) -> bool:
    if token is None:
        return False

    cleaned = normalize_decimal(token)
    if cleaned is None:
        return False

    return NUMBER_RE.fullmatch(cleaned) is not None


def is_null_result_token(token: str | None) -> bool:
    if token is None:
        return True

    cleaned = str(token).strip().lower()
    cleaned = cleaned.replace("−", "-").replace("—", "-").replace("–", "-")

    return cleaned in NULL_RESULT_TOKENS or re.fullmatch(r"[-_]{2,}", cleaned) is not None


def clean_reference_range(reference_range: str | None) -> str | None:
    if not reference_range:
        return None

    cleaned = str(reference_range)
    cleaned = cleaned.replace("—", "-").replace("–", "-").replace("−", "-")
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
        "103/ul": "10^3/uL",
        "10^3/ul": "10^3/uL",
        "10^3/uL": "10^3/uL",
        "106/uL": "10^6/uL",
        "106/ul": "10^6/uL",
        "10^6/ul": "10^6/uL",
        "10^6/uL": "10^6/uL",
        "FL": "fL",
        "fl": "fL",
        "g/dl": "g/dL",
        "g/dL": "g/dL",
    }

    return replacements.get(cleaned, cleaned) or None


def looks_like_unit(token: str | None) -> bool:
    if not token:
        return False

    cleaned = str(token).strip()
    lowered = cleaned.lower()

    if cleaned == "%":
        return True

    if "/" in cleaned or "^" in cleaned:
        return True

    if re.fullmatch(r"10\^?\d+/?[uµμ]?[lL]?", cleaned):
        return True

    if re.fullmatch(r"10\d+/?[uµμ]?[lL]?", cleaned):
        return True

    return lowered in {
        "fl",
        "pg",
        "g/dl",
        "mg/dl",
        "mmol/l",
        "u/l",
        "/ul",
        "/µl",
        "/μl",
        "%",
    }


def normalize_test_token(token: str | None) -> str:
    if token is None:
        return ""

    cleaned = str(token).strip().upper()
    cleaned = cleaned.replace("_", "-")
    cleaned = cleaned.replace(" ", "")
    cleaned = cleaned.replace("＃", "#")
    cleaned = cleaned.replace("％", "%")
    cleaned = cleaned.replace("–", "-")
    cleaned = cleaned.replace("—", "-")
    cleaned = cleaned.replace("−", "-")
    cleaned = cleaned.replace(".", "")

    if cleaned == "RDWSD":
        return "RDW-SD"
    if cleaned == "RDWCV":
        return "RDW-CV"
    if cleaned == "PLCR":
        return "P-LCR"
    if cleaned == "P LCR":
        return "P-LCR"

    return cleaned


def normalize_raw_test_name(raw_name: str) -> str:
    cleaned = str(raw_name or "").strip()

    for marker in list(ARROW_HIGH_MARKERS) + list(ARROW_LOW_MARKERS):
        cleaned = cleaned.replace(marker, "")

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    upper = normalize_test_token(cleaned)

    return KNOWN_TEST_ALIASES.get(upper, cleaned)


def infer_flag(value: str | None, reference_range: str | None) -> str | None:
    numeric_value = to_float(value)

    if numeric_value is None:
        return None

    if not reference_range:
        return "Normal"

    matches = NUMBER_RE.findall(str(reference_range))

    if len(matches) >= 2:
        low = to_float(matches[0])
        high = to_float(matches[1])

        if low is not None and high is not None:
            if numeric_value < low:
                return "Low"
            if numeric_value > high:
                return "High"

    return "Normal"


def extract_flag_from_line(original_line: str, value: str | None, reference_range: str | None) -> str | None:
    lowered = f" {str(original_line or '').lower()} "

    if any(marker in original_line for marker in ARROW_HIGH_MARKERS) or " high " in lowered:
        return "High"

    if any(marker in original_line for marker in ARROW_LOW_MARKERS) or " low " in lowered:
        return "Low"

    return infer_flag(value, reference_range)


def fix_numeric_scale(value: str | None, low: str | None, high: str | None) -> str | None:
    """
    Conservative decimal repair.

    Keeps true integers like PLT 395.
    Repairs OCR values like:
      547 with ref 3.93-6.08 -> 5.47
      676 with ref 3.93-6.08 -> 6.76
      473 with ref 34.1-51.0 -> 47.3
      207 with ref 25.6-32.2 -> 20.7

    Does not invent a missing digit. If OCR gives only 5.4 and no extra fragment,
    it stays 5.4. If OCR gives 5.4 7, choose_value_low_high joins it to 5.47.
    """
    if value is None:
        return None

    value_s = normalize_decimal(value)
    if value_s is None:
        return None

    value_f = to_float(value_s)
    low_f = to_float(low)
    high_f = to_float(high)

    if value_f is None or low_f is None or high_f is None:
        return value_s

    if low_f > high_f:
        low_f, high_f = high_f, low_f

    if low_f * 0.45 <= value_f <= high_f * 1.8:
        return value_s

    raw = value_s.replace(".", "").replace("-", "")

    if not raw.isdigit() or len(raw) < 2:
        return value_s

    candidates: list[tuple[float, str]] = []

    for divisor in [10, 100, 1000]:
        candidate = float(raw) / divisor

        if low_f * 0.45 <= candidate <= high_f * 1.8:
            formatted = f"{candidate:.6f}".rstrip("0").rstrip(".")
            candidates.append((abs(candidate - ((low_f + high_f) / 2)), formatted))

    if not candidates:
        return value_s

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def choose_value_low_high(numbers: list[str]) -> tuple[str | None, str | None, str | None, int]:
    """
    Returns value, low, high, consumed_count.

    Handles split decimals:
      ["5.4", "7", "3.93", "6.08"] -> value 5.47, low 3.93, high 6.08
      ["47", "3", "34.1", "51.0"] -> value 47.3 if plausible
    """
    nums = [normalize_decimal(item) for item in numbers if normalize_decimal(item) is not None]

    if len(nums) < 3:
        return None, None, None, 0

    if len(nums) >= 4:
        first = nums[0]
        second = nums[1]
        third = nums[2]
        fourth = nums[3]

        if first and "." in first and second and second.isdigit() and len(second) == 1:
            joined = f"{first}{second}"
            joined_f = to_float(joined)
            low_f = to_float(third)
            high_f = to_float(fourth)

            if joined_f is not None and low_f is not None and high_f is not None:
                low_ordered = min(low_f, high_f)
                high_ordered = max(low_f, high_f)

                if low_ordered * 0.45 <= joined_f <= high_ordered * 1.8:
                    return joined, third, fourth, 4

        if first and first.isdigit() and second and second.isdigit() and len(second) == 1:
            joined = f"{first}.{second}"
            joined_f = to_float(joined)
            low_f = to_float(third)
            high_f = to_float(fourth)

            if joined_f is not None and low_f is not None and high_f is not None:
                low_ordered = min(low_f, high_f)
                high_ordered = max(low_f, high_f)

                if low_ordered * 0.45 <= joined_f <= high_ordered * 1.8:
                    return joined, third, fourth, 4

    value, low, high = nums[0], nums[1], nums[2]
    fixed_value = fix_numeric_scale(value, low, high)

    return fixed_value, low, high, 3


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

    final_value = normalize_decimal(value)
    final_reference_range = clean_reference_range(reference_range)
    final_unit = clean_unit(unit)

    final_flag = flag if final_value is not None else None
    if final_value is not None and final_flag is None:
        final_flag = infer_flag(final_value, final_reference_range)

    return {
        "raw_test_name": str(raw_test_name or display_candidate).strip(),
        "canonical_name": normalized["canonical_name"],
        "display_name": normalized["display_name"],
        "category": normalized["category"],
        "value": final_value,
        "flag": final_flag,
        "reference_range": final_reference_range,
        "unit": final_unit,
        "confidence": confidence,
    }


def build_nil_result(
    raw_test_name: str,
    reference_range: str | None = None,
    unit: str | None = None,
    confidence: float = 0.99,
) -> dict:
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


def should_skip_line(line: str) -> bool:
    lowered = str(line or "").lower()

    if not lowered.strip():
        return True

    return any(keyword in lowered for keyword in SKIP_LINE_KEYWORDS)


def clean_ocr_text_for_rows(text: str) -> str:
    cleaned = text or ""

    cleaned = cleaned.replace("│", " ")
    cleaned = cleaned.replace("|", " ")
    cleaned = cleaned.replace("¦", " ")
    cleaned = cleaned.replace("€", " ")
    cleaned = cleaned.replace("®", " ")
    cleaned = cleaned.replace("™", " ")
    cleaned = cleaned.replace("µ", "u")
    cleaned = cleaned.replace("μ", "u")

    cleaned = cleaned.replace("RDW SD", "RDW-SD")
    cleaned = cleaned.replace("RDW CV", "RDW-CV")
    cleaned = cleaned.replace("P LCR", "P-LCR")

    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    return cleaned.strip()


def token_identity_keys(raw_test_name: str) -> set[str]:
    key = normalize_test_token(raw_test_name)
    display = KNOWN_TEST_ALIASES.get(key, raw_test_name)
    normalized = normalize_test_name(display)

    keys = {
        key.lower(),
        str(raw_test_name or "").lower(),
        str(display or "").lower(),
        str(normalized.get("canonical_name") or "").lower(),
        str(normalized.get("display_name") or "").lower(),
    }

    return {item for item in keys if item}


def lab_identity_keys(lab: dict) -> set[str]:
    keys = set()

    for field in ["raw_test_name", "canonical_name", "display_name"]:
        value = lab.get(field)
        if value:
            keys |= token_identity_keys(str(value))

    return {item for item in keys if item}


def find_test_key_in_line(line: str) -> tuple[str | None, int, int]:
    source = line or ""

    aliases = sorted(KNOWN_TEST_ALIASES.keys(), key=len, reverse=True)

    for alias in aliases:
        alias_pattern = re.escape(alias).replace(r"\-", r"[-\s]?")

        match = re.search(
            rf"(?<![A-Za-z0-9]){alias_pattern}(?![A-Za-z0-9])",
            source,
            re.IGNORECASE,
        )

        if match:
            return normalize_test_token(alias), match.start(), match.end()

    return None, -1, -1


def segment_has_null_before_first_number(segment: str) -> bool:
    if not segment:
        return False

    first_num = NUMBER_RE.search(segment)
    before_first_num = segment if not first_num else segment[: first_num.start()]
    before_first_num = before_first_num.replace("−", "-").replace("—", "-").replace("–", "-")

    return NULL_MARKER_RE.search(before_first_num.lower()) is not None


def find_explicit_blank_result_test_keys(text: str) -> set[str]:
    found: set[str] = set()

    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    flattened = re.sub(r"\s+", " ", text or "").strip()

    for source in lines + [flattened]:
        if not source:
            continue

        source = clean_ocr_text_for_rows(source)

        for alias in sorted(KNOWN_TEST_ALIASES.keys(), key=len, reverse=True):
            alias_pattern = re.escape(alias).replace(r"\-", r"[-\s]?")

            for match in re.finditer(
                rf"(?<![A-Za-z0-9]){alias_pattern}(?![A-Za-z0-9])(?P<after>.{{0,120}})",
                source,
                re.IGNORECASE,
            ):
                after = match.group("after") or ""

                next_positions = []

                for other_alias in KNOWN_TEST_ALIASES.keys():
                    if other_alias == alias:
                        continue

                    other_pattern = re.escape(other_alias).replace(r"\-", r"[-\s]?")
                    other_match = re.search(
                        rf"(?<![A-Za-z0-9]){other_pattern}(?![A-Za-z0-9])",
                        after,
                        re.IGNORECASE,
                    )

                    if other_match:
                        next_positions.append(other_match.start())

                if next_positions:
                    after = after[: min(next_positions)]

                if segment_has_null_before_first_number(after):
                    found |= token_identity_keys(alias)

    return found


def plausible_reference_range(low: str | None, high: str | None) -> bool:
    low_f = to_float(low)
    high_f = to_float(high)

    if low_f is None or high_f is None:
        return False

    if high_f < low_f:
        return False

    if high_f == low_f:
        return False

    return True


def extract_unit_after_numbers(segment: str, consumed_number_count: int) -> str | None:
    matches = list(NUMBER_RE.finditer(segment or ""))

    if len(matches) < consumed_number_count:
        return None

    tail = segment[matches[consumed_number_count - 1].end() :]

    unit_match = re.search(
        r"(10\^?\d+\s*/?\s*[uµμ]?[lL]|10\d+\s*/?\s*[uµμ]?[lL]|[%]|[A-Za-zµμ]+(?:/[A-Za-zµμ]+)?)",
        tail,
    )

    if not unit_match:
        return None

    unit = unit_match.group(1).strip()

    if looks_like_unit(unit):
        return unit

    return None


def parse_line_for_lab(line: str) -> dict | None:
    if should_skip_line(line):
        return None

    cleaned_line = clean_ocr_text_for_rows(line)
    test_key, _start, end = find_test_key_in_line(cleaned_line)

    if not test_key:
        return None

    segment = cleaned_line[end:]

    if segment_has_null_before_first_number(segment):
        numbers = NUMBER_RE.findall(segment)
        reference_range = None

        if len(numbers) >= 2:
            low = numbers[-2]
            high = numbers[-1]

            if plausible_reference_range(low, high):
                reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"

        unit = None

        for token in re.findall(r"[A-Za-zµμ/%^0-9]+", segment):
            if looks_like_unit(token):
                unit = token
                break

        if not unit:
            if test_key.endswith("%"):
                unit = "%"
            elif test_key.endswith("#"):
                unit = "10^3/uL"

        return build_nil_result(test_key, reference_range=reference_range, unit=unit, confidence=0.99)

    numbers = NUMBER_RE.findall(segment)

    if len(numbers) < 3:
        if test_key in BLANK_PRONE_TESTS and len(numbers) <= 2:
            reference_range = None

            if len(numbers) >= 2:
                low = numbers[-2]
                high = numbers[-1]

                if plausible_reference_range(low, high):
                    reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"

            return build_nil_result(test_key, reference_range=reference_range, unit=None, confidence=0.92)

        return None

    value, low, high, consumed = choose_value_low_high(numbers)

    if value is None or low is None or high is None:
        return None

    if not plausible_reference_range(low, high):
        if test_key in BLANK_PRONE_TESTS:
            return build_nil_result(test_key, reference_range=None, unit=None, confidence=0.9)

        reference_range = None
    else:
        reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"

    unit = extract_unit_after_numbers(segment, consumed)

    if not unit:
        if test_key.endswith("%"):
            unit = "%"
        elif test_key.endswith("#"):
            unit = "10^3/uL"

    flag = extract_flag_from_line(line, value, reference_range)

    return build_lab_result(
        raw_test_name=test_key,
        value=value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.88,
    )


def parse_generic_table_rows(text: str) -> list[dict]:
    labs: list[dict] = []
    seen: set[str] = set()

    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]

    for line in lines:
        parsed = parse_line_for_lab(line)

        if not parsed:
            continue

        key = parsed.get("canonical_name") or parsed.get("display_name") or parsed.get("raw_test_name")

        if not key:
            continue

        key = str(key).lower()

        if key in seen:
            continue

        seen.add(key)
        labs.append(parsed)

    return labs


def tokenize_ocr_text(text: str) -> list[str]:
    cleaned = clean_ocr_text_for_rows(text or "")

    tokens = re.findall(
        r"[A-Za-zĂÂÎȘȚăâîșț]+[#%]?"
        r"|[A-Z]+-[A-Z]+[#%]?"
        r"|[-+]?\d+(?:[.,]\d+)?"
        r"|[-_]{2,}"
        r"|10\^?\d+/?[uµμ]?[lL]?"
        r"|[%]"
        r"|[A-Za-zµμ/%^0-9]+",
        cleaned,
    )

    return [token.strip() for token in tokens if token.strip()]


def parse_token_stream_rows(text: str) -> list[dict]:
    labs: list[dict] = []
    seen: set[str] = set()
    tokens = tokenize_ocr_text(text)

    i = 0

    while i < len(tokens):
        token = tokens[i]
        test_key = normalize_test_token(token)

        if test_key == "RDW" and i + 1 < len(tokens):
            next_token = normalize_test_token(tokens[i + 1])
            if next_token in {"SD", "CV"}:
                test_key = f"RDW-{next_token}"
                i += 1

        if test_key == "P" and i + 1 < len(tokens):
            next_token = normalize_test_token(tokens[i + 1])
            if next_token == "LCR":
                test_key = "P-LCR"
                i += 1

        if test_key not in KNOWN_TEST_ALIASES:
            i += 1
            continue

        lookahead = tokens[i + 1 : i + 16]

        first_meaningful = None

        for candidate in lookahead:
            if candidate in ARROW_HIGH_MARKERS or candidate in ARROW_LOW_MARKERS:
                continue

            first_meaningful = candidate
            break

        if is_null_result_token(first_meaningful):
            result = build_nil_result(test_key, confidence=0.95)
            key = result.get("canonical_name") or result.get("display_name") or test_key
            key = str(key).lower()

            if key not in seen:
                seen.add(key)
                labs.append(result)

            i += 1
            continue

        bounded = []

        for candidate in lookahead:
            candidate_key = normalize_test_token(candidate)

            if candidate_key in KNOWN_TEST_ALIASES:
                break

            bounded.append(candidate)

        numbers = [candidate for candidate in bounded if is_number_token(candidate)]

        if len(numbers) < 3:
            if test_key in BLANK_PRONE_TESTS and len(numbers) <= 2:
                reference_range = None

                if len(numbers) >= 2 and plausible_reference_range(numbers[-2], numbers[-1]):
                    reference_range = f"{normalize_decimal(numbers[-2])} - {normalize_decimal(numbers[-1])}"

                result = build_nil_result(test_key, reference_range=reference_range, confidence=0.84)
                key = result.get("canonical_name") or result.get("display_name") or test_key
                key = str(key).lower()

                if key not in seen:
                    seen.add(key)
                    labs.append(result)

            i += 1
            continue

        value, low, high, _consumed = choose_value_low_high(numbers)

        if value is None or low is None or high is None:
            i += 1
            continue

        reference_range = None

        if plausible_reference_range(low, high):
            reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"

        unit = None

        for candidate in bounded:
            if looks_like_unit(candidate):
                unit = candidate
                break

        if not unit:
            if test_key.endswith("%"):
                unit = "%"
            elif test_key.endswith("#"):
                unit = "10^3/uL"

        local_text = " ".join(bounded)
        flag = extract_flag_from_line(local_text, value, reference_range)

        result = build_lab_result(
            raw_test_name=test_key,
            value=value,
            flag=flag,
            reference_range=reference_range,
            unit=unit,
            confidence=0.7,
        )

        key = result.get("canonical_name") or result.get("display_name") or test_key
        key = str(key).lower()

        if key not in seen:
            seen.add(key)
            labs.append(result)

        i += 1

    return labs


def parse_wrapped_table_rows(text: str) -> list[dict]:
    labs: list[dict] = []
    seen: set[str] = set()

    lines = [clean_ocr_text_for_rows(line.strip()) for line in (text or "").splitlines() if line.strip()]

    for idx, line in enumerate(lines):
        test_key = normalize_test_token(line)

        if test_key not in KNOWN_TEST_ALIASES:
            continue

        following = " ".join(lines[idx + 1 : idx + 6])

        if segment_has_null_before_first_number(following):
            result = build_nil_result(test_key, confidence=0.9)
        else:
            numbers = NUMBER_RE.findall(following)

            if len(numbers) < 3:
                continue

            value, low, high, _consumed = choose_value_low_high(numbers)

            if value is None or low is None or high is None:
                continue

            reference_range = None

            if plausible_reference_range(low, high):
                reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"

            unit = None

            for token in re.findall(r"[A-Za-zµμ/%^0-9]+", following):
                if looks_like_unit(token):
                    unit = token
                    break

            if not unit:
                if test_key.endswith("%"):
                    unit = "%"
                elif test_key.endswith("#"):
                    unit = "10^3/uL"

            result = build_lab_result(
                raw_test_name=test_key,
                value=value,
                flag=extract_flag_from_line(following, value, reference_range),
                reference_range=reference_range,
                unit=unit,
                confidence=0.75,
            )

        key = result.get("canonical_name") or result.get("display_name") or test_key
        key = str(key).lower()

        if key not in seen:
            seen.add(key)
            labs.append(result)

    return labs


def extract_known_inline_labs(text: str) -> list[dict]:
    labs: list[dict] = []
    seen: set[str] = set()

    inline_patterns = [
        (
            r"\b(Haemoglobin|Hemoglobin|Hemoglobina|Hemoglobină|HGB|Hb)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?",
            "Hemoglobin",
        ),
        (
            r"\b(Leucocite|Leukocite|WBC|White Blood Cells)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?",
            "White Blood Cells",
        ),
        (
            r"\b(Eritrocite|RBC|Red Blood Cells)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?",
            "Red Blood Cell Count",
        ),
        (
            r"\b(Hematocrit|Hematocritul|HCT)\b\s*[:\-]?\s*([\d.,]+)\s*(%)?",
            "Hematocrit",
        ),
        (
            r"\b(Platelets|Trombocite|PLT)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?",
            "Platelets",
        ),
        (
            r"\b(Creatinine|Creatinina|Creatinină)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?",
            "Creatinine",
        ),
        (
            r"\b(Glucose|Glucoza|Glicemie|Glicemia)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?",
            "Glucose",
        ),
        (
            r"\b(TSH)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?",
            "TSH",
        ),
        (
            r"\b(CRP|Proteina C reactiva|Proteina C reactivă)\b\s*[:\-]?\s*([\d.,]+)\s*([\w/%µμ^]+)?",
            "CRP",
        ),
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
                confidence=0.55,
            )

            key = result.get("canonical_name") or result.get("display_name") or raw_name
            key = str(key).lower()

            if key in seen:
                continue

            seen.add(key)
            labs.append(result)

    return labs


def lab_score(lab: dict) -> float:
    score = float(lab.get("confidence") or 0)

    if lab.get("value") is not None:
        score += 0.25

    if lab.get("reference_range"):
        score += 0.12

    if lab.get("unit"):
        score += 0.06

    if lab.get("value") is None:
        score += 0.35

    return score


def merge_labs(*lab_lists: list[dict]) -> list[dict]:
    merged: list[dict] = []

    for lab_list in lab_lists:
        for lab in lab_list:
            keys = lab_identity_keys(lab)

            if not keys:
                continue

            existing_index = None

            for idx, existing in enumerate(merged):
                if lab_identity_keys(existing) & keys:
                    existing_index = idx
                    break

            if existing_index is None:
                merged.append(lab)
                continue

            existing = merged[existing_index]

            if lab_score(lab) > lab_score(existing):
                merged[existing_index] = lab

    return merged


def force_nil_for_explicit_blank_rows(labs: list[dict], text: str) -> list[dict]:
    blank_keys = find_explicit_blank_result_test_keys(text)

    if not blank_keys:
        return labs

    cleaned = []

    for lab in labs:
        if lab_identity_keys(lab) & blank_keys:
            lab = {
                **lab,
                "value": None,
                "flag": None,
                "confidence": max(float(lab.get("confidence") or 0), 0.99),
            }

        cleaned.append(lab)

    return cleaned


def remove_fake_reference_stolen_values(labs: list[dict]) -> list[dict]:
    cleaned = []

    for lab in labs:
        raw_key = normalize_test_token(str(lab.get("raw_test_name") or ""))
        value = to_float(lab.get("value"))
        reference_range = lab.get("reference_range")
        numbers = NUMBER_RE.findall(str(reference_range or ""))

        if raw_key in BLANK_PRONE_TESTS and value is not None and len(numbers) >= 2:
            low = to_float(numbers[0])
            high = to_float(numbers[1])

            if low is not None and high is not None:
                if high < low or (value > 0 and high <= 0):
                    lab = {
                        **lab,
                        "value": None,
                        "flag": None,
                        "reference_range": None,
                        "confidence": 0.99,
                    }

        cleaned.append(lab)

    return cleaned


def parse_bloodwork_text(text: str) -> dict:
    safe_text = text or ""
    metadata = extract_report_metadata(safe_text)

    table_labs = parse_generic_table_rows(safe_text)
    wrapped_labs = parse_wrapped_table_rows(safe_text)
    token_labs = parse_token_stream_rows(safe_text)
    inline_labs = extract_known_inline_labs(safe_text)

    labs = merge_labs(table_labs, wrapped_labs, token_labs, inline_labs)
    labs = force_nil_for_explicit_blank_rows(labs, safe_text)
    labs = remove_fake_reference_stolen_values(labs)

    return {
        "metadata": metadata,
        "labs": labs,
    }