import re
from statistics import median

from app.parsers.bloodwork_parser import (
    KNOWN_TEST_ALIASES,
    build_lab_result,
    infer_flag,
    normalize_decimal,
    normalize_test_token,
    to_float,
)


ARROW_HIGH_MARKERS = {"↑", "▲", "↗", "⬆", "➚"}
ARROW_LOW_MARKERS = {"↓", "▼", "↘", "⬇", "➘"}


def clean_word(text: str | None) -> str:
    if text is None:
        return ""

    cleaned = str(text).strip()
    cleaned = cleaned.replace("│", "").replace("|", "")
    cleaned = cleaned.replace("¦", "").replace("·", "")
    cleaned = cleaned.replace("™", "").replace("®", "")
    cleaned = cleaned.strip()

    return cleaned


def is_number(text: str | None) -> bool:
    if not text:
        return False

    return re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", str(text).strip()) is not None


def looks_like_unit(text: str | None) -> bool:
    if not text:
        return False

    cleaned = str(text).strip()
    lowered = cleaned.lower()

    if cleaned == "%":
        return True

    if "/" in cleaned:
        return True

    if "^" in cleaned:
        return True

    if re.fullmatch(r"10\^?\d+/?[uµμ]?[lL]?", cleaned):
        return True

    if re.fullmatch(r"10\d+/?[uµμ]?[lL]?", cleaned):
        return True

    return lowered in {
        "fl",
        "pg",
        "g/dl",
        "mg/dl",
        "mmol/l",
        "u/l",
        "/ul",
        "/µl",
        "/μl",
    }


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None

    cleaned = str(unit).strip()
    cleaned = cleaned.replace("µ", "u").replace("μ", "u")
    cleaned = cleaned.replace(" ", "")

    replacements = {
        "103/uL": "10^3/uL",
        "103/ul": "10^3/uL",
        "10^3/uL": "10^3/uL",
        "10^3/ul": "10^3/uL",
        "106/uL": "10^6/uL",
        "106/ul": "10^6/uL",
        "10^6/uL": "10^6/uL",
        "10^6/ul": "10^6/uL",
        "FL": "fL",
        "fl": "fL",
        "g/dl": "g/dL",
        "g/dL": "g/dL",
    }

    return replacements.get(cleaned, cleaned)


def fix_decimal_if_obvious(value: str | None, low: str | None, high: str | None) -> str | None:
    if value is None or low is None or high is None:
        return value

    raw = str(value).strip()
    low_f = to_float(low)
    high_f = to_float(high)

    if not raw.isdigit() or low_f is None or high_f is None:
        return value

    numeric = float(raw)

    if numeric > high_f and numeric / 10 <= high_f * 1.5:
        return str(numeric / 10).rstrip("0").rstrip(".")

    return value


def detect_arrow_flag(words: list[dict], value: str | None, reference_range: str | None) -> str:
    text = " ".join(clean_word(word.get("text")) for word in words)
    lowered = f" {text.lower()} "

    if any(marker in text for marker in ARROW_HIGH_MARKERS) or " high " in lowered:
        return "High"

    if any(marker in text for marker in ARROW_LOW_MARKERS) or " low " in lowered:
        return "Low"

    return infer_flag(value, reference_range)


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
        y_threshold = max(8, typical_height * 0.65)

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


def parse_row_by_coordinates(row_words: list[dict]) -> dict | None:
    if not row_words:
        return None

    test_key, test_index = possible_test_key_from_row(row_words)

    if not test_key:
        return None

    words_after_test = row_words[test_index + 1 :]

    numeric_words = []

    for word in words_after_test:
        text = clean_word(word.get("text"))

        if text == "7" and len(numeric_words) == 0:
            continue

        if is_number(text):
            numeric_words.append(word)

    if len(numeric_words) < 3:
        return None

    value_word = numeric_words[0]
    low_word = numeric_words[1]
    high_word = numeric_words[2]

    value = clean_word(value_word.get("text"))
    low = clean_word(low_word.get("text"))
    high = clean_word(high_word.get("text"))

    if test_key.endswith("%"):
        value = fix_decimal_if_obvious(value, low, high)

        low_f = to_float(low)
        high_f = to_float(high)

        if low_f is not None and high_f is not None and high_f > 100:
            low = str(low_f / 10).rstrip("0").rstrip(".")
            high = str(high_f / 10).rstrip("0").rstrip(".")

    reference_range = f"{normalize_decimal(low)} - {normalize_decimal(high)}"

    unit = None

    high_right = high_word["left"] + high_word["width"]

    candidate_units = [
        word
        for word in row_words
        if word["left"] >= high_right - 4 and looks_like_unit(clean_word(word.get("text")))
    ]

    if candidate_units:
        unit = clean_word(candidate_units[0].get("text"))

    if not unit:
        for word in words_after_test:
            text = clean_word(word.get("text"))
            if looks_like_unit(text):
                unit = text
                break

    if not unit:
        if test_key.endswith("%"):
            unit = "%"
        elif test_key.endswith("#"):
            unit = "10^3/uL"

    unit = normalize_unit(unit)

    flag = detect_arrow_flag(row_words, value, reference_range)

    return build_lab_result(
        raw_test_name=test_key,
        value=value,
        flag=flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.93,
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