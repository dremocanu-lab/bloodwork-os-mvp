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
    "perioada internarii",
    "perioada internării",
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
            "hipocrate",
            "spital",
            "unitate sanitara",
            "unitate sanitară",
            "foaie observatie",
            "foaie observație",
            "nr foaie observatie",
            "nr foaie observație",
            "fo urgenta",
            "fo urgență",
            "numar fo",
            "număr fo",
            "medic curant",
            "medic",
            "doctor",
            "dr.",
            "email",
        ],
    ),
    (
        "patient_information",
        "Patient information",
        [
            "nume",
            "prenume",
            "varsta",
            "vârsta",
            "sex",
            "cnp",
            "cod pacient",
            "pacient",
        ],
    ),
    (
        "hospitalization",
        "Hospitalization",
        [
            "data eliberarii",
            "data eliberării",
            "perioada internarii",
            "perioada internării",
            "perioada de internare",
            "data internarii",
            "data internării",
            "data externarii",
            "data externării",
            "sectia",
            "secția",
            "compartiment",
        ],
    ),
    (
        "insurance_contact",
        "Insurance / Contact",
        [
            "casa asigurare",
            "categoria de asigurat",
            "numar de asigurat",
            "număr de asigurat",
            "telefon",
            "adresa",
            "loc de munca",
            "loc de muncă",
            "ocupatia",
            "ocupația",
            "pacient diagnosticat cu afectiune oncologica",
            "pacient diagnosticat cu afecțiune oncologică",
        ],
    ),
    (
        "discharge_status",
        "Discharge status",
        [
            "stare la externare",
            "starea la externare",
            "status la externare",
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
            "diagnostic formulare libera",
            "diagnostic formulare liberă",
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
            "investigatii paraclinice",
            "investigații paraclinice",
            "paraclinic",
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
SECTION_ALIASES = {key: aliases for key, _title, aliases in SECTION_DEFINITIONS}

SECTION_ORDER = [
    "administrative_information",
    "patient_information",
    "hospitalization",
    "insurance_contact",
    "discharge_status",
    "diagnoses",
    "epicriza",
    "investigations",
    "treatment_in_hospital",
    "recommended_treatment",
    "recommendations",
    "other",
]

FRONT_PAGE_KEYS = {
    "administrative_information",
    "patient_information",
    "hospitalization",
    "insurance_contact",
    "discharge_status",
    "diagnoses",
}

CLINICAL_KEYS = {
    "epicriza",
    "investigations",
    "treatment_in_hospital",
    "recommended_treatment",
    "recommendations",
}


def prepare_text_for_sectioning(text: str) -> str:
    text = clean_discharge_text(text)

    major_phrases = [
        "BILET DE IESIRE DIN SPITAL / SCRISOARE MEDICALA",
        "BILET DE IEȘIRE DIN SPITAL / SCRISOARE MEDICALĂ",
        "DATA ELIBERARII",
        "DATA ELIBERĂRII",
        "PERIOADA INTERNARII",
        "PERIOADA INTERNĂRII",
        "NUME",
        "PRENUME",
        "VARSTA",
        "VÂRSTA",
        "CNP",
        "CASA ASIGURARE",
        "CATEGORIA DE ASIGURAT",
        "TELEFON",
        "ADRESA",
        "LOC DE MUNCA / OCUPATIA",
        "LOC DE MUNCĂ / OCUPAȚIA",
        "STAREA LA EXTERNARE",
        "STARE LA EXTERNARE",
        "DIAGNOSTIC PRINCIPAL",
        "DIAGNOSTICE SECUNDARE",
        "DIAGNOSTIC SECUNDAR",
        "DIAGNOSTIC FORMULARE LIBERA",
        "DIAGNOSTIC FORMULARE LIBERĂ",
        "EPICRIZA",
        "EPICRIZĂ",
        "INVESTIGATII",
        "INVESTIGAȚII",
        "EXPLORARI PARACLINICE",
        "EXPLORĂRI PARACLINICE",
        "TRATAMENT ADMINISTRAT",
        "TRATAMENT RECOMANDAT",
        "TRATAMENT LA EXTERNARE",
        "RECOMANDARI",
        "RECOMANDĂRI",
        "INDICATII",
        "INDICAȚII",
    ]

    for phrase in major_phrases:
        text = re.sub(rf"(?<!\n)({re.escape(phrase)})", r"\n\1", text, flags=re.IGNORECASE)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_noise_heading(line: str) -> bool:
    normalized = normalize_for_matching(line)

    if not normalized:
        return True

    if re.fullmatch(r"[\d\s./,:-]+", normalized):
        return True

    if re.fullmatch(r"(da|nu|n|y|yes|no|-)", normalized):
        return True

    if re.search(r"biletexternare\.asp|192\.168|page\s*\d+|^\d+/\d+$", normalized):
        return True

    if len(normalized) <= 2:
        return True

    return False


def line_has_lab_or_visit_values(line: str) -> bool:
    normalized = normalize_for_matching(line)

    return bool(
        re.search(
            r"\b(hb|ht|leuc|tromb|plt|ldh|crp|urea|creatinina|glucoza|fibrinogen|inr|ast|alt|bilirubina|na|k|ta|av|spo2|mg/dl|mmc|g/dl|u/l)\b",
            normalized,
        )
        or re.search(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", normalized)
    )


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


def match_major_section_header(
    line: str,
    current_key: str | None = None,
    clinical_started: bool = False,
) -> tuple[str, str, str] | None:
    raw = clean_discharge_text(line)
    normalized = normalize_for_matching(raw)

    if not normalized or is_noise_heading(raw):
        return None

    if clinical_started or current_key == "epicriza":
        allowed_keys = {
            "investigations",
            "treatment_in_hospital",
            "recommended_treatment",
            "recommendations",
        }
    else:
        allowed_keys = set(CANONICAL_TITLES.keys())

    for key, _title, aliases in SECTION_DEFINITIONS:
        if key not in allowed_keys:
            continue

        for alias in aliases:
            alias_norm = normalize_for_matching(alias)

            if not alias_norm:
                continue

            exact_match = normalized == alias_norm
            colon_match = normalized.startswith(alias_norm + ":")
            dash_match = normalized.startswith(alias_norm + " -")
            short_prefix_match = normalized.startswith(alias_norm + " ") and len(normalized) <= len(alias_norm) + 95

            if not (exact_match or colon_match or dash_match or short_prefix_match):
                continue

            if clinical_started and line_has_lab_or_visit_values(raw) and key != "recommended_treatment":
                continue

            heading, body = split_heading_body(raw, alias)
            return key, heading, body

    return None


def extract_front_page_sections(text: str) -> list[dict[str, Any]]:
    prepared_text = prepare_text_for_sectioning(text)
    before_epicriza = re.split(r"\bEPICRIZ[ĂA]\b", prepared_text, maxsplit=1, flags=re.IGNORECASE)[0]

    lines = [clean_discharge_text(line) for line in before_epicriza.splitlines()]
    lines = [line for line in lines if line]

    buckets: dict[str, list[str]] = {
        "administrative_information": [],
        "patient_information": [],
        "hospitalization": [],
        "insurance_contact": [],
        "discharge_status": [],
        "diagnoses": [],
    }

    current_key = "administrative_information"

    for line in lines:
        matched = match_major_section_header(line, current_key=current_key, clinical_started=False)

        if matched:
            key, heading, inline_body = matched
            if key in buckets:
                current_key = key
                if inline_body:
                    buckets[current_key].append(inline_body)
                elif key in {"discharge_status", "diagnoses"}:
                    buckets[current_key].append(heading)
                continue

        normalized = normalize_for_matching(line)

        if any(token in normalized for token in ["diagnostic principal", "diagnostice secundare", "diagnostic formulare"]):
            current_key = "diagnoses"
        elif any(token in normalized for token in ["stare la externare", "starea la externare", "status la externare"]):
            current_key = "discharge_status"
        elif any(token in normalized for token in ["data eliberarii", "perioada internarii", "data internarii", "data externarii", "sectia", "compartiment"]):
            current_key = "hospitalization"
        elif any(token in normalized for token in ["casa asigurare", "categoria de asigurat", "telefon", "adresa", "loc de munca", "ocupatia", "numar de asigurat"]):
            current_key = "insurance_contact"
        elif any(token in normalized for token in ["nume", "prenume", "varsta", "cnp", "cod pacient"]):
            current_key = "patient_information"

        buckets[current_key].append(line)

    sections: list[dict[str, Any]] = []

    for key in SECTION_ORDER:
        if key not in buckets:
            continue

        body = clean_discharge_text("\n".join(buckets[key]))
        if not body:
            continue

        sections.append(
            {
                "key": key,
                "title": CANONICAL_TITLES[key],
                "original_title": CANONICAL_TITLES[key],
                "body": body,
                "confidence": 0.9,
            }
        )

    return sections


def extract_epicriza_text(text: str) -> str:
    prepared_text = prepare_text_for_sectioning(text)
    match = re.search(r"\bEPICRIZ[ĂA]\b\s*[:\-]?", prepared_text, flags=re.IGNORECASE)

    if not match:
        return ""

    return prepared_text[match.end() :].strip()


def split_clinical_sections(text: str) -> list[dict[str, Any]]:
    epicriza_body = extract_epicriza_text(text)

    if not epicriza_body:
        return []

    sections: list[dict[str, Any]] = []

    current_key = "epicriza"
    current_title = CANONICAL_TITLES["epicriza"]
    current_original_title = "EPICRIZA"
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_title, current_original_title, current_lines

        body = clean_discharge_text("\n".join(current_lines))
        if body:
            sections.append(
                {
                    "key": current_key,
                    "title": current_title,
                    "original_title": current_original_title,
                    "body": body,
                    "confidence": 0.9,
                }
            )

        current_lines = []

    lines = [clean_discharge_text(line) for line in epicriza_body.splitlines()]
    lines = [line for line in lines if line]

    for line in lines:
        matched = match_major_section_header(line, current_key=current_key, clinical_started=True)

        if matched:
            key, heading, inline_body = matched

            if key != current_key:
                flush()
                current_key = key
                current_title = CANONICAL_TITLES.get(key, heading)
                current_original_title = heading

            if inline_body:
                current_lines.append(inline_body)

            continue

        current_lines.append(line)

    flush()
    return sections


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
            separator = f"\n\n[{original_title}]\n" if original_title else "\n\n"
            grouped[key]["body"] = grouped[key]["body"].rstrip() + separator + body
            grouped[key]["confidence"] = max(float(grouped[key].get("confidence") or 0.5), confidence)

        if original_title and original_title not in grouped[key]["original_titles"]:
            grouped[key]["original_titles"].append(original_title)

    ordered: list[dict[str, Any]] = []

    for key in SECTION_ORDER:
        if key in grouped:
            ordered.append(grouped.pop(key))

    ordered.extend(grouped.values())
    return ordered


def split_into_sections(text: str) -> list[dict[str, Any]]:
    front_sections = extract_front_page_sections(text)
    clinical_sections = split_clinical_sections(text)
    sections = merge_duplicate_sections(front_sections + clinical_sections)

    if not sections and text.strip():
        sections.append(
            {
                "key": "other",
                "title": "Other relevant clinical text",
                "original_titles": [],
                "body": clean_discharge_text(text),
                "confidence": 0.35,
            }
        )

    return sections


def extract_discharge_dates(text: str) -> dict[str, str | None]:
    clean = clean_discharge_text(text)

    admission = None
    discharge = None
    issued = None

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


def extract_hospitalization_period(text: str) -> dict[str, str | None]:
    clean = clean_discharge_text(text)

    period_patterns = [
        r"perioada\s+intern[aă]rii\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(\d{1,2}:\d{2})?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(\d{1,2}:\d{2})?",
        r"perioada\s+de\s+internare\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(\d{1,2}:\d{2})?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(\d{1,2}:\d{2})?",
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


def parse_discharge_document(extraction: dict[str, Any] | str) -> dict[str, Any]:
    text = get_best_ocr_text(extraction)
    metadata = extract_report_metadata(text)

    date_metadata = extract_hospitalization_period(text)

    if not date_metadata.get("admission_date") and not date_metadata.get("discharge_date"):
        fallback_dates = extract_discharge_dates(text)
        date_metadata = {
            "admission_date": fallback_dates.get("admission_date"),
            "discharge_date": fallback_dates.get("discharge_date"),
        }

    issued_date = extract_issued_date(text)
    sections = split_into_sections(text)

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
            f"Discharge parser created {len(sections)} organized narrative sections using strict fișă de externare buckets.",
            "Hospitalization dates were extracted from Perioada internării when present.",
        ],
    }