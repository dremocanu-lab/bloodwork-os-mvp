from pathlib import Path
import re

ocr_path = Path(r"C:\Users\dremo\mvp1\backend\app\parsers\ocr_table_parser.py")
bloodwork_path = Path(r"C:\Users\dremo\mvp1\backend\app\parsers\bloodwork_parser.py")
main_path = Path(r"C:\Users\dremo\mvp1\backend\app\main.py")

ocr = ocr_path.read_text(encoding="utf-8")
bloodwork = bloodwork_path.read_text(encoding="utf-8")
main = main_path.read_text(encoding="utf-8")


# ---------- ocr_table_parser.py fixes ----------

if "NULL_RESULT_TOKENS" not in ocr:
    ocr = ocr.replace(
        'ARROW_LOW_MARKERS = {"↓", "▼", "↘", "⬇", "➘"}\n',
        'ARROW_LOW_MARKERS = {"↓", "▼", "↘", "⬇", "➘"}\n'
        'NULL_RESULT_TOKENS = {"", "-", "--", "---", "—", "–", "___", "____", "nil", "n/a", "na", "null"}\n'
    )

if "def is_null_result_token" not in ocr:
    insert_after = '''def is_number(text: str | None) -> bool:
    if not text:
        return False

    return re.fullmatch(r"[-+]?\\d+(?:[.,]\\d+)?", str(text).strip()) is not None
'''
    helper = '''

def is_null_result_token(text: str | None) -> bool:
    if text is None:
        return True

    cleaned = str(text).strip().lower()
    cleaned = cleaned.replace("−", "-")
    cleaned = cleaned.replace("—", "-").replace("–", "-")

    return cleaned in NULL_RESULT_TOKENS or re.fullmatch(r"-{2,}", cleaned) is not None


def first_meaningful_after_test(row_words: list[dict], start_index: int) -> str:
    for word in row_words[start_index:]:
        text = clean_word(word.get("text"))
        if not text:
            continue

        # Ignore visual arrows/flags when deciding whether a row has a true value.
        if text in ARROW_HIGH_MARKERS or text in ARROW_LOW_MARKERS:
            continue

        return text

    return ""


def build_nil_lab_result(test_key: str, row_words: list[dict]) -> dict:
    reference_range = None
    unit = None

    numeric_words = []
    for word in row_words:
        text = clean_word(word.get("text"))
        if is_number(text):
            numeric_words.append(text)

    if len(numeric_words) >= 2:
        reference_range = f"{normalize_decimal(numeric_words[-2])} - {normalize_decimal(numeric_words[-1])}"

    for word in row_words:
        text = clean_word(word.get("text"))
        if looks_like_unit(text):
            unit = normalize_unit(text)
            break

    if not unit:
        if test_key.endswith("%"):
            unit = "%"
        elif test_key.endswith("#"):
            unit = "10^3/uL"

    result = build_lab_result(
        raw_test_name=test_key,
        value=None,
        flag=None,
        reference_range=reference_range,
        unit=unit,
        confidence=0.95,
    )
    result["value"] = None
    result["flag"] = None
    return result
'''
    ocr = ocr.replace(insert_after, insert_after + helper)

old_parse = '''def parse_row_by_coordinates(row_words: list[dict]) -> dict | None:
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
'''

new_parse = '''def parse_row_by_coordinates(row_words: list[dict]) -> dict | None:
    if not row_words:
        return None

    test_key, test_index = possible_test_key_from_row(row_words)

    if not test_key:
        return None

    words_after_test = row_words[test_index + 1 :]

    first_value_token = first_meaningful_after_test(row_words, test_index + 1)

    # Critical: rows such as MPV --- --- 9.0-17.0 must not steal the reference-range
    # number and call it a measured value. Keep the row, but store value as nil.
    if is_null_result_token(first_value_token):
        return build_nil_lab_result(test_key, row_words)

    numeric_words = []

    for word in words_after_test:
        text = clean_word(word.get("text"))

        if text == "7" and len(numeric_words) == 0:
            continue

        if is_number(text):
            numeric_words.append(word)

    if len(numeric_words) < 3:
        return build_nil_lab_result(test_key, row_words)

    value_word = numeric_words[0]
    low_word = numeric_words[1]
    high_word = numeric_words[2]
'''

ocr = ocr.replace(old_parse, new_parse)


# ---------- bloodwork_parser.py fixes ----------

if "NULL_RESULT_TOKENS" not in bloodwork:
    bloodwork = bloodwork.replace(
        'JUNK_TOKENS = {\n',
        'NULL_RESULT_TOKENS = {"", "-", "--", "---", "—", "–", "___", "____", "nil", "n/a", "na", "null"}\n\n'
        'JUNK_TOKENS = {\n'
    )

if "def is_null_result_token" not in bloodwork:
    insert_after = '''def is_number_token(token: str) -> bool:
    return re.fullmatch(r"[-+]?\\d+(?:[.,]\\d+)?", token.strip()) is not None
'''
    helper = '''

def is_null_result_token(token: str | None) -> bool:
    if token is None:
        return True

    cleaned = str(token).strip().lower()
    cleaned = cleaned.replace("−", "-")
    cleaned = cleaned.replace("—", "-").replace("–", "-")

    return cleaned in NULL_RESULT_TOKENS or re.fullmatch(r"-{2,}", cleaned) is not None


def build_nil_result(raw_test_name: str, reference_range: str | None = None, unit: str | None = None, confidence: float = 0.72) -> dict:
    result = build_lab_result(
        raw_test_name=raw_test_name,
        value=None,
        flag=None,
        reference_range=reference_range,
        unit=unit,
        confidence=confidence,
    )
    result["value"] = None
    result["flag"] = None
    return result
'''
    bloodwork = bloodwork.replace(insert_after, insert_after + helper)

