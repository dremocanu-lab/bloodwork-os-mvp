import re
from datetime import datetime


MONTHS_RO_EN = {
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


def clean_spaces(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = re.sub(r"\s+", " ", str(value)).strip(" :-–—\t\r\n")

    return cleaned or None


def normalize_date_text(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = clean_spaces(value)

    if not cleaned:
        return None

    cleaned = cleaned.replace(",", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    for ro, en in MONTHS_RO_EN.items():
        cleaned = re.sub(rf"\b{re.escape(ro)}\b", en, cleaned, flags=re.IGNORECASE)

    return cleaned


def parse_date_to_display(value: str | None) -> str | None:
    cleaned = normalize_date_text(value)

    if not cleaned:
        return None

    formats = [
        "%d %b %Y %H:%M",
        "%d %B %Y %H:%M",
        "%d.%m.%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
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
            if "%H" in fmt:
                return parsed.strftime("%d %b %Y %H:%M")
            return parsed.strftime("%d %b %Y")
        except Exception:
            pass

    return cleaned


def first_match(text: str, patterns: list[str], flags: int = re.IGNORECASE | re.MULTILINE) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text or "", flags)

        if match:
            for group in match.groups():
                cleaned = clean_spaces(group)
                if cleaned:
                    return cleaned

    return None


def extract_date_after_label(text: str, labels: list[str]) -> str | None:
    safe_text = text or ""

    date_pattern = (
        r"("
        r"\d{1,2}\s+[A-Za-zăâîșțĂÂÎȘȚ]{3,12}\s+\d{4}\s+\d{1,2}:\d{2}"
        r"|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s+\d{1,2}:\d{2}"
        r"|\d{4}-\d{1,2}-\d{1,2}[T\s]\d{1,2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2})?"
        r"|\d{1,2}\s+[A-Za-zăâîșțĂÂÎȘȚ]{3,12}\s+\d{4}"
        r"|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
        r")"
    )

    for label in labels:
        pattern = rf"{label}\s*[:\-–—]?\s*(?:setului\s+de\s+analize\s*[:\-–—]?\s*)?{date_pattern}"
        match = re.search(pattern, safe_text, re.IGNORECASE | re.MULTILINE)

        if match:
            return parse_date_to_display(match.group(1))

    return None


def extract_patient_name(text: str) -> str | None:
    return first_match(
        text,
        [
            r"\bNume\s*[:\-]?\s*([A-ZĂÂÎȘȚ][A-ZĂÂÎȘȚa-zăâîșț .'-]{2,80})",
            r"\bPacient\s*[:\-]?\s*([A-ZĂÂÎȘȚ][A-ZĂÂÎȘȚa-zăâîșț .'-]{2,80})",
            r"\bName\s*[:\-]?\s*([A-Z][A-Za-z .'-]{2,80})",
        ],
    )


def extract_cnp(text: str) -> str | None:
    return first_match(
        text,
        [
            r"\bCNP\s*[:\-]?\s*(\d{13})",
            r"\bCod\s+numeric\s+personal\s*[:\-]?\s*(\d{13})",
        ],
    )


def extract_patient_identifier(text: str) -> str | None:
    return first_match(
        text,
        [
            r"\bCod\s+pacient\s*[:\-]?\s*([A-Za-z0-9\-_/]{4,40})",
            r"\bID\s+pacient\s*[:\-]?\s*([A-Za-z0-9\-_/]{4,40})",
            r"\bPatient\s+ID\s*[:\-]?\s*([A-Za-z0-9\-_/]{4,40})",
            r"\bNr\.?\s*Foaie\s+Observatie\s*[:\-]?\s*([A-Za-z0-9\-_/]{4,40})",
        ],
    )


def extract_age(text: str) -> str | None:
    raw = first_match(
        text,
        [
            r"\bV[âa]rsta\s*[:\-]?\s*([0-9]{1,3}\s*(?:ani|an|years?|y)?(?:\s*(?:si|și)?\s*[0-9]{1,2}\s*(?:luni|months?))?)",
            r"\bAge\s*[:\-]?\s*([0-9]{1,3}\s*(?:years?|y)?(?:\s*[0-9]{1,2}\s*months?)?)",
        ],
    )

    return clean_spaces(raw)


def extract_sex(text: str) -> str | None:
    raw = first_match(
        text,
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
    return first_match(
        text,
        [
            r"(Institutul\s+Clinic\s+Fundeni)",
            r"(Laborator(?:ul)?\s+de\s+Analize[^\n]{0,80})",
            r"(Synevo[^\n]{0,80})",
            r"(Regina\s+Maria[^\n]{0,80})",
            r"(MedLife[^\n]{0,80})",
        ],
    )


def extract_referring_doctor(text: str) -> str | None:
    return first_match(
        text,
        [
            r"\bMedic\s*[:\-]?\s*([A-ZĂÂÎȘȚa-zăâîșț .'-]{3,80})",
            r"\bDoctor\s*[:\-]?\s*([A-ZĂÂÎȘȚa-zăâîșț .'-]{3,80})",
            r"\bDr\.?\s*([A-ZĂÂÎȘȚa-zăâîșț .'-]{3,80})",
        ],
    )


def extract_sample_type(text: str) -> str | None:
    return first_match(
        text,
        [
            r"\bTip\s+proba\s*[:\-]?\s*([A-Za-zĂÂÎȘȚăâîșț0-9 .'-]{2,60})",
            r"\bTip\s+prob[ăa]\s*[:\-]?\s*([A-Za-zĂÂÎȘȚăâîșț0-9 .'-]{2,60})",
            r"\bSample\s+type\s*[:\-]?\s*([A-Za-z0-9 .'-]{2,60})",
            r"\bCod\s+proba\s*[:\-]?\s*([A-Za-z0-9\-_/]{2,40})",
        ],
    )


def extract_report_name(text: str, collected_on: str | None = None) -> str:
    lowered = (text or "").lower()

    if "hematologie" in lowered or "hemograma" in lowered or "hemogram" in lowered or "citomorfologie" in lowered:
        base = "Hematologie"
    elif "biochimie" in lowered:
        base = "Biochimie"
    elif "urina" in lowered or "urină" in lowered:
        base = "Urinalysis"
    else:
        base = "Analize medicale"

    if collected_on:
        return f"{base} {collected_on}"

    return base


def extract_source_language(text: str) -> str:
    lowered = (text or "").lower()

    romanian_markers = [
        "buletin analize",
        "recoltarii",
        "recoltării",
        "varsta",
        "vârsta",
        "sectie",
        "secție",
        "medic",
        "interval biologic",
    ]

    if any(marker in lowered for marker in romanian_markers):
        return "ro"

    return "en"


def extract_report_metadata(text: str) -> dict:
    safe_text = text or ""

    collected_on = extract_date_after_label(
        safe_text,
        [
            r"Data\s+si\s+ora\s+recoltarii",
            r"Data\s+și\s+ora\s+recoltării",
            r"Data\s+recoltarii",
            r"Data\s+recoltării",
            r"Recoltat(?:ă|a)?\s+la",
            r"Collected(?:\s+on)?",
            r"Collection\s+date",
        ],
    )

    reported_on = extract_date_after_label(
        safe_text,
        [
            r"Data\s+validare",
            r"Data\s+validarii",
            r"Data\s+validării",
            r"Data\s+si\s+ora\s+validarii",
            r"Data\s+și\s+ora\s+validării",
            r"Reported(?:\s+on)?",
            r"Validated(?:\s+on)?",
        ],
    )

    registered_on = extract_date_after_label(
        safe_text,
        [
            r"Data\s+si\s+ora\s+sosirii\s+in\s+laborator",
            r"Data\s+și\s+ora\s+sosirii\s+în\s+laborator",
            r"Sosit(?:ă|a)?\s+in\s+laborator",
            r"Registered(?:\s+on)?",
            r"Received(?:\s+on)?",
        ],
    )

    generated_on = extract_date_after_label(
        safe_text,
        [
            r"Generated(?:\s+on)?",
            r"Printed(?:\s+on)?",
            r"Printat(?:\s+la)?",
        ],
    )

    test_date = collected_on or reported_on or registered_on or generated_on

    report_name = extract_report_name(safe_text, collected_on or test_date)

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
        "report_name": report_name,
        "report_type": "Bloodwork",
        "source_language": extract_source_language(safe_text),
        "test_date": test_date,
        "collected_on": collected_on,
        "reported_on": reported_on,
        "registered_on": registered_on,
        "generated_on": generated_on,
    }
