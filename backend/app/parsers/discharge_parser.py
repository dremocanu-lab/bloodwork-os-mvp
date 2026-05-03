from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from app.report_fields import extract_report_metadata


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
    text = text.replace("â€“", "–").replace("â€”", "—")
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
    "diagnostic la externare",
    "diagnostic externare",
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


SECTION_DEFINITIONS: list[tuple[str, str, list[str]]] = [
    (
        "diagnoses",
        "Diagnoses / Diagnostic",
        [
            "diagnostic",
            "diagnostic principal",
            "diagnostic secundar",
            "diagnostic externare",
            "diagnostic la externare",
            "diagnostice",
            "cod diagnostic",
            "icd",
            "drg",
            "discharge diagnosis",
            "final diagnosis",
            "diagnoses",
        ],
    ),
    (
        "epicriza",
        "Epicriză / Clinical course",
        [
            "epicriza",
            "epicriză",
            "evolutie",
            "evoluție",
            "istoric",
            "anamneza",
            "anamneză",
            "boala actuala",
            "boala actuală",
            "motivul internarii",
            "motivul internării",
            "pacientul se interneaza",
            "pacientul se internează",
            "hospital course",
            "clinical course",
            "medical summary",
            "summary",
        ],
    ),
    (
        "investigations",
        "Investigations / Results",
        [
            "investigatii",
            "investigații",
            "explorari paraclinice",
            "explorări paraclinice",
            "paraclinic",
            "analize",
            "biologie",
            "hematologie",
            "biochimie",
            "imagistica",
            "imagistică",
            "ecografie",
            "ct",
            "computer tomograf",
            "rmn",
            "irm",
            "radiografie",
            "rx",
            "ecg",
            "ekg",
            "consult",
            "consulturi",
            "investigations",
            "imaging",
            "laboratory",
            "results",
        ],
    ),
    (
        "treatment_in_hospital",
        "Treatment during admission",
        [
            "tratament administrat",
            "tratamentul administrat",
            "tratament in spital",
            "tratament în spital",
            "tratament pe perioada internarii",
            "tratament pe perioada internării",
            "medicatie administrata",
            "medicație administrată",
            "s-a administrat",
            "pe parcursul internarii",
            "pe parcursul internării",
            "inpatient treatment",
            "hospital treatment",
            "treatment during admission",
        ],
    ),
    (
        "recommended_treatment",
        "Recommended treatment / Discharge medication",
        [
            "tratament recomandat",
            "tratamentul recomandat",
            "tratament la externare",
            "medicatie la externare",
            "medicație la externare",
            "recomandari terapeutice",
            "recomandări terapeutice",
            "rp",
            "reteta",
            "rețeta",
            "reteta la externare",
            "rețeta la externare",
            "discharge medication",
            "recommended treatment",
            "medication plan",
        ],
    ),
    (
        "recommendations",
        "Recommendations / Follow-up",
        [
            "recomandari",
            "recomandări",
            "indicatii",
            "indicații",
            "indicatii la externare",
            "indicații la externare",
            "regim",
            "control",
            "revine la control",
            "monitorizare",
            "se recomanda",
            "se recomandă",
            "follow-up",
            "follow up",
            "recommendations",
            "return precautions",
            "monitoring",
            "plan",
        ],
    ),
    (
        "discharge_status",
        "Discharge status",
        [
            "stare la externare",
            "starea la externare",
            "status la externare",
            "vindecat",
            "ameliorat",
            "stationar",
            "staționar",
            "externat",
            "discharge status",
            "condition at discharge",
        ],
    ),
]


CANONICAL_TITLES = {key: title for key, title, _aliases in SECTION_DEFINITIONS}


def match_section_header(line: str) -> tuple[str, str] | None:
    raw = clean_discharge_text(line)
    normalized = normalize_for_matching(raw)

    if not normalized:
        return None

    # Avoid classifying long clinical paragraphs as headers.
    if len(normalized) > 110 and ":" not in normalized:
        return None

    for key, title, aliases in SECTION_DEFINITIONS:
        for alias in aliases:
            alias_norm = normalize_for_matching(alias)

            if normalized == alias_norm:
                return key, raw

            if normalized.startswith(alias_norm + ":"):
                return key, raw

            if normalized.startswith(alias_norm + " -"):
                return key, raw

            if normalized.startswith(alias_norm + " "):
                # Allows headers like "Diagnostic externare:"
                if len(normalized) <= len(alias_norm) + 45:
                    return key, raw

    return None