old_token_section = '''        # Look ahead for the next 3 numbers. They are usually value, low, high.
        lookahead = tokens[i + 1 : i + 12]
        number_positions = []

        for offset, candidate in enumerate(lookahead):
            if is_number_token(candidate):
                number_positions.append((offset, candidate))
                if len(number_positions) >= 3:
                    break

        if len(number_positions) < 3:
            i += 1
            continue
'''

new_token_section = '''        # Look ahead for the next 3 numbers. They are usually value, low, high.
        # If the row starts with --- / nil / blank markers, do not steal reference-range
        # numbers and pretend they are measured values.
        lookahead = tokens[i + 1 : i + 12]

        first_non_arrow_token = None
        for candidate in lookahead:
            if candidate in ARROW_HIGH_MARKERS or candidate in ARROW_LOW_MARKERS:
                continue
            first_non_arrow_token = candidate
            break

        if is_null_result_token(first_non_arrow_token):
            unit = None
            if test_key.endswith("%"):
                unit = "%"
            elif test_key.endswith("#"):
                unit = "10^3/uL"

            result = build_nil_result(test_key, reference_range=None, unit=unit, confidence=0.76)
            dedupe_key = result["canonical_name"] or result["display_name"] or test_key

            if dedupe_key not in seen:
                seen.add(dedupe_key)
                labs.append(result)

            i += 1
            continue

        number_positions = []

        for offset, candidate in enumerate(lookahead):
            if is_number_token(candidate):
                number_positions.append((offset, candidate))
                if len(number_positions) >= 3:
                    break

        if len(number_positions) < 3:
            result = build_nil_result(test_key, reference_range=None, unit=None, confidence=0.68)
            dedupe_key = result["canonical_name"] or result["display_name"] or test_key

            if dedupe_key not in seen:
                seen.add(dedupe_key)
                labs.append(result)

            i += 1
            continue
'''

bloodwork = bloodwork.replace(old_token_section, new_token_section)

old_wrapped_section = '''        window = " ".join(cleaned_lines[idx + 1 : idx + 6])
        numbers = re.findall(r"[-+]?\\d+(?:[.,]\\d+)?", window)

        if len(numbers) < 3:
            continue
'''

new_wrapped_section = '''        following_lines = cleaned_lines[idx + 1 : idx + 6]
        first_following = following_lines[0] if following_lines else ""

        if is_null_result_token(first_following):
            result = build_nil_result(name, reference_range=None, unit=None, confidence=0.74)
            dedupe_key = result["canonical_name"] or result["display_name"] or name

            if dedupe_key not in seen:
                seen.add(dedupe_key)
                labs.append(result)

            continue

        window = " ".join(following_lines)
        numbers = re.findall(r"[-+]?\\d+(?:[.,]\\d+)?", window)

        if len(numbers) < 3:
            result = build_nil_result(name, reference_range=None, unit=None, confidence=0.66)
            dedupe_key = result["canonical_name"] or result["display_name"] or name

            if dedupe_key not in seen:
                seen.add(dedupe_key)
                labs.append(result)

            continue
'''

bloodwork = bloodwork.replace(old_wrapped_section, new_wrapped_section)


# ---------- main.py trends endpoint hardening ----------

if "def lab_value_to_float" not in main:
    helper = r'''
def lab_value_to_float(value) -> float | None:
    if value is None:
        return None

    cleaned = str(value).strip().lower()
    cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.replace("−", "-")
    cleaned = cleaned.replace("—", "-").replace("–", "-")

    if cleaned in {"", "-", "--", "---", "nil", "n/a", "na", "null", "none"}:
        return None

    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)

    if not match:
        return None

    try:
        return float(match.group(0))
    except Exception:
        return None
'''
    if "import re\n" not in main:
        main = main.replace("import shutil\n", "import shutil\nimport re\n")
    main = main.replace("\ndef serialize_lab_result(lab):", "\n" + helper.strip() + "\n\n\ndef serialize_lab_result(lab):")

# If your current endpoint already has numeric parsing, this replacement safely adds last-5 and nil filtering.
main = main.replace(
    "value = float(str(lab.value).replace(\",\", \".\"))",
    "value = lab_value_to_float(lab.value)\n            if value is None:\n                continue"
)

main = main.replace(
    "value = float(lab.value)",
    "value = lab_value_to_float(lab.value)\n            if value is None:\n                continue"
)

main = main.replace(
    ".sort(key=lambda point: point[\"date\"])",
    ".sort(key=lambda point: point[\"date\"])\n        points = points[-5:]"
)

main = main.replace(
    ".sort(key=lambda item: item[\"date\"])",
    ".sort(key=lambda item: item[\"date\"])\n        points = points[-5:]"
)


ocr_path.write_text(ocr, encoding="utf-8")
bloodwork_path.write_text(bloodwork, encoding="utf-8")
main_path.write_text(main, encoding="utf-8")

print("Fixed nil lab values and hardened trends against fake numeric values.")
