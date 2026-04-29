import re
from statistics import median

from app.parsers.bloodwork_parser import (
    ARROW_HIGH_MARKERS,
    ARROW_LOW_MARKERS,
    BLANK_PRONE_TESTS,
    KNOWN_TEST_ALIASES,
    build_lab_result,
    build_nil_result,
    choose_value_low_high,
    clean_unit,
    extract_flag_from_line,
    looks_like_unit,
    normalize_decimal,
    normalize_test_token,
    plausible_reference_range,
)


NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
NULL_MARKER_RE = re.compile(r"(^|\s)(?:-{2,}|_{2,}|—+|–+|nil|n/a|na|null)(?=$|\s)", re.IGNORECASE)


def clean_word(text: str | None) -> str:
    if text is None:
        return ""

    cleaned = str(text).strip()
    cleaned = cleaned.replace("│", "").replace("|", "")
    cleaned = cleaned.replace("¦", "").replace("·", "")
    cleaned = cleaned.replace("™", "").replace("®", "")
    cleaned = cleaned.replace("µ", "u").replace("μ", "u")
    cleaned = cleaned.strip()

    return cleaned


def is_number(text: str | None) -> bool:
    cleaned = normalize_decimal(clean_word(text))

    if cleaned is None:
        return False

    return NUMBER_RE.fullmatch(cleaned) is not None


def word_right(word: dict) -> float:
    return float(word.get("left", 0)) + float(word.get("width", 0))


def word_bottom(word: dict) -> float:
    return float(word.get("top", 0)) + float(word.get("height", 0))


def word_center_x(word: dict) -> float:
    return float(word.get("left", 0)) + float(word.get("width", 0)) / 2


def group_words_into_rows(words: list[dict]) -> list[list[dict]]:
    useful_words = []

    for word in words or []:
        text = clean_word(word.get("text"))

        if not text:
            continue

        try:
            conf = float(word.get("conf", 0))
        except Exception:
            conf = 0

        left = int(float(word.get("left", 0)))
        top = int(float(word.get("top", 0)))
        width = int(float(word.get("width", 0)))
        height = int(float(word.get("height", 0)))
        page = int(word.get("page", 0))

        if width <= 0 or height <= 0:
            continue

        useful_words.append(
            {
                **word,
                "text": text,
                "conf": conf,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "page": page,
                "x_center": left + width / 2,
                "y_center": top + height / 2,
            }
        )

    if not useful_words:
        return []

    rows: list[list[dict]] = []

    for page in sorted({word["page"] for word in useful_words}):
        page_words = [word for word in useful_words if word["page"] == page]
        heights = [word["height"] for word in page_words if word["height"] > 0]
        typical_height = median(heights) if heights else 12
        y_threshold = max(7, typical_height * 0.62)

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


def row_text(row_words: list[dict]) -> str:
    return " ".join(clean_word(word.get("text")) for word in row_words if clean_word(word.get("text")))


def segment_after_test(row_words: list[dict], test_index: int) -> str:
    return " ".join(clean_word(word.get("text")) for word in row_words[test_index + 1 :] if clean_word(word.get("text")))


def has_null_before_first_number(row_words: list[dict], test_index: int) -> bool:
    after = segment_after_test(row_words, test_index)
    after = after.replace("−", "-").replace("—", "-").replace("–", "-")

    number_match = NUMBER_RE.search(after)
    before = after if not number_match else after[: number_match.start()]

    return NULL_MARKER_RE.search(before.lower()) is not None


def normalize_numeric_cells(row_words: list[dict], test_index: int) -> list[dict]:
    """
    Turns OCR word boxes after the test name into numeric cells.

    Critical repair:
      ["5.4", "7", "3.93", "6.08"] can become 5.47, 3.93, 6.08
      because the parser keeps adjacent fragments instead of throwing away the 7.
    """
    numeric_words = []

    for word in row_words[test_index + 1 :]:
        text = clean_word(word.get("text"))

        if text in ARROW_HIGH_MARKERS or text in ARROW_LOW_MARKERS:
            continue

        if is_number(text):
            numeric_words.append(
                {
                    **word,
                    "number_text": normalize_decimal(text),
                    "left": float(word.get("left", 0)),
                    "right": word_right(word),
                    "top": float(word.get("top", 0)),
                    "height": float(word.get("height", 0)),
                }
            )

    if not numeric_words:
        return []

    merged = []
    i = 0

    while i < len(numeric_words):
        current = dict(numeric_words[i])
        current_text = str(current["number_text"])

        if i + 1 < len(numeric_words):
            next_cell = numeric_words[i + 1]
            next_text = str(next_cell["number_text"])

            gap = float(next_cell["left"]) - float(current["right"])
            max_height = max(float(current.get("height", 0)), float(next_cell.get("height", 0)), 1)
            close_enough = gap <= max(18, max_height * 1.25)

            if close_enough and next_text.isdigit() and len(next_text) == 1:
                if "." in current_text:
                    current["number_text"] = f"{current_text}{next_text}"
                    current["right"] = next_cell["right"]
                    i += 2
                    merged.append(current)
                    continue

                if current_text.isdigit():
                    current["number_text"] = f"{current_text}.{next_text}"
                    current["right"] = next_cell["right"]
                    i += 2
                    merged.append(current)
                    continue

        merged.append(current)
        i += 1

    return merged


