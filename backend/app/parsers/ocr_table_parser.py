import re
from statistics import median

from app.parsers.bloodwork_parser import (
    ARROW_HIGH_MARKERS,
    ARROW_LOW_MARKERS,
    KNOWN_TEST_ALIASES,
    build_lab_result,
    build_nil_result,
    extract_flag_from_line,
    normalize_decimal,
    normalize_test_token,
    to_float,
)


NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
NULL_RE = re.compile(r"^(?:-{2,}|_{2,}|—+|–+|nil|n/a|na|null)$", re.IGNORECASE)

DEFAULT_UNITS = {
    "WBC": "10^3/uL",
    "RBC": "10^6/uL",
    "HGB": "g/dL",
    "HB": "g/dL",
    "HCT": "%",
    "MCV": "fL",
    "MCH": "pg",
    "MCHC": "g/dL",
    "PLT": "10^3/uL",
    "RDW": "%",
    "RDW-SD": "fL",
    "RDWSD": "fL",
    "RDW-CV": "%",
    "RDWCV": "%",
    "PDW": "fL",
    "MPV": "fL",
    "P-LCR": "%",
    "PLCR": "%",
    "PCT": "%",
    "NRBC#": "10^3/uL",
    "NRBC": "10^3/uL",
    "NRBC%": "%",
    "NEUT#": "10^3/uL",
    "NEUT": "10^3/uL",
    "NEUT%": "%",
    "LYMPH#": "10^3/uL",
    "LYMPH": "10^3/uL",
    "LYMPH%": "%",
    "MONO#": "10^3/uL",
    "MONO": "10^3/uL",
    "MONO%": "%",
    "EO#": "10^3/uL",
    "EO": "10^3/uL",
    "EO%": "%",
    "EOS#": "10^3/uL",
    "EOS": "10^3/uL",
    "EOS%": "%",
    "BASO#": "10^3/uL",
    "BASO": "10^3/uL",
    "BASO%": "%",
    "IG#": "10^3/uL",
    "IG": "10^3/uL",
    "IG%": "%",
}

BLANK_RESULT_TESTS = {
    "PDW",
    "MPV",
    "P-LCR",
    "PLCR",
    "PCT",
    "NRBC#",
    "NRBC",
    "NRBC%",
}


def clean_word(text: str | None) -> str:
    if text is None:
        return ""

    cleaned = str(text).strip()
    cleaned = cleaned.replace("│", "")
    cleaned = cleaned.replace("|", "")
    cleaned = cleaned.replace("¦", "")
    cleaned = cleaned.replace("·", "")
    cleaned = cleaned.replace("™", "")
    cleaned = cleaned.replace("®", "")
    cleaned = cleaned.replace("µ", "u")
    cleaned = cleaned.replace("μ", "u")
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

    cleaned = cleaned.replace("−", "-").replace("—", "-").replace("–", "-")

    return NULL_RE.fullmatch(cleaned) is not None


def word_right(word: dict) -> float:
    return float(word.get("left", 0)) + float(word.get("width", 0))


def word_center_x(word: dict) -> float:
    return float(word.get("left", 0)) + float(word.get("width", 0)) / 2


def word_center_y(word: dict) -> float:
    return float(word.get("top", 0)) + float(word.get("height", 0)) / 2


def default_unit_for_test(test_key: str) -> str | None:
    return DEFAULT_UNITS.get(normalize_test_token(test_key))


def clean_unit_from_text(text: str | None, test_key: str) -> str | None:
    if not text:
        return default_unit_for_test(test_key)

    cleaned = clean_word(text)
    cleaned = cleaned.replace(" ", "")
    cleaned = cleaned.replace("µ", "u").replace("μ", "u")

    if cleaned in {"%", "fL", "fl", "FL", "pg", "g/dL", "g/dl"}:
        if cleaned.lower() == "fl":
            return "fL"
        if cleaned.lower() == "g/dl":
            return "g/dL"
        return cleaned

    if re.search(r"10\s*\^?\s*3\s*/?\s*u?l", cleaned, re.IGNORECASE):
        return "10^3/uL"

    if re.search(r"10\s*\^?\s*6\s*/?\s*u?l", cleaned, re.IGNORECASE):
        return "10^6/uL"

    if re.fullmatch(r"\d+", cleaned):
        return default_unit_for_test(test_key)

    if "/" in cleaned and len(cleaned) <= 16:
        return cleaned

    return default_unit_for_test(test_key)


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


def extract_numbers_from_words(words: list[dict]) -> list[str]:
    numbers = []

    for word in words:
        text = clean_word(word.get("text"))

        if is_number(text):
            normalized = normalize_decimal(text)

            if normalized is not None:
                numbers.append(normalized)

    return numbers


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
            close_enough = gap <= max(16, max_height * 1.15)

            if close_enough and next_text.isdigit() and len(next_text) == 1:
                if "." in current_text:
                    current["number_text"] = f"{current_text}{next_text}"
                    current["right_f"] = next_cell["right_f"]
                    current["x"] = (float(current["left_f"]) + float(next_cell["right_f"])) / 2
                    i += 2
                    merged.append(current)
                    continue

                if current_text.isdigit():
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

        result.append(
            {
                **word,
                "number_text": normalize_decimal(text),
                "x": word_center_x(word),
                "left_f": float(word.get("left", 0)),
                "right_f": word_right(word),
            }
        )

    return merge_split_decimal_numbers(result)


