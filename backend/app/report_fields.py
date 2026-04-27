import re


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    value = re.sub(r"\s+", " ", str(value)).strip(" :-\t")
    return value or None


def _match_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return _clean(match.group(1))
    return None


def _extract_standalone_name_before_age(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines()]

    for i, line in enumerate(lines):
        if re.match(r"^(Age|Varsta|Vârsta|VARSTA|VÂRSTA)\s*[:\-]", line, re.IGNORECASE):
            if i <= 0:
                continue

            candidate = lines[i - 1].strip()

            if not candidate:
                continue

            if re.search(
                r"(pathology|laboratory|lab|doctor|dr\.|technician|generated|reported|registered|sample|collection|ref\. by|accurate|caring|instant|smart|drlogy|fundeni|spital|institut)",
                candidate,
                re.IGNORECASE,
            ):
                continue

            if len(candidate.split()) >= 2 and re.match(r"^[A-Za-zĂÂÎȘŞȚŢăâîșşțţ.\- ]+$", candidate):
                return candidate

    return None


def _extract_age_and_sex_combo(text: str) -> tuple[str | None, str | None]:
    value = _match_first(
        text,
        [
            r"(?:Age\/Gender|Varsta\/Sex|Vârsta\/Sex|Varsta\/Gen|Vârstă\/Gen)\s*[:\-]?\s*([^\n]+)",
        ],
    )

    age = None
    sex = None

    if value and "/" in value:
        left, right = value.split("/", 1)
        age = _clean(left)
        sex = _clean(right)

    return age, sex


def extract_report_metadata(text: str) -> dict:
    patient_name = _match_first(
        text,
        [
            r"(?:NUME SI PRENUME|NUME ȘI PRENUME|Nume si prenume|Nume și prenume)\s*[:\-]?\s*([^\n]+)",
            r"(?:NUME|Nume)\s*[:\-]?\s*([A-ZĂÂÎȘŞȚŢ][A-ZĂÂÎȘŞȚŢa-zăâîșşțţ.\- ]{2,})",
            r"(?:Nume pacient|Pacient|Name|Patient)\s*[:\-]?\s*([^\n]+)",
        ],
    )

    if not patient_name:
        patient_name = _extract_standalone_name_before_age(text)

    first_name = _match_first(text, [r"(?:Prenume|First Name)\s*[:\-]?\s*([^\n]+)"])
    last_name = _match_first(text, [r"(?:Nume de familie|Last Name|Surname)\s*[:\-]?\s*([^\n]+)"])

    if not patient_name and (first_name or last_name):
        patient_name = _clean(" ".join(part for part in [last_name, first_name] if part))

    combo_age, combo_sex = _extract_age_and_sex_combo(text)

    date_of_birth = _match_first(
        text,
        [
            r"(?:Data nasterii|Data nașterii|Data de nastere|Data de naștere|DOB|Date of Birth)\s*[:\-]?\s*([^\n]+)",
        ],
    )

    age = combo_age or _match_first(
        text,
        [
            r"(?:VARSTA|VÂRSTA|Varsta|Vârsta|Age)\s*[:\-]?\s*([^\n]+)",
        ],
    )

    sex = combo_sex or _match_first(
        text,
        [
            r"(?:SEX|Sex|Gen|Gender)\s*[:\-]?\s*([^\n]+)",
        ],
    )

    cnp = _match_first(
        text,
        [
            r"(?:CNP)\s*[:\-]?\s*([0-9]{13})",
        ],
    )

    patient_identifier = _match_first(
        text,
        [
            r"(?:COD PACIENT|Cod pacient|ID pacient|Pacient ID|Patient ID|PID)\s*[:\-]?\s*([^\n]+)",
        ],
    )

    lab_name = _match_first(
        text,
        [
            r"(?:Laborator|Laboratory|Lab Name)\s*[:\-]?\s*([^\n]+)",
            r"(Laborator de Analize Hematologice Speciale[^\n]*)",
            r"(Citomorfologie)",
            r"(Anatomie Patologic[ăa])",
        ],
    )

    sample_type = _match_first(
        text,
        [
            r"(?:Tip proba|Tip probă|Tip esantion|Tip eșantion|Sample Type|Primary Sample Type)\s*[:\-]?\s*([^\n]+)",
            r"(?:PROBA|Prob[ăa])\s*[:\-]?\s*([^\n]+)",
        ],
    )

    referring_doctor = _match_first(
        text,
        [
            r"(?:MEDIC|Medic)\s*[:\-]?\s*([^\n]+)",
            r"(?:Medic trimitator|Medic trimițător|Ref\. By|Ref By|Referred By|Doctor)\s*[:\-]?\s*([^\n]+)",
            r"(?:DR\.|Dr\.)\s*([A-ZĂÂÎȘŞȚŢa-zăâîșşțţ.\- ]+)",
        ],
    )

    collected_on = _match_first(
        text,
        [
            r"(?:Data si ora recoltarii setului de analize|Data și ora recoltării setului de analize)\s*[:\-]?\s*([^\n]+)",
            r"(?:Data recoltarii|Data recoltării|Recoltat la|Collected on|Collection Date)\s*[:\-]?\s*([^\n]+)",
        ],
    )

    reported_on = _match_first(
        text,
        [
            r"(?:Data validare|Data validării|Data validarii)\s*[:\-]?\s*([^\n]+)",
            r"(?:Data raportarii|Data raportării|Reported on|Report Date)\s*[:\-]?\s*([^\n]+)",
        ],
    )

    registered_on = _match_first(
        text,
        [
            r"(?:Inregistrat la|Înregistrat la|Registered on)\s*[:\-]?\s*([^\n]+)",
        ],
    )

    generated_on = _match_first(
        text,
        [
            r"(?:Data eliberarii|Data eliberării|Eliberat la|Released on)\s*[:\-]?\s*([^\n]+)",
            r"(?:Generated on)\s*[:\-]?\s*(.+?)(?:Page\s+\d+\s+of\s+\d+|$)",
        ],
    )

    report_type = _match_first(
        text,
        [
            r"(Buletin Analize Medicale)",
            r"(Hemograma simpla cu reticulocite)",
            r"(Hemogram[ăa][^\n]*)",
            r"(Citomorfologie)",
            r"(Buletin Anatomie Patologic[ăa])",
            r"(ANATOMIE PATOLOGIC[ĂA])",
            r"(Histopatologic)",
            r"(Raport Histopatologic)",
            r"(Complete Blood Count\s*CBC)",
            r"(CBC)",
            r"(Biochimie)",
            r"(Lipid Profile)",
            r"(Profil lipidic)",
            r"(TSH)",
            r"(Free T4)",
        ],
    )

    source_language = (
        "ro"
        if re.search(
            r"\b(?:nume|varsta|vârsta|data recoltarii|data recoltării|medic|tip probă|tip proba|cnp|cod pacient|buletin analize)\b",
            text,
            re.IGNORECASE,
        )
        else "en"
    )

    return {
        "patient_name": patient_name,
        "date_of_birth": date_of_birth,
        "age": age,
        "sex": sex,
        "cnp": cnp,
        "patient_identifier": patient_identifier,
        "lab_name": lab_name,
        "sample_type": sample_type,
        "referring_doctor": referring_doctor,
        "collected_on": collected_on,
        "reported_on": reported_on,
        "registered_on": registered_on,
        "generated_on": generated_on,
        "report_type": report_type,
        "source_language": source_language,
    }