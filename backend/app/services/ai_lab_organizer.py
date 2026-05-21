from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def env_value(name: str) -> str | None:
    value = os.getenv(name)

    if value is None:
        return None

    value = value.strip()
    return value or None


def is_openai_configured() -> bool:
    return bool(env_value("OPENAI_API_KEY"))


def safe_json_loads(value: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(value)

        if isinstance(loaded, dict):
            return loaded
    except Exception:
        return None

    return None


def guess_mime_type(file_path: Path, filename: str | None = None) -> str:
    guessed, _ = mimetypes.guess_type(filename or str(file_path))

    if guessed:
        return guessed

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return "application/pdf"

    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"

    if suffix == ".png":
        return "image/png"

    if suffix in {".tif", ".tiff"}:
        return "image/tiff"

    if suffix == ".webp":
        return "image/webp"

    return "application/octet-stream"


def file_to_data_url(file_path: Path, filename: str | None = None) -> str:
    mime_type = guess_mime_type(file_path, filename)

    with file_path.open("rb") as file:
        encoded = base64.b64encode(file.read()).decode("utf-8")

    return f"data:{mime_type};base64,{encoded}"


def compact_text_for_ai(text: str, max_chars: int = 24000) -> str:
    safe = text or ""

    markers = [
        "BULETIN ANALIZE MEDICALE",
        "Citomorfologie",
        "Hemograma simpla",
        "Hemograma simplă",
        "Sysmex",
        "WBC",
        "RBC",
        "HGB",
        "HCT",
        "PLT",
        "INTERVAL BIOLOGIC",
        "--- GOOGLE DOCUMENT AI LINES ---",
        "--- GOOGLE DOCUMENT AI TABLE",
        "--- GOOGLE DOCUMENT AI PLAIN TEXT ---",
    ]

    chunks: list[str] = []

    for marker in markers:
        index = safe.lower().find(marker.lower())

        if index >= 0:
            chunks.append(safe[max(0, index - 1200) : index + 14000])

    combined = "\n\n".join(chunks) if chunks else safe
    return combined[:max_chars]


QUALITATIVE_TOKENS = frozenset({
    "pozitiv", "negativ", "reactiv", "nereactiv",
    "prezent", "absent", "normal", "patologic",
    "nedetectabil", "detectabil", "trace", "urme",
    "slab pozitiv", "intens pozitiv",
    "positive", "negative", "reactive", "non-reactive", "nonreactive",
    "present", "detected", "not detected",
    "borderline", "indeterminate", "nedeterminat", "echivoc", "equivocal",
    "inconclusive",
})

QUALITATIVE_PREFIX_RE = re.compile(r"^[<>≤≥]=?\s*\d", re.UNICODE)


def is_qualitative_ai_value(value: str) -> bool:
    lowered = value.lower().strip()
    if lowered in QUALITATIVE_TOKENS:
        return True
    if QUALITATIVE_PREFIX_RE.match(value.strip()):
        return True
    return False


def normalize_ai_lab_row(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("value")

    if value is not None:
        value_str = str(value).strip()

        if value_str.lower() in {"nil", "null", "none", "n/a", "na", "-", "--", "---", "—", ""}:
            value = None
        elif is_qualitative_ai_value(value_str):
            value = value_str  # preserve verbatim
        else:
            value = value_str.replace(",", ".")

    reference_range = row.get("reference_range")
    if reference_range is not None:
        reference_range = str(reference_range).replace("–", "-").replace("—", "-").strip() or None

    unit = row.get("unit")
    if unit is not None:
        unit = str(unit).strip() or None

    flag = row.get("flag")
    if flag is not None:
        flag_lower = str(flag).strip().lower()

        if flag_lower in {"high", "h", "crescut", "mare"}:
            flag = "High"
        elif flag_lower in {"low", "l", "scazut", "scăzut", "mic"}:
            flag = "Low"
        elif flag_lower == "normal":
            flag = "Normal"
        else:
            flag = None

    if value is None:
        flag = None

    if value is not None and not reference_range and flag == "Normal":
        flag = None

    name = row.get("raw_test_name") or row.get("test") or row.get("name") or row.get("display_name")

    # Map section_title → source_section
    source_section = row.get("source_section") or row.get("section_title") or None

    result: dict[str, Any] = {
        "raw_test_name": name,
        "canonical_name": row.get("canonical_name") or name,
        "display_name": row.get("display_name") or row.get("test") or name,
        "category": row.get("category") or "Alte analize",
        "value": value,
        "flag": flag,
        "reference_range": reference_range,
        "unit": unit,
        "confidence": float(row.get("confidence") or 0.86),
    }

    if source_section:
        result["source_section"] = source_section

    return result


def extract_response_text(response_json: dict[str, Any]) -> str:
    if isinstance(response_json.get("output_text"), str):
        return response_json["output_text"]

    output = response_json.get("output") or []
    parts: list[str] = []

    for item in output:
        if not isinstance(item, dict):
            continue

        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue

            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                parts.append(content["text"])

    return "\n".join(parts).strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    parsed = safe_json_loads(text)

    if parsed:
        return parsed

    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:
        return safe_json_loads(text[start : end + 1])

    return None


def build_lab_extraction_prompt(extracted_text: str, deterministic_labs: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "task": "Extract every visible lab test row from this Romanian medical laboratory report. The report may contain multiple sections (Hemograma, Biochimie, Coagulare, Imunologie, Endocrinologie, Oncomarkeri, etc.). Extract ALL sections.",
            "critical_rules": [
                "Use the uploaded PDF/image visually if present. The table is more important than OCR text.",
                "Extract ALL visible lab sections — not just CBC. Include Biochimie, Coagulare, Imunologie, Endocrinologie, Oncomarkeri, Biologie moleculara, Sumar urina, Lipide, Vitamine, Markeri cardiaci, and any other section visible.",
                "For each test row, record the exact section title from the document in section_title (e.g. 'HEMOGRAMA', 'BIOCHIMIE GENERALA', 'HEMOSTAZA').",
                "Do not collapse tests from different sections. Each row must keep its section_title.",
                "Qualitative results like Pozitiv, Negativ, Reactiv, Nereactiv, Prezent, Absent, Nedetectabil, Detectabil, Slab pozitiv, Intens pozitiv, Borderline must be preserved verbatim in the value field — never convert or discard them.",
                "Values like '< 0.400', '> 500', '< 1.0' are also qualitative — preserve them verbatim.",
                "Do not invent values. Do not invent reference ranges. Do not use default lab ranges.",
                "Preserve decimals exactly as shown.",
                "If result is blank or --- then value must be null.",
                "If reference range and unit are combined, split them.",
                "Reference range must be only the numeric interval, e.g. 3.98 - 10.00.",
                "Unit must be separate, e.g. 10^3/uL, 10^6/uL, g/dL, %, fL, pg, mg/dL, mmol/L, U/L, IU/L, mIU/L.",
                "If arrows are visible, use them only to set High/Low flag; still calculate Normal only if value and reference range exist.",
                "Return all visible rows, including rows with --- values if the test row exists.",
                "For qualitative results, set flag only if explicitly shown (High/Low marker). Do not infer flag from qualitative values.",
            ],
            "lab_categories": {
                "Hematologie": "CBC / Hemograma: WBC, RBC, HGB, HCT, MCV, MCH, MCHC, PLT, RDW-SD, RDW-CV, PDW, MPV, P-LCR, PCT, NRBC#, NRBC%, NEUT#, NEUT%, LYMPH#, LYMPH%, MONO#, MONO%, EO#, EO%, BASO#, BASO%, IG#, IG%",
                "Biochimie generala": "Glucoza, Uree, Creatinina, Acid uric, Bilirubina totala/directa/indirecta, ALT/TGP, AST/TGO, GGT, Fosfataza alcalina, LDH, Amilaza, Lipaza, Proteine totale, Albumina, Calciu, Fosfor, Magneziu, Sodiu, Potasiu, Clor, Fier, TIBC, Feritina, Transferina",
                "Coagulare": "Timp protrombina (PT), INR, APTT, Fibrinogen, Trombina, D-dimeri, Antitrombina III, Proteina C, Proteina S",
                "Imunologie": "CRP, VSH, Interleukina 6, Procalcitonina, Complement C3/C4, IgA/IgG/IgM, ANA, ANCA, FR (Factor reumatoid), Anti-CCP, Anti-dsDNA",
                "Endocrinologie": "TSH, FT4, FT3, T4, T3, Anti-TPO, Anti-Tg, Insulina, C-peptid, HbA1c, Cortizol, ACTH, Prolactina, LH, FSH, Estradiol, Progesteron, Testosteron, PTH, Vitamina D",
                "Oncomarkeri": "PSA, PSA liber, AFP, CEA, CA 19-9, CA 125, CA 15-3, CA 72-4, HE4, CYFRA 21-1, NSE, SCC, Cromogranina A, Beta-HCG",
                "Lipide": "Colesterol total, HDL, LDL, Trigliceride, non-HDL, Apo A1, Apo B",
                "Vitamine/Minerale": "Vitamina B12, Vitamina D (25-OH), Vitamina B9/Acid folic, Vitamina B1, Zinc, Seleniu, Cupru",
                "Biologie moleculara": "PCR Chlamydia, PCR Mycoplasma, PCR HPV, PCR Hepatita B (HBV-DNA), PCR Hepatita C (HCV-RNA), PCR SARS-CoV-2",
                "Sumar urina": "pH, Densitate, Proteine, Glucoza, Corpi cetonici, Hemoglobina, Bilirubina, Urobilinogen, Nitrit, Leucocite",
                "Microbiologie": "Urocultura, Coprocultura, Hemocultura, Exsudat faringian, Antibiograma",
                "Markeri cardiaci": "Troponina I/T, CK-MB, BNP, NT-proBNP, Mioglobina",
                "Serologie": "Toxoplasma IgG/IgM, CMV IgG/IgM, EBV IgG/IgM, Rubeola IgG/IgM, HSV IgG/IgM, Helicobacter pylori IgG, HIV Ag/Ac, Sifilis (VDRL/TPHA)",
                "Alte analize": "Any test not covered by the above categories",
            },
            "output_schema": {
                "metadata": {
                    "patient_name": "string|null",
                    "date_of_birth": "string|null",
                    "age": "string|null",
                    "sex": "string|null",
                    "cnp": "string|null",
                    "patient_identifier": "string|null",
                    "lab_name": "string|null",
                    "sample_type": "string|null",
                    "referring_doctor": "string|null",
                    "report_name": "string|null",
                    "report_type": "Bloodwork",
                    "source_language": "ro",
                    "test_date": "string|null",
                    "collected_on": "string|null",
                    "reported_on": "string|null",
                    "registered_on": "string|null",
                    "generated_on": "string|null",
                },
                "labs": [
                    {
                        "raw_test_name": "string (exact test name from document)",
                        "canonical_name": "string",
                        "display_name": "string",
                        "category": "one of the lab_categories keys above",
                        "section_title": "string|null (exact section heading from document, e.g. 'BIOCHIMIE GENERALA')",
                        "value": "string|null (preserve qualitative values verbatim)",
                        "unit": "string|null",
                        "reference_range": "string|null (numeric interval only, e.g. '3.98 - 10.00')",
                        "flag": "High|Low|Normal|null",
                        "confidence": "number",
                    }
                ],
            },
            "deterministic_labs_so_far": deterministic_labs,
            "google_document_ai_text": compact_text_for_ai(extracted_text),
        },
        ensure_ascii=False,
    )


def organize_labs_with_ai(
    extracted_text: str,
    deterministic_labs: list[dict[str, Any]] | None = None,
    file_path: Path | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    api_key = env_value("OPENAI_API_KEY")

    if not api_key:
        return {
            "ok": False,
            "warning": "OpenAI organizer skipped because OPENAI_API_KEY is not configured.",
            "metadata": {},
            "labs": [],
        }

    model = env_value("OPENAI_EXTRACTION_MODEL") or "gpt-4o-mini"
    deterministic_labs = deterministic_labs or []

    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": build_lab_extraction_prompt(extracted_text, deterministic_labs),
        }
    ]

    if file_path and file_path.exists():
        suffix = file_path.suffix.lower()
        data_url = file_to_data_url(file_path, filename)

        if suffix == ".pdf":
            content.insert(
                0,
                {
                    "type": "input_file",
                    "filename": filename or file_path.name,
                    "file_data": data_url,
                },
            )
        else:
            content.insert(
                0,
                {
                    "type": "input_image",
                    "image_url": data_url,
                    "detail": "high",
                },
            )

    payload = {
        "model": model,
        "temperature": 0,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You are a strict medical document extraction engine. "
                            "Return JSON only. Extract only visible facts. Never invent lab values or reference ranges."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": content,
            },
        ],
    }

    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "warning": f"OpenAI vision organizer HTTP error: {exc.code}. {body[:900]}",
            "metadata": {},
            "labs": [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "warning": f"OpenAI vision organizer failed: {exc}",
            "metadata": {},
            "labs": [],
        }

    outer = safe_json_loads(raw)

    if not outer:
        return {
            "ok": False,
            "warning": "OpenAI vision organizer returned non-JSON API response.",
            "metadata": {},
            "labs": [],
        }

    response_text = extract_response_text(outer)
    parsed = extract_json_object(response_text)

    if not parsed:
        return {
            "ok": False,
            "warning": f"OpenAI vision organizer response was not valid JSON. Response preview: {response_text[:500]}",
            "metadata": {},
            "labs": [],
        }

    metadata = parsed.get("metadata") or parsed.get("report_metadata") or {}
    labs = parsed.get("labs") or parsed.get("lab_results") or []

    if not isinstance(metadata, dict):
        metadata = {}

    if not isinstance(labs, list):
        labs = []

    normalized_labs: list[dict[str, Any]] = []

    for row in labs:
        if isinstance(row, dict):
            normalized_labs.append(normalize_ai_lab_row(row))

    return {
        "ok": True,
        "metadata": metadata,
        "labs": normalized_labs,
    }