def row_looks_like_missing_result(
    row_words: list[dict],
    test_index: int,
    numeric_cells: list[dict],
    test_key: str,
) -> bool:
    if has_null_before_first_number(row_words, test_index):
        return True

    if not numeric_cells:
        return True

    if len(numeric_cells) <= 2 and test_key in BLANK_PRONE_TESTS:
        return True

    if len(numeric_cells) <= 2:
        return True

    test_word = row_words[test_index]
    test_right = word_right(test_word)

    first_number = numeric_cells[0]
    first_left = float(first_number.get("left", 0))

    row_lefts = [float(word.get("left", 0)) for word in row_words]
    row_rights = [word_right(word) for word in row_words]
    row_width = max(row_rights) - min(row_lefts) if row_lefts and row_rights else 0

    distance_from_test = first_left - test_right

    if test_key in BLANK_PRONE_TESTS and row_width > 0 and distance_from_test > row_width * 0.38:
        return True

    return False


def extract_reference_and_unit_for_nil(test_key: str, row_words: list[dict]) -> tuple[str | None, str | None]:
    numbers = [normalize_decimal(clean_word(word.get("text"))) for word in row_words if is_number(clean_word(word.get("text")))]
    numbers = [number for number in numbers if number is not None]

    reference_range = None

    if len(numbers) >= 2:
        low = numbers[-2]
        high = numbers[-1]

        if plausible_reference_range(low, high):
            reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"

    unit = None

    for word in row_words:
        text = clean_word(word.get("text"))

        if looks_like_unit(text):
            unit = text
            break

    if not unit:
        if test_key.endswith("%"):
            unit = "%"
        elif test_key.endswith("#"):
            unit = "10^3/uL"

    return reference_range, clean_unit(unit)


def parse_row_by_coordinates(row_words: list[dict]) -> dict | None:
    if not row_words:
        return None

    test_key, test_index = possible_test_key_from_row(row_words)

    if not test_key:
        return None

    numeric_cells = normalize_numeric_cells(row_words, test_index)

    if row_looks_like_missing_result(row_words, test_index, numeric_cells, test_key):
        reference_range, unit = extract_reference_and_unit_for_nil(test_key, row_words)
        return build_nil_result(test_key, reference_range=reference_range, unit=unit, confidence=0.99)

    numbers = [str(cell["number_text"]) for cell in numeric_cells]
    value, low, high, consumed = choose_value_low_high(numbers)

    if value is None or low is None or high is None:
        reference_range, unit = extract_reference_and_unit_for_nil(test_key, row_words)
        return build_nil_result(test_key, reference_range=reference_range, unit=unit, confidence=0.9)

    reference_range = None

    if plausible_reference_range(low, high):
        reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"

    unit = None

    high_cell_index = min(consumed - 1, len(numeric_cells) - 1)
    high_cell = numeric_cells[high_cell_index]
    high_right = float(high_cell.get("right", 0))

    candidate_units = [
        word
        for word in row_words
        if float(word.get("left", 0)) >= high_right - 4 and looks_like_unit(clean_word(word.get("text")))
    ]

    if candidate_units:
        unit = clean_word(candidate_units[0].get("text"))

    if not unit:
        for word in row_words[test_index + 1 :]:
            text = clean_word(word.get("text"))

            if looks_like_unit(text):
                unit = text
                break

    if not unit:
        if test_key.endswith("%"):
            unit = "%"
        elif test_key.endswith("#"):
            unit = "10^3/uL"

    flag = extract_flag_from_line(row_text(row_words), value, reference_range)

    return build_lab_result(
        raw_test_name=test_key,
        value=value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.96,
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