def classify_body_without_header(body: str) -> tuple[str, str, float]:
    normalized = normalize_for_matching(body)

    if not normalized:
        return "other", "Other clinical text", 0.2

    scores: dict[str, int] = {}

    for key, _title, aliases in SECTION_DEFINITIONS:
        score = 0
        for alias in aliases:
            alias_norm = normalize_for_matching(alias)
            if alias_norm and alias_norm in normalized:
                score += 1

        scores[key] = score

    if re.search(r"\b(ct|rmn|irm|ecografie|radiografie|ecg|ekg|analize|hemoglobina|leucocite|trombocite)\b", normalized):
        scores["investigations"] = scores.get("investigations", 0) + 2

    if re.search(r"\b(se recomanda|control|monitorizare|regim|revine|indicatii|indicatii)\b", normalized):
        scores["recommendations"] = scores.get("recommendations", 0) + 2

    if re.search(r"\b(rp|comprimate|capsule|mg|ml|x\s*\d|dimineata|seara|tratament)\b", normalized):
        scores["recommended_treatment"] = scores.get("recommended_treatment", 0) + 1

    best_key = max(scores, key=lambda key: scores[key])
    best_score = scores.get(best_key, 0)

    if best_score <= 0:
        return "other", "Other clinical text", 0.35

    return best_key, CANONICAL_TITLES.get(best_key, "Other clinical text"), min(0.85, 0.45 + best_score * 0.12)


def split_into_sections(text: str) -> list[dict[str, Any]]:
    lines = [clean_discharge_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    sections: list[dict[str, Any]] = []

    current_key: str | None = None
    current_title: str | None = None
    current_original_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_title, current_original_title, current_lines

        body = "\n".join(current_lines).strip()

        if not body:
            current_key = None
            current_title = None
            current_original_title = None
            current_lines = []
            return

        if current_key is None:
            classified_key, classified_title, confidence = classify_body_without_header(body)
            sections.append(
                {
                    "key": classified_key,
                    "title": classified_title,
                    "original_title": None,
                    "body": body,
                    "confidence": confidence,
                }
            )
        else:
            sections.append(
                {
                    "key": current_key,
                    "title": current_title or CANONICAL_TITLES.get(current_key, current_key),
                    "original_title": current_original_title,
                    "body": body,
                    "confidence": 0.92,
                }
            )

        current_key = None
        current_title = None
        current_original_title = None
        current_lines = []

    for line in lines:
        matched = match_section_header(line)

        if matched:
            flush()
            current_key, current_original_title = matched
            current_title = CANONICAL_TITLES.get(current_key, current_original_title)

            # If the header has text after a colon, keep that text in the section body.
            if ":" in line:
                after_colon = line.split(":", 1)[1].strip()
                if after_colon:
                    current_lines.append(after_colon)
            continue

        current_lines.append(line)

    flush()

    if not sections and text.strip():
        sections.append(
            {
                "key": "other",
                "title": "Other clinical text",
                "original_title": None,
                "body": text.strip(),
                "confidence": 0.25,
            }
        )

    return merge_duplicate_sections(sections)


def merge_duplicate_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered_keys = [
        "diagnoses",
        "epicriza",
        "investigations",
        "treatment_in_hospital",
        "recommended_treatment",
        "recommendations",
        "discharge_status",
        "other",
    ]

    grouped: dict[str, dict[str, Any]] = {}

    for section in sections:
        key = section.get("key") or "other"
        body = clean_discharge_text(section.get("body"))

        if not body:
            continue

        if key not in grouped:
            grouped[key] = {
                "key": key,
                "title": section.get("title") or CANONICAL_TITLES.get(key, "Other clinical text"),
                "original_titles": [],
                "body": body,
                "confidence": float(section.get("confidence") or 0.5),
            }
        else:
            grouped[key]["body"] = grouped[key]["body"].rstrip() + "\n\n" + body
            grouped[key]["confidence"] = max(
                float(grouped[key].get("confidence") or 0.5),
                float(section.get("confidence") or 0.5),
            )

        original_title = section.get("original_title")
        if original_title and original_title not in grouped[key]["original_titles"]:
            grouped[key]["original_titles"].append(original_title)

    ordered: list[dict[str, Any]] = []

    for key in ordered_keys:
        if key in grouped:
            ordered.append(grouped.pop(key))

    ordered.extend(grouped.values())
    return ordered


def extract_discharge_dates(text: str) -> dict[str, str | None]:
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
            admission = clean_discharge_text(match.group(1))[:80]
            break

    for pattern in discharge_patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            discharge = clean_discharge_text(match.group(1))[:80]
            break

    return {
        "admission_date": admission,
        "discharge_date": discharge,
    }


def parse_discharge_document(extraction: dict[str, Any] | str) -> dict[str, Any]:
    text = get_best_ocr_text(extraction)
    metadata = extract_report_metadata(text)
    date_metadata = extract_discharge_dates(text)
    sections = split_into_sections(text)

    patient_name = metadata.get("patient_name")
    report_date = date_metadata.get("discharge_date") or metadata.get("generated_on") or metadata.get("reported_on")

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
        "reported_on": date_metadata.get("discharge_date"),
        "registered_on": metadata.get("registered_on"),
        "generated_on": metadata.get("generated_on"),
        "admission_date": date_metadata.get("admission_date"),
        "discharge_date": date_metadata.get("discharge_date"),
        "note_body": json.dumps(note_payload, ensure_ascii=False),
        "labs": [],
        "warnings": [
            f"Discharge parser created {len(sections)} structured narrative sections."
        ],
    }