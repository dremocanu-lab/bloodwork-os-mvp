import re
from datetime import datetime


ROMANIAN_MONTHS = {
    "ian": "Jan",
    "ianuarie": "Jan",
    "jan": "Jan",
    "feb": "Feb",
    "februarie": "Feb",
    "mar": "Mar",
    "martie": "Mar",
    "apr": "Apr",
    "aprilie": "Apr",
    "mai": "May",
    "may": "May",
    "iun": "Jun",
    "iunie": "Jun",
    "jun": "Jun",
    "iul": "Jul",
    "iulie": "Jul",
    "jul": "Jul",
    "aug": "Aug",
    "august": "Aug",
    "sep": "Sep",
    "sept": "Sep",
    "septembrie": "Sep",
    "oct": "Oct",
    "octombrie": "Oct",
    "nov": "Nov",
    "noiembrie": "Nov",
    "dec": "Dec",
    "decembrie": "Dec",
}

DATE_CAPTURE = (
    r"("
    r"\d{1,2}\s+[A-Za-z]{3,12}\s+\d{4}\s+\d{1,2}:\d{2}"
    r"|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s+\d{1,2}:\d{2}"
    r"|\d{4}-\d{1,2}-\d{1,2}[T\s]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:?\d{2})?"
    r"|\d{1,2}\s+[A-Za-z]{3,12}\s+\d{4}"
    r"|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r")"
)

COLLECTION_LABELS = [
    "data si ora recoltarii setului de analize",
    "data si ora recoltarii",
    "data recoltarii",
    "recoltarii setului de analize",
    "data recoltare",
    "recoltare",
    "collected on",
    "collection date",
    "collection datetime",
]

RECEIVED_LABELS = [
    "data si ora sosirii in laborator",
    "data sosirii in laborator",
    "sosirii in laborator",
    "received on",
    "registered on",
    "arrived in laboratory",
]

REPORTED_LABELS = [
    "data validare",
    "data validarii",
    "data si ora validarii",
    "reported on",
    "validated on",
    "validation date",
]


def strip_accents_ro(value: str | None) -> str:
    if not value:
        return ""

    safe = str(value)
    replacements = {
        "ă": "a",
        "Ă": "A",
        "â": "a",
        "Â": "A",
        "î": "i",
        "Î": "I",
        "ș": "s",
        "Ș": "S",
        "ş": "s",
        "Ş": "S",
        "ț": "t",
        "Ț": "T",
        "ţ": "t",
        "Ţ": "T",
    }

    for old, new in replacements.items():
        safe = safe.replace(old, new)

    return safe


def clean_spaces(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = str(value)
    cleaned = cleaned.replace("\ufeff", "")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("|", " ")
    cleaned = cleaned.replace("–", "-").replace("—", "-").replace("−", "-")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" :-;\t\r\n")

    return cleaned or None


def normalize_ocr_text(text: str | None) -> str:
    safe = strip_accents_ro(text or "")
    safe = safe.replace("\ufeff", "")
    safe = safe.replace("\u00a0", " ")
    safe = safe.replace("\r", "\n")
    safe = safe.replace("|", " ")
    safe = safe.replace("–", "-").replace("—", "-").replace("−", "-")
    safe = safe.replace("Data si ora recoltarii setului de analize", "\nData si ora recoltarii setului de analize")
    safe = safe.replace("Data si ora sosirii in laborator", "\nData si ora sosirii in laborator")
    safe = safe.replace("Data validare", "\nData validare")
    safe = re.sub(r"[ \t]+", " ", safe)
    return safe


def flatten_text(text: str | None) -> str:
    safe = normalize_ocr_text(text)
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe


def normalize_month_words(value: str) -> str:
    cleaned = value

    for ro, en in ROMANIAN_MONTHS.items():
        cleaned = re.sub(rf"\b{re.escape(ro)}\b", en, cleaned, flags=re.IGNORECASE)

    return cleaned


def looks_like_upload_timestamp(value: str | None) -> bool:
    if not value:
        return False

    cleaned = str(value).strip()

    # Frontend/backend upload timestamps look like this:
    # 2026-04-29T18:55:41.792880+00:00
    # These should never become clinical collection dates.
    if re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", cleaned):
        return True

    if "+00:00" in cleaned or cleaned.endswith("Z"):
        return True

    return False


