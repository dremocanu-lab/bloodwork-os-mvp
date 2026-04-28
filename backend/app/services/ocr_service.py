import os
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageOps, ImageFilter


tesseract_cmd = os.getenv("TESSERACT_CMD")
if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def preprocess_image_for_ocr(file_path: Path) -> Image.Image:
    image = Image.open(file_path).convert("RGB")

    # Convert to grayscale
    image = ImageOps.grayscale(image)

    # Light denoising/sharpening. Conservative so we do not destroy lab text.
    image = image.filter(ImageFilter.SHARPEN)

    # Upscale small images for better OCR.
    width, height = image.size
    if width < 1600:
        scale = 1600 / max(width, 1)
        new_size = (int(width * scale), int(height * scale))
        image = image.resize(new_size)

    return image


def extract_text_from_image(file_path: Path) -> str:
    image = preprocess_image_for_ocr(file_path)

    try:
        return pytesseract.image_to_string(image, lang="ron+eng")
    except Exception:
        return pytesseract.image_to_string(image, lang="eng")


def extract_text_from_pdf(file_path: Path) -> str:
    text_parts: list[str] = []

    pdf_document = fitz.open(file_path)
    try:
        for page in pdf_document:
            text_parts.append(page.get_text())
    finally:
        pdf_document.close()

    return "\n".join(text_parts).strip()


def extract_text_from_scanned_pdf(file_path: Path, temp_dir: Path) -> str:
    text_parts: list[str] = []

    pdf_document = fitz.open(file_path)
    try:
        for page_index in range(len(pdf_document)):
            page = pdf_document.load_page(page_index)

            # Higher DPI improves OCR quality for scanned lab PDFs.
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)

            temp_image_path = temp_dir / f"temp_ocr_page_{page_index}.png"
            pix.save(str(temp_image_path))

            try:
                page_text = extract_text_from_image(temp_image_path)
                text_parts.append(page_text)
            finally:
                if temp_image_path.exists():
                    temp_image_path.unlink()

    finally:
        pdf_document.close()

    return "\n".join(text_parts).strip()


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
                "method": "pdf_text",
                "warnings": [],
            }

        ocr_text = extract_text_from_scanned_pdf(file_path, temp_dir)

        return {
            "text": ocr_text,
            "method": "pdf_ocr",
            "warnings": ["PDF text layer was weak or missing, OCR fallback was used."],
        }

    if lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        image_text = extract_text_from_image(file_path)

        return {
            "text": image_text,
            "method": "image_ocr",
            "warnings": [],
        }

    return {
        "text": "",
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