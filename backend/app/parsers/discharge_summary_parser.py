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
    "diagnostic la externare",
    "diagnostic externare",
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


SECTION_DEFINITIONS: list[tuple[str, str, list[str]]] = [
    (
        "administrative_information",
        "Administrative information",
        [
            "institutul clinic fundeni",
            "spital",
            "unitate sanitara",
            "unitate sanitară",
            "sectia",
            "secția",
            "foaie observatie",
            "foaie observație",
            "nr foaie observatie",
            "nr foaie observație",
            "numar fo",
            "număr fo",
            "fo urgenta",
            "fo urgență",
            "medic",
            "medic curant",
            "doctor",
            "dr.",
            "data eliberarii",
            "data eliberării",
            "perioada internarii",
            "perioada internării",
            "data internarii",
            "data internării",
            "data externarii",
            "data externării",
            "nume",
            "prenume",
            "varsta",
            "vârsta",
            "sex",
            "cnp",
            "cod pacient",
            "telefon",
            "adresa",
            "casa asigurare",
            "categoria de asigurat",
            "loc de munca",
            "loc de muncă",
            "ocupatia",
            "ocupația",
            "numar de asigurat",
            "număr de asigurat",
            "pacient diagnosticat cu afectiune oncologica",
            "pacient diagnosticat cu afecțiune oncologică",
            "email",
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
    (
        "diagnoses",
        "Diagnoses / Diagnostic",
        [
            "diagnostic principal",
            "diagnosticul principal",
            "diagnostic secundar",
            "diagnostice secundare",
            "diagnostic externare",
            "diagnostic la externare",
            "diagnostice",
            "cod diagnostic",
            "drg",
            "icd",
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
            "coagulare",
            "imagistica",
            "imagistică",
            "ecografie",
            "ecografie abdominala",
            "ecografie abdominală",
            "ecografie cardiaca",
            "ecografie cardiacă",
            "ct",
            "computer tomograf",
            "rmn",
            "irm",
            "radiografie",
            "rx",
            "rx cp",
            "ecg",
            "ekg",
            "consult",
            "consult neurologic",
            "consult cardiologic",
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
            "proceduri efectuate",
            "procedura efectuata",
            "procedură efectuată",
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
]


CANONICAL_TITLES = {key: title for key, title, _aliases in SECTION_DEFINITIONS}

CLINICAL_SECTION_KEYS = {
    "discharge_status",
    "diagnoses",
    "epicriza",
    "investigations",
    "treatment_in_hospital",
    "recommended_treatment",
    "recommendations",
}

SECTION_ORDER = [
    "administrative_information",
    "discharge_status",
    "diagnoses",
    "epicriza",
    "investigations",
    "treatment_in_hospital",
    "recommended_treatment",
    "recommendations",
    "other",
]


def prepare_text_for_sectioning(text: str) -> str:
    text = clean_discharge_text(text)

    major_phrases = [
        "DIAGNOSTIC PRINCIPAL",
        "DIAGNOSTICE SECUNDARE",
        "DIAGNOSTIC SECUNDAR",
        "DIAGNOSTIC LA EXTERNARE",
        "EPICRIZA",
        "EPICRIZĂ",
        "INVESTIGATII",
        "INVESTIGAȚII",
        "EXPLORARI PARACLINICE",
        "EXPLORĂRI PARACLINICE",
        "TRATAMENT RECOMANDAT",
        "TRATAMENT LA EXTERNARE",
        "RECOMANDARI",
        "RECOMANDĂRI",
        "INDICATII",
        "INDICAȚII",
        "STAREA LA EXTERNARE",
        "STARE LA EXTERNARE",
    ]

    for phrase in major_phrases:
        text = re.sub(
            rf"(?<!\n)({re.escape(phrase)})",
            r"\n\1",
            text,
            flags=re.IGNORECASE,
        )

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_probably_noise_heading(line: str) -> bool:
    normalized = normalize_for_matching(line)

    if not normalized:
        return True

    if re.fullmatch(r"[\d\s./,:-]+", normalized):
        return True

    if re.fullmatch(r"(da|nu|n|y|yes|no)", normalized):
        return True

    if re.search(r"biletexternare\.asp|192\.168|page\s*\d+|^\d+/\d+$", normalized):
        return True

    if len(normalized) <= 3:
        return True

    return False


def split_heading_body(line: str, alias: str) -> tuple[str, str]:
    raw = clean_discharge_text(line)
    alias_norm = normalize_for_matching(alias)
    raw_norm = normalize_for_matching(raw)

    body = ""

    if ":" in raw:
        before, after = raw.split(":", 1)
        if normalize_for_matching(before).startswith(alias_norm) or alias_norm in normalize_for_matching(before):
            body = after.strip()

    if not body and raw_norm.startswith(alias_norm):
        body = raw[len(raw[: len(alias)]) :].strip(" :-")

    return raw, clean_discharge_text(body)


def match_major_section_header(line: str, current_key: str | None = None) -> tuple[str, str, str] | None:
    raw = clean_discharge_text(line)
    normalized = normalize_for_matching(raw)

    if not normalized:
        return None

    if is_probably_noise_heading(raw):
        return None

    # Do not let random short subheadings inside Epicriză break the clinical course.
    if current_key == "epicriza":
        strong_breakers = {
            "diagnoses",
            "investigations",
            "treatment_in_hospital",
            "recommended_treatment",
            "recommendations",
            "discharge_status",
        }
    else:
        strong_breakers = set(CANONICAL_TITLES.keys())

    for key, _title, aliases in SECTION_DEFINITIONS:
        if key not in strong_breakers:
            continue

        for alias in aliases:
            alias_norm = normalize_for_matching(alias)

            if not alias_norm:
                continue

            if normalized == alias_norm:
                heading, body = split_heading_body(raw, alias)
                return key, heading, body

            if normalized.startswith(alias_norm + ":"):
                heading, body = split_heading_body(raw, alias)
                return key, heading, body

            if normalized.startswith(alias_norm + " -"):
                heading, body = split_heading_body(raw, alias)
                return key, heading, body

            # Strict prefix match for real form headings, but avoid long paragraphs.
            if normalized.startswith(alias_norm + " ") and len(normalized) <= len(alias_norm) + 90:
                heading, body = split_heading_body(raw, alias)
                return key, heading, body

    return None


def classify_body_without_header(body: str, preferred_key: str | None = None) -> tuple[str, str, float]:
    normalized = normalize_for_matching(body)

    if not normalized:
        return "other", "Other relevant clinical text", 0.2

    if preferred_key:
        return preferred_key, CANONICAL_TITLES.get(preferred_key, "Other relevant clinical text"), 0.72

    scores: dict[str, int] = {}

    for key, _title, aliases in SECTION_DEFINITIONS:
        if key == "administrative_information":
            continue

        score = 0
        for alias in aliases:
            alias_norm = normalize_for_matching(alias)
            if alias_norm and alias_norm in normalized:
                score += 1

        scores[key] = score

    if re.search(r"\b(ct|rmn|irm|ecografie|radiografie|ecg|ekg|analize|hemograma|hemoglobina|leucocite|trombocite)\b", normalized):
        scores["investigations"] = scores.get("investigations", 0) + 2

    if re.search(r"\b(se recomanda|control|monitorizare|regim|revine|indicatii|indicatii)\b", normalized):
        scores["recommendations"] = scores.get("recommendations", 0) + 2

    if re.search(r"\b(rp|comprimate|capsule|mg|ml|x\s*\d|dimineata|seara|tratament)\b", normalized):
        scores["recommended_treatment"] = scores.get("recommended_treatment", 0) + 1

    best_key = max(scores, key=lambda key: scores[key])
    best_score = scores.get(best_key, 0)

    if best_score <= 0:
        return "other", "Other relevant clinical text", 0.35

    return best_key, CANONICAL_TITLES.get(best_key, "Other relevant clinical text"), min(0.85, 0.45 + best_score * 0.12)


def split_into_sections(text: str) -> list[dict[str, Any]]:
    prepared_text = prepare_text_for_sectioning(text)
    lines = [clean_discharge_text(line) for line in prepared_text.splitlines()]
    lines = [line for line in lines if line]

    sections: list[dict[str, Any]] = []

    current_key: str | None = "administrative_information"
    current_title: str | None = CANONICAL_TITLES["administrative_information"]
    current_original_title: str | None = "Document header"
    current_lines: list[str] = []
    clinical_started = False
    epicriza_seen = False

    def flush() -> None:
        nonlocal current_key, current_title, current_original_title, current_lines

        body = "\n".join(current_lines).strip()

        if body:
            key = current_key or "other"
            title = current_title or CANONICAL_TITLES.get(key, "Other relevant clinical text")
            confidence = 0.90 if key != "other" else 0.45

            sections.append(
                {
                    "key": key,
                    "title": title,
                    "original_title": current_original_title,
                    "body": body,
                    "confidence": confidence,
                }
            )

        current_key = None
        current_title = None
        current_original_title = None
        current_lines = []

    for line in lines:
        matched = match_major_section_header(line, current_key=current_key)

        if matched:
            matched_key, original_heading, inline_body = matched

            if matched_key in CLINICAL_SECTION_KEYS:
                clinical_started = True

            if matched_key == "epicriza":
                epicriza_seen = True

            # Administrative lines after clinical content should usually not create new clinical cards.
            # Keep them only if we are still before the clinical document body.
            if matched_key == "administrative_information" and clinical_started:
                if current_key:
                    current_lines.append(line)
                else:
                    current_key = "other"
                    current_title = "Other relevant clinical text"
                    current_original_title = None
                    current_lines.append(line)
                continue

            flush()

            current_key = matched_key
            current_title = CANONICAL_TITLES.get(matched_key, original_heading)
            current_original_title = original_heading
            current_lines = []

            if inline_body:
                current_lines.append(inline_body)

            continue

        # If we already saw Epicriză, most unidentified clinical text should remain Epicriză
        # until a strong major heading appears.
        if current_key is None:
            if epicriza_seen:
                current_key = "epicriza"
                current_title = CANONICAL_TITLES["epicriza"]
                current_original_title = "EPICRIZA continuation"
            else:
                current_key = "other"
                current_title = "Other relevant clinical text"
                current_original_title = None

        current_lines.append(line)

    flush()

    if not sections and prepared_text.strip():
        key, title, confidence = classify_body_without_header(prepared_text)
        sections.append(
            {
                "key": key,
                "title": title,
                "original_title": None,
                "body": prepared_text.strip(),
                "confidence": confidence,
            }
        )

    return merge_duplicate_sections(sections)


def merge_duplicate_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for section in sections:
        key = section.get("key") or "other"
        body = clean_discharge_text(section.get("body"))

        if not body:
            continue

        title = section.get("title") or CANONICAL_TITLES.get(key, "Other relevant clinical text")
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
            if original_title:
                grouped[key]["body"] = (
                    grouped[key]["body"].rstrip()
                    + "\n\n"
                    + f"[{original_title}]\n"
                    + body
                )
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


def extract_discharge_dates(text: str) -> dict[str, str | None]:
    clean = clean_discharge_text(text)

    admission = None
    discharge = None
    issued = None

    admission_patterns = [
        r"perioada\s+intern[aă]rii\s*[:\-]?\s*([^\n]+)",
        r"data\s+(?:si\s+ora\s+)?intern[aă]rii\s*[:\-]?\s*([^\n]+)",
        r"data\s+internare\s*[:\-]?\s*([^\n]+)",
        r"admission\s+date\s*[:\-]?\s*([^\n]+)",
    ]

    discharge_patterns = [
        r"data\s+(?:si\s+ora\s+)?extern[aă]rii\s*[:\-]?\s*([^\n]+)",
        r"data\s+externare\s*[:\-]?\s*([^\n]+)",
        r"discharge\s+date\s*[:\-]?\s*([^\n]+)",
    ]

    issued_patterns = [
        r"data\s+eliber[aă]rii\s*[:\-]?\s*([^\n]+)",
        r"data\s+emiterii\s*[:\-]?\s*([^\n]+)",
        r"issued\s+date\s*[:\-]?\s*([^\n]+)",
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

    for pattern in issued_patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            issued = clean_discharge_text(match.group(1))[:120]
            break

    return {
        "admission_date": admission,
        "discharge_date": discharge,
        "issued_date": issued,
    }


def parse_discharge_document(extraction: dict[str, Any] | str) -> dict[str, Any]:
    text = get_best_ocr_text(extraction)
    metadata = extract_report_metadata(text)
    date_metadata = extract_discharge_dates(text)
    sections = split_into_sections(text)

    patient_name = metadata.get("patient_name")
    report_date = (
        date_metadata.get("discharge_date")
        or date_metadata.get("issued_date")
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
        "reported_on": date_metadata.get("discharge_date") or date_metadata.get("issued_date"),
        "registered_on": metadata.get("registered_on"),
        "generated_on": metadata.get("generated_on"),
        "admission_date": date_metadata.get("admission_date"),
        "discharge_date": date_metadata.get("discharge_date"),
        "issued_date": date_metadata.get("issued_date"),
        "note_body": json.dumps(note_payload, ensure_ascii=False),
        "labs": [],
        "warnings": [
            f"Discharge parser created {len(sections)} narrative sections using strict fișă de externare buckets."
        ],
    }