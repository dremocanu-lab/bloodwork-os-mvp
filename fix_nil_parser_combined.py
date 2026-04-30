from pathlib import Path
import re

path = Path(r"C:\Users\dremo\mvp1\backend\app\parsers\ocr_table_parser.py")
text = path.read_text(encoding="utf-8")

# 1) Make dashed blank values explicit nil tokens.
text = text.replace(
    'NULL_RESULT_TOKENS = {"", "-", "--", "---", "—", "–", "___", "____", "nil", "n/a", "na", "null"}',
    'NULL_RESULT_TOKENS = {"", "-", "--", "---", "----", "-----", "—", "–", "___", "____", "nil", "n/a", "na", "null"}',
)

# 2) Add stricter row helpers once.
helper = r'''
def word_right(word: dict) -> float:
    return float(word.get("left", 0)) + float(word.get("width", 0))


def row_numeric_words_after_test(row_words: list[dict], test_index: int) -> list[dict]:
    numbers = []

    for word in row_words[test_index + 1 :]:
        text = clean_word(word.get("text"))

        if is_number(text):
            numbers.append(word)

    return numbers


def has_explicit_nil_before_first_number(row_words: list[dict], test_index: int) -> bool:
    for word in row_words[test_index + 1 :]:
        text = clean_word(word.get("text"))

        if not text:
            continue

        if text in ARROW_HIGH_MARKERS or text in ARROW_LOW_MARKERS:
            continue

        if is_number(text):
            return False

        if is_null_result_token(text):
            return True

        compact = text.strip().lower().replace("−", "-").replace("—", "-").replace("–", "-")

        # OCR sometimes reads empty cells as ----, -----, ____, etc.
        if re.fullmatch(r"[_\-]{2,}", compact):
            return True

    return False


def row_looks_like_missing_result(row_words: list[dict], test_index: int, numeric_words: list[dict]) -> bool:
    if not numeric_words:
        return True

    if has_explicit_nil_before_first_number(row_words, test_index):
        return True

    test_word = row_words[test_index]
    test_right = word_right(test_word)

    first_number = numeric_words[0]
    first_number_left = float(first_number.get("left", 0))

    row_lefts = [float(word.get("left", 0)) for word in row_words]
    row_rights = [word_right(word) for word in row_words]
    row_width = max(row_rights) - min(row_lefts) if row_lefts and row_rights else 0

    distance_from_test = first_number_left - test_right

    # If the first number is far to the right, it is probably from the reference range,
    # not the measured result column. This fixes blank MPV/P-LCR-style rows.
    if row_width > 0 and distance_from_test > row_width * 0.42:
        return True

    # If the only numbers after the test name are reference-range numbers,
    # do not invent a measured value.
    if len(numeric_words) <= 2:
        return True

    return False
'''

if "def row_looks_like_missing_result" not in text:
    text = text.replace(
        "\ndef parse_row_by_coordinates(row_words: list[dict]) -> dict | None:",
        "\n" + helper.strip() + "\n\n\ndef parse_row_by_coordinates(row_words: list[dict]) -> dict | None:",
    )

# 3) Replace the fragile measured-value extraction block.
old_block = '''    words_after_test = row_words[test_index + 1 :]

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
'''

new_block = '''    words_after_test = row_words[test_index + 1 :]

    numeric_words = []

    for word in words_after_test:
        text = clean_word(word.get("text"))

        if text == "7" and len(numeric_words) == 0:
            continue

        if is_number(text):
            numeric_words.append(word)

    # Critical: rows such as MPV ---- 9.0-17.0 must not steal the reference-range
    # number and call it a measured value. Keep the row, but store value as nil.
    if row_looks_like_missing_result(row_words, test_index, numeric_words):
        return build_nil_lab_result(test_key, row_words)
'''

if old_block not in text:
    raise RuntimeError("Could not find the old numeric_words block in ocr_table_parser.py. The file may already be partially patched.")

text = text.replace(old_block, new_block, 1)

path.write_text(text, encoding="utf-8")
print("Patched OCR parser: dashed blanks stay nil and reference-range values are not stolen.")
