from __future__ import annotations

import re
import unicodedata
from statistics import median
from typing import Any

from app.parsers.bloodwork_parser import (
    KNOWN_TEST_ALIASES,
    build_lab_result,
    build_nil_result,
    clean_text,
    normalize_decimal,
    normalize_test_token,
)


NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")

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

DIFFERENTIAL_PREFIXES = ["NRBC", "NEUT", "LYMPH", "MONO", "EO", "BASO", "IG"]

NO_REFERENCE_KEYS = {
    "NRBC#",
    "NRBC%",
    "IG#",
    "IG%",
}

CBC_KEY_RE = re.compile(
    r"^(WBC|RBC|HGB|HCT|MCV|MCHC|MCH|PLT|RDW[\s\-]?SD|RDW[\s\-]?CV|PDW|MPV|P[\s\-]?LCR|PCT|NRBC[#%]?|NEUT[#%]?|LYMPH[#%]?|MONO[#%]?|EO[#%]?|BASO[#%]?|IG[#%]?)$",
    re.IGNORECASE,
)

UNIT_PATTERNS: list[tuple[str, str]] = [
    (r"10\s*[\^]?\s*3\s*/?\s*u?l", "10^3/uL"),
    (r"10\s*[\^]?\s*6\s*/?\s*u?l", "10^6/uL"),
    (r"10\s*[\^]?\s*9\s*/?\s*l", "10^9/L"),
    (r"10\s*[\^]?\s*12\s*/?\s*l", "10^12/L"),
    (r"10\s*[\^]?\s*3", "10^3/uL"),
    (r"10\s*[\^]?\s*6", "10^6/uL"),
    (r"\bg\s*/\s*dL\b", "g/dL"),
    (r"\bg\s*/\s*dl\b", "g/dL"),
    (r"\bg\s*/\s*L\b", "g/L"),
    (r"\bmg\s*/\s*dL\b", "mg/dL"),
    (r"\bmg\s*/\s*dl\b", "mg/dL"),
    (r"\bmg\s*/\s*L\b", "mg/L"),
    (r"\bmmol\s*/\s*L\b", "mmol/L"),
    (r"\bumol\s*/\s*L\b", "umol/L"),
    (r"\buIU\s*/\s*mL\b", "uIU/mL"),
    (r"\bmIU\s*/\s*L\b", "mIU/L"),
    (r"\bIU\s*/\s*L\b", "IU/L"),
    (r"\bU\s*/\s*L\b", "U/L"),
    (r"\bfL\b", "fL"),
    (r"\bFL\b", "fL"),
    (r"\bfl\b", "fL"),
    (r"\bpg\b", "pg"),
    (r"%", "%"),
]

DEFAULT_CBC_UNITS: dict[str, str] = {
    "WBC": "10^3/uL",
    "RBC": "10^6/uL",
    "HGB": "g/dL",
    "HCT": "%",
    "MCV": "fL",
    "MCH": "pg",
    "MCHC": "g/dL",
    "PLT": "10^3/uL",
    "RDW-SD": "fL",
    "RDW-CV": "%",
    "PDW": "fL",
    "MPV": "fL",
    "P-LCR": "%",
    "PCT": "%",
    "NRBC#": "10^3/uL",
    "NRBC%": "%",
    "NEUT#": "10^3/uL",
    "NEUT%": "%",
    "LYMPH#": "10^3/uL",
    "LYMPH%": "%",
    "MONO#": "10^3/uL",
    "MONO%": "%",
    "EO#": "10^3/uL",
    "EO%": "%",
    "BASO#": "10^3/uL",
    "BASO%": "%",
    "IG#": "10^3/uL",
    "IG%": "%",
}

NULL_TEXT = {
    "",
    "-",
    "--",
    "---",
    "----",
    "—",
    "–",
    "nil",
    "n/a",
    "na",
    "null",
    "none",
    "absent",
}

HEADER_HINTS_TEST = {
    "denumire",
    "analiza",
    "analiză",
    "test",
    "parameter",
    "parametru",
    "investigatie",
    "investigație",
    "investigation",
}

HEADER_HINTS_RESULT = {
    "rezultat",
    "result",
    "valoare",
    "value",
}

HEADER_HINTS_REFERENCE = {
    "interval",
    "referinta",
    "referință",
    "reference",
    "ref",
    "biologic",
    "biologică",
    "range",
}

HEADER_HINTS_UNIT = {
    "unit",
    "unitate",
    "um",
    "u/m",
}

