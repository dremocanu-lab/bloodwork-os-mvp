from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from app.report_fields import extract_report_metadata
try:
    from app.services.discharge_layout_formatter import format_discharge_sections_with_ai
except Exception:
    format_discharge_sections_with_ai = None


def clean_discharge_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\ufeff", "")
    text = text.replace("\u00a0", " ")
    text = text.replace("Â·", "·").replace("Â", "")
    text = text.replace("â€™", "'")
    text = text.replace("â€œ", '"').replace("â€\x9d", '"')
    text = text.replace("â€“", "-").replace("â€”", "-")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_for_matching(value: Any) -> str:
    text = clean_discharge_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ș", "s").replace("ț", "t").replace("ă", "a").replace("â", "a").replace("î", "i")
    text = re.sub(r"[^a-z0-9%#./:+ -]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_best_ocr_text(extraction: dict[str, Any] | str) -> str:
    if isinstance(extraction, str):
        return clean_discharge_text(extraction)

    for field in ["plain_text", "text", "extracted_text", "debug_text"]:
        value = extraction.get(field)
        if isinstance(value, str) and value.strip():
            text = value
            break
    else:
        text = ""

    if "--- GOOGLE DOCUMENT AI PLAIN TEXT ---" in text:
        text = text.split("--- GOOGLE DOCUMENT AI PLAIN TEXT ---", 1)[1]
        next_marker = re.search(r"\n--- GOOGLE DOCUMENT AI [A-Z ]+ ---", text)
        if next_marker:
            text = text[: next_marker.start()]

    return clean_discharge_text(text)


DISCHARGE_HINTS = [
    "fisa de externare",
    "fișa de externare",
    "bilet de iesire",
    "bilet de ieșire",
    "scrisoare medicala",
    "scrisoare medicală",
    "externare",
    "epicriza",
    "epicriză",
    "data externarii",
    "data externării",
    "data eliberarii",
    "data eliberării",
    "diagnostic principal",
    "diagnostice secundare",
    "recomandari la externare",
    "recomandări la externare",
    "tratament recomandat",
    "discharge summary",
    "discharge diagnosis",
    "hospital course",
    "discharge medication",
]


def detect_discharge_document(extraction: dict[str, Any] | str) -> bool:
    text = normalize_for_matching(get_best_ocr_text(extraction))
    score = 0

    for hint in DISCHARGE_HINTS:
        if normalize_for_matching(hint) in text:
            score += 1

    return score >= 2


SECTION_ORDER = [
    "administrative_information",
    "diagnoses",
    "discharge_status",
    "epicriza",
    "investigations",
    "laboratory_normal",
    "laboratory_abnormal",
    "treatment_in_hospital",
    "recommended_treatment",
    "recommendations",
    "other",
]


SECTION_TITLES = {
    "administrative_information": "Administrative / admission information",
    "diagnoses": "Diagnoses / Diagnostic",
    "discharge_status": "Discharge status",
    "epicriza": "Epicriză / Clinical course",
    "investigations": "Investigations / Results",
    "laboratory_normal": "Laboratory values - normal",
    "laboratory_abnormal": "Laboratory values - abnormal",
    "treatment_in_hospital": "Treatment during admission",
    "recommended_treatment": "Recommended treatment / Discharge medication",
    "recommendations": "Recommendations / Follow-up",
    "other": "Other relevant clinical text",
}


# This is the important part:
# Only these are allowed to split the document into top-level sections.
# Small clinical lines like "Consult neurologic", "Rx CP", "Hemograma", "Biochimie"
# should stay inside the active section unless they appear as a real major document heading.
MAJOR_HEADING_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "diagnoses",
        [
            r"diagnostic\s+principal(?:\s*\([^)]*\))?",
            r"diagnostice\s+secundare(?:\s*\([^)]*\))?",
            r"diagnostic\s+secundar(?:\s*\([^)]*\))?",
            r"diagnostic\s+la\s+externare",
            r"diagnostic\s+de\s+externare",
            r"diagnostic\s+formulare\s+libera",
            r"diagnostic\s+formulare\s+liber[aă]",
            r"discharge\s+diagnosis",
            r"final\s+diagnosis",
        ],
    ),
    (
        "discharge_status",
        [
            r"starea\s+la\s+externare",
            r"stare\s+la\s+externare",
            r"status\s+la\s+externare",
            r"condition\s+at\s+discharge",
            r"discharge\s+status",
        ],
    ),
    (
        "epicriza",
        [
            r"epicriza",
            r"epicriz[aă]",
            r"evolu[tț]ie",
            r"evolutia\s+bolii",
            r"evoluția\s+bolii",
            r"hospital\s+course",
            r"clinical\s+course",
            r"medical\s+summary",
        ],
    ),
    (
        "investigations",
        [
            r"investiga[tț]ii",
            r"explor[aă]ri\s+paraclinice",
            r"rezultate\s+investiga[tț]ii",
            r"imagistic[aă]",
            r"investigations",
            r"imaging",
            r"results",
        ],
    ),
    (
        "laboratory_abnormal",
        [
            r"analize\s+modificate",
            r"valori\s+modificate",
            r"valori\s+anormale",
            r"analize\s+anormale",
            r"laboratory\s+abnormal",
            r"abnormal\s+laboratory",
            r"abnormal\s+labs",
        ],
    ),
    (
        "laboratory_normal",
        [
            r"analize\s+normale",
            r"valori\s+normale",
            r"laboratory\s+normal",
            r"normal\s+laboratory",
            r"normal\s+labs",
        ],
    ),
    (
        "treatment_in_hospital",
        [
            r"tratament\s+administrat",
            r"tratamentul\s+administrat",
            r"tratament\s+in\s+spital",
            r"tratament\s+în\s+spital",
            r"tratament\s+pe\s+perioada\s+intern[aă]rii",
            r"medica[tț]ie\s+administrat[aă]",
            r"proceduri\s+efectuate",
            r"treatment\s+during\s+admission",
            r"inpatient\s+treatment",
            r"hospital\s+treatment",
        ],
    ),
    (
        "recommended_treatment",
        [
            r"tratament\s+recomandat",
            r"tratamentul\s+recomandat",
            r"tratament\s+la\s+externare",
            r"medica[tț]ie\s+la\s+externare",
            r"re[tț]et[aă]\s+la\s+externare",
            r"re[tț]et[aă]",
            r"rp",
            r"discharge\s+medication",
            r"recommended\s+treatment",
            r"medication\s+plan",
        ],
    ),
    (
        "recommendations",
        [
            r"recomand[aă]ri",
            r"indica[tț]ii",
            r"indica[tț]ii\s+la\s+externare",
            r"regim",
            r"control",
            r"monitorizare",
            r"follow[\s-]*up",
            r"recommendations",
            r"return\s+precautions",
            r"monitoring",
            r"plan",
        ],
    ),
]


