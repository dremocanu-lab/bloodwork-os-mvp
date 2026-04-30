from __future__ import annotations

import re
from statistics import median
from typing import Any

from app.parsers.bloodwork_parser import (
    KNOWN_TEST_ALIASES,
    build_lab_result,
    build_nil_result,
    clean_text,
    infer_flag,
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

CBC_DISPLAY_NAMES = {
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

EXPECTED_UNITS = {
    "WBC": {"10^3/uL", "10^9/L"},
    "RBC": {"10^6/uL", "10^12/L"},
    "HGB": {"g/dL", "g/L"},
    "HCT": {"%"},
    "MCV": {"fL"},
    "MCH": {"pg"},
    "MCHC": {"g/dL", "g/L"},
    "PLT": {"10^3/uL", "10^9/L"},
    "RDW-SD": {"fL"},
    "RDW-CV": {"%"},
    "PDW": {"fL"},
    "MPV": {"fL"},
    "P-LCR": {"%"},
    "PCT": {"%"},
    "NRBC#": {"10^3/uL", "10^9/L"},
    "NRBC%": {"%"},
    "NEUT#": {"10^3/uL", "10^9/L"},
    "NEUT%": {"%"},
    "LYMPH#": {"10^3/uL", "10^9/L"},
    "LYMPH%": {"%"},
    "MONO#": {"10^3/uL", "10^9/L"},
    "MONO%": {"%"},
    "EO#": {"10^3/uL", "10^9/L"},
    "EO%": {"%"},
    "BASO#": {"10^3/uL", "10^9/L"},
    "BASO%": {"%"},
    "IG#": {"10^3/uL", "10^9/L"},
    "IG%": {"%"},
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
}

HEADER_HINTS_UNIT = {
    "unit",
    "unitate",
    "um",
    "u/m",
}


def norm(value: Any) -> str:
    text = clean_text(value)
    text = text.replace("\ufeff", "")
    text = text.replace("\u00a0", " ")
    text = text.replace("µ", "u").replace("μ", "u")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.replace("＃", "#").replace("％", "%")
    text = text.replace("Â", "")
    text = text.replace("â€", "")
    text = text.replace("�", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def norm_key(value: str) -> str:
    raw = norm(value).upper()
    raw = raw.replace("＃", "#").replace("％", "%")
    raw = raw.replace(" ", "")
    raw = raw.replace("_", "-")
    raw = raw.replace("–", "-").replace("—", "-")

    # OCR sometimes reads MONO as M0NO / MON0.
    # Only fix MONO-like tokens so we don't corrupt real numeric values.
    if raw.startswith(("M0N", "MON0", "M0NO")):
        raw = raw.replace("0", "O")

    raw = raw.replace("RDWSD", "RDW-SD")
    raw = raw.replace("RDWCV", "RDW-CV")
    raw = raw.replace("PLCR", "P-LCR")
    raw = raw.replace("P.LCR", "P-LCR")

    differential_prefixes = ["NRBC", "NEUT", "LYMPH", "MONO", "EO", "BASO", "IG"]

    for prefix in differential_prefixes:
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

    cleaned = cleaned.strip()

    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    if cleaned.lower() in NULL_TEXT:
        return None

    if cleaned in {"+", "-", ".", "+.", "-."}:
        return None

    return cleaned


def is_null_value(value: Any) -> bool:
    return norm(value).lower() in NULL_TEXT


def float_or_none(value: Any) -> float | None:
    cleaned = clean_number(value)

    if cleaned is None:
        return None

    try:
        return float(cleaned)
    except Exception:
        return None


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

    for pattern, _unit in UNIT_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def format_range(low: Any, high: Any) -> str | None:
    low_clean = clean_number(low)
    high_clean = clean_number(high)

    if low_clean is None or high_clean is None:
        return None

    low_float = float_or_none(low_clean)
    high_float = float_or_none(high_clean)

    if low_float is None or high_float is None:
        return None

    if high_float < low_float:
        low_clean, high_clean = high_clean, low_clean

    return f"{low_clean} - {high_clean}"


def split_fused_range_token(token: str) -> tuple[str, str] | None:
    compact = norm(token).replace(" ", "").replace(",", ".")
    compact = re.sub(r"[^0-9.\-]", "", compact)

    if not compact or "-" not in compact or "." not in compact:
        return None

    # 3.9810-00 -> 3.98 - 10.00
    # 3.9310-00 -> 3.93 - 10.00
    match = re.search(r"(\d{1,3})\.(\d{2})(\d{2})-(\d{2})", compact)
    if match:
        low = f"{match.group(1)}.{match.group(2)}"
        high = f"{match.group(3)}.{match.group(4)}"
        return low, high

    # 3.936-08 -> 3.93 - 6.08
    # 1.183-74 -> 1.18 - 3.74
    # 0.244-82 -> 0.24 - 4.82
    match = re.search(r"(\d{1,3})\.(\d{2})(\d)-(\d{2})", compact)
    if match:
        low = f"{match.group(1)}.{match.group(2)}"
        high = f"{match.group(3)}.{match.group(4)}"
        return low, high

    # 34.151-0 -> 34.1 - 51.0
    # 35.146-3 -> 35.1 - 46.3
    # 11.614-4 -> 11.6 - 14.4
    # 19.353-1 -> 19.3 - 53.1
    match = re.search(r"(\d{1,3})\.(\d)(\d{2})-(\d)", compact)
    if match:
        low = f"{match.group(1)}.{match.group(2)}"
        high = f"{match.group(3)}.{match.group(4)}"
        return low, high

    return None


def repair_malformed_reference_range(reference_range: str | None, source_text: Any = "") -> str | None:
    raw = norm(source_text)

    raw_repaired = split_fused_range_token(raw)
    if raw_repaired:
        return format_range(raw_repaired[0], raw_repaired[1])

    if not reference_range:
        return None

    text = norm(reference_range).replace(",", ".")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")

    # 0 - 34.151 -> 34.1 - 51.0
    # 3 - 35.146 -> 35.1 - 46.3
    # 4 - 11.614 -> 11.6 - 14.4
    # 1 - 19.353 -> 19.3 - 53.1
    match = re.fullmatch(r"(\d)\s*-\s*(\d{1,3})\.(\d)(\d{2})", text)
    if match:
        trailing_decimal = match.group(1)
        low_whole = match.group(2)
        low_decimal = match.group(3)
        high_whole = match.group(4)

        low = f"{low_whole}.{low_decimal}"
        high = f"{high_whole}.{trailing_decimal}"

        return format_range(low, high)

    # General stolen-decimal repair:
    # 3.9 - 8.10 -> 3.98 - 10.00
    # This is not WBC-specific. It catches the second low decimal digit
    # being pulled into the high-side number.
    match = re.fullmatch(r"(\d{1,3})\.(\d)\s*-\s*(\d)\.(\d{2})", text)
    if match:
        low_whole = match.group(1)
        low_first_decimal = match.group(2)
        stolen_low_second_decimal = match.group(3)
        high_digits = match.group(4)

        if high_digits in {"10", "00"}:
            low = f"{low_whole}.{low_first_decimal}{stolen_low_second_decimal}"

            if high_digits == "10":
                return format_range(low, "10.00")

            if high_digits == "00":
                return format_range(low, "0.00")

    return reference_range

def extract_reference_range(value: Any) -> str | None:
    raw_text = norm(value).replace(",", ".")
    raw_text = raw_text.replace("–", "-").replace("—", "-").replace("−", "-")

    raw_repaired = split_fused_range_token(raw_text)
    if raw_repaired:
        return format_range(raw_repaired[0], raw_repaired[1])

    text = remove_units(raw_text).replace(",", ".")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")

    compact_for_repair = re.sub(r"[^0-9.\-]", "", text)
    compact_repaired = split_fused_range_token(compact_for_repair)

    if compact_repaired:
        return format_range(compact_repaired[0], compact_repaired[1])

    for token in text.split():
        repaired = split_fused_range_token(token)

        if repaired:
            return format_range(repaired[0], repaired[1])

    explicit = re.search(
        r"(?<!\d)(-?\d{1,4}(?:\.\d+)?)\s*-\s*(-?\d{1,4}(?:\.\d+)?)(?!\d)",
        text,
    )

    if explicit:
        low = explicit.group(1)
        high = explicit.group(2)

        if high.startswith("-") and not low.startswith("-"):
            high = high[1:]

        return repair_malformed_reference_range(format_range(low, high), raw_text)

    found = numbers(text)
    filtered: list[str] = []

    for item in found:
        if item in {"10", "3", "6", "9", "12"} and re.search(
            r"10\s*[\^]?\s*(3|6|9|12)",
            raw_text,
            re.IGNORECASE,
        ):
            continue

        filtered.append(item)

    if len(filtered) >= 2:
        return repair_malformed_reference_range(format_range(filtered[0], filtered[1]), raw_text)

    return None


def split_reference_and_unit(value: Any) -> tuple[str | None, str | None]:
    text = norm(value)

    if not text:
        return None, None

    unit = extract_unit(text)
    reference_text = remove_units(text)
    reference_range = extract_reference_range(reference_text)
    reference_range = repair_malformed_reference_range(reference_range, text)

    return reference_range, unit


def extract_result(value: Any) -> str | None:
    text = norm(value)

    if is_null_value(text):
        return None

    if extract_unit(text) and len(numbers(remove_units(text))) == 0:
        return None

    if extract_reference_range(text):
        return None

    found = numbers(text)

    if len(found) != 1:
        return None

    return clean_number(found[0])


def cell_has_only_one_result_number(value: Any) -> bool:
    text = remove_units(value)
    found = numbers(text)

    if len(found) != 1:
        return False

    if extract_reference_range(text):
        return False

    return True


def score_test_cell(value: Any) -> float:
    text = norm(value)
    lowered = text.lower()

    score = 0.0

    if detect_key(text):
        score += 10.0

    for hint in HEADER_HINTS_TEST:
        if hint in lowered:
            score += 3.0

    if any(char.isalpha() for char in text) and len(numbers(text)) == 0:
        score += 1.0

    return score


def score_result_cell(value: Any) -> float:
    text = norm(value)
    lowered = text.lower()

    score = 0.0

    if is_null_value(text):
        score += 2.0

    if cell_has_only_one_result_number(text):
        score += 6.0

    for hint in HEADER_HINTS_RESULT:
        if hint in lowered:
            score += 3.0

    if extract_reference_range(text):
        score -= 5.0

    if extract_unit(text):
        score -= 1.5

    if detect_key(text):
        score -= 5.0

    return score


def score_reference_cell(value: Any) -> float:
    text = norm(value)
    lowered = text.lower()

    score = 0.0

    reference_range, unit = split_reference_and_unit(text)

    if reference_range:
        score += 8.0

    if unit:
        score += 1.5

    for hint in HEADER_HINTS_REFERENCE:
        if hint in lowered:
            score += 3.0

    if detect_key(text):
        score -= 5.0

    return score


def score_unit_cell(value: Any) -> float:
    text = norm(value)
    lowered = text.lower()

    reference_range, unit = split_reference_and_unit(text)

    score = 0.0

    if unit:
        score += 6.0

    for hint in HEADER_HINTS_UNIT:
        if hint in lowered:
            score += 3.0

    if reference_range:
        score -= 1.0

    return score


def make_lab_row(
    key: str,
    result_text: str | None,
    reference_text: str | None,
    unit_text: str | None,
    confidence: float,
) -> dict | None:
    key = norm_key(key)
    value = extract_result(result_text or "")

    reference_range, unit_from_reference = split_reference_and_unit(reference_text or "")
    reference_range = repair_malformed_reference_range(reference_range, reference_text or "")

    _unit_ref_from_unit_cell, unit_from_unit_cell = split_reference_and_unit(unit_text or "")

    unit = (
        unit_from_unit_cell
        or unit_from_reference
        or extract_unit(unit_text or "")
        or extract_unit(reference_text or "")
        or extract_unit(result_text or "")
    )

    if value is None:
        row = build_nil_result(
            raw_test_name=key,
            reference_range=reference_range,
            unit=unit,
            confidence=confidence,
        )
    else:
        flag = infer_flag(value, reference_range)

        row = build_lab_result(
            raw_test_name=key,
            value=value,
            flag=flag,
            reference_range=reference_range,
            unit=unit,
            confidence=confidence,
        )

    display_name = CBC_DISPLAY_NAMES.get(key)

    if display_name:
        row["raw_test_name"] = key
        row["canonical_name"] = display_name
        row["display_name"] = display_name
        row["category"] = "Hematologie"

    return row


def row_is_plausible(row: dict[str, Any]) -> bool:
    key = detect_key(row.get("raw_test_name"))

    if not key:
        return False

    value = row.get("value")
    unit = row.get("unit")

    if value is None:
        return True

    numeric_value = float_or_none(value)

    if numeric_value is None:
        return False

    expected = EXPECTED_UNITS.get(key)

    if unit and expected and unit not in expected:
        return False

    if key == "RBC" and unit in {"10^3/uL", "10^9/L"}:
        return False

    if key.endswith("%") and unit and unit != "%":
        return False

    if key.endswith("#") and unit == "%":
        return False

    plausible_value_ranges = {
        "WBC": (0.1, 300),
        "RBC": (0.1, 15),
        "HGB": (1, 30),
        "HCT": (1, 80),
        "MCV": (30, 150),
        "MCH": (5, 60),
        "MCHC": (10, 60),
        "PLT": (1, 3000),
        "RDW-SD": (10, 120),
        "RDW-CV": (1, 40),
        "PDW": (1, 40),
        "MPV": (1, 30),
        "P-LCR": (0, 100),
        "PCT": (0, 10),
        "NRBC#": (0, 100),
        "NRBC%": (0, 100),
        "NEUT#": (0, 200),
        "NEUT%": (0, 100),
        "LYMPH#": (0, 200),
        "LYMPH%": (0, 100),
        "MONO#": (0, 200),
        "MONO%": (0, 100),
        "EO#": (0, 200),
        "EO%": (0, 100),
        "BASO#": (0, 200),
        "BASO%": (0, 100),
        "IG#": (0, 200),
        "IG%": (0, 100),
    }

    low_high = plausible_value_ranges.get(key)

    if low_high:
        low, high = low_high

        if numeric_value < low or numeric_value > high:
            return False

    return True


def token_center(token: dict[str, Any]) -> tuple[float, float]:
    left = float(token.get("left") or 0)
    top = float(token.get("top") or 0)
    width = float(token.get("width") or 0)
    height = float(token.get("height") or 0)

    return left + width / 2, top + height / 2


def group_tokens_into_rows(tokens: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    ordered = sorted(
        tokens,
        key=lambda token: (
            int(token.get("page") or 0),
            float(token.get("top") or 0),
            float(token.get("left") or 0),
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
        row.sort(key=lambda token: float(token.get("left") or 0))

    return rows


def infer_column_bands_from_token_rows(rows: list[list[dict[str, Any]]]) -> dict[str, float] | None:
    test_xs: list[float] = []
    result_xs: list[float] = []
    reference_xs: list[float] = []
    unit_xs: list[float] = []

    for row in rows:
        for token in row:
            text = norm(token.get("text"))
            cx, _cy = token_center(token)

            if detect_key(text):
                test_xs.append(cx)
                continue

            reference_range, unit = split_reference_and_unit(text)

            if reference_range:
                reference_xs.append(cx)

            if unit:
                unit_xs.append(cx)

            if cell_has_only_one_result_number(text):
                result_xs.append(cx)

    if not test_xs:
        return None

    bands: dict[str, float] = {"test": median(test_xs)}

    if result_xs:
        bands["result"] = median(result_xs)

    if reference_xs:
        bands["reference"] = median(reference_xs)

    if unit_xs:
        bands["unit"] = median(unit_xs)

    return bands


def closest_band_name(x: float, bands: dict[str, float]) -> str:
    return min(bands, key=lambda name: abs(x - bands[name]))


def row_tokens_to_dynamic_cells(
    row: list[dict[str, Any]],
    bands: dict[str, float],
) -> dict[str, str]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "test": [],
        "result": [],
        "reference": [],
        "unit": [],
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

    for name, tokens in buckets.items():
        tokens.sort(key=lambda token: float(token.get("left") or 0))
        cells[name] = " ".join(norm(token.get("text")) for token in tokens if norm(token.get("text"))).strip()

    return cells


def parse_token_row_dynamic(row: list[dict[str, Any]], bands: dict[str, float]) -> dict | None:
    cells = row_tokens_to_dynamic_cells(row, bands)

    key = detect_key(cells.get("test") or "")

    if not key:
        for value in cells.values():
            detected = detect_key(value)

            if detected:
                key = detected
                break

    if not key:
        return None

    joined = " ".join(cells.values()).lower()

    if "hemograma" in joined or "denumire" in joined or "rezultat" in joined:
        return None

    result_text = cells.get("result") or ""
    reference_text = cells.get("reference") or ""
    unit_text = cells.get("unit") or ""

    if not reference_text:
        for value in cells.values():
            reference_range, _unit = split_reference_and_unit(value)

            if reference_range:
                reference_text = value
                break

    if not result_text:
        for value in cells.values():
            if cell_has_only_one_result_number(value) or is_null_value(value):
                if not extract_reference_range(value) and not detect_key(value):
                    result_text = value
                    break

    if not unit_text:
        for value in cells.values():
            _reference_range, unit = split_reference_and_unit(value)

            if unit:
                unit_text = value
                break

    parsed = make_lab_row(
        key=key,
        result_text=result_text,
        reference_text=reference_text,
        unit_text=unit_text,
        confidence=0.97,
    )

    if parsed and row_is_plausible(parsed):
        return parsed

    return None


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
    }

    for row in rows:
        for index in range(column_count):
            value = row[index] if index < len(row) else ""

            scores["test"][index] += score_test_cell(value)
            scores["result"][index] += score_result_cell(value)
            scores["reference"][index] += score_reference_cell(value)
            scores["unit"][index] += score_unit_cell(value)

    chosen: dict[str, int] = {}
    used: set[int] = set()

    for role in ["test", "reference", "result", "unit"]:
        ranked = sorted(
            range(column_count),
            key=lambda index: scores[role][index],
            reverse=True,
        )

        for index in ranked:
            if scores[role][index] <= 0:
                continue

            if role != "unit" and index in used:
                continue

            chosen[role] = index

            if role != "unit":
                used.add(index)

            break

    return chosen


def parse_labs_from_table_rows_dynamic(table_rows: list[list[str]]) -> list[dict]:
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
            continue

        result_text = row[columns["result"]] if "result" in columns and columns["result"] < len(row) else ""
        reference_text = row[columns["reference"]] if "reference" in columns and columns["reference"] < len(row) else ""
        unit_text = row[columns["unit"]] if "unit" in columns and columns["unit"] < len(row) else ""

        if not result_text:
            for cell in row:
                if cell_has_only_one_result_number(cell) or is_null_value(cell):
                    if not detect_key(cell) and not extract_reference_range(cell):
                        result_text = cell
                        break

        if not reference_text:
            for cell in row:
                reference_range, _unit = split_reference_and_unit(cell)

                if reference_range:
                    reference_text = cell
                    break

        if not unit_text:
            for cell in row:
                _reference_range, unit = split_reference_and_unit(cell)

                if unit:
                    unit_text = cell
                    break

        parsed = make_lab_row(
            key=key,
            result_text=result_text,
            reference_text=reference_text,
            unit_text=unit_text,
            confidence=0.99,
        )

        if parsed and row_is_plausible(parsed):
            labs.append(parsed)

    return labs


def parse_labs_from_google_tables(tables: list[dict[str, Any]]) -> list[dict]:
    labs: list[dict] = []

    for table in tables or []:
        table_rows: list[list[str]] = []

        for row in table.get("rows", []) or []:
            table_rows.append(table_row_to_cells(row))

        labs.extend(parse_labs_from_table_rows_dynamic(table_rows))

    return labs


def parse_labs_from_text_lines(text: str) -> list[dict]:
    labs: list[dict] = []

    for line in (text or "").splitlines():
        line = norm(line)
        parts = line.split()

        if len(parts) < 2:
            continue

        key = None
        key_index = -1

        for index, part in enumerate(parts[:8]):
            detected = detect_key(part)

            if detected:
                key = detected
                key_index = index
                break

        if not key or key_index < 0:
            continue

        result_text = ""
        reference_text = ""
        unit_text = ""

        remaining = parts[key_index + 1 :]

        for offset, part in enumerate(remaining):
            part_index = key_index + 1 + offset

            if cell_has_only_one_result_number(part) or is_null_value(part):
                result_text = part
                reference_text = " ".join(parts[part_index + 1 :])
                unit_text = reference_text
                break

        if not result_text:
            joined_remaining = " ".join(remaining)
            result = extract_result(joined_remaining)

            if result is not None:
                result_text = result
                reference_text = joined_remaining
                unit_text = joined_remaining

        if not result_text:
            continue

        parsed = make_lab_row(
            key=key,
            result_text=result_text,
            reference_text=reference_text,
            unit_text=unit_text,
            confidence=0.65,
        )

        if parsed and row_is_plausible(parsed):
            labs.append(parsed)

    return labs


def lab_key(row: dict) -> str:
    key = (
        row.get("raw_test_name")
        or row.get("canonical_name")
        or row.get("display_name")
        or ""
    )

    return norm_key(str(key)).lower()


def quality_score(row: dict) -> float:
    score = float(row.get("confidence") or 0)

    if row.get("value") is not None:
        score += 0.5

    if row.get("reference_range"):
        score += 0.4

    if row.get("unit"):
        score += 0.2

    if row_is_plausible(row):
        score += 1.0
    else:
        score -= 10.0

    return score


def order_labs(labs_by_key: dict[str, dict]) -> list[dict]:
    ordered: list[dict] = []

    for key in CBC_ORDER:
        normalized = norm_key(key).lower()

        if normalized in labs_by_key:
            ordered.append(labs_by_key.pop(normalized))

    ordered.extend(labs_by_key.values())
    return ordered


def add_missing_text_backfill(
    candidates: list[dict],
    extraction: dict[str, Any],
) -> list[dict]:
    existing_keys = {
        lab_key(row)
        for row in candidates
        if row_is_plausible(row) and lab_key(row)
    }

    text_candidates: list[dict] = []
    text_candidates.extend(parse_labs_from_text_lines(extraction.get("lines_text") or ""))
    text_candidates.extend(parse_labs_from_text_lines(extraction.get("plain_text") or ""))

    for row in text_candidates:
        if not row_is_plausible(row):
            continue

        key = lab_key(row)

        if not key:
            continue

        if key in existing_keys:
            continue

        candidates.append(row)
        existing_keys.add(key)

    return candidates

def cbc_key_regex(target_key: str, strict_symbol: bool = False) -> str:
    """
    Build a regex that works for CBC keys with #/% and OCR variants.

    Important:
    NRBC# can work while MONO# fails because MONO is often read as M0NO/MON0
    or loses its symbol in OCR/table extraction.
    """
    key = norm_key(target_key)

    suffix = ""
    base = key

    if key.endswith("#"):
        base = key[:-1]
        suffix = r"\s*(?:#|＃)" if strict_symbol else r"\s*(?:#|＃)?"
    elif key.endswith("%"):
        base = key[:-1]
        suffix = r"\s*(?:%|％)" if strict_symbol else r"\s*(?:%|％)?"

    if base == "MONO":
        base_pattern = r"M[O0]N[O0]"
    else:
        base_pattern = re.escape(base).replace(r"\-", r"[\s\-]?")

    return rf"(?<![A-Z0-9]){base_pattern}{suffix}(?![A-Z0-9#%])"


def text_contains_cbc_key(text: str, target_key: str) -> bool:
    cleaned = norm(text).upper()

    return (
        re.search(cbc_key_regex(target_key, strict_symbol=True), cleaned, re.IGNORECASE) is not None
        or re.search(cbc_key_regex(target_key, strict_symbol=False), cleaned, re.IGNORECASE) is not None
    )


def extract_cbc_row_from_text(text: str, target_key: str) -> dict | None:
    clean = norm(text)
    upper = clean.upper()

    match = re.search(cbc_key_regex(target_key, strict_symbol=True), upper, re.IGNORECASE)

    if not match:
        match = re.search(cbc_key_regex(target_key, strict_symbol=False), upper, re.IGNORECASE)

    if not match:
        return None

    tail = clean[match.end() : match.end() + 180]
    tail = norm(tail)

    if not tail:
        return None

    tokens = tail.split()

    result_text = ""
    reference_text = ""

    for index, token in enumerate(tokens):
        if cell_has_only_one_result_number(token) or is_null_value(token):
            result_text = token
            reference_text = " ".join(tokens[index + 1 :])
            break

    if not result_text:
        return None

    parsed = make_lab_row(
        key=target_key,
        result_text=result_text,
        reference_text=reference_text,
        unit_text=reference_text,
        confidence=0.72,
    )

    if parsed and row_is_plausible(parsed):
        return parsed

    return None

def force_backfill_missing_cbc_from_plain_text(
    candidates: list[dict],
    extraction: dict[str, Any],
) -> list[dict]:
    existing_keys = {
        lab_key(row)
        for row in candidates
        if row_is_plausible(row) and lab_key(row)
    }

    combined_text = "\n".join(
        [
            extraction.get("lines_text") or "",
            extraction.get("plain_text") or "",
        ]
    )

    # First try clean line-by-line extraction.
    for line in combined_text.splitlines():
        clean_line = norm(line)

        for target_key in CBC_ORDER:
            normalized_target = norm_key(target_key).lower()

            if normalized_target in existing_keys:
                continue

            if not text_contains_cbc_key(clean_line, target_key):
                continue

            parsed = extract_cbc_row_from_text(clean_line, target_key)

            if parsed and row_is_plausible(parsed):
                candidates.append(parsed)
                existing_keys.add(normalized_target)

    # Then try whole-document text in case Google merged the table into one block.
    compact_text = norm(combined_text)

    for target_key in CBC_ORDER:
        normalized_target = norm_key(target_key).lower()

        if normalized_target in existing_keys:
            continue

        if not text_contains_cbc_key(compact_text, target_key):
            continue

        parsed = extract_cbc_row_from_text(compact_text, target_key)

        if parsed and row_is_plausible(parsed):
            candidates.append(parsed)
            existing_keys.add(normalized_target)

    return candidates


def parse_labs_from_google_extraction(extraction: dict[str, Any]) -> list[dict]:
    table_candidates = parse_labs_from_google_tables(extraction.get("tables") or [])
    token_candidates = parse_labs_from_token_coordinates(extraction.get("words") or [])

    candidates: list[dict] = []
    candidates.extend(table_candidates)
    candidates.extend(token_candidates)

    candidates = add_missing_text_backfill(candidates, extraction)
    candidates = force_backfill_missing_cbc_from_plain_text(candidates, extraction)

    if len(candidates) < 4:
        candidates.extend(parse_labs_from_text_lines(extraction.get("lines_text") or ""))
        candidates.extend(parse_labs_from_text_lines(extraction.get("plain_text") or ""))

    labs_by_key: dict[str, dict] = {}

    for row in candidates:
        if not row_is_plausible(row):
            continue

        key = lab_key(row)

        if not key:
            continue

        if key not in labs_by_key:
            labs_by_key[key] = row
            continue

        if quality_score(row) > quality_score(labs_by_key[key]):
            labs_by_key[key] = row

    return order_labs(labs_by_key)