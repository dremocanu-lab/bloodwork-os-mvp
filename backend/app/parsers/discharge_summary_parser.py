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


def slugify(value: Any) -> str:
    normalized = normalize(value)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return normalized or "section"


def strip_google_markers(text: str) -> str:
    cleaned = clean_text(text)
    cleaned = re.sub(
        r"--- GOOGLE DOCUMENT AI [A-Z0-9 =_-]+ ---",
        "\n",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_best_text(extraction_or_text: dict[str, Any] | str) -> str:
    if isinstance(extraction_or_text, str):
        return strip_google_markers(extraction_or_text)

    parts: list[str] = []

    for key in [
        "plain_text",
        "lines_text",
        "table_text",
        "tokens_text",
        "text",
        "extracted_text",
        "debug_text",
    ]:
        value = extraction_or_text.get(key)

        if isinstance(value, str) and value.strip():
            parts.append(strip_google_markers(value))

    seen: set[str] = set()
    unique_parts: list[str] = []

    for part in parts:
        compact = " ".join(part.split())

        if not compact or compact in seen:
            continue

        seen.add(compact)
        unique_parts.append(part)

    return clean_text("\n\n".join(unique_parts))


SECTION_BUCKETS: list[dict[str, Any]] = [
    {
        "key": "patient_admission_info",
        "title": "Patient and admission information",
        "aliases": [
            "date pacient",
            "datele pacientului",
            "date identificare pacient",
            "foaie de observatie",
            "foaie observatie",
            "nr foaie observatie",
            "sectia",
            "sectie",
            "medic curant",
            "medic",
            "data internarii",
            "data internare",
            "data externarii",
            "data externare",
            "unitatea sanitara",
            "spital",
            "admission information",
            "patient information",
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
        "key": "objective_exam",
        "title": "Objective exam / Clinical examination",
        "aliases": [
            "examen obiectiv",
            "examen clinic",
            "stare generala",
            "stare generală",
            "status clinic",
            "clinical examination",
            "physical examination",
            "objective exam",
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
            "rezultate laborator",
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
        "key": "procedures",
        "title": "Procedures / Interventions",
        "aliases": [
            "proceduri",
            "interventii",
            "intervenții",
            "proceduri efectuate",
            "manevre",
            "interventions",
            "procedures",
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
            "tratament de urmat",
            "medicatie la externare",
            "medicație la externare",
            "medicatie recomandata",
            "medicație recomandată",
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


HEADER_NOISE_PATTERNS = [
    r"^pagina\s+\d+",
    r"^\d+\s*/\s*\d+$",
    r"^page\s+\d+",
    r"^printabile",
    r"^http",
    r"^www\.",
    r"^cod\s+bare",
    r"^semnatura",
    r"^parafa",
    r"^validat",
    r"^nevalidat",
]


def is_noise_line(line: str) -> bool:
    norm = normalize(line)

    if not norm:
        return True

    for pattern in HEADER_NOISE_PATTERNS:
        if re.search(pattern, norm):
            return True

    return False


def canonical_title(key: str) -> str:
    for bucket in SECTION_BUCKETS:
        if bucket["key"] == key:
            return bucket["title"]

    return "Clinical section"


def match_known_heading(line: str) -> tuple[str, str] | None:
    raw = clean_text(line)
    norm = normalize(raw)

    if not norm:
        return None

    heading_part = raw.split(":", 1)[0].strip()
    heading_norm = normalize(heading_part)

    for bucket in SECTION_BUCKETS:
        for alias in bucket["aliases"]:
            alias_norm = normalize(alias)

            if not alias_norm:
                continue

            if heading_norm == alias_norm:
                return bucket["key"], raw

            if heading_norm.startswith(alias_norm) and len(heading_norm) <= len(alias_norm) + 55:
                return bucket["key"], raw

            if norm.startswith(alias_norm + ":"):
                return bucket["key"], raw

            if norm.startswith(alias_norm + " -"):
                return bucket["key"], raw

    return None


def has_value_after_colon(line: str) -> bool:
    if ":" not in line:
        return False

    left, right = line.split(":", 1)
    return bool(left.strip() and right.strip())


def looks_like_dynamic_heading(line: str) -> bool:
    raw = clean_text(line)

    if is_noise_line(raw):
        return False

    norm = normalize(raw)

    if not norm:
        return False

    if re.search(r"\d{4,}|\d+\.\d+|mg|g/dl|10\^|mmol|trombocite|hemoglobina", norm):
        return False

    if len(norm) < 3:
        return False

    # Known headings are always accepted.
    if match_known_heading(raw):
        return True

    # Numbered section headings:
    # 1. Epicriza
    # 2) Tratament recomandat
    if re.match(r"^\s*\d{1,2}[\.)]\s+[A-Za-zĂÂÎȘȚăâîșț]", raw):
        return len(norm) <= 120

    # Romanian forms sometimes use title + colon.
    # Accept short labels before the colon as section headings.
    if ":" in raw:
        left, right = raw.split(":", 1)
        left_norm = normalize(left)

        if 3 <= len(left_norm) <= 95:
            # If right side is long, it is still a section with same-line body.
            return True

    # All caps headings are very common in discharge summaries.
    letters = re.sub(r"[^A-Za-zĂÂÎȘȚăâîșț]", "", raw)
    if letters and len(letters) >= 4:
        uppercase_letters = sum(1 for char in letters if char.isupper())
        uppercase_ratio = uppercase_letters / max(len(letters), 1)

        if uppercase_ratio >= 0.75 and len(norm) <= 120:
            return True

    # Title case short lines can be headings, but avoid generic sentence fragments.
    words = raw.split()
    if 1 <= len(words) <= 9 and len(norm) <= 90:
        title_like_words = 0

        for word in words:
            stripped = word.strip(" .,:;-()[]")
            if not stripped:
                continue

            if stripped[:1].isupper():
                title_like_words += 1

        if title_like_words >= max(1, len(words) - 1):
            return True

    return False


def classify_heading_title(line: str, index: int) -> tuple[str, str, str]:
    raw = clean_text(line)
    known = match_known_heading(raw)

    if known:
        key, original_title = known
        return key, canonical_title(key), original_title

    heading_text = raw.split(":", 1)[0].strip() if ":" in raw else raw.strip()
    heading_text = re.sub(r"^\s*\d{1,2}[\.)]\s*", "", heading_text).strip()
    heading_text = heading_text.strip(" -–—:;.")

    key = f"custom_{index}_{slugify(heading_text)[:50]}"
    title = heading_text or f"Clinical section {index}"

    return key, title, raw


def split_inline_headings(text: str) -> str:
    result = text

    aliases: list[str] = []
    for bucket in SECTION_BUCKETS:
        aliases.extend(bucket["aliases"])

    for alias in sorted(set(aliases), key=len, reverse=True):
        escaped = re.escape(alias)
        result = re.sub(
            rf"(?i)(?<!\n)\b({escaped})\s*:",
            r"\n\1:",
            result,
        )

    return result


def split_into_sections(text: str) -> list[dict[str, Any]]:
    cleaned = split_inline_headings(clean_text(text))

    raw_lines = [clean_text(line) for line in cleaned.splitlines()]
    lines = [line for line in raw_lines if line and not is_noise_line(line)]

    sections: list[dict[str, Any]] = []

    current_key: str | None = None
    current_title: str | None = None
    current_original_title: str | None = None
    current_lines: list[str] = []
    section_index = 0

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
                    "title": current_title or "Clinical section",
                    "original_titles": [current_original_title] if current_original_title else [],
                    "body": body,
                    "confidence": 0.9,
                }
            )
        else:
            sections.append(
                {
                    "key": "other_intro",
                    "title": "Introductory / unclassified text",
                    "original_titles": [],
                    "body": body,
                    "confidence": 0.45,
                }
            )

        current_key = None
        current_title = None
        current_original_title = None
        current_lines = []

    for line in lines:
        if looks_like_dynamic_heading(line):
            section_index += 1
            flush()

            current_key, current_title, current_original_title = classify_heading_title(line, section_index)

            if has_value_after_colon(line):
                after_colon = line.split(":", 1)[1].strip()
                if after_colon:
                    current_lines.append(after_colon)

            continue

        current_lines.append(line)

    flush()

    if not sections and cleaned:
        sections.append(
            {
                "key": "full_discharge_text",
                "title": "Full discharge text",
                "original_titles": [],
                "body": cleaned,
                "confidence": 0.25,
            }
        )

    return remove_empty_and_tiny_sections(sections)


def remove_empty_and_tiny_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned_sections: list[dict[str, Any]] = []

    for section in sections:
        body = clean_text(section.get("body"))

        if not body:
            continue

        # Avoid tiny administrative leftovers unless they are the only content.
        if len(body) < 2:
            continue

        next_section = {
            "key": section.get("key") or f"custom_{len(cleaned_sections) + 1}",
            "title": section.get("title") or "Clinical section",
            "original_titles": section.get("original_titles") or [],
            "body": body,
            "confidence": float(section.get("confidence") or 0.5),
        }

        cleaned_sections.append(next_section)

    if not cleaned_sections and sections:
        first_body = clean_text(sections[0].get("body"))
        if first_body:
            cleaned_sections.append(
                {
                    "key": "full_discharge_text",
                    "title": "Full discharge text",
                    "original_titles": [],
                    "body": first_body,
                    "confidence": 0.25,
                }
            )

    return cleaned_sections


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
            f"Dynamic discharge summary parser created {len(sections)} narrative sections."
        ],
    }