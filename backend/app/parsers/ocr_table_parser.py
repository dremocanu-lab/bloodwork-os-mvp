from __future__ import annotations

import re
from statistics import median

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
    normalize_reference_number,
    normalize_test_token,
    split_fused_reference_range,
    to_float,
)


NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
NULL_RE = re.compile(r"^(?:-{2,}|_{2,}|—+|–+|nil|n/a|na|null|none)$", re.IGNORECASE)


def clean_word(text: str | None) -> str:
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
    cleaned = cleaned.strip()

    return cleaned


def is_number(text: str | None) -> bool:
    cleaned = normalize_decimal(clean_word(text))

    if cleaned is None:
        return False

    return NUMBER_RE.fullmatch(cleaned) is not None


def is_null_marker(text: str | None) -> bool:
    cleaned = clean_word(text)

    if not cleaned:
        return False

    return NULL_RE.fullmatch(cleaned) is not None


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
        y_threshold = max(6, typical_height * 0.70)

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


def merge_split_decimal_numbers(number_words: list[dict]) -> list[dict]:
    merged = []
    i = 0

    while i < len(number_words):
        current = dict(number_words[i])
        current_text = str(current["number_text"])

        if i + 1 < len(number_words):
            next_cell = number_words[i + 1]
            next_text = str(next_cell["number_text"])

            gap = float(next_cell["left_f"]) - float(current["right_f"])
            max_height = max(float(current.get("height", 0)), float(next_cell.get("height", 0)), 1)
            close_enough = gap <= max(18, max_height * 1.25)

            if close_enough and next_text.isdigit() and len(next_text) == 1:
                if "." in current_text:
                    current["number_text"] = f"{current_text}{next_text}"
                    current["right_f"] = next_cell["right_f"]
                    current["x"] = (float(current["left_f"]) + float(next_cell["right_f"])) / 2
                    i += 2
                    merged.append(current)
                    continue

                if current_text.isdigit() and len(current_text) <= 2:
                    current["number_text"] = f"{current_text}.{next_text}"
                    current["right_f"] = next_cell["right_f"]
                    current["x"] = (float(current["left_f"]) + float(next_cell["right_f"])) / 2
                    i += 2
                    merged.append(current)
                    continue

        merged.append(current)
        i += 1

    return merged


def numeric_words_after_test(row_words: list[dict], test_index: int) -> list[dict]:
    test_word = row_words[test_index]
    test_right = word_right(test_word)

    result = []

    for word in row_words[test_index + 1 :]:
        if float(word.get("left", 0)) < test_right - 3:
            continue

        text = clean_word(word.get("text"))

        if not is_number(text):
            continue

        normalized = normalize_decimal(text)

        if normalized is None:
            continue

        result.append(
            {
                **word,
                "number_text": normalized,
                "x": word_center_x(word),
                "left_f": float(word.get("left", 0)),
                "right_f": word_right(word),
            }
        )

    return merge_split_decimal_numbers(result)


def split_row_into_result_and_reference(row_words: list[dict], test_index: int) -> tuple[list[dict], list[dict], list[dict]]:
    numbers = numeric_words_after_test(row_words, test_index)
    null_words = [word for word in row_words[test_index + 1 :] if is_null_marker(clean_word(word.get("text")))]

    if not numbers:
        return [], [], null_words

    # For Fundeni CBC rows:
    # first number after test = result
    # next two numbers = reference interval
    result_numbers = numbers[:1]
    reference_numbers = numbers[1:3]

    return result_numbers, reference_numbers, null_words


def get_reference_range(reference_numbers: list[dict], row_words: list[dict] | None = None) -> str | None:
    if len(reference_numbers) >= 2:
        low = normalize_reference_number(str(reference_numbers[0].get("number_text")))
        high = normalize_reference_number(str(reference_numbers[1].get("number_text")))

        if low is not None and high is not None:
            low_float = to_float(low)
            high_float = to_float(high)

            if low_float is not None and high_float is not None:
                if high_float < low_float:
                    low, high = high, low

                return f"{low} - {high}"

    if row_words:
        text = row_text(row_words)

        fused = split_fused_reference_range(text)

        if fused:
            return f"{fused[0]} - {fused[1]}"

        return extract_reference_range(text)

    return None


def detect_unit(row_words: list[dict], test_key: str, reference_numbers: list[dict]) -> str | None:
    row = row_text(row_words)

    explicit_patterns = [
        r"10\s*\^?\s*3\s*/?\s*u?l",
        r"10\s*\^?\s*6\s*/?\s*u?l",
        r"\bg\s*/\s*dL\b",
        r"\bg\s*/\s*dl\b",
        r"\bfL\b",
        r"\bFL\b",
        r"\bfl\b",
        r"\bpg\b",
        r"%",
    ]

    for pattern in explicit_patterns:
        match = re.search(pattern, row, re.IGNORECASE)

        if match:
            return clean_unit(match.group(0), test_key)

    return DEFAULT_CBC_UNITS.get(test_key)


def detect_flag(row_words: list[dict], value: str | None, reference_range: str | None) -> str | None:
    row = row_text(row_words)

    if any(marker in row for marker in ARROW_HIGH_MARKERS):
        return "High"

    if any(marker in row for marker in ARROW_LOW_MARKERS):
        return "Low"

    return infer_flag(value, reference_range)


def parse_row_by_coordinates(row_words: list[dict]) -> dict | None:
    test_key, test_index = possible_test_key_from_row(row_words)

    if not test_key:
        return None

    result_numbers, reference_numbers, null_words = split_row_into_result_and_reference(row_words, test_index)

    reference_range = get_reference_range(reference_numbers, row_words)
    unit = detect_unit(row_words, test_key, reference_numbers)

    if null_words and not result_numbers:
        return build_nil_result(
            raw_test_name=test_key,
            reference_range=reference_range,
            unit=unit,
            confidence=0.99,
        )

    if not result_numbers:
        return None

    value = normalize_decimal(str(result_numbers[0].get("number_text")))

    if value is None:
        return build_nil_result(
            raw_test_name=test_key,
            reference_range=reference_range,
            unit=unit,
            confidence=0.95,
        )

    flag = detect_flag(row_words, value, reference_range)

    return build_lab_result(
        raw_test_name=test_key,
        value=value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.98 if reference_range else 0.80,
    )


def parse_labs_from_ocr_words(words: list[dict]) -> list[dict]:
    rows = group_words_into_rows(words)
    labs: list[dict] = []
    seen: set[str] = set()

    for row in rows:
        parsed = parse_row_by_coordinates(row)

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