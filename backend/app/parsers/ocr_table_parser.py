from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from typing import Any

from app.parsers.bloodwork_parser import (
    ARROW_HIGH_MARKERS,
    ARROW_LOW_MARKERS,
    DEFAULT_CBC_UNITS,
    KNOWN_TEST_ALIASES,
    build_lab_result,
    build_nil_result,
    clean_unit,
    extract_reference_range,
    infer_flag,
    normalize_decimal,
    normalize_test_token,
)


NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
NULL_RE = re.compile(r"^(?:-{2,}|_{2,}|—+|–+|nil|n/a|na|null|none)$", re.IGNORECASE)


@dataclass
class PageColumns:
    page: int
    test_left: float
    result_left: float
    reference_left: float
    right_edge: float


def clean_word(text: Any) -> str:
    if text is None:
        return ""

    cleaned = str(text).strip()
    cleaned = cleaned.replace("\ufeff", "")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("│", "")
    cleaned = cleaned.replace("|", "")
    cleaned = cleaned.replace("¦", "")
    cleaned = cleaned.replace("·", "")
    cleaned = cleaned.replace("™", "")
    cleaned = cleaned.replace("®", "")
    cleaned = cleaned.replace("µ", "u")
    cleaned = cleaned.replace("μ", "u")
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


def is_number(text: Any) -> bool:
    cleaned = normalize_decimal(clean_word(text))

    if cleaned is None:
        return False

    return NUMBER_RE.fullmatch(cleaned) is not None


def is_null_marker(text: Any) -> bool:
    cleaned = clean_word(text)

    if not cleaned:
        return False

    return NULL_RE.fullmatch(cleaned) is not None


def word_left(word: dict) -> float:
    return float(word.get("left", 0))


def word_right(word: dict) -> float:
    return float(word.get("left", 0)) + float(word.get("width", 0))


def word_center_x(word: dict) -> float:
    return float(word.get("left", 0)) + float(word.get("width", 0)) / 2


def word_center_y(word: dict) -> float:
    return float(word.get("top", 0)) + float(word.get("height", 0)) / 2


def normalize_words(words: list[dict]) -> list[dict]:
    normalized = []

    for index, word in enumerate(words or []):
        text = clean_word(word.get("text"))

        if not text:
            continue

        try:
            left = float(word.get("left", 0))
            top = float(word.get("top", 0))
            width = float(word.get("width", 0))
            height = float(word.get("height", 0))
            page = int(word.get("page", 0))
            conf = float(word.get("conf", 0))
        except Exception:
            continue

        if width <= 0 or height <= 0:
            continue

        normalized.append(
            {
                **word,
                "text": text,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "page": page,
                "conf": conf,
                "index": index,
                "x_center": left + width / 2,
                "y_center": top + height / 2,
            }
        )

    return normalized


def group_words_into_rows(words: list[dict]) -> list[list[dict]]:
    useful_words = normalize_words(words)

    if not useful_words:
        return []

    rows: list[list[dict]] = []

    for page in sorted({word["page"] for word in useful_words}):
        page_words = [word for word in useful_words if word["page"] == page]
        heights = [word["height"] for word in page_words if word["height"] > 0]
        typical_height = median(heights) if heights else 12
        y_threshold = max(5, typical_height * 0.70)

        page_words.sort(key=lambda item: (item["y_center"], item["left"]))

        page_rows: list[list[dict]] = []

        for word in page_words:
            placed = False

            for row in page_rows:
                row_y = median([item["y_center"] for item in row])

                if abs(word["y_center"] - row_y) <= y_threshold:
                    row.append(word)
                    placed = True
                    break

            if not placed:
                page_rows.append([word])

        for row in page_rows:
            row.sort(key=lambda item: item["left"])
            rows.append(row)

    return rows


def row_text(row_words: list[dict]) -> str:
    return " ".join(clean_word(word.get("text")) for word in row_words if clean_word(word.get("text")))


def possible_test_key_from_row(row_words: list[dict]) -> tuple[str | None, int]:
    texts = [clean_word(word.get("text")) for word in row_words]

    for idx, text in enumerate(texts):
        token = normalize_test_token(text)

        if token in KNOWN_TEST_ALIASES:
            return token, idx

        if token == "RDW" and idx + 1 < len(texts):
            next_token = normalize_test_token(texts[idx + 1])

            if next_token in {"SD", "CV"}:
                return f"RDW-{next_token}", idx

        if token == "P" and idx + 1 < len(texts):
            next_token = normalize_test_token(texts[idx + 1])

            if next_token == "LCR":
                return "P-LCR", idx

    return None, -1


def page_words_from_rows(rows: list[list[dict]], page: int) -> list[dict]:
    output = []

    for row in rows:
        if row and int(row[0].get("page", 0)) == page:
            output.extend(row)

    return output


def find_header_column_x(page_words: list[dict], header_words: set[str]) -> float | None:
    candidates = []

    for word in page_words:
        token = clean_word(word.get("text")).upper()

        if token in header_words:
            candidates.append(word_center_x(word))

    if not candidates:
        return None

    return median(candidates)