HEADER_HINTS_FLAG = {
    "flag",
    "status",
    "abnormal",
    "interpretare",
}

STOP_LINE_HINTS = {
    "validat de",
    "lucrat de",
    "frotiu",
    "citomorfologie manual",
    "manual citomorfologie",
    "data validare",
    "parafa",
    "pagina",
    "buletin",
    "biletin",
    "fundeni",
    "telefon",
    "nume:",
    "cnp:",
    "medic:",
    "sectie:",
    "secție:",
    "sex:",
    "varsta:",
    "vârsta:",
    "cod pacient",
    "nr.reg",
    "cod proba",
    "afisat de",
    "afișat de",
    "data eliberarii",
    "data eliberării",
    "http",
    "192.168",
}


def norm(value: Any) -> str:
    text = clean_text(value)
    text = unicodedata.normalize("NFKC", text)

    greek_to_latin = str.maketrans(
        {
            "Μ": "M",
            "μ": "u",
            "Ο": "O",
            "ο": "o",
            "Ν": "N",
            "ν": "v",
            "Α": "A",
            "Β": "B",
            "Ε": "E",
            "Ι": "I",
            "Κ": "K",
            "Ρ": "P",
            "Τ": "T",
            "Χ": "X",
        }
    )

    text = text.translate(greek_to_latin)
    text = text.replace("\ufeff", "")
    text = text.replace("\u00a0", " ")
    text = text.replace("µ", "u").replace("μ", "u")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.replace("＃", "#").replace("％", "%")
    text = text.replace("Â·", "·").replace("Â", "")
    text = text.replace("â€™", "'").replace("â€˜", "'")
    text = text.replace("â€œ", '"').replace("â€�", '"')
    text = text.replace("â€“", "-").replace("â€”", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def norm_key(value: str) -> str:
    raw = norm(value).upper()
    raw = raw.replace("＃", "#").replace("％", "%")
    raw = raw.replace(" ", "")
    raw = raw.replace("_", "-")
    raw = raw.replace(".", "")
    raw = raw.replace("–", "-").replace("—", "-")
    raw = raw.replace("0", "O") if re.search(r"[A-Z]", raw) else raw

    raw = raw.replace("RDWSD", "RDW-SD")
    raw = raw.replace("RDWCV", "RDW-CV")
    raw = raw.replace("PLCR", "P-LCR")
    raw = raw.replace("P.LCR", "P-LCR")

    if raw in {"-LCR", "LCR"}:
        return "P-LCR"

    for prefix in DIFFERENTIAL_PREFIXES:
        if raw in {prefix, f"{prefix}#", f"{prefix}%"}:
            return raw

        if raw.startswith(prefix):
            if "#" in raw:
                return f"{prefix}#"
            if "%" in raw:
                return f"{prefix}%"

    key = normalize_test_token(raw)
    key = key.replace("RDWSD", "RDW-SD")
    key = key.replace("RDWCV", "RDW-CV")
    key = key.replace("PLCR", "P-LCR")
    key = key.replace("P LCR", "P-LCR")
    return key


def detect_key(value: Any) -> str | None:
    text = norm(value)

    if not text:
        return None

    compact = norm_key(text)

    if compact in KNOWN_TEST_ALIASES:
        return compact

    if compact in CBC_ORDER:
        return compact

    if CBC_KEY_RE.fullmatch(text):
        return norm_key(text)

    parts = re.split(r"[\s:;|/]+", text)

    for part in parts:
        compact_part = norm_key(part)

        if compact_part in KNOWN_TEST_ALIASES:
            return compact_part

        if compact_part in CBC_ORDER:
            return compact_part

        if CBC_KEY_RE.fullmatch(part):
            return norm_key(part)

    return None


def numbers(value: Any) -> list[str]:
    return NUMBER_RE.findall(norm(value).replace(",", "."))


def clean_number(value: Any) -> str | None:
    cleaned = normalize_decimal(value)

    if cleaned is None:
        return None

    cleaned = cleaned.strip().replace(",", ".")

    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    if cleaned.lower() in NULL_TEXT:
        return None

    if not re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
        found = NUMBER_RE.findall(cleaned)

        if not found:
            return None

        cleaned = found[0].replace(",", ".")

    return cleaned


def safe_float(value: Any) -> float | None:
    cleaned = clean_number(value)

    if cleaned is None:
        return None

    try:
        return float(cleaned)
    except Exception:
        return None


def is_null_value(value: Any) -> bool:
    return norm(value).lower() in NULL_TEXT


def extract_unit(value: Any) -> str | None:
    text = norm(value)

    if not text:
        return None

    for pattern, unit in UNIT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return unit

    return None


def remove_units(value: Any) -> str:
    text = norm(value)

    text = re.sub(r"10\s*\^\s*3\s*/\s*u\s*l", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"10\s*\^\s*6\s*/\s*u\s*l", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"10\s*\^\s*9\s*/\s*l", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"10\s*\^\s*12\s*/\s*l", " ", text, flags=re.IGNORECASE)

    for pattern, _unit in UNIT_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    text = text.replace(",", ".")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def format_number(value: Any) -> str | None:
    cleaned = clean_number(value)

    if cleaned is None:
        return None

    return cleaned


def format_range(low: Any, high: Any) -> str | None:
    low_clean = format_number(low)
    high_clean = format_number(high)

    if low_clean is None or high_clean is None:
        return None

    try:
        low_float = float(low_clean)
        high_float = float(high_clean)
    except Exception:
        return None

    if high_float < low_float:
        low_clean, high_clean = high_clean, low_clean

    return f"{low_clean} - {high_clean}"


def split_fused_range_token(token: str) -> tuple[str, str] | None:
    compact = norm(token)
    compact = remove_units(compact)
    compact = compact.replace(" ", "").replace(",", ".")

    if not compact or "-" in compact:
        return None

    # 3.936.08 -> 3.93 - 6.08
    # 1.566.13 -> 1.56 - 6.13
    # 0.240.82 -> 0.24 - 0.82
    match = re.fullmatch(r"(\d{1,3})\.(\d{2})(\d{1,3})\.(\d{2})", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    # 11.217.5 -> 11.2 - 17.5
    # 34.151.0 -> 34.1 - 51.0
    # 35.146.3 -> 35.1 - 46.3
    # 19.353.1 -> 19.3 - 53.1
    match = re.fullmatch(r"(\d{1,3})\.(\d)(\d{1,3})\.(\d)", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    return None


def extract_reference_range(value: Any) -> str | None:
    text = remove_units(value)
    text = text.replace(",", ".")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")

    if not text:
        return None

    explicit = re.search(
        r"(?<!\d)(-?\d{1,4}(?:\.\d+)?)\s*-\s*(-?\d{1,4}(?:\.\d+)?)(?!\d)",
        text,
    )

    if explicit:
        low = explicit.group(1)
        high = explicit.group(2)

        if high.startswith("-") and not low.startswith("-"):
            high = high[1:]

        return format_range(low, high)

    for token in text.split():
        fused = split_fused_range_token(token)

        if fused:
            return format_range(fused[0], fused[1])

    fused = split_fused_range_token(text)

    if fused:
        return format_range(fused[0], fused[1])

    found = numbers(text)

    if len(found) >= 2 and extract_unit(value):
        return format_range(found[0], found[1])

    return None


def split_reference_and_unit(
    value: Any,
    key: str | None = None,
    allow_default_unit: bool = False,
) -> tuple[str | None, str | None]:
    text = norm(value)

    if not text:
        return None, None

    unit = extract_unit(text)
    reference_range = extract_reference_range(text)

    if allow_default_unit and key and not unit:
        unit = DEFAULT_CBC_UNITS.get(norm_key(key))

    return reference_range, unit


def extract_result(value: Any) -> str | None:
    text = norm(value)

    if is_null_value(text):
        return None

    if extract_reference_range(text):
        return None

    stripped = remove_units(text)

    if not stripped:
        return None

    found = numbers(stripped)

    if len(found) != 1:
        return None

    return clean_number(found[0])


def line_is_result(value: Any) -> bool:
    return extract_result(value) is not None


def line_is_reference(value: Any) -> bool:
    return extract_reference_range(value) is not None


def line_is_unit_only(value: Any) -> bool:
    text = norm(value)

    if not text:
        return False

    if extract_reference_range(text):
        return False

    stripped = remove_units(text)

    if numbers(stripped):
        return False

    return extract_unit(text) is not None


def is_header_or_stop_line(value: Any) -> bool:
    lowered = norm(value).lower()

    if not lowered:
        return True

    exact_headers = {
        "denumire analiza",
        "denumire analiză",
        "rezultat",
        "interval biologic de referinta/um",
        "interval biologic de referință/um",
        "unitate",
        "um",
    }

    if lowered in exact_headers:
        return True

    return any(hint in lowered for hint in STOP_LINE_HINTS)


def infer_lab_flag(value: Any, reference_range: Any) -> str | None:
    value_float = safe_float(value)

    if value_float is None:
        return None

    ref = extract_reference_range(reference_range) or norm(reference_range)

    if not ref:
        return None

    nums = numbers(ref)

    if len(nums) < 2:
        return None

    low = safe_float(nums[0])
    high = safe_float(nums[1])

    if low is None or high is None:
        return None

    if high < low:
        low, high = high, low

    if value_float < low:
        return "Low"

    if value_float > high:
        return "High"

    return "Normal"


def units_compatible(expected: str | None, actual: str | None) -> bool:
    if not expected or not actual:
        return True

    expected_norm = expected.lower().replace(" ", "")
    actual_norm = actual.lower().replace(" ", "")

    aliases = {
        "10^3/ul": {"10^3/ul", "10^9/l"},
        "10^6/ul": {"10^6/ul", "10^12/l"},
        "fl": {"fl"},
        "pg": {"pg"},
        "%": {"%"},
        "g/dl": {"g/dl", "g/l"},
    }

    if expected_norm in aliases:
        return actual_norm in aliases[expected_norm]

    return expected_norm == actual_norm


def reference_compatible_with_key(key: str, reference_text: Any) -> bool:
    key = norm_key(key)

    if key in NO_REFERENCE_KEYS:
        return False

    reference_range, unit = split_reference_and_unit(reference_text, key)

    if not reference_range:
        return False

    expected_unit = DEFAULT_CBC_UNITS.get(key)

    if unit and expected_unit and not units_compatible(expected_unit, unit):
        return False

    if key.endswith("%") and unit and unit != "%":
        return False

    if key.endswith("#") and unit == "%":
        return False

    if expected_unit != "%" and unit == "%":
        return False

    return True


def score_test_cell(value: Any) -> float:
    text = norm(value)
    lowered = text.lower()

    score = 0.0

    if detect_key(text):
        score += 12.0

    for hint in HEADER_HINTS_TEST:
        if hint in lowered:
            score += 5.0

    if any(char.isalpha() for char in text) and not numbers(text):
        score += 1.0

    return score


def score_result_cell(value: Any) -> float:
    text = norm(value)
    lowered = text.lower()

    score = 0.0

    if is_null_value(text):
        score += 2.0

    if line_is_result(text):
        score += 7.0

    for hint in HEADER_HINTS_RESULT:
        if hint in lowered:
            score += 5.0

    if extract_reference_range(text):
        score -= 7.0

    if line_is_unit_only(text):
        score -= 4.0

    if detect_key(text):
        score -= 8.0

    return score


def score_reference_cell(value: Any) -> float:
    text = norm(value)
    lowered = text.lower()

    score = 0.0

    reference_range, unit = split_reference_and_unit(text)

    if reference_range:
        score += 9.0

    if unit:
        score += 1.5

    for hint in HEADER_HINTS_REFERENCE:
        if hint in lowered:
            score += 5.0

    if detect_key(text):
        score -= 8.0

    return score


def score_unit_cell(value: Any) -> float:
    text = norm(value)
    lowered = text.lower()

    reference_range, unit = split_reference_and_unit(text)

    score = 0.0

    if unit:
        score += 7.0

    for hint in HEADER_HINTS_UNIT:
        if hint in lowered:
            score += 5.0

    if reference_range:
        score -= 2.0

    if detect_key(text):
        score -= 6.0

    return score


def score_flag_cell(value: Any) -> float:
    text = norm(value)
    lowered = text.lower()

    score = 0.0

    for hint in HEADER_HINTS_FLAG:
        if hint in lowered:
            score += 5.0

    if lowered in {"h", "high", "l", "low", "normal", "crescut", "scazut", "scăzut"}:
        score += 5.0

    return score


def make_lab_row(
    key: str,
    result_text: str | None,
    reference_text: str | None,
    unit_text: str | None,
    confidence: float,
    flag_text: str | None = None,
) -> dict | None:
    key = norm_key(key)
    value = extract_result(result_text or "")

    reference_range, unit_from_reference = split_reference_and_unit(reference_text or "", key)
    _unit_ref_from_unit_cell, unit_from_unit_cell = split_reference_and_unit(unit_text or "", key)

    if key in NO_REFERENCE_KEYS:
        reference_range = None
    elif reference_text and not reference_compatible_with_key(key, reference_text):
        reference_range = None
        unit_from_reference = None

    unit = (
        unit_from_unit_cell
        or unit_from_reference
        or extract_unit(unit_text or "")
        or extract_unit(reference_text or "")
        or extract_unit(result_text or "")
        or DEFAULT_CBC_UNITS.get(key)
    )

    if value is None:
        return build_nil_result(
            raw_test_name=key,
            reference_range=reference_range,
            unit=unit,
            confidence=confidence,
        )

    explicit_flag = None

    if flag_text:
        lowered = norm(flag_text).lower()

        if lowered in {"high", "h", "crescut", "mare"}:
            explicit_flag = "High"
        elif lowered in {"low", "l", "scazut", "scăzut", "mic"}:
            explicit_flag = "Low"
        elif lowered in {"normal", "ok"}:
            explicit_flag = "Normal"

    flag = explicit_flag or (infer_lab_flag(value, reference_range) if reference_range else None)

    return build_lab_result(
        raw_test_name=key,
        value=value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=confidence,
    )


def collect_lines_from_blob(blob: str, marker: str | None = None) -> list[str]:
    text = blob or ""

    if marker and marker in text:
        text = text.split(marker, 1)[1]
        next_marker = re.search(r"\n--- [A-Z ]+ ---", text)

        if next_marker:
            text = text[: next_marker.start()]

    return [norm(line) for line in text.splitlines() if norm(line)]


def collect_lines_from_extraction(extraction: dict[str, Any], field: str) -> list[str]:
    value = extraction.get(field)

    if isinstance(value, str) and value.strip():
        return collect_lines_from_blob(value)

    extracted_text = extraction.get("extracted_text") or extraction.get("debug_text") or ""

    if not isinstance(extracted_text, str):
        return []

    marker_map = {
        "lines_text": "--- GOOGLE DOCUMENT AI LINES ---",
        "plain_text": "--- GOOGLE DOCUMENT AI PLAIN TEXT ---",
        "tokens_text": "--- GOOGLE DOCUMENT AI TOKENS ---",
    }

    marker = marker_map.get(field)

    if marker:
        return collect_lines_from_blob(extracted_text, marker)

    return collect_lines_from_blob(extracted_text)


def table_row_to_cells(row: dict[str, Any]) -> list[str]:
    cells = row.get("cells", []) or []
    return [norm(cell.get("text") or "") for cell in cells]


def infer_columns_from_table_rows(rows: list[list[str]]) -> dict[str, int]:
    column_count = max((len(row) for row in rows), default=0)

    scores: dict[str, list[float]] = {
        "test": [0.0] * column_count,
        "result": [0.0] * column_count,
        "reference": [0.0] * column_count,
        "unit": [0.0] * column_count,
        "flag": [0.0] * column_count,
    }

    for row in rows:
        for index in range(column_count):
            value = row[index] if index < len(row) else ""

            scores["test"][index] += score_test_cell(value)
            scores["result"][index] += score_result_cell(value)
            scores["reference"][index] += score_reference_cell(value)
            scores["unit"][index] += score_unit_cell(value)
            scores["flag"][index] += score_flag_cell(value)

    chosen: dict[str, int] = {}
    used: set[int] = set()

    for role in ["test", "result", "reference", "unit", "flag"]:
        ranked = sorted(
            range(column_count),
            key=lambda index: scores[role][index],
            reverse=True,
        )

        for index in ranked:
            if scores[role][index] <= 0:
                continue

            if role not in {"unit", "flag"} and index in used:
                continue

            chosen[role] = index

            if role not in {"unit", "flag"}:
                used.add(index)

            break

    return chosen


def parse_labs_from_table_rows_dynamic(table_rows: list[list[str]], confidence: float = 0.99) -> list[dict]:
    rows = [[norm(cell) for cell in row] for row in table_rows]
    rows = [row for row in rows if any(row)]

    if not rows:
        return []

    columns = infer_columns_from_table_rows(rows)

    if "test" not in columns:
        return []

    labs: list[dict] = []

    for row in rows:
        test_text = row[columns["test"]] if columns["test"] < len(row) else ""
        key = detect_key(test_text)

        if not key:
            joined = " ".join(row)
            key = detect_key(joined)

        if not key:
            continue

        if is_header_or_stop_line(test_text):
            continue

        result_text = row[columns["result"]] if "result" in columns and columns["result"] < len(row) else ""
        reference_text = row[columns["reference"]] if "reference" in columns and columns["reference"] < len(row) else ""
        unit_text = row[columns["unit"]] if "unit" in columns and columns["unit"] < len(row) else ""
        flag_text = row[columns["flag"]] if "flag" in columns and columns["flag"] < len(row) else ""

        if not result_text:
            for cell in row:
                if line_is_result(cell) or is_null_value(cell):
                    if not detect_key(cell) and not extract_reference_range(cell):
                        result_text = cell
                        break

        if not reference_text and key not in NO_REFERENCE_KEYS:
            for cell in row:
                if reference_compatible_with_key(key, cell):
                    reference_text = cell
                    break

        if not unit_text:
            for cell in row:
                _reference_range, unit = split_reference_and_unit(cell, key)

                if unit:
                    unit_text = cell
                    break

        parsed = make_lab_row(
            key=key,
            result_text=result_text,
            reference_text=reference_text,
            unit_text=unit_text,
            confidence=confidence,
            flag_text=flag_text,
        )

        if parsed:
            labs.append(parsed)

    return labs


def parse_labs_from_google_tables(tables: list[dict[str, Any]]) -> list[dict]:
    labs: list[dict] = []

    for table in tables or []:
        table_rows: list[list[str]] = []

        for row in table.get("rows", []) or []:
            table_rows.append(table_row_to_cells(row))

        labs.extend(parse_labs_from_table_rows_dynamic(table_rows, confidence=0.995))

    return labs


def token_center(token: dict[str, Any]) -> tuple[float, float]:
    left = float(token.get("left") or token.get("x") or 0)
    top = float(token.get("top") or token.get("y") or 0)
    width = float(token.get("width") or 0)
    height = float(token.get("height") or 0)

    return left + width / 2, top + height / 2


def token_has_geometry(token: dict[str, Any]) -> bool:
    return any(token.get(name) is not None for name in ["left", "top", "x", "y"])


def group_tokens_into_rows(tokens: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    usable = [token for token in tokens or [] if token_has_geometry(token) and norm(token.get("text"))]

    ordered = sorted(
        usable,
        key=lambda token: (
            int(token.get("page") or 0),
            float(token.get("top") or token.get("y") or 0),
            float(token.get("left") or token.get("x") or 0),
        ),
    )

    rows: list[list[dict[str, Any]]] = []

    for token in ordered:
        text = norm(token.get("text"))

        if not text:
            continue

        cy = token_center(token)[1]
        height = float(token.get("height") or 8)
        tolerance = max(5.5, height * 0.75)

        placed = False

        for row in rows:
            row_cy = sum(token_center(item)[1] for item in row) / len(row)

            if abs(cy - row_cy) <= tolerance:
                row.append(token)
                placed = True
                break

        if not placed:
            rows.append([token])

    for row in rows:
        row.sort(key=lambda token: float(token.get("left") or token.get("x") or 0))

    return rows


def infer_column_bands_from_token_rows(rows: list[list[dict[str, Any]]]) -> dict[str, float] | None:
    xs: dict[str, list[float]] = {
        "test": [],
        "result": [],
        "reference": [],
        "unit": [],
        "flag": [],
    }

    for row in rows:
        for token in row:
            text = norm(token.get("text"))
            lowered = text.lower()
            cx, _cy = token_center(token)

            if detect_key(text):
                xs["test"].append(cx)
                continue

            if line_is_result(text):
                xs["result"].append(cx)

            reference_range, unit = split_reference_and_unit(text)

            if reference_range:
                xs["reference"].append(cx)

            if unit:
                xs["unit"].append(cx)

            for hint in HEADER_HINTS_TEST:
                if hint in lowered:
                    xs["test"].append(cx)

            for hint in HEADER_HINTS_RESULT:
                if hint in lowered:
                    xs["result"].append(cx)

            for hint in HEADER_HINTS_REFERENCE:
                if hint in lowered:
                    xs["reference"].append(cx)

            for hint in HEADER_HINTS_UNIT:
                if hint in lowered:
                    xs["unit"].append(cx)

            for hint in HEADER_HINTS_FLAG:
                if hint in lowered:
                    xs["flag"].append(cx)

    if not xs["test"]:
        return None

    bands: dict[str, float] = {"test": median(xs["test"])}

    for role in ["result", "reference", "unit", "flag"]:
        if xs[role]:
            bands[role] = median(xs[role])

    if "result" not in bands and "reference" in bands:
        non_test_reference_distance = abs(bands["reference"] - bands["test"])
        bands["result"] = bands["test"] + (non_test_reference_distance / 2)

    return bands


def closest_band_name(x: float, bands: dict[str, float]) -> str:
    return min(bands, key=lambda name: abs(x - bands[name]))


def row_tokens_to_dynamic_cells(row: list[dict[str, Any]], bands: dict[str, float]) -> dict[str, str]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "test": [],
        "result": [],
        "reference": [],
        "unit": [],
        "flag": [],
        "other": [],
    }

    for token in row:
        text = norm(token.get("text"))

        if not text:
            continue

        cx, _cy = token_center(token)
        band = closest_band_name(cx, bands)

        buckets.setdefault(band, []).append(token)

    cells: dict[str, str] = {}

    for name, bucket_tokens in buckets.items():
        bucket_tokens.sort(key=lambda token: float(token.get("left") or token.get("x") or 0))
        cells[name] = " ".join(norm(token.get("text")) for token in bucket_tokens if norm(token.get("text"))).strip()

    return cells


def parse_token_row_dynamic(row: list[dict[str, Any]], bands: dict[str, float]) -> dict | None:
    cells = row_tokens_to_dynamic_cells(row, bands)
    joined = " ".join(value for value in cells.values() if value)

    if not joined:
        return None

    lowered = joined.lower()

    if "hemograma" in lowered or "denumire" in lowered or "rezultat" in lowered:
        return None

    key = detect_key(cells.get("test") or "")

    if not key:
        for value in cells.values():
            detected = detect_key(value)

            if detected:
                key = detected
                break

    if not key:
        key = detect_key(joined)

    if not key:
        return None

    result_text = cells.get("result") or ""
    reference_text = cells.get("reference") or ""
    unit_text = cells.get("unit") or ""
    flag_text = cells.get("flag") or ""

    if not result_text:
        for value in cells.values():
            if line_is_result(value) or is_null_value(value):
                if not detect_key(value) and not extract_reference_range(value):
                    result_text = value
                    break

    if not reference_text and key not in NO_REFERENCE_KEYS:
        for value in cells.values():
            if reference_compatible_with_key(key, value):
                reference_text = value
                break

    if not unit_text:
        for value in cells.values():
            _reference_range, unit = split_reference_and_unit(value, key)

            if unit:
                unit_text = value
                break

    return make_lab_row(
        key=key,
        result_text=result_text,
        reference_text=reference_text,
        unit_text=unit_text,
        confidence=0.965,
        flag_text=flag_text,
    )


def parse_labs_from_token_coordinates(words: list[dict[str, Any]]) -> list[dict]:
    rows = group_tokens_into_rows(words or [])
    bands = infer_column_bands_from_token_rows(rows)

    if not bands:
        return []

    labs: list[dict] = []

    for row in rows:
        parsed = parse_token_row_dynamic(row, bands)

        if parsed:
            labs.append(parsed)

    return labs


def nearby_lines_until_key(
    lines: list[str],
    index: int,
    direction: int,
    limit: int = 5,
) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    cursor = index + direction
    distance = 1

    while 0 <= cursor < len(lines) and distance <= limit:
        line = lines[cursor]

        if detect_key(line):
            break

        if is_header_or_stop_line(line):
            cursor += direction
            distance += 1
            continue

        found.append((distance, line))
        cursor += direction
        distance += 1

    return found


def nearest_result_around_key(lines: list[str], index: int) -> str | None:
    candidates: list[tuple[float, str]] = []

    # Only look forward for result values.
    # Looking backward can steal the previous test's result when the current row is blank.
    for distance, line in nearby_lines_until_key(lines, index, direction=1, limit=5):
        if line_is_result(line) or is_null_value(line):
            candidates.append((distance, line))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def nearest_reference_around_key(lines: list[str], index: int, key: str) -> str | None:
    if norm_key(key) in NO_REFERENCE_KEYS:
        return None

    candidates: list[tuple[float, str]] = []

    # Backward gets a slight preference because Fundeni/Hippocrate often emits:
    # reference, key, value.
    for distance, line in nearby_lines_until_key(lines, index, direction=-1, limit=5):
        if reference_compatible_with_key(key, line):
            candidates.append((distance, line))

    for distance, line in nearby_lines_until_key(lines, index, direction=1, limit=5):
        if reference_compatible_with_key(key, line):
            candidates.append((distance + 0.25, line))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def nearest_unit_around_key(lines: list[str], index: int, key: str) -> str | None:
    candidates: list[tuple[float, str]] = []

    for distance, line in nearby_lines_until_key(lines, index, direction=-1, limit=5):
        _reference_range, unit = split_reference_and_unit(line, key)

        if unit:
            candidates.append((distance, line))

    for distance, line in nearby_lines_until_key(lines, index, direction=1, limit=5):
        _reference_range, unit = split_reference_and_unit(line, key)

        if unit:
            candidates.append((distance + 0.15, line))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def parse_labs_from_ordered_lines(lines: list[str], confidence: float = 0.935) -> list[dict]:
    labs: list[dict] = []

    for index, line in enumerate(lines):
        key = detect_key(line)

        if not key:
            continue

        if is_header_or_stop_line(line):
            continue

        result_text = nearest_result_around_key(lines, index)
        reference_text = nearest_reference_around_key(lines, index, key)
        unit_text = nearest_unit_around_key(lines, index, key)

        parsed = make_lab_row(
            key=key,
            result_text=result_text,
            reference_text=reference_text,
            unit_text=unit_text,
            confidence=confidence,
        )

        if parsed:
            labs.append(parsed)

    return labs


def parse_labs_from_extraction_lines(extraction: dict[str, Any]) -> list[dict]:
    lines = collect_lines_from_extraction(extraction, "lines_text")

    if not lines:
        lines = collect_lines_from_extraction(extraction, "plain_text")

    if not lines:
        lines = collect_lines_from_extraction(extraction, "text")

    return parse_labs_from_ordered_lines(lines, confidence=0.935)


def parse_labs_from_text_lines(text: str) -> list[dict]:
    return parse_labs_from_ordered_lines(collect_lines_from_blob(text or ""), confidence=0.70)


def lab_key(row: dict) -> str:
    key = (
        row.get("raw_test_name")
        or row.get("canonical_name")
        or row.get("display_name")
        or ""
    )

    return norm_key(str(key)).lower()


def row_reference_compatible(row: dict) -> bool:
    key = norm_key(str(row.get("raw_test_name") or ""))

    if not key:
        return False

    reference_range = row.get("reference_range")

    if key in NO_REFERENCE_KEYS:
        return reference_range is None

    if not reference_range:
        return True

    unit = row.get("unit")
    expected = DEFAULT_CBC_UNITS.get(key)

    return units_compatible(expected, unit)


def quality_score(row: dict) -> float:
    score = float(row.get("confidence") or 0)

    if row.get("value") is not None:
        score += 0.8

    if row.get("reference_range"):
        score += 0.55

    if row.get("unit"):
        score += 0.2

    if row_reference_compatible(row):
        score += 0.25
    else:
        score -= 1.0

    return score


def clean_final_row(row: dict) -> dict:
    cleaned = dict(row)
    key = norm_key(str(cleaned.get("raw_test_name") or ""))

    if key in NO_REFERENCE_KEYS:
        cleaned["reference_range"] = None
        cleaned["flag"] = None
        cleaned["unit"] = cleaned.get("unit") or DEFAULT_CBC_UNITS.get(key)

    if not cleaned.get("reference_range"):
        cleaned["flag"] = None

    return cleaned


def order_labs(labs_by_key: dict[str, dict]) -> list[dict]:
    ordered: list[dict] = []

    for key in CBC_ORDER:
        normalized = norm_key(key).lower()

        if normalized in labs_by_key:
            ordered.append(labs_by_key.pop(normalized))

    ordered.extend(labs_by_key.values())
    return ordered


def merge_lab_candidates(candidate_groups: list[list[dict]]) -> list[dict]:
    labs_by_key: dict[str, dict] = {}

    for group in candidate_groups:
        for row in group:
            key = lab_key(row)

            if not key:
                continue

            cleaned = clean_final_row(row)

            if key not in labs_by_key:
                labs_by_key[key] = cleaned
                continue

            if quality_score(cleaned) > quality_score(labs_by_key[key]):
                labs_by_key[key] = cleaned

    return order_labs(labs_by_key)


def parse_labs_from_google_extraction(extraction: dict[str, Any]) -> list[dict]:
    table_labs = parse_labs_from_google_tables(extraction.get("tables") or [])

    # Main fallback for scanned / weird PDFs: rebuild the visual table from word coordinates.
    token_labs = parse_labs_from_token_coordinates(extraction.get("words") or [])

    # Safer text fallback: looks both before and after each detected test key.
    line_labs = parse_labs_from_extraction_lines(extraction)

    # Lowest-confidence fallbacks.
    plain_labs = parse_labs_from_text_lines(extraction.get("plain_text") or "")
    text_labs = parse_labs_from_text_lines(extraction.get("text") or "")

    return merge_lab_candidates(
        [
            plain_labs,
            text_labs,
            line_labs,
            token_labs,
            table_labs,
        ]
    )