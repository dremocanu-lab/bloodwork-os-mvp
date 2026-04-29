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

    # Common OCR-fused ranges:
    # 3.936-08 -> 3.93 - 6.08
    # 34.151-0 -> 34.1 - 51.0
    # 11.217-5 -> 11.2 - 17.5
    # 35.146-3 -> 35.1 - 46.3
    # 11.614-4 -> 11.6 - 14.4
    # 19.353-1 -> 19.3 - 53.1
    match = re.fullmatch(r"(\d{1,3})\.(\d{2})(\d)-(\d{2})", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    match = re.fullmatch(r"(\d{1,3})\.(\d)(\d{2})-(\d)", compact)
    if match:
        return f"{match.group(1)}.{match.group(2)}", f"{match.group(3)}.{match.group(4)}"

    return None


def extract_reference_range(value: Any) -> str | None:
    text = remove_units(value).replace(",", ".")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")

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


def token_text(tokens: list[dict[str, Any]]) -> str:
    ordered = sorted(tokens, key=lambda token: token_left(token))
    return " ".join(norm(token.get("text")) for token in ordered if norm(token.get("text"))).strip()


def is_header_or_noise_text(text: str) -> bool:
    lowered = text.lower()

    return any(
        marker in lowered
        for marker in [
            "hemograma",
            "denumire",
            "rezultat",
            "interval biologic",
            "starea probei",
            "citomorfologie",
            "tip proba",
            "automatic",
        ]
    )


def get_all_tokens(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [token for token in words or [] if norm(token.get("text"))],
        key=lambda token: (
            int(token.get("page") or 0),
            token_top(token),
            token_left(token),
        ),
    )


def find_test_anchors(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []

    for token in tokens:
        text = norm(token.get("text"))
        key = detect_key(text)

        if not key:
            continue

        if is_header_or_noise_text(text):
            continue

        x, y = token_center(token)

        # Test names in this report are in the left half of the CBC table.
        # This prevents weird right-column fragments from becoming anchors.
        if x > 0.45:
            continue

        anchors.append(
            {
                "key": key,
                "token": token,
                "x": x,
                "y": y,
                "page": int(token.get("page") or 0),
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int]] = set()

    for anchor in anchors:
        bucket = int(anchor["y"] * 1000)
        marker = (anchor["page"], anchor["key"], bucket)

        if marker in seen:
            continue

        seen.add(marker)
        deduped.append(anchor)

    return deduped


def infer_table_columns(tokens: list[dict[str, Any]], anchors: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    result_xs: list[float] = []
    reference_xs: list[float] = []

    for anchor in anchors:
        page = anchor["page"]
        y = anchor["y"]
        anchor_x = anchor["x"]

        row_tokens = [
            token
            for token in tokens
            if int(token.get("page") or 0) == page
            and abs(token_center(token)[1] - y) <= 0.012
            and token_center(token)[0] > anchor_x
        ]

        for token in sorted(row_tokens, key=lambda item: token_left(item)):
            text = norm(token.get("text"))

            if cell_has_result_value(text):
                x, _ = token_center(token)
                result_xs.append(x)
                break

        for token in sorted(row_tokens, key=lambda item: token_left(item)):
            text = norm(token.get("text"))

            if looks_like_reference(text) or extract_unit(text):
                x, _ = token_center(token)
                reference_xs.append(x)
                break

    result_x = median(result_xs) if result_xs else None
    reference_x = median(reference_xs) if reference_xs else None

    return result_x, reference_x


def row_band_for_anchor(
    anchor: dict[str, Any],
    anchors: list[dict[str, Any]],
) -> tuple[float, float]:
    same_page = [
        item
        for item in anchors
        if item["page"] == anchor["page"]
    ]

    same_page = sorted(same_page, key=lambda item: item["y"])
    index = same_page.index(anchor)

    y = anchor["y"]

    if index > 0:
        previous_y = same_page[index - 1]["y"]
        top = (previous_y + y) / 2
    else:
        top = y - 0.012

    if index + 1 < len(same_page):
        next_y = same_page[index + 1]["y"]
        bottom = (y + next_y) / 2
    else:
        bottom = y + 0.012

    return top, bottom


def collect_tokens_for_anchor_row(
    anchor: dict[str, Any],
    anchors: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    top, bottom = row_band_for_anchor(anchor, anchors)
    anchor_x = anchor["x"]

    row_tokens = [
        token
        for token in tokens
        if int(token.get("page") or 0) == anchor["page"]
        and top <= token_center(token)[1] < bottom
        and token_center(token)[0] > anchor_x + 0.005
    ]

    return sorted(row_tokens, key=lambda token: token_left(token))


def choose_result_token(
    row_tokens: list[dict[str, Any]],
    result_x: float | None,
    reference_x: float | None,
) -> dict[str, Any] | None:
    candidates: list[tuple[float, dict[str, Any]]] = []

    for token in row_tokens:
        text = norm(token.get("text"))

        if not cell_has_result_value(text):
            continue

        x, _ = token_center(token)

        if reference_x is not None and x >= reference_x - 0.015:
            continue

        distance = abs(x - result_x) if result_x is not None else 0
        candidates.append((distance, token))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def build_reference_text_after_result(
    row_tokens: list[dict[str, Any]],
    result_token: dict[str, Any],
) -> str:
    result_x, _ = token_center(result_token)

    reference_tokens = [
        token
        for token in row_tokens
        if token_center(token)[0] > result_x + 0.01
    ]

    return token_text(reference_tokens)


def parse_labs_from_anchor_rows(words: list[dict[str, Any]]) -> list[dict]:
    tokens = get_all_tokens(words)
    anchors = find_test_anchors(tokens)

    if not anchors:
        return []

    result_x, reference_x = infer_table_columns(tokens, anchors)

    labs: list[dict] = []

    for anchor in anchors:
        row_tokens = collect_tokens_for_anchor_row(anchor, anchors, tokens)

        if not row_tokens:
            continue

        result_token = choose_result_token(
            row_tokens=row_tokens,
            result_x=result_x,
            reference_x=reference_x,
        )

        if result_token is None:
            continue

        result_text = norm(result_token.get("text"))
        reference_text = build_reference_text_after_result(row_tokens, result_token)

        parsed = make_lab_row(
            key=anchor["key"],
            result_text=result_text,
            reference_text=reference_text,
            unit_text=reference_text,
            confidence=0.985,
        )

        if parsed:
            labs.append(parsed)

    return labs


def table_row_to_cells(row: dict[str, Any]) -> list[str]:
    cells = row.get("cells", []) or []
    return [norm(cell.get("text") or "") for cell in cells]


def parse_labs_from_table_rows_strict(table_rows: list[list[str]]) -> list[dict]:
    labs: list[dict] = []

    for row in table_rows:
        clean_row = [norm(cell) for cell in row if norm(cell)]

        if not clean_row:
            continue

        key = None
        key_index = -1

        for index, cell in enumerate(clean_row):
            detected = detect_key(cell)

            if detected:
                key = detected
                key_index = index
                break

        if not key:
            continue

        after = clean_row[key_index + 1 :]

        if not after:
            continue

        result_text = None
        result_index = -1

        for index, cell in enumerate(after):
            if cell_has_result_value(cell):
                result_text = cell
                result_index = index
                break

        if result_text is None:
            continue

        reference_text = " ".join(after[result_index + 1 :])

        parsed = make_lab_row(
            key=key,
            result_text=result_text,
            reference_text=reference_text,
            unit_text=reference_text,
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

        labs.extend(parse_labs_from_table_rows_strict(table_rows))

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

    # Table cells first, anchor-row token parser second.
    # No sequential fallback. No plain-text fallback. No fabricated rows.
    candidates.extend(parse_labs_from_google_tables(extraction.get("tables") or []))
    candidates.extend(parse_labs_from_anchor_rows(extraction.get("words") or []))

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