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

CBC_ORDER_SET = set(CBC_ORDER)

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

CBC_KEY_RE = re.compile(
    r"^(WBC|RBC|HGB|HCT|MCV|MCHC|MCH|PLT|RDW[\s\-]?SD|RDW[\s\-]?CV|PDW|MPV|P[\s\-]?LCR|PCT|NRBC[#%]?|NEUT[#%]?|LYMPH[#%]?|MONO[#%]?|EO[#%]?|BASO[#%]?|IG[#%]?)$",
    re.IGNORECASE,
)

UNIT_PATTERNS: list[tuple[str, str]] = [
    (r"10\s*\^?\s*3\s*/?\s*u?l", "10^3/uL"),
    (r"10\s*\^?\s*6\s*/?\s*u?l", "10^6/uL"),
    (r"10\s*\^?\s*9\s*/?\s*l", "10^9/L"),
    (r"10\s*\^?\s*12\s*/?\s*l", "10^12/L"),
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

    # Google Document AI can read Latin CBC labels as Greek lookalikes.
    # Example: ΜΟΝΟ# instead of MONO#.
    greek_to_latin = str.maketrans(
        {
            "Μ": "M",
            "Ο": "O",
            "Ν": "N",
            "μ": "u",
            "ο": "o",
            "ν": "v",
            "Α": "A",
            "α": "a",
            "Β": "B",
            "β": "b",
            "Ε": "E",
            "ε": "e",
            "Η": "H",
            "η": "n",
            "Ι": "I",
            "ι": "i",
            "Κ": "K",
            "κ": "k",
            "Ρ": "P",
            "ρ": "p",
            "Τ": "T",
            "τ": "t",
            "Χ": "X",
            "χ": "x",
            "Υ": "Y",
            "υ": "u",
            "Ζ": "Z",
            "ζ": "z",
        }
    )
    text = text.translate(greek_to_latin)

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def norm_key(value: str) -> str:
    raw = norm(value).upper()
    raw = raw.replace("＃", "#").replace("％", "%")
    raw = raw.replace(" ", "")
    raw = raw.replace("_", "-")
    raw = raw.replace("–", "-").replace("—", "-")

    mono_candidate = raw.replace("#", "").replace("%", "")
    if re.fullmatch(r"M[O0]N[O0]", mono_candidate):
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

    if compact in KNOWN_TEST_ALIASES or compact in CBC_ORDER_SET:
        return compact

    if CBC_KEY_RE.fullmatch(text):
        return norm_key(text)

    parts = re.split(r"[\s:;|/]+", text)

    for part in parts:
        compact_part = norm_key(part)

        if compact_part in KNOWN_TEST_ALIASES or compact_part in CBC_ORDER_SET:
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

    return cleaned


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

    for pattern, _unit in UNIT_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def format_range(low: Any, high: Any) -> str | None:
    low_clean = clean_number(low)
    high_clean = clean_number(high)

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
    compact = norm(token).replace(" ", "").replace(",", ".")
    compact = re.sub(r"[^0-9.\-]", "", compact)

    if not compact:
        return None

    # IMPORTANT:
    # Use fullmatch only. Search was corrupting valid ranges like:
    # 3.98-10.00 -> 3.9 - 8.10

    # 3.936.08 -> 3.93 - 6.08
    # 1.183.74 -> 1.18 - 3.74
    # 0.240.82 -> 0.24 - 0.82
    # 0.010.08 -> 0.01 - 0.08
    match = re.fullmatch(r"(\d{1,3})\.(\d{2})(\d)\.(\d{2})", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    # 34.151.0 -> 34.1 - 51.0
    # 35.146.3 -> 35.1 - 46.3
    # 11.614.4 -> 11.6 - 14.4
    # 19.353.1 -> 19.3 - 53.1
    match = re.fullmatch(r"(\d{1,3})\.(\d)(\d{2})\.(\d)", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    # 3.936-08 -> 3.93 - 6.08
    # 1.183-74 -> 1.18 - 3.74
    # 0.240-82 -> 0.24 - 0.82
    # 0.010-08 -> 0.01 - 0.08
    match = re.fullmatch(r"(\d{1,3})\.(\d{2})(\d)-(\d{2})", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    # 34.151-0 -> 34.1 - 51.0
    # 35.146-3 -> 35.1 - 46.3
    # 11.614-4 -> 11.6 - 14.4
    # 19.353-1 -> 19.3 - 53.1
    match = re.fullmatch(r"(\d{1,3})\.(\d)(\d{2})-(\d)", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    return None


def extract_reference_range(value: Any) -> str | None:
    text = remove_units(value).replace(",", ".")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return None

    # Never parse dates or report metadata as lab reference ranges.
    if re.search(r"\b(19|20)\d{2}\b", text):
        return None

    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", text, re.IGNORECASE):
        return None

    # Correct normal explicit ranges first.
    # This prevents 3.98-10.00 from becoming 3.9 - 8.10.
    explicit = re.fullmatch(
        r"\s*(-?\d{1,4}(?:\.\d+)?)\s*-\s*(-?\d{1,4}(?:\.\d+)?)\s*",
        text,
    )

    if explicit:
        low = explicit.group(1)
        high = explicit.group(2)

        if high.startswith("-") and not low.startswith("-"):
            high = high[1:]

        return format_range(low, high)

    # Then repair fused OCR ranges.
    fused = split_fused_range_token(text)
    if fused:
        return format_range(fused[0], fused[1])

    # Do not fall back to "any two numbers".
    # That is what created garbage like IG% reference 14 - 2023.
    return None


def repair_malformed_reference_range(reference_range: str | None, source_text: Any = "") -> str | None:
    raw = norm(source_text).replace(",", ".")
    raw = raw.replace("–", "-").replace("—", "-").replace("−", "-")
    raw_compact = re.sub(r"\s+", "", raw)

    raw_repaired = split_fused_range_token(raw_compact)
    if raw_repaired:
        return format_range(raw_repaired[0], raw_repaired[1])

    if not reference_range:
        return None

    text = norm(reference_range).replace(",", ".")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")

    text_repaired = split_fused_range_token(text)
    if text_repaired:
        return format_range(text_repaired[0], text_repaired[1])

    # Safe repair for WBC-like broken 10.00 ranges:
    # 3.9 - 8.10 -> 3.98 - 10.00
    match = re.fullmatch(r"(\d{1,3})\.(\d)\s*-\s*(\d)\.(10|00)", text)
    if match:
        low = f"{match.group(1)}.{match.group(2)}{match.group(3)}"
        high = "10.00" if match.group(4) == "10" else "0.00"
        return format_range(low, high)

    return reference_range


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

    found = numbers(text)

    if not found:
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


def decorate_cbc_row(row: dict) -> dict:
    key = norm_key(str(row.get("raw_test_name") or ""))

    display_name = CBC_DISPLAY_NAMES.get(key)

    if display_name:
        row["raw_test_name"] = key
        row["canonical_name"] = display_name
        row["display_name"] = display_name
        row["category"] = "Hematologie"

    return row


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
        row = build_lab_result(
            raw_test_name=key,
            value=value,
            flag=infer_flag(value, reference_range),
            reference_range=reference_range,
            unit=unit,
            confidence=confidence,
        )

        row["flag"] = infer_flag(value, reference_range)

    return decorate_cbc_row(row)


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

    return make_lab_row(
        key=key,
        result_text=result_text,
        reference_text=reference_text,
        unit_text=unit_text,
        confidence=0.90,
    )


def parse_labs_from_token_coordinates(words: list[dict[str, Any]]) -> list[dict]:
    rows = group_tokens_into_rows(words or [])
    bands = infer_column_bands_from_token_rows(rows)

    if not bands:
        return []

    labs: list[dict] = []

    for row in rows:
        parsed = parse_token_row_dynamic(row, bands)

        if parsed and row_is_plausible(parsed):
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
            confidence=0.92,
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


def line_is_reference_or_unit(line: str) -> bool:
    reference_range, unit = split_reference_and_unit(line)
    return bool(reference_range or unit)


def line_is_result(line: str) -> bool:
    return cell_has_only_one_result_number(line) and not line_is_reference_or_unit(line) and not detect_key(line)


def parse_cbc_from_lines(lines_text: str) -> list[dict]:
    lines = [norm(line) for line in (lines_text or "").splitlines()]
    lines = [line for line in lines if line]

    # Keep only the automatic CBC area.
    start_index = 0
    end_index = len(lines)

    for index, line in enumerate(lines):
        lowered = line.lower()
        if "hemograma simpla" in lowered or "cbc" in lowered:
            start_index = index
            break

    for index in range(start_index, len(lines)):
        lowered = lines[index].lower()
        if "validat de" in lowered or "citomorfologie (manual" in lowered:
            end_index = index
            break

    cbc_lines = lines[start_index:end_index]

    key_positions: list[tuple[int, str]] = []

    for index, line in enumerate(cbc_lines):
        key = detect_key(line)
        if key and key in CBC_ORDER_SET:
            key_positions.append((index, key))

    if not key_positions:
        return []

    labs: list[dict] = []
    pending_reference_text: str | None = None
    pending_unit_text: str | None = None

    for position_index, (key_index, key) in enumerate(key_positions):
        next_key_index = (
            key_positions[position_index + 1][0]
            if position_index + 1 < len(key_positions)
            else len(cbc_lines)
        )

        segment = cbc_lines[key_index + 1 : next_key_index]

        result_text: str | None = None
        reference_text: str | None = None
        unit_text: str | None = None
        trailing_reference_text: str | None = None
        trailing_unit_text: str | None = None

        for candidate in segment:
            if detect_key(candidate):
                break

            candidate_reference, candidate_unit = split_reference_and_unit(candidate)

            if candidate_unit and unit_text is None:
                unit_text = candidate

            if candidate_reference and reference_text is None:
                reference_text = candidate
                continue

            if result_text is None and line_is_result(candidate):
                result_text = candidate
                continue

            # Sometimes Document AI places the next row's reference before the next key.
            # Example:
            # RDW-CV
            # 11.614.4%
            # 21.2
            # 9.0-17.0 FL
            # PDW
            if result_text is not None:
                extra_reference, extra_unit = split_reference_and_unit(candidate)

                if extra_reference:
                    trailing_reference_text = candidate

                if extra_unit:
                    trailing_unit_text = candidate

        if reference_text is None and pending_reference_text is not None:
            reference_text = pending_reference_text

        if unit_text is None and pending_unit_text is not None:
            unit_text = pending_unit_text

        parsed = make_lab_row(
            key=key,
            result_text=result_text,
            reference_text=reference_text,
            unit_text=unit_text,
            confidence=1.20,
        )

        if parsed and row_is_plausible(parsed):
            labs.append(parsed)

        pending_reference_text = trailing_reference_text
        pending_unit_text = trailing_unit_text

    return labs


def parse_labs_from_text_lines(text: str) -> list[dict]:
    labs: list[dict] = []

    for line in (text or "").splitlines():
        line = norm(line)
        parts = line.split()

        if len(parts) < 3:
            continue

        key = detect_key(parts[0])

        if not key:
            continue

        result_text = ""
        reference_text = ""
        unit_text = ""

        for part_index, part in enumerate(parts[1:], start=1):
            if cell_has_only_one_result_number(part) or is_null_value(part):
                result_text = part
                reference_text = " ".join(parts[part_index + 1 :])
                unit_text = reference_text
                break

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


def row_is_plausible(row: dict) -> bool:
    key = norm_key(str(row.get("raw_test_name") or ""))

    if not key:
        return False

    if key not in CBC_ORDER_SET and key not in KNOWN_TEST_ALIASES:
        return True

    value = row.get("value")

    if value is None:
        return True

    try:
        number = float(str(value).replace(",", "."))
    except Exception:
        return False

    if number < -1:
        return False

    # Broad sanity bounds, not lab defaults.
    max_values = {
        "WBC": 500,
        "RBC": 20,
        "HGB": 40,
        "HCT": 100,
        "MCV": 200,
        "MCH": 100,
        "MCHC": 100,
        "PLT": 5000,
        "RDW-SD": 300,
        "RDW-CV": 100,
        "NEUT#": 500,
        "LYMPH#": 500,
        "MONO#": 500,
        "EO#": 500,
        "BASO#": 500,
        "IG#": 500,
    }

    if key.endswith("%"):
        return 0 <= number <= 100

    max_allowed = max_values.get(key)

    if max_allowed is not None and number > max_allowed:
        return False

    return True


def quality_score(row: dict) -> float:
    score = float(row.get("confidence") or 0)

    if row.get("value") is not None:
        score += 0.5

    if row.get("reference_range"):
        score += 0.4

    if row.get("unit"):
        score += 0.2

    key = norm_key(str(row.get("raw_test_name") or ""))

    if key in CBC_ORDER_SET:
        score += 0.2

    return score


def order_labs(labs_by_key: dict[str, dict]) -> list[dict]:
    ordered: list[dict] = []

    for key in CBC_ORDER:
        normalized = norm_key(key).lower()

        if normalized in labs_by_key:
            ordered.append(labs_by_key.pop(normalized))

    ordered.extend(labs_by_key.values())
    return ordered


def correct_cbc_references_from_lines(
    labs: list[dict],
    extraction: dict[str, Any],
) -> list[dict]:
    line_labs = parse_cbc_from_lines(extraction.get("lines_text") or "")
    by_key = {lab_key(row): row for row in line_labs if lab_key(row)}

    for row in labs:
        key = lab_key(row)

        if not key or key not in by_key:
            continue

        line_row = by_key[key]

        # For CBC rows, line parser owns the final reference.
        # This matters because NRBC#, NRBC%, IG#, IG% may legitimately have no range.
        row["reference_range"] = line_row.get("reference_range")

        if line_row.get("unit"):
            row["unit"] = line_row.get("unit")

        if line_row.get("value") is not None:
            row["value"] = line_row.get("value")

        value = row.get("value")
        reference_range = row.get("reference_range")

        if value is not None and reference_range:
            row["flag"] = infer_flag(str(value), reference_range)
        else:
            row["flag"] = None

        decorate_cbc_row(row)

    return labs

def parse_labs_from_google_extraction(extraction: dict[str, Any]) -> list[dict]:
    candidates: list[dict] = []

    # Line parser is most reliable for this Fundeni CBC layout because Document AI
    # preserves the key/reference/value sequence even when table cells are not returned.
    candidates.extend(parse_cbc_from_lines(extraction.get("lines_text") or ""))

    # Keep the other parsers as fallback/support for other labs/layouts.
    candidates.extend(parse_labs_from_google_tables(extraction.get("tables") or []))
    candidates.extend(parse_labs_from_token_coordinates(extraction.get("words") or []))
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

    ordered = order_labs(labs_by_key)
    ordered = correct_cbc_references_from_lines(ordered, extraction)

    return ordered