def infer_columns_from_header(page: int, rows: list[list[dict]]) -> PageColumns | None:
    words = page_words_from_rows(rows, page)

    if not words:
        return None

    left_edge = min(word_left(word) for word in words)
    right_edge = max(word_right(word) for word in words)

    result_x = find_header_column_x(words, {"REZULTAT", "RESULT", "VALUE"})
    reference_x = find_header_column_x(
        words,
        {
            "INTERVAL",
            "REFERINTA",
            "REFERINȚĂ",
            "REFERENCE",
            "BIOLOGIC",
            "BIOLOGICĂ",
            "REF",
        },
    )

    if result_x is not None and reference_x is not None and reference_x > result_x:
        return PageColumns(
            page=page,
            test_left=left_edge,
            result_left=result_x - 30,
            reference_left=reference_x - 36,
            right_edge=right_edge,
        )

    return None


def infer_columns_from_lab_rows(page: int, rows: list[list[dict]]) -> PageColumns | None:
    result_x_values = []
    reference_x_values = []
    test_left_values = []
    right_values = []

    for row in rows:
        if not row or int(row[0].get("page", 0)) != page:
            continue

        test_key, test_index = possible_test_key_from_row(row)

        if not test_key or test_index < 0:
            continue

        numbers = []

        for word in row[test_index + 1 :]:
            if is_number(word.get("text")):
                numbers.append(word_center_x(word))

        # Normal row:
        # test | result | ref low | ref high | unit
        if len(numbers) >= 3:
            result_x_values.append(numbers[0])
            reference_x_values.append(numbers[1])
            test_left_values.append(word_left(row[test_index]))
            right_values.append(max(word_right(word) for word in row))

        # Blank result row:
        # test | --- | ref low | ref high | unit
        elif len(numbers) >= 2:
            null_words = [word for word in row[test_index + 1 :] if is_null_marker(word.get("text"))]

            if null_words:
                result_x_values.append(min(word_center_x(word) for word in null_words))
                reference_x_values.append(numbers[0])
                test_left_values.append(word_left(row[test_index]))
                right_values.append(max(word_right(word) for word in row))

    if not result_x_values or not reference_x_values:
        return None

    result_x = median(result_x_values)
    reference_x = median(reference_x_values)

    if reference_x <= result_x:
        return None

    return PageColumns(
        page=page,
        test_left=min(test_left_values) if test_left_values else 0,
        result_left=result_x - 26,
        reference_left=reference_x - 26,
        right_edge=max(right_values) if right_values else reference_x + 240,
    )


def build_page_columns(rows: list[list[dict]]) -> dict[int, PageColumns]:
    pages = sorted({int(row[0].get("page", 0)) for row in rows if row})
    output: dict[int, PageColumns] = {}

    for page in pages:
        columns = infer_columns_from_header(page, rows) or infer_columns_from_lab_rows(page, rows)

        if columns:
            output[page] = columns

    return output


def words_between_x(row_words: list[dict], left: float, right: float) -> list[dict]:
    return [word for word in row_words if word_center_x(word) >= left and word_center_x(word) < right]


def words_after_x(row_words: list[dict], left: float) -> list[dict]:
    return [word for word in row_words if word_center_x(word) >= left]


def extract_first_number_from_words(words: list[dict]) -> str | None:
    for word in words:
        text = clean_word(word.get("text"))

        if is_null_marker(text):
            continue

        if is_number(text):
            return normalize_decimal(text)

    text = " ".join(clean_word(word.get("text")) for word in words)
    match = NUMBER_RE.search(text)

    if not match:
        return None

    return normalize_decimal(match.group(0))


def words_have_null_marker(words: list[dict]) -> bool:
    return any(is_null_marker(word.get("text")) for word in words)


def extract_unit_from_text(text: str, test_key: str) -> str | None:
    unit_patterns = [
        (r"10\s*\^?\s*3\s*/?\s*u?l", "10^3/uL"),
        (r"10\s*\^?\s*6\s*/?\s*u?l", "10^6/uL"),
        (r"\bg\s*/\s*dL\b", "g/dL"),
        (r"\bg\s*/\s*dl\b", "g/dL"),
        (r"\bfL\b", "fL"),
        (r"\bFL\b", "fL"),
        (r"\bfl\b", "fL"),
        (r"\bpg\b", "pg"),
        (r"%", "%"),
    ]

    for pattern, normalized_unit in unit_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return normalized_unit

    return clean_unit(None, test_key)


