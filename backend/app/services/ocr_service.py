import os
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageFilter, ImageOps
from pytesseract import Output


tesseract_cmd = os.getenv("TESSERACT_CMD")
if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def preprocess_image_for_ocr(file_path: Path) -> Image.Image:
    image = Image.open(file_path).convert("RGB")
    image = ImageOps.grayscale(image)
    image = image.filter(ImageFilter.SHARPEN)

    width, height = image.size

    if width < 1800:
        scale = 1800 / max(width, 1)
        new_size = (int(width * scale), int(height * scale))
        image = image.resize(new_size)

    return image


def extract_text_from_image_object(image: Image.Image) -> str:
    try:
        return pytesseract.image_to_string(
            image,
            lang="ron+eng",
            config="--oem 3 --psm 6",
        )
    except Exception:
        return pytesseract.image_to_string(
            image,
            lang="eng",
            config="--oem 3 --psm 6",
        )


def extract_ocr_words_from_image_object(image: Image.Image, page_index: int = 0) -> list[dict]:
    try:
        data = pytesseract.image_to_data(
            image,
            lang="ron+eng",
            config="--oem 3 --psm 6",
            output_type=Output.DICT,
        )
    except Exception:
        data = pytesseract.image_to_data(
            image,
            lang="eng",
            config="--oem 3 --psm 6",
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

        words.append(
            {
                "text": text,
                "conf": conf,
                "left": int(data["left"][index]),
                "top": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index]),
                "page": page_index,
                "block_num": int(data.get("block_num", [0])[index]),
                "par_num": int(data.get("par_num", [0])[index]),
                "line_num": int(data.get("line_num", [0])[index]),
                "word_num": int(data.get("word_num", [0])[index]),
            }
        )

    return words


def extract_text_from_image(file_path: Path) -> str:
    image = preprocess_image_for_ocr(file_path)
    return extract_text_from_image_object(image)


def extract_words_from_image(file_path: Path) -> list[dict]:
    image = preprocess_image_for_ocr(file_path)
    return extract_ocr_words_from_image_object(image, page_index=0)


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

    pdf_document = fitz.open(file_path)

    try:
        for page_index in range(len(pdf_document)):
            page = pdf_document.load_page(page_index)

            # 3x render gives Tesseract much better table-row OCR on scanned lab reports.
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)

            temp_image_path = temp_dir / f"temp_ocr_page_{page_index}.png"
            pix.save(str(temp_image_path))

            try:
                image = preprocess_image_for_ocr(temp_image_path)

                page_text = extract_text_from_image_object(image)
                text_parts.append(page_text)

                page_words = extract_ocr_words_from_image_object(image, page_index=page_index)
                all_words.extend(page_words)
            finally:
                if temp_image_path.exists():
                    temp_image_path.unlink()

    finally:
        pdf_document.close()

    return {
        "text": "\n".join(text_parts).strip(),
        "words": all_words,
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

        return {
            "text": ocr_result["text"],
            "words": ocr_result["words"],
            "method": "pdf_ocr",
            "warnings": ["PDF text layer was weak or missing, OCR fallback was used."],
        }

    if lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        image = preprocess_image_for_ocr(file_path)

        image_text = extract_text_from_image_object(image)
        image_words = extract_ocr_words_from_image_object(image, page_index=0)

        return {
            "text": image_text,
            "words": image_words,
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