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

CBC_KEY_RE = re.compile(
    r"^(WBC|RBC|HGB|HCT|MCV|MCHC|MCH|PLT|RDW[\s\-]?SD|RDW[\s\-]?CV|PDW|MPV|P[\s\-]?LCR|PCT|NRBC[#%]?|NEUT[#%]?|LYMPH[#%]?|MONO[#%]?|EO[#%]?|BASO[#%]?|IG[#%]?)$",
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
    (r"\bmg\s*/\s*dl\b", "mg/dL"),
    (r"\bmg\s*/\s*L\b", "mg/L"),
    (r"\bmmol\s*/\s*L\b", "mmol/L"),
    (r"\bumol\s*/\s*L\b", "umol/L"),
    (r"\bµmol\s*/\s*L\b", "umol/L"),
    (r"\bμmol\s*/\s*L\b", "umol/L"),
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
    key = normalize_test_token(value)
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

    if CBC_KEY_RE.fullmatch(text):
        return norm_key(text)

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
    text = norm(value).lower()
    return text in NULL_TEXT or re.fullmatch(r"[-_]{2,}", text or "") is not None


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

    return re.sub(r"\s+", " ", text).strip()


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

    # OCR-fused examples:
    # 3.936-08   -> 3.93 - 6.08
    # 34.151-0   -> 34.1 - 51.0
    # 11.217-5   -> 11.2 - 17.5
    # 35.146-3   -> 35.1 - 46.3
    # 11.614-4   -> 11.6 - 14.4
    # 19.353-1   -> 19.3 - 53.1
    match = re.fullmatch(r"(\d{1,3})\.(\d{2})(\d)-(\d{2})", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    match = re.fullmatch(r"(\d{1,3})\.(\d)(\d{2})-(\d)", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    return None


def extract_reference_range(value: Any) -> str | None:
    text = remove_units(value).replace(",", ".")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")

    if not text:
        return None

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

    found = numbers(text)

    if len(found) >= 2:
        return format_range(found[0], found[1])

    return None


def split_reference_and_unit(value: Any) -> tuple[str | None, str | None]:
    text = norm(value)

    if not text:
        return None, None

    return extract_reference_range(text), extract_unit(text)


def extract_result(value: Any) -> str | None:
    text = norm(value)

    if is_null_value(text):
        return None

    found = numbers(text)

    if not found:
        return None

    return clean_number(found[0])


def looks_like_unit_only(value: Any) -> bool:
    text = norm(value)

    if not text:
        return False

    return extract_unit(text) is not None and len(numbers(remove_units(text))) == 0


def looks_like_reference(value: Any) -> bool:
    return extract_reference_range(value) is not None


def cell_has_result_value(value: Any) -> bool:
    text = norm(value)

    if is_null_value(text):
        return True

    if looks_like_unit_only(text):
        return False

    if looks_like_reference(text):
        return False

    found = numbers(text)
    return len(found) == 1


def make_lab_row(
    key: str,
    result_text: str | None,
    reference_text: str | None,
    unit_text: str | None,
    confidence: float,
) -> dict | None:
    value = extract_result(result_text or "")

    reference_range, unit_from_reference = split_reference_and_unit(reference_text or "")
    _reference_from_unit_cell, unit_from_unit_cell = split_reference_and_unit(unit_text or "")

    unit = (
        unit_from_unit_cell
        or unit_from_reference
        or extract_unit(unit_text or "")
        or extract_unit(reference_text or "")
        or extract_unit(result_text or "")
    )

    if value is None:
        return build_nil_result(
            raw_test_name=key,
            reference_range=reference_range,
            unit=unit,
            confidence=confidence,
        )

    flag = infer_flag(value, reference_range)

    return build_lab_result(
        raw_test_name=key,
        value=value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=confidence,
    )


def token_left(token: dict[str, Any]) -> float:
    return float(token.get("left") or 0)


def token_top(token: dict[str, Any]) -> float:
    return float(token.get("top") or 0)


def token_width(token: dict[str, Any]) -> float:
    return float(token.get("width") or 0)


def token_height(token: dict[str, Any]) -> float:
    return float(token.get("height") or 0)


def token_center(token: dict[str, Any]) -> tuple[float, float]:
    return token_left(token) + token_width(token) / 2, token_top(token) + token_height(token) / 2


def get_tokens(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens = []

    for token in words or []:
        text = norm(token.get("text"))

        if not text:
            continue

        copy = dict(token)
        copy["text"] = text
        tokens.append(copy)

    return sorted(
        tokens,
        key=lambda token: (
            int(token.get("page") or 0),
            token_top(token),
            token_left(token),
        ),
    )


def coordinate_stats(tokens: list[dict[str, Any]]) -> dict[str, float]:
    xs = [token_center(token)[0] for token in tokens]
    ys = [token_center(token)[1] for token in tokens]
    heights = [token_height(token) for token in tokens if token_height(token) > 0]

    max_x = max(xs) if xs else 1.0
    max_y = max(ys) if ys else 1.0
    med_h = median(heights) if heights else (0.01 if max_y <= 2 else 8.0)

    normalized = max_x <= 2 and max_y <= 2

    return {
        "max_x": max_x,
        "max_y": max_y,
        "med_h": med_h,
        "normalized": 1.0 if normalized else 0.0,
        "row_tol": max(0.007, med_h * 0.90) if normalized else max(5.0, med_h * 0.90),
        "x_gap": max(0.003, max_x * 0.002) if normalized else max(2.0, max_x * 0.002),
    }


def group_tokens_into_visual_rows(tokens: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    stats = coordinate_stats(tokens)
    row_tol = stats["row_tol"]

    rows_by_page: dict[int, list[list[dict[str, Any]]]] = {}

    for token in tokens:
        page = int(token.get("page") or 0)
        _x, y = token_center(token)

        page_rows = rows_by_page.setdefault(page, [])
        best_row = None
        best_distance = None

        for row in page_rows:
            row_y = median([token_center(item)[1] for item in row])
            distance = abs(y - row_y)

            if distance <= row_tol and (best_distance is None or distance < best_distance):
                best_row = row
                best_distance = distance

        if best_row is None:
            page_rows.append([token])
        else:
            best_row.append(token)

    all_rows: list[list[dict[str, Any]]] = []

    for page in sorted(rows_by_page):
        for row in rows_by_page[page]:
            row.sort(key=lambda token: token_left(token))
            all_rows.append(row)

    all_rows.sort(
        key=lambda row: (
            int(row[0].get("page") or 0),
            median([token_center(token)[1] for token in row]),
        )
    )

    return all_rows


def row_text(row: list[dict[str, Any]]) -> str:
    return " ".join(norm(token.get("text")) for token in row if norm(token.get("text")))


def is_header_or_noise_row(row: list[dict[str, Any]]) -> bool:
    text = row_text(row).lower()

    return any(
        marker in text
        for marker in [
            "hemograma",
            "denumire analiza",
            "denumire analiză",
            "rezultat",
            "interval biologic",
            "starea probei",
            "citomorfologie",
            "tip proba",
            "tip probă",
            "automatic",
            "automat",
        ]
    )


def find_key_in_row(row: list[dict[str, Any]]) -> tuple[int, str] | None:
    for index, token in enumerate(row):
        key = detect_key(token.get("text"))

        if key:
            return index, key

    return None


def infer_result_column_x(rows: list[list[dict[str, Any]]]) -> float | None:
    xs: list[float] = []

    for row in rows:
        if is_header_or_noise_row(row):
            continue

        key_hit = find_key_in_row(row)

        if not key_hit:
            continue

        key_index, _key = key_hit
        key_x, _ = token_center(row[key_index])

        right_tokens = [
            token
            for token in row[key_index + 1 :]
            if token_center(token)[0] > key_x
        ]

        for token in right_tokens:
            text = norm(token.get("text"))

            if cell_has_result_value(text):
                x, _ = token_center(token)
                xs.append(x)
                break

    return median(xs) if xs else None


def infer_reference_column_x(rows: list[list[dict[str, Any]]]) -> float | None:
    xs: list[float] = []

    for row in rows:
        if is_header_or_noise_row(row):
            continue

        key_hit = find_key_in_row(row)

        if not key_hit:
            continue

        key_index, _key = key_hit
        key_x, _ = token_center(row[key_index])

        for token in row[key_index + 1 :]:
            x, _ = token_center(token)

            if x <= key_x:
                continue

            text = norm(token.get("text"))

            if looks_like_reference(text) or extract_unit(text):
                xs.append(x)
                break

    return median(xs) if xs else None


def token_join(tokens: list[dict[str, Any]]) -> str:
    ordered = sorted(tokens, key=lambda token: token_left(token))
    return " ".join(norm(token.get("text")) for token in ordered if norm(token.get("text"))).strip()


def choose_result_token(
    row: list[dict[str, Any]],
    start_index: int,
    result_x: float | None,
    reference_x: float | None,
) -> dict[str, Any] | None:
    candidates: list[tuple[float, float, dict[str, Any]]] = []

    key_x, _ = token_center(row[start_index])

    for token in row[start_index + 1 :]:
        text = norm(token.get("text"))

        if not cell_has_result_value(text):
            continue

        x, _ = token_center(token)

        if x <= key_x:
            continue

        # This is the key guard: never let the reference/unit column become the result.
        if reference_x is not None and x >= reference_x:
            continue

        column_distance = abs(x - result_x) if result_x is not None else 0.0
        left_to_right = x

        candidates.append((column_distance, left_to_right, token))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def build_reference_text(
    row: list[dict[str, Any]],
    result_token: dict[str, Any],
) -> str:
    result_x, _ = token_center(result_token)

    tokens = [
        token
        for token in row
        if token_center(token)[0] > result_x
        and token is not result_token
    ]

    return token_join(tokens)


def parse_visual_row(
    row: list[dict[str, Any]],
    result_x: float | None,
    reference_x: float | None,
) -> dict | None:
    if is_header_or_noise_row(row):
        return None

    key_hit = find_key_in_row(row)

    if not key_hit:
        return None

    key_index, key = key_hit

    result_token = choose_result_token(
        row=row,
        start_index=key_index,
        result_x=result_x,
        reference_x=reference_x,
    )

    if result_token is None:
        return None

    result_text = norm(result_token.get("text"))
    reference_text = build_reference_text(row, result_token)

    return make_lab_row(
        key=key,
        result_text=result_text,
        reference_text=reference_text,
        unit_text=reference_text,
        confidence=0.985,
    )


def parse_labs_from_visual_token_rows(words: list[dict[str, Any]]) -> list[dict]:
    tokens = get_tokens(words)
    rows = group_tokens_into_visual_rows(tokens)

    if not rows:
        return []

    result_x = infer_result_column_x(rows)
    reference_x = infer_reference_column_x(rows)

    labs: list[dict] = []

    for row in rows:
        parsed = parse_visual_row(
            row=row,
            result_x=result_x,
            reference_x=reference_x,
        )

        if parsed:
            labs.append(parsed)

    return labs


def table_row_to_cells(row: dict[str, Any]) -> list[str]:
    cells = row.get("cells", []) or []
    return [norm(cell.get("text") or "") for cell in cells]


def parse_table_cells_dynamic(row: list[str]) -> dict | None:
    cells = [norm(cell) for cell in row if norm(cell)]

    if not cells:
        return None

    key = None
    key_index = -1

    for index, cell in enumerate(cells):
        detected = detect_key(cell)

        if detected:
            key = detected
            key_index = index
            break

    if not key:
        return None

    after = cells[key_index + 1 :]

    if not after:
        return None

    result_index = -1
    result_text = None

    for index, cell in enumerate(after):
        if cell_has_result_value(cell):
            result_index = index
            result_text = cell
            break

    if result_index < 0 or result_text is None:
        return None

    reference_text = " ".join(after[result_index + 1 :])

    return make_lab_row(
        key=key,
        result_text=result_text,
        reference_text=reference_text,
        unit_text=reference_text,
        confidence=0.99,
    )


def parse_labs_from_google_tables(tables: list[dict[str, Any]]) -> list[dict]:
    labs: list[dict] = []

    for table in tables or []:
        for row in table.get("rows", []) or []:
            parsed = parse_table_cells_dynamic(table_row_to_cells(row))

            if parsed:
                labs.append(parsed)

    return labs


def lab_key(row: dict) -> str:
    key = row.get("raw_test_name") or row.get("canonical_name") or row.get("display_name") or ""
    return norm_key(str(key)).lower()


def quality_score(row: dict) -> float:
    score = float(row.get("confidence") or 0)

    if row.get("value") is not None:
        score += 0.5

    if row.get("reference_range"):
        score += 0.4

    if row.get("unit"):
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


def parse_labs_from_google_extraction(extraction: dict[str, Any]) -> list[dict]:
    candidates: list[dict] = []

    # Use both sources, but both are strict:
    # - Google table cells if available.
    # - Visual rows rebuilt from Google token coordinates.
    # No sequential fallback. No plain-text fallback. No invented rows.
    candidates.extend(parse_labs_from_google_tables(extraction.get("tables") or []))
    candidates.extend(parse_labs_from_visual_token_rows(extraction.get("words") or []))

    labs_by_key: dict[str, dict] = {}

    for row in candidates:
        key = lab_key(row)

        if not key:
            continue

        if key not in labs_by_key:
            labs_by_key[key] = row
            continue

        if quality_score(row) > quality_score(labs_by_key[key]):
            labs_by_key[key] = row

    return order_labs(labs_by_key)