def extract_reference_and_unit_from_words(
    words: list[dict],
    test_key: str,
) -> tuple[str | None, str | None]:
    """
    Reference column can be:
      3.98 - 10.00 10^3/uL
      3.93 - 6.08 10^6/uL
      11.2 - 17.5 g/dL
      34.1 - 51.0 %
      13.0 - 43.0 %
    This function separates:
      reference_range -> only numeric interval
      unit -> only unit
    """
    if not words:
        return None, clean_unit(None, test_key)

    text = " ".join(clean_word(word.get("text")) for word in words)
    text = text.replace(",", ".")
    unit = extract_unit_from_text(text, test_key)

    reference_range = extract_reference_range(text)

    if reference_range:
        return reference_range, unit

    numbers = []

    for word in words:
        if is_number(word.get("text")):
            parsed = normalize_decimal(word.get("text"))

            if parsed is not None:
                numbers.append(parsed)

    if len(numbers) >= 2:
        low = numbers[0]
        high = numbers[1]

        try:
            low_float = float(low)
            high_float = float(high)
        except Exception:
            low_float = None
            high_float = None

        if low_float is not None and high_float is not None:
            if high_float < low_float:
                low, high = high, low

            reference_range = f"{low} - {high}"

    return reference_range, unit


def detect_flag(row_words: list[dict], value: str | None, reference_range: str | None) -> str | None:
    row = row_text(row_words)

    if any(marker in row for marker in ARROW_HIGH_MARKERS):
        return "High"

    if any(marker in row for marker in ARROW_LOW_MARKERS):
        return "Low"

    return infer_flag(value, reference_range)


def parse_row_by_grid(row_words: list[dict], columns: PageColumns | None) -> dict | None:
    test_key, _test_index = possible_test_key_from_row(row_words)

    if not test_key:
        return None

    if columns is None:
        return parse_row_without_columns(row_words)

    result_words = words_between_x(row_words, columns.result_left, columns.reference_left)
    reference_words = words_after_x(row_words, columns.reference_left)

    result_value = extract_first_number_from_words(result_words)
    result_is_null = words_have_null_marker(result_words)

    reference_range, unit = extract_reference_and_unit_from_words(reference_words, test_key)

    if result_is_null or result_value is None:
        return build_nil_result(
            raw_test_name=test_key,
            reference_range=reference_range,
            unit=unit,
            confidence=0.98,
        )

    flag = detect_flag(row_words, result_value, reference_range)

    return build_lab_result(
        raw_test_name=test_key,
        value=result_value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.98 if reference_range else 0.82,
    )


def parse_row_without_columns(row_words: list[dict]) -> dict | None:
    test_key, test_index = possible_test_key_from_row(row_words)

    if not test_key:
        return None

    after_test = row_words[test_index + 1 :]

    null_positions = [word_center_x(word) for word in after_test if is_null_marker(word.get("text"))]
    number_words = [word for word in after_test if is_number(word.get("text"))]

    if null_positions and number_words:
        first_null = min(null_positions)
        first_number = min(word_center_x(word) for word in number_words)

        # Result is blank/---, numbers belong to reference range.
        if first_null <= first_number + 8:
            reference_range, unit = extract_reference_and_unit_from_words(number_words, test_key)

            return build_nil_result(
                raw_test_name=test_key,
                reference_range=reference_range,
                unit=unit,
                confidence=0.90,
            )

    if null_positions and not number_words:
        _, unit = extract_reference_and_unit_from_words(after_test, test_key)

        return build_nil_result(
            raw_test_name=test_key,
            reference_range=None,
            unit=unit,
            confidence=0.90,
        )

    if not number_words:
        return None

    result_value = normalize_decimal(number_words[0].get("text"))
    reference_range, unit = extract_reference_and_unit_from_words(number_words[1:], test_key)

    if result_value is None:
        return build_nil_result(
            raw_test_name=test_key,
            reference_range=reference_range,
            unit=unit,
            confidence=0.85,
        )

    flag = detect_flag(row_words, result_value, reference_range)

    return build_lab_result(
        raw_test_name=test_key,
        value=result_value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.78,
    )


def merge_duplicate_labs(existing: dict, candidate: dict) -> dict:
    def score(row: dict) -> float:
        total = float(row.get("confidence") or 0)

        if row.get("value") is not None:
            total += 0.40

        if row.get("reference_range"):
            total += 0.35

        if row.get("unit"):
            total += 0.15

        if row.get("flag") in {"High", "Low"}:
            total += 0.05

        return total

    return candidate if score(candidate) >= score(existing) else existing


def parse_labs_from_ocr_words(words: list[dict]) -> list[dict]:
    rows = group_words_into_rows(words)
    columns_by_page = build_page_columns(rows)

    labs_by_key: dict[str, dict] = {}

    for row in rows:
        if not row:
            continue

        page = int(row[0].get("page", 0))
        columns = columns_by_page.get(page)

        parsed = parse_row_by_grid(row, columns)

        if not parsed:
            continue

        key = parsed.get("canonical_name") or parsed.get("display_name") or parsed.get("raw_test_name")

        if not key:
            continue

        key = str(key).lower()

        if key in labs_by_key:
            labs_by_key[key] = merge_duplicate_labs(labs_by_key[key], parsed)
        else:
            labs_by_key[key] = parsed

    return list(labs_by_key.values())