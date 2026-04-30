# backend/app/parsers/google_table_parser.py

from __future__ import annotations

import re
from statistics import median
from typing import Any

from app.parsers.bloodwork_parser import (
    CBC_ORDER,
    DEFAULT_CBC_UNITS,
    KNOWN_TEST_ALIASES,
    build_lab_result,
    build_nil_result,
    clean_text,
    clean_unit,
    extract_reference_range,
    extract_unit_from_reference,
    infer_flag,
    is_null_result,
    normalize_decimal,
    normalize_test_token,
    remove_units,
)

NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
CBC_ORDER_SET = set(CBC_ORDER)

CBC_KEY_RE = re.compile(
    r"^(WBC|RBC|HGB|HCT|MCV|MCHC|MCH|PLT|RDW[\s\-]?SD|RDW[\s\-]?CV|PDW|MPV|P[\s\-]?LCR|PCT|NRBC[#%]?|NEUT[#%]?|LYMPH[#%]?|MONO[#%]?|EO[#%]?|EOS[#%]?|BASO[#%]?|IG[#%]?)$",
    re.IGNORECASE,
)

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
    return clean_text(value)


def norm_key(value: str) -> str:
    return normalize_test_token(value)


def detect_key(value: Any) -> str | None:
    text = norm(value)

    if not text:
        return None

    compact = norm_key(text)

    if compact in KNOWN_TEST_ALIASES:
        return compact

    if compact in CBC_ORDER_SET:
        return compact

    if CBC_KEY_RE.fullmatch(text):
        return norm_key(text)

    parts = re.split(r"[\s:;|/]+", text)

    for part in parts:
        compact_part = norm_key(part)

        if compact_part in KNOWN_TEST_ALIASES:
            return compact_part

        if compact_part in CBC_ORDER_SET:
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

    return cleaned or None


def is_null_value(value: Any) -> bool:
    return is_null_result(value)


def extract_unit(value: Any, key: str | None = None) -> str | None:
    return extract_unit_from_reference(value, key)


def is_unit_only(value: Any) -> bool:
    text = norm(value)

    if not text:
        return False

    unit = extract_unit(text)

    if not unit:
        return False

    stripped = remove_units(text)
    stripped = stripped.replace("^", "")
    stripped = re.sub(r"[\s/]+", "", stripped)

    return stripped == ""


def split_reference_and_unit(value: Any, key: str | None = None) -> tuple[str | None, str | None]:
    text = norm(value)

    if not text:
        return None, None

    reference_range = extract_reference_range(text)
    unit = extract_unit_from_reference(text, key)

    return reference_range, unit


def extract_result(value: Any) -> str | None:
    text = norm(value)

    if not text:
        return None

    if is_null_value(text):
        return None

    if is_unit_only(text):
        return None

    if extract_reference_range(text):
        return None

    found = numbers(text)

    if len(found) != 1:
        return None

    return clean_number(found[0])


def line_is_result(value: Any) -> bool:
    text = norm(value)

    if not text:
        return False

    if detect_key(text):
        return False

    if is_null_value(text):
        return True

    if is_unit_only(text):
        return False

    if extract_reference_range(text):
        return False

    return len(numbers(text)) == 1


def cell_has_only_one_result_number(value: Any) -> bool:
    return line_is_result(value)


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

    reference_range, unit_from_reference = split_reference_and_unit(reference_text or "", key)
    _reference_from_unit_cell, unit_from_unit_cell = split_reference_and_unit(unit_text or "", key)

    unit = (
        unit_from_unit_cell
        or unit_from_reference
        or extract_unit(unit_text or "", key)
        or extract_unit(reference_text or "", key)
        or extract_unit(result_text or "", key)
        or DEFAULT_CBC_UNITS.get(key)
    )

    if value is None:
        row = build_nil_result(
            raw_test_name=key,
            reference_range=reference_range,
            unit=unit,
            confidence=confidence,
        )
        row["raw_test_name"] = key
        return row

    flag = infer_flag(value, reference_range) if reference_range else None

    row = build_lab_result(
        raw_test_name=key,
        value=value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=confidence,
    )
    row["raw_test_name"] = key
    return row


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

    if row.get("flag") in {"High", "Low"}:
        score += 0.1

    return score


def order_labs(labs_by_key: dict[str, dict]) -> list[dict]:
    ordered: list[dict] = []

    for key in CBC_ORDER:
        normalized = norm_key(key).lower()

        if normalized in labs_by_key:
            ordered.append(labs_by_key.pop(normalized))

    ordered.extend(labs_by_key.values())
    return ordered


def is_metadata_line(line: str) -> bool:
    lowered = norm(line).lower()

    metadata_markers = [
        "buletin",
        "fundeni",
        "laborator",
        "citomorfologie",
        "starea probei",
        "denumire analiza",
        "denumire analiză",
        "rezultat",
        "interval biologic",
        "referinta",
        "referință",
        "hemograma simpla",
        "hemogramă simplă",
        "tip proba",
        "tip probă",
        "validat",
        "parafa",
        "data validare",
        "telefon",
        "pacient",
        "sectie",
        "secție",
        "medic",
        "cnp",
        "sex",
        "urgenta",
        "urgență",
        "varsta",
        "vârsta",
        "foaie",
        "observatie",
        "observație",
        "afisat",
        "afișat",
        "codificare",
        "nota",
        "neverificat",
        "http",
        "192.168",
    ]

    return any(marker in lowered for marker in metadata_markers)