def parse_date_to_display(value: str | None) -> str | None:
    cleaned = clean_spaces(value)

    if not cleaned:
        return None

    if looks_like_upload_timestamp(cleaned):
        return None

    cleaned = normalize_month_words(cleaned)
    cleaned = cleaned.replace(",", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    formats = [
        "%d %b %Y %H:%M",
        "%d %B %Y %H:%M",
        "%d.%m.%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%d %b %Y",
        "%d %B %Y",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(cleaned, fmt)

            if parsed.year < 1900 or parsed.year > 2100:
                return None

            if "%H" in fmt:
                return parsed.strftime("%d %b %Y %H:%M")

            return parsed.strftime("%d %b %Y")
        except Exception:
            continue

    return cleaned


def first_match(text: str, patterns: list[str], flags: int = re.IGNORECASE | re.MULTILINE) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text or "", flags)

        if not match:
            continue

        for group in match.groups():
            cleaned = clean_spaces(group)

            if cleaned:
                return cleaned

    return None


def date_after_label(text: str, labels: list[str]) -> str | None:
    multiline = normalize_ocr_text(text)
    flat = flatten_text(text)

    sources = [multiline, flat]

    for source in sources:
        for label in labels:
            label_pattern = re.escape(label).replace(r"\ ", r"\s+")

            patterns = [
                rf"{label_pattern}\s*[:\-]?\s*{DATE_CAPTURE}",
                rf"{label_pattern}[^\d]{{0,120}}{DATE_CAPTURE}",
            ]

            for pattern in patterns:
                match = re.search(pattern, source, re.IGNORECASE | re.DOTALL)

                if not match:
                    continue

                parsed = parse_date_to_display(match.group(1))

                if parsed:
                    return parsed

    return None


def all_header_dates(text: str) -> list[str]:
    flat = flatten_text(text)
    header = flat[:2200]
    dates: list[str] = []

    for match in re.finditer(DATE_CAPTURE, header, re.IGNORECASE):
        parsed = parse_date_to_display(match.group(1))

        if parsed and parsed not in dates:
            dates.append(parsed)

    return dates


def extract_collection_date(text: str) -> str | None:
    labeled = date_after_label(text, COLLECTION_LABELS)

    if labeled:
        return labeled

    flat = flatten_text(text)

    # Fundeni reports usually have:
    # BULETIN ANALIZE MEDICALE
    # Data si ora recoltarii setului de analize: 02 Mar 2023 08:41
    title_match = re.search(
        rf"BULETIN\s+ANALIZE\s+MEDICALE[^\d]{{0,260}}{DATE_CAPTURE}",
        flat,
        re.IGNORECASE | re.DOTALL,
    )

    if title_match:
        parsed = parse_date_to_display(title_match.group(1))

        if parsed:
            return parsed

    # Last clinical fallback: first date in report header, not upload timestamp.
    dates = all_header_dates(text)

    if dates:
        return dates[0]

    return None


def extract_registered_date(text: str) -> str | None:
    return date_after_label(text, RECEIVED_LABELS)


def extract_reported_date(text: str) -> str | None:
    return date_after_label(text, REPORTED_LABELS)


def extract_patient_name(text: str) -> str | None:
    safe = normalize_ocr_text(text)

    raw = first_match(
        safe,
        [
            r"\bNume\s*[:\-]?\s*([A-Z][A-Z .'\-]{2,80})",
            r"\bPacient\s*[:\-]?\s*([A-Z][A-Z .'\-]{2,80})",
            r"\bName\s*[:\-]?\s*([A-Z][A-Za-z .'\-]{2,80})",
        ],
    )

    if not raw:
        return None

    raw = re.split(
        r"\b(?:CNP|Telefon|Varsta|Cod pacient|Sex|Sectie|Medic|Nr\.?\s*Foaie)\b",
        raw,
        flags=re.IGNORECASE,
    )[0]

    return clean_spaces(raw)


def extract_cnp(text: str) -> str | None:
    safe = normalize_ocr_text(text)

    return first_match(
        safe,
        [
            r"\bCNP\s*[:\-]?\s*(\d{13})",
            r"\bCod\s+numeric\s+personal\s*[:\-]?\s*(\d{13})",
        ],
    )


def extract_patient_identifier(text: str) -> str | None:
    safe = normalize_ocr_text(text)

    return first_match(
        safe,
        [
            r"\bCod\s+pacient\s*[:\-]?\s*([A-Za-z0-9\-_/.]{4,40})",
            r"\bID\s+pacient\s*[:\-]?\s*([A-Za-z0-9\-_/.]{4,40})",
            r"\bPatient\s+ID\s*[:\-]?\s*([A-Za-z0-9\-_/.]{4,40})",
            r"\bNr\.?\s*Foaie\s+Observatie\s*[:\-]?\s*([A-Za-z0-9\-_/.]{4,40})",
        ],
    )


def extract_age(text: str) -> str | None:
    safe = normalize_ocr_text(text)

    return first_match(
        safe,
        [
            r"\bVarsta\s*[:\-]?\s*([0-9]{1,3}\s*(?:ani|an|years?|y)?(?:\s*(?:si)?\s*[0-9]{1,2}\s*(?:luni|months?))?)",
            r"\bAge\s*[:\-]?\s*([0-9]{1,3}\s*(?:years?|y)?(?:\s*[0-9]{1,2}\s*months?)?)",
        ],
    )


def extract_sex(text: str) -> str | None:
    safe = normalize_ocr_text(text)

    raw = first_match(
        safe,
        [
            r"\bSex\s*[:\-]?\s*(Masculin|Feminin|Male|Female|M|F)\b",
            r"\bGen\s*[:\-]?\s*(Masculin|Feminin|Male|Female|M|F)\b",
        ],
    )

    if not raw:
        return None

    lowered = raw.lower()

    if lowered in {"m", "male", "masculin"}:
        return "Male"

    if lowered in {"f", "female", "feminin"}:
        return "Female"

    return raw


def extract_lab_name(text: str) -> str | None:
    safe = normalize_ocr_text(text)

    return first_match(
        safe,
        [
            r"(Institutul\s+Clinic\s+Fundeni)",
            r"(Laborator(?:ul)?\s+de\s+Analize[^\n]{0,80})",
            r"(Synevo[^\n]{0,80})",
            r"(Regina\s+Maria[^\n]{0,80})",
            r"(MedLife[^\n]{0,80})",
        ],
    )


def extract_referring_doctor(text: str) -> str | None:
    safe = normalize_ocr_text(text)

    raw = first_match(
        safe,
        [
            r"\bMedic\s*[:\-]?\s*([A-Z][A-Za-z .'\-]{3,80})",
            r"\bDoctor\s*[:\-]?\s*([A-Z][A-Za-z .'\-]{3,80})",
            r"\bDr\.?\s*([A-Z][A-Za-z .'\-]{3,80})",
        ],
    )

    if not raw:
        return None

    raw = re.split(
        r"\b(?:Data|Validat|Parafa|Sectie|CNP|Telefon)\b",
        raw,
        flags=re.IGNORECASE,
    )[0]

    return clean_spaces(raw)


def extract_sample_type(text: str) -> str | None:
    safe = normalize_ocr_text(text)

    return first_match(
        safe,
        [
            r"\bTip\s+proba\s*[:\-]?\s*([A-Za-z0-9 .'\-]{2,60})",
            r"\bSample\s+type\s*[:\-]?\s*([A-Za-z0-9 .'\-]{2,60})",
            r"\bCod\s+proba\s*[:\-]?\s*([A-Za-z0-9\-_/.]{2,40})",
        ],
    )


def extract_report_type(text: str) -> str:
    lowered = normalize_ocr_text(text).lower()

    if "hematologie" in lowered or "hemograma" in lowered or "hemogram" in lowered or "citomorfologie" in lowered:
        return "Bloodwork"

    if "biochimie" in lowered or "glucoza" in lowered or "creatinina" in lowered:
        return "Bloodwork"

    if "urina" in lowered or "sumar urina" in lowered:
        return "Bloodwork"

    return "Bloodwork"


def extract_report_name(text: str, collected_on: str | None = None) -> str:
    lowered = normalize_ocr_text(text).lower()

    if "hematologie" in lowered or "hemograma" in lowered or "hemogram" in lowered or "citomorfologie" in lowered:
        base = "Hematologie"
    elif "biochimie" in lowered:
        base = "Biochimie"
    elif "urina" in lowered:
        base = "Urinalysis"
    else:
        base = "Analize medicale"

    if collected_on:
        return f"{base} {collected_on}"

    return base


def extract_source_language(text: str) -> str:
    lowered = normalize_ocr_text(text).lower()

    romanian_markers = [
        "buletin analize",
        "recoltarii",
        "varsta",
        "sectie",
        "medic",
        "interval biologic",
        "laborator",
    ]

    if any(marker in lowered for marker in romanian_markers):
        return "ro"

    return "en"


def extract_report_metadata(text: str) -> dict:
    safe_text = text or ""

    collected_on = extract_collection_date(safe_text)
    reported_on = extract_reported_date(safe_text)
    registered_on = extract_registered_date(safe_text)

    # Important: this must be a true clinical date, not upload created_at.
    test_date = collected_on or reported_on or registered_on

    return {
        "patient_name": extract_patient_name(safe_text),
        "date_of_birth": None,
        "age": extract_age(safe_text),
        "sex": extract_sex(safe_text),
        "cnp": extract_cnp(safe_text),
        "patient_identifier": extract_patient_identifier(safe_text),
        "lab_name": extract_lab_name(safe_text),
        "sample_type": extract_sample_type(safe_text),
        "referring_doctor": extract_referring_doctor(safe_text),
        "report_name": extract_report_name(safe_text, collected_on or test_date),
        "report_type": extract_report_type(safe_text),
        "source_language": extract_source_language(safe_text),
        "test_date": test_date,
        "collected_on": collected_on,
        "reported_on": reported_on,
        "registered_on": registered_on,
        "generated_on": None,
    }