def strip_document_noise(text: str) -> str:
    lines = [clean_discharge_text(line) for line in text.splitlines()]
    cleaned_lines: list[str] = []

    noise_patterns = [
        r"^\d+\s*/\s*\d+$",
        r"^\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*(am|pm)?$",
        r"^hipocrate\s*-\s*imprimare\s*fisa$",
        r"^hipocrate\s*-\s*imprimare\s+fi[sș]a$",
        r"192\.168\.",
        r"biletexternare\.asp",
        r"relname=",
        r"relid=",
    ]

    for line in lines:
        if not line:
            continue

        normalized = normalize_for_matching(line)

        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in noise_patterns):
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def force_heading_linebreaks(text: str) -> str:
    """
    OCR/PDF text sometimes places a major heading in the middle of a line.
    This forces known headings to start on their own line.
    """
    result = text

    raw_heading_phrases = [
        "DIAGNOSTIC PRINCIPAL",
        "DIAGNOSTICE SECUNDARE",
        "DIAGNOSTIC SECUNDAR",
        "DIAGNOSTIC LA EXTERNARE",
        "DIAGNOSTIC FORMULARE LIBERA",
        "STAREA LA EXTERNARE",
        "STARE LA EXTERNARE",
        "EPICRIZA",
        "EPICRIZĂ",
        "INVESTIGATII",
        "INVESTIGAȚII",
        "EXPLORARI PARACLINICE",
        "EXPLORĂRI PARACLINICE",
        "ANALIZE MODIFICATE",
        "VALORI MODIFICATE",
        "VALORI ANORMALE",
        "ANALIZE ANORMALE",
        "ANALIZE NORMALE",
        "VALORI NORMALE",
        "TRATAMENT ADMINISTRAT",
        "TRATAMENT RECOMANDAT",
        "TRATAMENT LA EXTERNARE",
        "RECOMANDARI",
        "RECOMANDĂRI",
        "INDICATII",
        "INDICAȚII",
    ]

    for phrase in raw_heading_phrases:
        result = re.sub(
            rf"(?<!\n)({re.escape(phrase)})",
            r"\n\1",
            result,
            flags=re.IGNORECASE,
        )

    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def is_probably_major_heading_line(line: str) -> bool:
    clean = clean_discharge_text(line)
    normalized = normalize_for_matching(clean)

    if not normalized:
        return False

    if len(normalized) > 150:
        return False

    if re.fullmatch(r"[\d\s./,:;-]+", normalized):
        return False

    # Real headings often have colon, uppercase, or very short title style.
    has_colon = ":" in clean
    uppercase_ratio = 0.0

    letters = [char for char in clean if char.isalpha()]
    if letters:
        uppercase_ratio = len([char for char in letters if char.isupper()]) / max(len(letters), 1)

    return has_colon or uppercase_ratio > 0.65 or len(normalized.split()) <= 7


