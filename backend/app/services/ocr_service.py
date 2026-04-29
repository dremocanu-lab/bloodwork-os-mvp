import os
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pytesseract import Output

from app.services.google_document_ai_service import (
    get_document_ai_debug_config,
    is_google_document_ai_configured,
    process_with_google_document_ai,
)


tesseract_cmd = os.getenv("TESSERACT_CMD")
if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def get_ocr_provider() -> str:
    return (os.getenv("OCR_PROVIDER") or "tesseract").strip().lower()


def ocr_failed_response(method: str, warnings: list[str]) -> dict:
    return {
        "text": "",
        "words": [],
        "method": method,
        "warnings": [
            *warnings,
            "No OCR text could be extracted. Manual review is required.",
        ],
    }


def preprocess_image_for_ocr(file_path: Path) -> Image.Image:
    image = Image.open(file_path).convert("RGB")
    image = ImageOps.grayscale(image)
    image = ImageEnhance.Contrast(image).enhance(1.4)
    image = image.filter(ImageFilter.SHARPEN)

    width, height = image.size

    if width < 1800:
        scale = 1800 / max(width, 1)
        new_size = (int(width * scale), int(height * scale))
        image = image.resize(new_size)

    return image


def safe_image_to_string(image: Image.Image, lang: str = "ron+eng") -> str:
    try:
        return pytesseract.image_to_string(
            image,
            lang=lang,
            config="--oem 3 --psm 6",
        )
    except Exception:
        return pytesseract.image_to_string(
            image,
            lang="eng",
            config="--oem 3 --psm 6",
        )


def safe_image_to_data(image: Image.Image, page_index: int = 0, lang: str = "ron+eng") -> list[dict]:
    try:
        data = pytesseract.image_to_data(
            image,
            lang=lang,
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
                "ocr_config": "tesseract_psm6",
            }
        )

    return words


def group_words_into_lines(words: list[dict]) -> str:
    if not words:
        return ""

    grouped: dict[tuple[int, int, int, int], list[dict]] = {}

    for word in words:
        key = (
            int(word.get("page", 0)),
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


def extract_tesseract_from_image_object(image: Image.Image, page_index: int = 0) -> dict:
    text = safe_image_to_string(image)
    words = safe_image_to_data(image, page_index=page_index)
    rebuilt_lines = group_words_into_lines(words)

    if rebuilt_lines:
        text = f"{text}\n\n--- TESSERACT POSITIONAL ROWS ---\n{rebuilt_lines}"

    return {
        "text": text.strip(),
        "words": words,
    }


def extract_text_from_pdf(file_path: Path) -> str:
    text_parts: list[str] = []

    pdf_document = fitz.open(file_path)

    try:
        for page in pdf_document:
            text_parts.append(page.get_text())
    finally:
        pdf_document.close()

    return "\n".join(text_parts).strip()


def extract_tesseract_from_scanned_pdf(file_path: Path, temp_dir: Path) -> dict:
    text_parts: list[str] = []
    all_words: list[dict] = []

    pdf_document = fitz.open(file_path)

    try:
        for page_index in range(len(pdf_document)):
            page = pdf_document.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)

            temp_image_path = temp_dir / f"temp_ocr_page_{page_index}.png"
            pix.save(str(temp_image_path))

            try:
                image = preprocess_image_for_ocr(temp_image_path)
                result = extract_tesseract_from_image_object(image, page_index=page_index)

                text_parts.append(result["text"])
                all_words.extend(result["words"])
            finally:
                if temp_image_path.exists():
                    temp_image_path.unlink()

    finally:
        pdf_document.close()

    return {
        "text": "\n\n".join(text_parts).strip(),
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


def extract_text_with_tesseract(file_path: Path, filename: str, temp_dir: Path) -> dict:
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

        ocr_result = extract_tesseract_from_scanned_pdf(file_path, temp_dir)

        return {
            "text": ocr_result["text"],
            "words": ocr_result["words"],
            "method": "tesseract_pdf_ocr",
            "warnings": ["PDF text layer was weak or missing, Tesseract OCR fallback was used."],
        }

    if lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        image = preprocess_image_for_ocr(file_path)
        result = extract_tesseract_from_image_object(image, page_index=0)

        return {
            "text": result["text"],
            "words": result["words"],
            "method": "tesseract_image_ocr",
            "warnings": ["Tesseract image OCR was used."],
        }

    return {
        "text": "",
        "words": [],
        "method": "unsupported",
        "warnings": ["Unsupported file type for OCR/text extraction."],
    }


def extract_text(file_path: Path, filename: str, temp_dir: Path) -> dict:
    provider = get_ocr_provider()

    if provider == "google_document_ai":
        if not is_google_document_ai_configured():
            return ocr_failed_response(
                method="google_document_ai_not_configured",
                warnings=[
                    "OCR_PROVIDER is google_document_ai, but Google Document AI environment variables are missing.",
                    f"Current config: {get_document_ai_debug_config()}",
                ],
            )

        try:
            return process_with_google_document_ai(file_path=file_path, filename=filename)
        except Exception as google_error:
            try:
                fallback = extract_text_with_tesseract(file_path, filename, temp_dir)
                fallback["warnings"] = [
                    f"Google Document AI failed. Error: {str(google_error)}",
                    *fallback.get("warnings", []),
                ]
                return fallback
            except Exception as tesseract_error:
                return ocr_failed_response(
                    method="ocr_failed",
                    warnings=[
                        f"Google Document AI failed. Error: {str(google_error)}",
                        f"Tesseract fallback also failed. Error: {str(tesseract_error)}",
                        f"Current Google Document AI config: {get_document_ai_debug_config()}",
                    ],
                )

    try:
        return extract_text_with_tesseract(file_path, filename, temp_dir)
    except Exception as tesseract_error:
        return ocr_failed_response(
            method="tesseract_failed",
            warnings=[
                f"Tesseract OCR failed. Error: {str(tesseract_error)}",
                "Set OCR_PROVIDER=google_document_ai and configure Google Document AI, or install Tesseract locally.",
            ],
        )


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