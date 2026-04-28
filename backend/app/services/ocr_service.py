import os
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pytesseract import Output


tesseract_cmd = os.getenv("TESSERACT_CMD")
if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


OCR_CONFIGS = [
    "--oem 3 --psm 6",
    "--oem 3 --psm 4",
    "--oem 3 --psm 11",
]


def preprocess_image_for_ocr(file_path: Path) -> Image.Image:
    image = Image.open(file_path).convert("RGB")

    image = ImageOps.grayscale(image)

    # Improve contrast for scanned hospital/lab PDFs.
    image = ImageEnhance.Contrast(image).enhance(1.6)
    image = image.filter(ImageFilter.SHARPEN)

    width, height = image.size

    if width < 2200:
        scale = 2200 / max(width, 1)
        new_size = (int(width * scale), int(height * scale))
        image = image.resize(new_size)

    return image


def lab_text_score(text: str) -> int:
    cleaned = (text or "").lower()

    keywords = [
        "wbc",
        "rbc",
        "hgb",
        "hct",
        "mcv",
        "mch",
        "mchc",
        "plt",
        "rdw",
        "neut",
        "lymph",
        "mono",
        "baso",
        "hemoglobina",
        "hematocrit",
        "leucocite",
        "eritrocite",
        "trombocite",
        "rezultat",
        "interval",
        "referinta",
        "referință",
    ]

    keyword_score = sum(12 for keyword in keywords if keyword in cleaned)
    digit_score = min(sum(ch.isdigit() for ch in cleaned), 300)
    length_score = min(len(cleaned) // 20, 150)

    return keyword_score + digit_score + length_score


def safe_image_to_string(image: Image.Image, config: str, lang: str = "ron+eng") -> str:
    try:
        return pytesseract.image_to_string(image, lang=lang, config=config)
    except Exception:
        return pytesseract.image_to_string(image, lang="eng", config=config)


def safe_image_to_data(image: Image.Image, config: str, page_index: int = 0, lang: str = "ron+eng") -> list[dict]:
    try:
        data = pytesseract.image_to_data(
            image,
            lang=lang,
            config=config,
            output_type=Output.DICT,
        )
    except Exception:
        data = pytesseract.image_to_data(
            image,
            lang="eng",
            config=config,
            output_type=Output.DICT,
        )

    words: list[dict] = []
    total = len(data.get("text", []))

    for index in range(total):
        text = (data["text"][index] or "").strip()

        if not text:
            continue

        try:
            conf = float(data["conf"][index])
        except Exception:
            conf = 0.0

        left = int(data["left"][index])
        top = int(data["top"][index])
        width = int(data["width"][index])
        height = int(data["height"][index])

        if width <= 0 or height <= 0:
            continue

        words.append(
            {
                "text": text,
                "conf": conf,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "page": page_index,
                "block_num": int(data.get("block_num", [0])[index]),
                "par_num": int(data.get("par_num", [0])[index]),
                "line_num": int(data.get("line_num", [0])[index]),
                "word_num": int(data.get("word_num", [0])[index]),
                "ocr_config": config,
            }
        )

    return words


def group_words_into_debug_lines(words: list[dict]) -> str:
    """
    Rebuild row-like text from OCR word positions.
    This gives the regex parser another chance when image_to_string is messy.
    """
    if not words:
        return ""

    grouped: dict[tuple[int, str, int, int, int], list[dict]] = {}

    for word in words:
        key = (
            int(word.get("page", 0)),
            str(word.get("ocr_config", "")),
            int(word.get("block_num", 0)),
            int(word.get("par_num", 0)),
            int(word.get("line_num", 0)),
        )
        grouped.setdefault(key, []).append(word)

    lines = []

    for key in sorted(grouped.keys()):
        row_words = grouped[key]
        row_words.sort(key=lambda item: int(item.get("left", 0)))

        line = " ".join(str(word.get("text", "")).strip() for word in row_words if str(word.get("text", "")).strip())
        line = line.strip()

        if line:
            lines.append(line)

    return "\n".join(lines)


def extract_text_and_words_from_image_object(image: Image.Image, page_index: int = 0) -> dict:
    text_candidates = []
    word_candidates = []

    for config in OCR_CONFIGS:
        page_text = safe_image_to_string(image, config=config)
        page_words = safe_image_to_data(image, config=config, page_index=page_index)

        rebuilt_lines = group_words_into_debug_lines(page_words)

        combined_text = page_text
        if rebuilt_lines:
            combined_text = f"{page_text}\n\n--- OCR ROWS {config} ---\n{rebuilt_lines}"

        text_candidates.append(
            {
                "config": config,
                "text": combined_text,
                "score": lab_text_score(combined_text),
            }
        )

        word_candidates.append(
            {
                "config": config,
                "words": page_words,
                "score": lab_text_score(combined_text),
            }
        )

    best_text = max(text_candidates, key=lambda item: item["score"]) if text_candidates else {"text": "", "config": ""}

    # Keep words from all configs, because one mode may see rows the other misses.
    all_words = []
    seen_word_keys = set()

    for candidate in sorted(word_candidates, key=lambda item: item["score"], reverse=True):
        for word in candidate["words"]:
            key = (
                word.get("page"),
                word.get("ocr_config"),
                word.get("text"),
                word.get("left"),
                word.get("top"),
                word.get("width"),
                word.get("height"),
            )

            if key in seen_word_keys:
                continue

            seen_word_keys.add(key)
            all_words.append(word)

    all_rebuilt_lines = group_words_into_debug_lines(all_words)

    final_text = best_text["text"]

    if all_rebuilt_lines:
        final_text = f"{final_text}\n\n--- ALL OCR POSITIONAL ROWS ---\n{all_rebuilt_lines}"

    return {
        "text": final_text.strip(),
        "words": all_words,
        "best_config": best_text.get("config"),
    }


def extract_text_from_image(file_path: Path) -> str:
    image = preprocess_image_for_ocr(file_path)
    result = extract_text_and_words_from_image_object(image, page_index=0)
    return result["text"]


def extract_words_from_image(file_path: Path) -> list[dict]:
    image = preprocess_image_for_ocr(file_path)
    result = extract_text_and_words_from_image_object(image, page_index=0)
    return result["words"]


def extract_text_from_pdf(file_path: Path) -> str:
    text_parts: list[str] = []

    pdf_document = fitz.open(file_path)

    try:
        for page in pdf_document:
            text_parts.append(page.get_text())
    finally:
        pdf_document.close()

    return "\n".join(text_parts).strip()


def extract_text_and_words_from_scanned_pdf(file_path: Path, temp_dir: Path) -> dict:
    text_parts: list[str] = []
    all_words: list[dict] = []
    best_configs: list[str] = []

    pdf_document = fitz.open(file_path)

    try:
        for page_index in range(len(pdf_document)):
            page = pdf_document.load_page(page_index)

            # Stronger render for hospital table scans.
            pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)

            temp_image_path = temp_dir / f"temp_ocr_page_{page_index}.png"
            pix.save(str(temp_image_path))

            try:
                image = preprocess_image_for_ocr(temp_image_path)
                result = extract_text_and_words_from_image_object(image, page_index=page_index)

                text_parts.append(result["text"])
                all_words.extend(result["words"])

                if result.get("best_config"):
                    best_configs.append(result["best_config"])
            finally:
                if temp_image_path.exists():
                    temp_image_path.unlink()

    finally:
        pdf_document.close()

    return {
        "text": "\n\n".join(text_parts).strip(),
        "words": all_words,
        "best_configs": best_configs,
    }