def split_heading_and_inline_body(line: str, matched_pattern: str) -> tuple[str, str]:
    clean = clean_discharge_text(line)

    if ":" in clean:
        before, after = clean.split(":", 1)
        return clean_discharge_text(before), clean_discharge_text(after)

    # If no colon, keep the full line as heading.
    return clean, ""


def match_major_heading(line: str) -> tuple[str, str, str] | None:
    clean = clean_discharge_text(line)
    normalized = normalize_for_matching(clean)

    if not normalized:
        return None

    if not is_probably_major_heading_line(clean):
        return None

    for key, patterns in MAJOR_HEADING_PATTERNS:
        for pattern in patterns:
            # Match only at the beginning of the line.
            # This prevents "Consult cardiologic..." or a sentence mentioning treatment
            # from splitting the current section.
            if re.match(rf"^\s*{pattern}\b", normalized, flags=re.IGNORECASE):
                heading, inline_body = split_heading_and_inline_body(clean, pattern)
                return key, heading, inline_body

    return None


def prepare_text_for_sectioning(text: str) -> str:
    text = clean_discharge_text(text)
    text = strip_document_noise(text)
    text = force_heading_linebreaks(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_major_sections(text: str) -> list[dict[str, Any]]:
    prepared = prepare_text_for_sectioning(text)
    lines = [clean_discharge_text(line) for line in prepared.splitlines()]
    lines = [line for line in lines if line]

    sections: list[dict[str, Any]] = []

    current_key = "administrative_information"
    current_title = SECTION_TITLES[current_key]
    current_original_title = "Document header"
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_title, current_original_title, current_lines

        body = "\n".join(current_lines).strip()

        if body:
            sections.append(
                {
                    "key": current_key,
                    "title": current_title,
                    "original_title": current_original_title,
                    "body": body,
                    "confidence": 0.95,
                }
            )

        current_key = "other"
        current_title = SECTION_TITLES["other"]
        current_original_title = None
        current_lines = []

    for line in lines:
        matched = match_major_heading(line)

        if matched:
            matched_key, original_heading, inline_body = matched

            flush()

            current_key = matched_key
            current_title = SECTION_TITLES.get(matched_key, original_heading)
            current_original_title = original_heading
            current_lines = []

            if inline_body:
                current_lines.append(inline_body)

            continue

        current_lines.append(line)

    flush()

    if not sections and prepared:
        sections.append(
            {
                "key": "other",
                "title": SECTION_TITLES["other"],
                "original_title": None,
                "body": prepared,
                "confidence": 0.45,
            }
        )

    return merge_repeated_major_sections(sections)


def merge_repeated_major_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for section in sections:
        key = section.get("key") or "other"
        body = clean_discharge_text(section.get("body"))

        if not body:
            continue

        title = section.get("title") or SECTION_TITLES.get(key, key)
        original_title = section.get("original_title")
        confidence = float(section.get("confidence") or 0.5)

        if key not in grouped:
            grouped[key] = {
                "key": key,
                "title": title,
                "original_titles": [],
                "body": body,
                "confidence": confidence,
            }
        else:
            # Repeated EPICRIZA on page 2, page 3, etc. should stay in Epicriză,
            # not create dozens of duplicate cards.
            if original_title and original_title not in grouped[key]["original_titles"]:
                grouped[key]["body"] = grouped[key]["body"].rstrip() + "\n\n" + body
            else:
                grouped[key]["body"] = grouped[key]["body"].rstrip() + "\n\n" + body

            grouped[key]["confidence"] = max(float(grouped[key].get("confidence") or 0.5), confidence)

        if original_title and original_title not in grouped[key]["original_titles"]:
            grouped[key]["original_titles"].append(original_title)

    ordered: list[dict[str, Any]] = []

    for key in SECTION_ORDER:
        if key in grouped:
            ordered.append(grouped.pop(key))

    ordered.extend(grouped.values())
    return ordered


def extract_hospitalization_period(text: str) -> dict[str, str | None]:
    clean = clean_discharge_text(text)

    period_patterns = [
        r"perioada\s+intern[aă]rii\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(\d{1,2}:\d{2})?\s*[-–—]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(\d{1,2}:\d{2})?",
        r"perioada\s+de\s+internare\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(\d{1,2}:\d{2})?\s*[-–—]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(\d{1,2}:\d{2})?",
    ]

    for pattern in period_patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            admission_date = match.group(1)
            admission_time = match.group(2) or ""
            discharge_date = match.group(3)
            discharge_time = match.group(4) or ""

            return {
                "admission_date": clean_discharge_text(f"{admission_date} {admission_time}"),
                "discharge_date": clean_discharge_text(f"{discharge_date} {discharge_time}"),
            }

    return {
        "admission_date": None,
        "discharge_date": None,
    }


def extract_issued_date(text: str) -> str | None:
    clean = clean_discharge_text(text)

    patterns = [
        r"data\s+eliber[aă]rii\s*[:\-]?\s*([^\n]+)",
        r"data\s+emiterii\s*[:\-]?\s*([^\n]+)",
        r"issued\s+date\s*[:\-]?\s*([^\n]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            return clean_discharge_text(match.group(1))[:120]

    return None


def extract_discharge_dates_fallback(text: str) -> dict[str, str | None]:
    clean = clean_discharge_text(text)

    admission = None
    discharge = None

    admission_patterns = [
        r"data\s+(?:si\s+ora\s+)?intern[aă]rii\s*[:\-]?\s*([^\n]+)",
        r"data\s+internare\s*[:\-]?\s*([^\n]+)",
        r"admission\s+date\s*[:\-]?\s*([^\n]+)",
    ]

    discharge_patterns = [
        r"data\s+(?:si\s+ora\s+)?extern[aă]rii\s*[:\-]?\s*([^\n]+)",
        r"data\s+externare\s*[:\-]?\s*([^\n]+)",
        r"discharge\s+date\s*[:\-]?\s*([^\n]+)",
    ]

    for pattern in admission_patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            admission = clean_discharge_text(match.group(1))[:120]
            break

    for pattern in discharge_patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            discharge = clean_discharge_text(match.group(1))[:120]
            break

    return {
        "admission_date": admission,
        "discharge_date": discharge,
    }


def parse_discharge_document(extraction: dict[str, Any] | str) -> dict[str, Any]:
    text = get_best_ocr_text(extraction)
    metadata = extract_report_metadata(text)

    date_metadata = extract_hospitalization_period(text)

    if not date_metadata.get("admission_date") and not date_metadata.get("discharge_date"):
        date_metadata = extract_discharge_dates_fallback(text)

    issued_date = extract_issued_date(text)
    sections = split_into_major_sections(text)
    formatter_warnings: list[str] = []

    if format_discharge_sections_with_ai is not None:
        sections, formatter_warnings = format_discharge_sections_with_ai(sections)
    else:
        formatter_warnings.append("OpenAI discharge layout formatter module is unavailable.")
    patient_name = metadata.get("patient_name")
    report_date = (
        date_metadata.get("discharge_date")
        or issued_date
        or metadata.get("generated_on")
        or metadata.get("reported_on")
    )

    report_name = "Fișă de externare"
    if report_date:
        report_name = f"Fișă de externare {report_date}"

    note_payload = {
        "document_type": "discharge_summary",
        "sections": sections,
    }

    return {
        "patient_name": patient_name,
        "date_of_birth": metadata.get("date_of_birth"),
        "age": metadata.get("age"),
        "sex": metadata.get("sex"),
        "cnp": metadata.get("cnp"),
        "patient_identifier": metadata.get("patient_identifier"),
        "lab_name": metadata.get("lab_name"),
        "sample_type": None,
        "referring_doctor": metadata.get("referring_doctor"),
        "report_name": report_name,
        "report_type": "Discharge summary",
        "source_language": metadata.get("source_language") or "ro",
        "test_date": None,
        "collected_on": date_metadata.get("admission_date"),
        "reported_on": date_metadata.get("discharge_date") or issued_date,
        "registered_on": metadata.get("registered_on"),
        "generated_on": metadata.get("generated_on"),
        "admission_date": date_metadata.get("admission_date"),
        "discharge_date": date_metadata.get("discharge_date"),
        "issued_date": issued_date,
        "note_body": json.dumps(note_payload, ensure_ascii=False),
        "labs": [],
        "warnings": [
            f"Discharge parser created {len(sections)} major sections using heading-boundary parsing.",
            *formatter_warnings,
        ],
    }