def find_cbc_window(lines: list[str]) -> list[str]:
    if not lines:
        return []

    start_index = 0
    end_index = len(lines)

    for index, line in enumerate(lines):
        lowered = line.lower()

        if "hemograma simpla" in lowered or "hemogramă simplă" in lowered or "cbc" in lowered:
            start_index = index
            break

    for index in range(start_index, len(lines)):
        lowered = lines[index].lower()

        if "validat de" in lowered or "citomorfologie (manual" in lowered:
            end_index = index
            break

    return lines[start_index:end_index]


def collect_lines_from_extraction(extraction: dict[str, Any], key: str) -> list[str]:
    value = extraction.get(key)

    if isinstance(value, str):
        return [norm(line) for line in value.splitlines() if norm(line)]

    if isinstance(value, list):
        lines: list[str] = []

        for item in value:
            if isinstance(item, str):
                text = norm(item)
            elif isinstance(item, dict):
                text = norm(item.get("text") or item.get("layout_text") or "")
            else:
                text = norm(item)

            if text:
                lines.append(text)

        return lines

    return []


def parse_cbc_from_ordered_lines(lines: list[str], confidence: float) -> list[dict]:
    clean_lines = [norm(line) for line in lines if norm(line)]
    cbc_lines = find_cbc_window(clean_lines)

    key_positions: list[tuple[int, str]] = []

    for index, line in enumerate(cbc_lines):
        key = detect_key(line)

        if key and key in CBC_ORDER_SET:
            key_positions.append((index, key))

    if not key_positions:
        return []

    labs: list[dict] = []

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

        for candidate in segment:
            candidate = norm(candidate)

            if not candidate:
                continue

            if detect_key(candidate):
                break

            if is_metadata_line(candidate):
                continue

            candidate_reference, candidate_unit = split_reference_and_unit(candidate, key)

            if candidate_reference and reference_text is None:
                reference_text = candidate

            if candidate_unit and unit_text is None:
                unit_text = candidate

            if result_text is None and line_is_result(candidate):
                result_text = candidate

        parsed = make_lab_row(
            key=key,
            result_text=result_text,
            reference_text=reference_text,
            unit_text=unit_text,
            confidence=confidence,
        )

        if parsed:
            labs.append(parsed)

    labs_by_key: dict[str, dict] = {}

    for row in labs:
        key = lab_key(row)

        if key:
            labs_by_key[key] = row

    return order_labs(labs_by_key)


def parse_labs_from_text_lines(text: str) -> list[dict]:
    lines = [norm(line) for line in (text or "").splitlines() if norm(line)]

    if not lines:
        return []

    return parse_cbc_from_ordered_lines(lines, confidence=0.95)


def parse_labs_from_extraction_lines(extraction: dict[str, Any]) -> list[dict]:
    candidates: list[dict] = []

    # Prefer Document AI line order. It usually preserves row structure better than plain_text.
    for key, confidence in [
        ("lines_text", 1.25),
        ("lines", 1.15),
        ("plain_text", 0.90),
        ("text", 0.85),
    ]:
        lines = collect_lines_from_extraction(extraction, key)

        if lines:
            candidates.extend(parse_cbc_from_ordered_lines(lines, confidence=confidence))

    labs_by_key: dict[str, dict] = {}

    for row in candidates:
        key = lab_key(row)

        if not key:
            continue

        if key not in labs_by_key or quality_score(row) > quality_score(labs_by_key[key]):
            labs_by_key[key] = row

    return order_labs(labs_by_key)


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
            reference_range, _unit = split_reference_and_unit(value, key)

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
            _reference_range, unit = split_reference_and_unit(value, key)

            if unit:
                unit_text = value
                break

    return make_lab_row(
        key=key,
        result_text=result_text,
        reference_text=reference_text,
        unit_text=unit_text,
        confidence=0.80,
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

    for role in ["test", "result", "reference", "unit"]:
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
                reference_range, _unit = split_reference_and_unit(cell, key)

                if reference_range:
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
            confidence=0.99,
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

        labs.extend(parse_labs_from_table_rows_dynamic(table_rows))

    return labs


def parse_labs_from_google_extraction(extraction: dict[str, Any]) -> list[dict]:
    candidates: list[dict] = []

    candidates.extend(parse_labs_from_google_tables(extraction.get("tables") or []))

    # This is now the preferred path for Fundeni-style CBC PDFs.
    candidates.extend(parse_labs_from_extraction_lines(extraction))

    # Fallbacks only. Lower confidence means good line parsing wins during dedupe.
    candidates.extend(parse_labs_from_token_coordinates(extraction.get("words") or []))
    candidates.extend(parse_labs_from_text_lines(extraction.get("plain_text") or ""))
    candidates.extend(parse_labs_from_text_lines(extraction.get("text") or ""))

    labs_by_key: dict[str, dict] = {}

    for row in candidates:
        key = lab_key(row)

        if not key:
            continue

        if key not in labs_by_key or quality_score(row) > quality_score(labs_by_key[key]):
            labs_by_key[key] = row

    return order_labs(labs_by_key)