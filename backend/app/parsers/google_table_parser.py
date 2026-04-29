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
NULL_RESULT_RE = re.compile(r"^(?:-{1,}|_{1,}|—+|–+|nil|n/a|na|null|none|nu|absent)$", re.IGNORECASE)

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
    "referinta",
    "reference",
    "unit",
    "unitate",
    "um",
    "flag",
}


def normalize_space(value: Any) -> str:
    text = clean_text(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("µ", "u").replace("μ", "u")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = " ".join(text.split())
    return text.strip()


def is_null_result(value: Any) -> bool:
    text = normalize_space(value)

    if not text:
        return True

    return NULL_RESULT_RE.fullmatch(text) is not None


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

    text = " ".join(text.split())
    return text.strip()


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

    # 3.936-08 -> 3.93 - 6.08
    match = re.fullmatch(r"(\d{1,3})\.(\d{1,3})(\d)-(\d{1,3})", compact)

    if match:
        low = f"{match.group(1)}.{match.group(2)}"
        high = f"{match.group(3)}.{match.group(4)}"
        parsed = format_range(low, high)

        if parsed:
            low_final, high_final = parsed.split(" - ")
            return low_final, high_final

    # 34.151-0 -> 34.1 - 51.0
    match = re.fullmatch(r"(\d{1,3})\.(\d)(\d{2})-(\d)", compact)

    if match:
        low = f"{match.group(1)}.{match.group(2)}"
        high = f"{match.group(3)}.{match.group(4)}"
        parsed = format_range(low, high)

        if parsed:
            low_final, high_final = parsed.split(" - ")
            return low_final, high_final

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
            return f"{fused[0]} - {fused[1]}"

    explicit = re.search(
        r"(?<!\d)(-?\d{1,4}(?:\.\d+)?)\s*-\s*(-?\d{1,4}(?:\.\d+)?)(?!\d)",
        text,
    )

    if explicit:
        low = explicit.group(1)
        high = explicit.group(2)

        # In real lab references here, negative refs are rare.
        # The minus is almost always the separator stuck to the second number.
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
        token = normalize_test_token(piece)

        if token in KNOWN_TEST_ALIASES:
            return token

    compact = normalize_test_token(text)

    for alias in sorted(KNOWN_TEST_ALIASES.keys(), key=len, reverse=True):
        alias_pattern = re.escape(alias)
        alias_pattern = alias_pattern.replace(r"\-", r"[-\s]?")
        alias_pattern = alias_pattern.replace(r"\#", r"[#＃]?")
        alias_pattern = alias_pattern.replace(r"\%", r"[%％]?")

        if re.search(rf"(?<![A-Z0-9]){alias_pattern}(?![A-Z0-9])", compact, re.IGNORECASE):
            return normalize_test_token(alias)

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


def choose_result_and_reference_cells(cells: list[str], test_cell_index: int) -> tuple[str, str, str | None]:
    """
    Returns:
      result_cell_text, reference_cell_text, explicit_flag
    """
    after = cells[test_cell_index + 1 :]

    if not after:
        return "", "", None

    result_cell = after[0]
    explicit_flag = detect_explicit_flag(" ".join(after))

    reference_parts = after[1:]

    if len(after) >= 3:
        # Sometimes table is:
        # test | result | unit | reference
        second = after[1]
        third = after[2]

        second_has_unit = extract_unit(second) is not None and extract_reference_range(second) is None
        third_has_range = extract_reference_range(third) is not None

        if second_has_unit and third_has_range:
            reference_parts = [third, second, *after[3:]]

    reference_cell = " ".join(part for part in reference_parts if normalize_space(part)).strip()

    return result_cell, reference_cell, explicit_flag


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

    result_cell, reference_cell, explicit_flag = choose_result_and_reference_cells(clean_cells, test_cell_index)

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


def parse_labs_from_google_tables(tables: list[dict[str, Any]]) -> list[dict]:
    labs_by_key: dict[str, dict] = {}

    for table in tables or []:
        for row in table.get("rows", []) or []:
            cell_texts = []

            for cell in row.get("cells", []) or []:
                cell_texts.append(cell.get("text") or "")

            parsed = parse_table_row_cells(cell_texts)

            if not parsed:
                continue

            key = (
                parsed.get("canonical_name")
                or parsed.get("display_name")
                or parsed.get("raw_test_name")
                or ""
            )
            key = str(key).strip().lower()

            if not key:
                continue

            if key not in labs_by_key:
                labs_by_key[key] = parsed
                continue

            existing = labs_by_key[key]

            existing_score = quality_score(existing)
            candidate_score = quality_score(parsed)

            if candidate_score >= existing_score:
                labs_by_key[key] = parsed

    return list(labs_by_key.values())


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