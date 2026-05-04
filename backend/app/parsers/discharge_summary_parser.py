from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from app.report_fields import extract_report_metadata


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\ufeff", "")
    text = text.replace("\u00a0", " ")
    text = text.replace("Â", "")
    text = text.replace("â€™", "'")
    text = text.replace("â€œ", '"').replace("â€\x9d", '"')
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize(value: Any) -> str:
    text = clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ș", "s").replace("ț", "t")
    text = text.replace("ă", "a").replace("â", "a").replace("î", "i")
    text = re.sub(r"[^a-z0-9%#./:+ -]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_best_text(extraction_or_text: dict[str, Any] | str) -> str:
    if isinstance(extraction_or_text, str):
        return clean_text(extraction_or_text)

    for key in ["plain_text", "lines_text", "text", "extracted_text", "debug_text"]:
        value = extraction_or_text.get(key)
        if isinstance(value, str) and value.strip():
            text = value
            break
    else:
        return ""

    if "--- GOOGLE DOCUMENT AI PLAIN TEXT ---" in text:
        text = text.split("--- GOOGLE DOCUMENT AI PLAIN TEXT ---", 1)[1]
        marker = re.search(r"\n--- GOOGLE DOCUMENT AI [A-Z ]+ ---", text)
        if marker:
            text = text[: marker.start()]

    return clean_text(text)


SECTION_BUCKETS: list[dict[str, Any]] = [
    {
        "key": "patient_admission_info",
        "title": "Patient and admission information",
        "aliases": [
            "date pacient",
            "datele pacientului",
            "foaie de observatie",
            "foaie observatie",
            "sectia",
            "sectie",
            "medic curant",
            "data internarii",
            "data internare",
            "data externarii",
            "data externare",
            "admission information",
        ],
    },
    {
        "key": "diagnoses",
        "title": "Diagnoses / Diagnostic",
        "aliases": [
            "diagnostic",
            "diagnostic principal",
            "diagnostic secundar",
            "diagnostic la internare",
            "diagnostic la externare",
            "diagnostic externare",
            "diagnostice",
            "cod diagnostic",
            "icd",
            "drg",
            "discharge diagnosis",
            "final diagnosis",
            "diagnoses",
        ],
    },
    {
        "key": "epicriza",
        "title": "Epicriză / Clinical course",
        "aliases": [
            "epicriza",
            "epicriză",
            "evolutie",
            "evoluție",
            "evolutia",
            "evoluția",
            "istoric",
            "anamneza",
            "anamneză",
            "boala actuala",
            "boala actuală",
            "motivul internarii",
            "motivul internării",
            "pacientul se interneaza",
            "pacientul se internează",
            "clinical course",
            "hospital course",
            "medical summary",
            "summary",
        ],
    },
    {
        "key": "investigations",
        "title": "Investigations / Results",
        "aliases": [
            "investigatii",
            "investigații",
            "explorari paraclinice",
            "explorări paraclinice",
            "examene paraclinice",
            "paraclinic",
            "analize",
            "rezultate analize",
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
    },
    {
        "key": "treatment_in_hospital",
        "title": "Treatment during admission",
        "aliases": [
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
    },
    {
        "key": "recommended_treatment",
        "title": "Recommended treatment / Discharge medication",
        "aliases": [
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
    },
    {
        "key": "recommendations",
        "title": "Recommendations / Follow-up",
        "aliases": [
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
    },
    {
        "key": "discharge_status",
        "title": "Discharge status",
        "aliases": [
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
    },
]


ORDERED_KEYS = [
    "patient_admission_info",
    "diagnoses",
    "epicriza",
    "investigations",
    "treatment_in_hospital",
    "recommended_treatment",
    "recommendations",
    "discharge_status",
    "other",
]


def canonical_title(key: str) -> str:
    for bucket in SECTION_BUCKETS:
        if bucket["key"] == key:
            return bucket["title"]
    return "Other clinical text"


def looks_like_heading(line: str) -> bool:
    raw = clean_text(line)
    norm = normalize(raw)

    if not norm:
        return False

    if len(norm) > 130 and ":" not in norm:
        return False

    if raw.isupper() and len(raw) <= 120:
        return True

    if ":" in raw and len(raw.split(":", 1)[0]) <= 90:
        return True

    return False


def match_heading(line: str) -> tuple[str, str, str] | None:
    raw = clean_text(line)
    norm = normalize(raw)

    if not norm or not looks_like_heading(raw):
        return None

    heading_part = raw.split(":", 1)[0].strip()
    heading_norm = normalize(heading_part)

    for bucket in SECTION_BUCKETS:
        for alias in bucket["aliases"]:
            alias_norm = normalize(alias)

            if not alias_norm:
                continue

            if heading_norm == alias_norm:
                return bucket["key"], bucket["title"], raw

            if heading_norm.startswith(alias_norm):
                return bucket["key"], bucket["title"], raw

            if norm.startswith(alias_norm + ":"):
                return bucket["key"], bucket["title"], raw

            if norm.startswith(alias_norm + " -"):
                return bucket["key"], bucket["title"], raw

    return None


def classify_unheaded_text(body: str) -> tuple[str, str, float]:
    norm = normalize(body)

    if not norm:
        return "other", "Other clinical text", 0.2

    scores: dict[str, int] = {}

    for bucket in SECTION_BUCKETS:
        score = 0

        for alias in bucket["aliases"]:
            alias_norm = normalize(alias)
            if alias_norm and alias_norm in norm:
                score += 1

        scores[bucket["key"]] = score

    if re.search(r"\b(diagnostic|diagnostice|icd|drg)\b", norm):
        scores["diagnoses"] = scores.get("diagnoses", 0) + 3

    if re.search(r"\b(epicriza|evolutie|anamneza|internarii|pacientul)\b", norm):
        scores["epicriza"] = scores.get("epicriza", 0) + 3

    if re.search(r"\b(ct|rmn|irm|rx|ecografie|ecg|ekg|analize|hemoglobina|leucocite|trombocite)\b", norm):
        scores["investigations"] = scores.get("investigations", 0) + 3

    if re.search(r"\b(se recomanda|control|monitorizare|regim|revine|indicatii)\b", norm):
        scores["recommendations"] = scores.get("recommendations", 0) + 3

    if re.search(r"\b(rp|comprimate|capsule|mg|ml|x\s*\d|dimineata|seara|tratament)\b", norm):
        scores["recommended_treatment"] = scores.get("recommended_treatment", 0) + 2

    best_key = max(scores, key=lambda key: scores[key])
    best_score = scores.get(best_key, 0)

    if best_score <= 0:
        return "other", "Other clinical text", 0.35

    return best_key, canonical_title(best_key), min(0.9, 0.45 + best_score * 0.12)


def split_into_sections(text: str) -> list[dict[str, Any]]:
    cleaned = clean_text(text)
    lines = [clean_text(line) for line in cleaned.splitlines()]
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

        if current_key:
            sections.append(
                {
                    "key": current_key,
                    "title": current_title or canonical_title(current_key),
                    "original_title": current_original_title,
                    "body": body,
                    "confidence": 0.92,
                }
            )
        else:
            key, title, confidence = classify_unheaded_text(body)
            sections.append(
                {
                    "key": key,
                    "title": title,
                    "original_title": None,
                    "body": body,
                    "confidence": confidence,
                }
            )

        current_key = None
        current_title = None
        current_original_title = None
        current_lines = []

    for line in lines:
        matched = match_heading(line)

        if matched:
            flush()

            current_key, current_title, current_original_title = matched

            if ":" in line:
                after_colon = line.split(":", 1)[1].strip()
                if after_colon:
                    current_lines.append(after_colon)

            continue

        current_lines.append(line)

    flush()

    if not sections and cleaned:
        sections.append(
            {
                "key": "other",
                "title": "Full discharge text",
                "original_title": None,
                "body": cleaned,
                "confidence": 0.25,
            }
        )

    merged = merge_sections(sections)

    if not merged and cleaned:
        merged = [
            {
                "key": "other",
                "title": "Full discharge text",
                "original_titles": [],
                "body": cleaned,
                "confidence": 0.25,
            }
        ]

    return merged


def merge_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for section in sections:
        key = section.get("key") or "other"
        body = clean_text(section.get("body"))

        if not body:
            continue

        if key not in grouped:
            grouped[key] = {
                "key": key,
                "title": section.get("title") or canonical_title(key),
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

    for key in ORDERED_KEYS:
        if key in grouped:
            ordered.append(grouped.pop(key))

    ordered.extend(grouped.values())
    return ordered


def extract_discharge_dates(text: str) -> dict[str, str | None]:
    cleaned = clean_text(text)

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
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            admission = clean_text(match.group(1))[:100]
            break

    for pattern in discharge_patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            discharge = clean_text(match.group(1))[:100]
            break

    return {
        "admission_date": admission,
        "discharge_date": discharge,
    }


def parse_discharge_summary(extraction_or_text: dict[str, Any] | str) -> dict[str, Any]:
    text = extract_best_text(extraction_or_text)
    metadata = extract_report_metadata(text)
    dates = extract_discharge_dates(text)
    sections = split_into_sections(text)

    report_date = (
        dates.get("discharge_date")
        or metadata.get("generated_on")
        or metadata.get("reported_on")
        or metadata.get("registered_on")
    )

    report_name = "Fișă de externare"
    if report_date:
        report_name = f"Fișă de externare {report_date}"

    note_payload = {
        "document_type": "discharge_summary",
        "sections": sections,
    }

    return {
        "patient_name": metadata.get("patient_name"),
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
        "collected_on": dates.get("admission_date"),
        "reported_on": dates.get("discharge_date"),
        "registered_on": metadata.get("registered_on"),
        "generated_on": metadata.get("generated_on"),
        "note_body": json.dumps(note_payload, ensure_ascii=False),
        "labs": [],
        "warnings": [
            f"New discharge summary parser created {len(sections)} narrative sections."
        ],
    }