def looks_like_bad_text(text: str) -> bool:
    cleaned = (text or "").strip()

    if len(cleaned) < 80:
        return True

    letters = sum(ch.isalpha() for ch in cleaned)
    digits = sum(ch.isdigit() for ch in cleaned)
    useful_chars = letters + digits

    if useful_chars < 40:
        return True

    return False


def extract_text(file_path: Path, filename: str, temp_dir: Path) -> dict:
    lower_name = filename.lower()

    if lower_name.endswith(".pdf"):
        embedded_text = extract_text_from_pdf(file_path)

        if not looks_like_bad_text(embedded_text):
            return {
                "text": embedded_text,
                "words": [],
                "method": "pdf_text",
                "warnings": [],
            }

        ocr_result = extract_text_and_words_from_scanned_pdf(file_path, temp_dir)

        warning = "PDF text layer was weak or missing, OCR fallback was used."
        if ocr_result.get("best_configs"):
            warning += f" OCR configs used: {', '.join(ocr_result['best_configs'])}."

        return {
            "text": ocr_result["text"],
            "words": ocr_result["words"],
            "method": "pdf_ocr",
            "warnings": [warning],
        }

    if lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        image = preprocess_image_for_ocr(file_path)
        result = extract_text_and_words_from_image_object(image, page_index=0)

        return {
            "text": result["text"],
            "words": result["words"],
            "method": "image_ocr",
            "warnings": [],
        }

    return {
        "text": "",
        "words": [],
        "method": "unsupported",
        "warnings": ["Unsupported file type for OCR/text extraction."],
    }


def score_ocr_quality(text: str) -> dict:
    cleaned = (text or "").strip()

    if not cleaned:
        return {
            "score": 0.0,
            "level": "empty",
            "warnings": ["No text could be extracted from this document."],
        }

    letters = sum(ch.isalpha() for ch in cleaned)
    digits = sum(ch.isdigit() for ch in cleaned)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    lab_keywords = [
        "hemoglobin",
        "hemoglobina",
        "hemoglobină",
        "leucocyte",
        "leukocyte",
        "leucocite",
        "eritrocite",
        "creatinina",
        "creatinine",
        "glucoza",
        "glucose",
        "colesterol",
        "cholesterol",
        "trigliceride",
        "triglycerides",
        "tsh",
        "alt",
        "ast",
        "wbc",
        "rbc",
        "hgb",
        "hct",
        "plt",
        "mcv",
        "mch",
        "mchc",
        "neut",
        "lymph",
        "mono",
    ]

    lowered = cleaned.lower()
    keyword_hits = sum(1 for keyword in lab_keywords if keyword in lowered)

    score = 0.0

    if len(cleaned) >= 200:
        score += 0.25
    elif len(cleaned) >= 80:
        score += 0.15

    if letters >= 80:
        score += 0.2

    if digits >= 10:
        score += 0.2

    if len(lines) >= 5:
        score += 0.15

    if keyword_hits >= 3:
        score += 0.2
    elif keyword_hits >= 1:
        score += 0.1

    score = min(round(score, 2), 1.0)

    warnings = []

    if score < 0.4:
        warnings.append("OCR/text quality appears low. Manual review is recommended.")
    elif score < 0.7:
        warnings.append("OCR/text quality is moderate. Some fields may need review.")

    level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"

    return {
        "score": score,
        "level": level,
        "warnings": warnings,
    }