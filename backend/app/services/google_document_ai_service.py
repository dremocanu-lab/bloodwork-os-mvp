from __future__ import annotations

import re
from typing import Any

from app.parsers.bloodwork_parser import (
    ARROW_HIGH_MARKERS,
    ARROW_LOW_MARKERS,
    KNOWN_TEST_ALIASES,
    build_lab_result,
    build_nil_result,
    clean_text,
    infer_flag,
    normalize_decimal,
    normalize_test_token,
)


NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
NULL_RESULT_RE = re.compile(
    r"^(?:-{1,}|_{1,}|—+|–+|nil|n/a|na|null|none|nu|absent)$",
    re.IGNORECASE,
)

UNIT_PATTERNS: list[tuple[str, str]] = [
    (r"10\s*[\^]?\s*3\s*/?\s*u?l", "10^3/uL"),
    (r"10\s*[\^]?\s*6\s*/?\s*u?l", "10^6/uL"),
    (r"10\s*[\^]?\s*9\s*/?\s*l", "10^9/L"),
    (r"10\s*[\^]?\s*12\s*/?\s*l", "10^12/L"),
    (r"\bg\s*/\s*dL\b", "g/dL"),
    (r"\bg\s*/\s*dl\b", "g/dL"),
    (r"\bg\s*/\s*L\b", "g/L"),
    (r"\bmg\s*/\s*dL\b", "mg/dL"),
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

HEADER_WORDS = {
    "denumire",
    "analiza",
    "analiză",
    "test",
    "rezultat",
    "result",
    "valoare",
    "value",
    "interval",
    "referinta",
    "referință",
    "reference",
    "unit",
    "unitate",
    "um",
    "flag",
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

CBC_KEY_RE = re.compile(
    r"(?<![A-Z0-9])("
    r"RDW[\s\-]?SD|RDW[\s\-]?CV|P[\s\-]?LCR|"
    r"NRBC[#%]?|NEUT[#%]?|LYMPH[#%]?|MONO[#%]?|BASO[#%]?|"
    r"EO[#%]?|IG[#%]?|"
    r"WBC|RBC|HGB|HCT|MCV|MCHC|MCH|PLT|PDW|MPV|PCT"
    r")(?![A-Z0-9])",
    re.IGNORECASE,
)


def normalize_space(value: Any) -> str:
    text = clean_text(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("µ", "u").replace("μ", "u")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.replace("＃", "#").replace("％", "%")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_cbc_key(raw_key: str) -> str:
    key = normalize_test_token(raw_key)
    key = key.replace("RDWSD", "RDW-SD")
    key = key.replace("RDWCV", "RDW-CV")
    key = key.replace("PLCR", "P-LCR")
    key = key.replace("P LCR", "P-LCR")
    return key


def is_null_result(value: Any) -> bool:
    text = normalize_space(value)

    if not text:
        return True

    return NULL_RESULT_RE.fullmatch(text) is not None


def get_numbers(value: Any) -> list[str]:
    text = normalize_space(value).replace(",", ".")
    return NUMBER_RE.findall(text)


def clean_number(value: Any) -> str | None:
    cleaned = normalize_decimal(value)

    if cleaned is None:
        return None

    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    return cleaned


def extract_unit(value: Any) -> str | None:
    text = normalize_space(value)

    if not text:
        return None

    for pattern, unit in UNIT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return unit

    return None


def remove_unit_text(value: Any) -> str:
    text = normalize_space(value)

    for pattern, _unit in UNIT_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def format_range(low: str, high: str) -> str | None:
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
    compact = normalize_space(token).replace(" ", "").replace(",", ".")

    # OCR sometimes fuses 3.93 - 6.08 as 3.936-08
    match = re.fullmatch(r"(\d{1,3})\.(\d{1,3})(\d)-(\d{1,3})", compact)
    if match:
        low = f"{match.group(1)}.{match.group(2)}"
        high = f"{match.group(3)}.{match.group(4)}"
        return low, high

    # OCR sometimes fuses 34.1 - 51.0 as 34.151-0
    match = re.fullmatch(r"(\d{1,3})\.(\d)(\d{2})-(\d)", compact)
    if match:
        low = f"{match.group(1)}.{match.group(2)}"
        high = f"{match.group(3)}.{match.group(4)}"
        return low, high

    return None


def extract_reference_range(value: Any) -> str | None:
    text = remove_unit_text(value)

    if not text:
        return None

    text = text.replace(",", ".")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")

    for token in text.split():
        fused = split_fused_range_token(token)
        if fused:
            return format_range(fused[0], fused[1])

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

    numbers = get_numbers(text)

    if len(numbers) >= 2:
        return format_range(numbers[0], numbers[1])

    return None


def extract_result_value(value: Any) -> str | None:
    text = normalize_space(value)

    if is_null_result(text):
        return None

    numbers = get_numbers(text)

    if not numbers:
        return None

    return clean_number(numbers[0])


def detect_test_key(value: Any) -> str | None:
    text = normalize_space(value)

    if not text:
        return None

    pieces = re.split(r"[\s:/|;]+", text)

    for piece in pieces:
        token = normalize_cbc_key(piece)

        if token in KNOWN_TEST_ALIASES:
            return token

    compact = normalize_cbc_key(text)

    if compact in KNOWN_TEST_ALIASES:
        return compact

    match = CBC_KEY_RE.search(text)

    if match:
        candidate = normalize_cbc_key(match.group(1))

        if candidate in KNOWN_TEST_ALIASES:
            return candidate

    return None


def is_probably_header_row(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    hits = sum(1 for word in HEADER_WORDS if word in joined)
    return hits >= 2


def detect_explicit_flag(value: Any) -> str | None:
    text = normalize_space(value)
    lowered = f" {text.lower()} "

    if any(marker in text for marker in ARROW_HIGH_MARKERS):
        return "High"

    if any(marker in text for marker in ARROW_LOW_MARKERS):
        return "Low"

    if " high " in lowered or " crescut " in lowered:
        return "High"

    if " low " in lowered or " scazut " in lowered:
        return "Low"

    if " normal " in lowered:
        return "Normal"

    return None


def parse_table_row_cells(cells: list[str]) -> dict | None:
    clean_cells = [normalize_space(cell) for cell in cells]
    clean_cells = [cell for cell in clean_cells if cell]

    if len(clean_cells) < 2:
        return None

    if is_probably_header_row(clean_cells):
        return None

    test_key = None
    test_cell_index = -1

    for index, cell in enumerate(clean_cells):
        detected = detect_test_key(cell)

        if detected:
            test_key = detected
            test_cell_index = index
            break

    if not test_key:
        return None

    after = clean_cells[test_cell_index + 1 :]

    if not after:
        return None

    result_cell = after[0]
    reference_cell = " ".join(after[1:])

    # If Document AI splits unit and ref:
    # test | result | unit | reference
    if len(after) >= 3:
        second = after[1]
        third = after[2]

        second_is_unit_only = extract_unit(second) is not None and extract_reference_range(second) is None
        third_has_ref = extract_reference_range(third) is not None

        if second_is_unit_only and third_has_ref:
            reference_cell = f"{third} {second}"

    explicit_flag = detect_explicit_flag(" ".join(after))
    result_value = extract_result_value(result_cell)
    reference_range = extract_reference_range(reference_cell)
    unit = extract_unit(reference_cell) or extract_unit(result_cell)

    if result_value is None:
        return build_nil_result(
            raw_test_name=test_key,
            reference_range=reference_range,
            unit=unit,
            confidence=0.99 if reference_range else 0.85,
        )

    flag = explicit_flag or infer_flag(result_value, reference_range)

    return build_lab_result(
        raw_test_name=test_key,
        value=result_value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.99 if reference_range else 0.82,
    )


def normalize_line_for_cbc(line: str) -> str:
    text = normalize_space(line)
    text = re.sub(r"\bRDW\s+SD\b", "RDW-SD", text, flags=re.IGNORECASE)
    text = re.sub(r"\bRDW\s+CV\b", "RDW-CV", text, flags=re.IGNORECASE)
    text = re.sub(r"\bP\s+LCR\b", "P-LCR", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNRBC\s+#\b", "NRBC#", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNRBC\s+%\b", "NRBC%", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNEUT\s+#\b", "NEUT#", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNEUT\s+%\b", "NEUT%", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLYMPH\s+#\b", "LYMPH#", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLYMPH\s+%\b", "LYMPH%", text, flags=re.IGNORECASE)
    text = re.sub(r"\bMONO\s+#\b", "MONO#", text, flags=re.IGNORECASE)
    text = re.sub(r"\bMONO\s+%\b", "MONO%", text, flags=re.IGNORECASE)
    text = re.sub(r"\bBASO\s+#\b", "BASO#", text, flags=re.IGNORECASE)
    text = re.sub(r"\bBASO\s+%\b", "BASO%", text, flags=re.IGNORECASE)
    text = re.sub(r"\bEO\s+#\b", "EO#", text, flags=re.IGNORECASE)
    text = re.sub(r"\bEO\s+%\b", "EO%", text, flags=re.IGNORECASE)
    text = re.sub(r"\bIG\s+#\b", "IG#", text, flags=re.IGNORECASE)
    text = re.sub(r"\bIG\s+%\b", "IG%", text, flags=re.IGNORECASE)
    return text


def extract_candidate_cbc_block(text: str) -> str:
    safe = text or ""

    start_markers = [
        "Hemograma simpla",
        "Hemograma simplă",
        "Citomorfologie",
        "Sysmex",
        "WBC",
    ]

    end_markers = [
        "Citomorfologie (Manual",
        "Manual Citomorfologie",
        "Frotiu Tub",
        "Frotiu",
        "Validat de",
        "Parafa",
    ]

    start = -1

    for marker in start_markers:
        found = safe.lower().find(marker.lower())

        if found >= 0 and (start < 0 or found < start):
            start = found

    if start < 0:
        start = 0

    end = len(safe)

    for marker in end_markers:
        found = safe.lower().find(marker.lower(), start + 20)

        if found >= 0:
            end = min(end, found)

    return safe[start:end]


def line_contains_cbc_key(line: str) -> str | None:
    text = normalize_line_for_cbc(line)

    match = CBC_KEY_RE.search(text)

    if not match:
        return None

    key = normalize_cbc_key(match.group(1))

    if key in KNOWN_TEST_ALIASES:
        return key

    return None


def extract_cbc_lines_from_text(text: str) -> list[str]:
    block = extract_candidate_cbc_block(text)
    output: list[str] = []

    for raw_line in block.splitlines():
        line = normalize_line_for_cbc(raw_line)

        if not line:
            continue

        if line_contains_cbc_key(line):
            output.append(line)

    return output


def parse_cbc_line(line: str) -> dict | None:
    line = normalize_line_for_cbc(line)
    key = line_contains_cbc_key(line)

    if not key:
        return None

    match = CBC_KEY_RE.search(line)

    if not match:
        return None

    after = line[match.end() :].strip()
    after = after.replace("|", " ")
    after = normalize_space(after)

    explicit_flag = detect_explicit_flag(after)
    has_null_marker = bool(re.search(r"(?:^|\s)(?:---+|--+|nil|n/a|na)(?:\s|$)", after, re.IGNORECASE))
    unit = extract_unit(after)

    if has_null_marker:
        reference_range = extract_reference_range(after)
        return build_nil_result(
            raw_test_name=key,
            reference_range=reference_range,
            unit=unit,
            confidence=0.92 if reference_range else 0.80,
        )

    numbers = get_numbers(after)

    if not numbers:
        return None

    result_value = clean_number(numbers[0])

    if result_value is None:
        return None

    reference_range = None

    if len(numbers) >= 3:
        reference_range = format_range(numbers[1], numbers[2])
    else:
        reference_range = extract_reference_range(after)

    flag = explicit_flag or infer_flag(result_value, reference_range)

    return build_lab_result(
        raw_test_name=key,
        value=result_value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.88 if reference_range else 0.72,
    )


def parse_labs_from_google_text(text: str) -> list[dict]:
    labs_by_key: dict[str, dict] = {}

    for line in extract_cbc_lines_from_text(text):
        parsed = parse_cbc_line(line)

        if not parsed:
            continue

        key = lab_key(parsed)

        if not key:
            continue

        if key not in labs_by_key:
            labs_by_key[key] = parsed
            continue

        if quality_score(parsed) >= quality_score(labs_by_key[key]):
            labs_by_key[key] = parsed

    ordered: list[dict] = []

    for desired_key in CBC_ORDER:
        normalized_desired = normalize_cbc_key(desired_key).lower()

        found_key = None

        for existing_key in labs_by_key:
            if existing_key == normalized_desired:
                found_key = existing_key
                break

        if found_key:
            ordered.append(labs_by_key.pop(found_key))

    ordered.extend(labs_by_key.values())

    return ordered


def parse_labs_from_google_extraction(extraction: dict[str, Any]) -> list[dict]:
    labs_by_key: dict[str, dict] = {}

    # 1. Try true Google Document AI table cells first.
    for table in extraction.get("tables") or []:
        for row in table.get("rows", []) or []:
            cells = [cell.get("text") or "" for cell in row.get("cells", []) or []]
            parsed = parse_table_row_cells(cells)

            if not parsed:
                continue

            key = lab_key(parsed)

            if not key:
                continue

            if key not in labs_by_key or quality_score(parsed) >= quality_score(labs_by_key[key]):
                labs_by_key[key] = parsed

    # 2. Fallback to Google Document AI extracted lines/plain text.
    combined_text = "\n".join(
        [
            extraction.get("table_text") or "",
            extraction.get("lines_text") or "",
            extraction.get("plain_text") or "",
            extraction.get("text") or "",
        ]
    )

    text_labs = parse_labs_from_google_text(combined_text)

    for parsed in text_labs:
        key = lab_key(parsed)

        if not key:
            continue

        if key not in labs_by_key or quality_score(parsed) >= quality_score(labs_by_key[key]):
            labs_by_key[key] = parsed

    return list(labs_by_key.values())


def lab_key(row: dict) -> str:
    key = (
        row.get("raw_test_name")
        or row.get("canonical_name")
        or row.get("display_name")
        or ""
    )

    return normalize_cbc_key(str(key)).lower()


def quality_score(row: dict) -> float:
    score = float(row.get("confidence") or 0)

    if row.get("value") is not None:
        score += 0.40

    if row.get("reference_range"):
        score += 0.35

    if row.get("unit"):
        score += 0.15

    if row.get("flag") in {"High", "Low"}:
        score += 0.05

    return score