def split_row_into_result_and_reference(
    row_words: list[dict],
    test_index: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    CBC table is visually:
      test name | result | reference range

    The safest rule:
      - first numeric cluster after test = result
      - everything far to the right = reference range cell
    """
    numbers = numeric_words_after_test(row_words, test_index)
    null_words = [word for word in row_words[test_index + 1 :] if is_null_marker(clean_word(word.get("text")))]

    if not numbers:
        return [], [], null_words

    result_number = numbers[0]
    result_x = float(result_number.get("x", 0))

    # Reference column is usually clearly to the right of the result column.
    # Use adaptive gap so 150 - 450 and 3.98 - 10.00 are captured as one reference cell.
    right_numbers = [
        number
        for number in numbers[1:]
        if float(number.get("x", 0)) > result_x + 70
    ]

    # If OCR is tight and the 70px gap misses it, fall back to next two numbers.
    if len(right_numbers) < 2 and len(numbers) >= 3:
        right_numbers = numbers[1:3]

    return [result_number], right_numbers[:2], null_words


def get_reference_range(reference_numbers: list[dict]) -> str | None:
    if len(reference_numbers) < 2:
        return None

    low = normalize_decimal(str(reference_numbers[0].get("number_text")))
    high = normalize_decimal(str(reference_numbers[1].get("number_text")))

    if low is None or high is None:
        return None

    low_float = to_float(low)
    high_float = to_float(high)

    if low_float is None or high_float is None:
        return None

    if high_float < low_float:
        low, high = high, low

    return f"{low} - {high}"


def detect_unit(row_words: list[dict], test_key: str, reference_numbers: list[dict]) -> str | None:
    if reference_numbers:
        ref_right = max(float(number.get("right_f", 0)) for number in reference_numbers)

        candidate_words = [
            word
            for word in row_words
            if float(word.get("left", 0)) >= ref_right - 4
        ]

        candidate_text = " ".join(clean_word(word.get("text")) for word in candidate_words)

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
            match = re.search(pattern, candidate_text, re.IGNORECASE)

            if match:
                return clean_unit_from_text(match.group(0), test_key)

    full_row = row_text(row_words)

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
        match = re.search(pattern, full_row, re.IGNORECASE)

        if match:
            return clean_unit_from_text(match.group(0), test_key)

    return default_unit_for_test(test_key)


def detect_flag(row_words: list[dict], value: str | None, reference_range: str | None) -> str | None:
    row = row_text(row_words)

    if any(marker in row for marker in ARROW_HIGH_MARKERS):
        return "High"

    if any(marker in row for marker in ARROW_LOW_MARKERS):
        return "Low"

    return extract_flag_from_line(row, value, reference_range)


def adjust_value_using_flag_and_reference(
    value: str | None,
    reference_range: str | None,
    flag: str | None,
) -> str | None:
    if value is None:
        return None

    value_float = to_float(value)

    if value_float is None:
        return value

    numbers = NUMBER_RE.findall(reference_range or "")

    if len(numbers) < 2:
        return value

    low = to_float(numbers[0])
    high = to_float(numbers[1])

    if low is None or high is None:
        return value

    if high < low:
        low, high = high, low

    flag_lower = (flag or "").lower()

    if flag_lower == "high" and value_float <= high:
        for multiplier in [10, 100]:
            candidate = value_float * multiplier

            if candidate > high and candidate < high * 5:
                return f"{candidate:.6f}".rstrip("0").rstrip(".")

    if flag_lower == "low" and value_float >= low:
        for divisor in [10, 100]:
            candidate = value_float / divisor

            if candidate < low and candidate > 0:
                return f"{candidate:.6f}".rstrip("0").rstrip(".")

    return value


def row_is_true_blank_result(test_key: str, result_numbers: list[dict], null_words: list[dict]) -> bool:
    if null_words and not result_numbers:
        return True

    if test_key in BLANK_RESULT_TESTS and not result_numbers:
        return True

    return False


def parse_row_by_coordinates(row_words: list[dict]) -> dict | None:
    test_key, test_index = possible_test_key_from_row(row_words)

    if not test_key:
        return None

    result_numbers, reference_numbers, null_words = split_row_into_result_and_reference(row_words, test_index)
    reference_range = get_reference_range(reference_numbers)
    unit = detect_unit(row_words, test_key, reference_numbers)

    if row_is_true_blank_result(test_key, result_numbers, null_words):
        return build_nil_result(
            raw_test_name=test_key,
            reference_range=reference_range,
            unit=unit,
            confidence=0.99,
        )

    if not result_numbers:
        return build_nil_result(
            raw_test_name=test_key,
            reference_range=reference_range,
            unit=unit,
            confidence=0.92,
        )

    value = normalize_decimal(str(result_numbers[0].get("number_text")))
    flag = detect_flag(row_words, value, reference_range)
    value = adjust_value_using_flag_and_reference(value, reference_range, flag)
    flag = detect_flag(row_words, value, reference_range)

    return build_lab_result(
        raw_test_name=test_key,
        value=value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.98,
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
