import base64
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import fitz
from openai import OpenAI


OPENAI_MODEL = os.getenv("OPENAI_EXTRACTION_MODEL", "gpt-5.4")


def _client() -> OpenAI | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None
    return OpenAI()


def _safe_json_loads(text: str) -> dict[str, Any] | None:
    if not text:
        return None

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _image_to_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def render_pdf_pages(file_path: Path, output_dir: Path, max_pages: int = 10) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf = fitz.open(file_path)
    paths: list[Path] = []

    try:
        for page_index in range(min(len(pdf), max_pages)):
            page = pdf.load_page(page_index)

            # Higher scale helps table rows and tiny CBC values.
            matrix = fitz.Matrix(5, 5)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            output_path = output_dir / f"page_{page_index + 1}.png"
            pix.save(str(output_path))
            paths.append(output_path)
    finally:
        pdf.close()

    return paths


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned or None


def normalize_ai_extraction(payload: dict[str, Any]) -> dict[str, Any]:
    patient = payload.get("patient") or {}
    report = payload.get("report") or {}
    labs = payload.get("labs") or []

    normalized_labs: list[dict[str, str | None]] = []

    for lab in labs:
        if not isinstance(lab, dict):
            continue

        raw_name = _clean_value(lab.get("raw_test_name") or lab.get("test_name") or lab.get("name"))
        value = _clean_value(lab.get("value") or lab.get("result"))

        if not raw_name or not value:
            continue

        normalized_labs.append(
            {
                "raw_test_name": raw_name,
                "value": value,
                "unit": _clean_value(lab.get("unit")) or "",
                "reference_range": _clean_value(lab.get("reference_range") or lab.get("range")) or "",
                "flag": _clean_value(lab.get("flag")) or "Normal",
            }
        )

    return {
        "patient_name": _clean_value(patient.get("full_name") or patient.get("name")),
        "date_of_birth": _clean_value(patient.get("date_of_birth")),
        "age": _clean_value(patient.get("age")),
        "sex": _clean_value(patient.get("sex")),
        "cnp": _clean_value(patient.get("cnp")),
        "patient_identifier": _clean_value(patient.get("patient_identifier") or patient.get("patient_id")),
        "lab_name": _clean_value(report.get("lab_name")),
        "sample_type": _clean_value(report.get("sample_type")),
        "referring_doctor": _clean_value(report.get("referring_doctor") or report.get("doctor")),
        "report_name": _clean_value(report.get("report_name") or report.get("title")),
        "report_type": _clean_value(report.get("report_type")),
        "source_language": _clean_value(report.get("source_language")) or "unknown",
        "test_date": _clean_value(report.get("test_date") or report.get("collected_on")),
        "collected_on": _clean_value(report.get("collected_on")),
        "reported_on": _clean_value(report.get("reported_on") or report.get("validated_on")),
        "registered_on": _clean_value(report.get("registered_on")),
        "generated_on": _clean_value(report.get("generated_on") or report.get("released_on")),
        "labs": normalized_labs,
        "ai_extraction_used": True,
    }


def _extract_page_with_ai(
    image_path: Path,
    page_number: int,
    total_pages: int,
    ocr_text: str = "",
) -> dict[str, Any] | None:
    client = _client()

    if client is None:
        print("AI extraction skipped: OPENAI_API_KEY is missing")
        return None

    prompt = f"""
You are Bloodwork OS table extraction engine.

You are reading PAGE {page_number} of {total_pages} from a medical document.

Return ONLY valid JSON. No markdown. No explanation.

Your task is NOT to summarize.
Your task is to copy every visible structured result row from this page.

Very important:
- Extract EVERY row from every visible table.
- Do not stop after the first result.
- Do not only extract abnormal rows.
- Do not ignore rows with abbreviations.
- If the page has a CBC / hemogram / hematology table, extract all rows from the CBC table.
- If a row has a test name and a numeric/text result, include it.
- If unit or reference range is missing/unclear, leave it blank but still include the row.
- Preserve test abbreviations exactly.

Romanian terms:
- Nume / Nume si prenume / Nume și prenume = patient name
- Varsta / Vârsta = age
- Sex = sex
- CNP = national ID
- Cod pacient / ID pacient = patient identifier
- Data recoltarii / Data recoltării = collected on
- Data validarii / Data validării = validated/reported on
- Buletin Analize Medicale = medical report
- Hemograma / Hemoleucograma = CBC

Common CBC rows to look for:
WBC, RBC, HGB, HCT, MCV, MCH, MCHC, PLT, RDW-SD, RDW-CV, PDW, MPV, P-LCR, PCT,
NEUT#, NEUT%, LYMPH#, LYMPH%, MONO#, MONO%, EO#, EO%, BASO#, BASO%, IG#, IG%,
NRBC#, NRBC%, RET%, RET#, IRF, LFR, MFR, HFR, RET-HE, RBC-HE, HYPO-HE, HYPER-HE, DELTA-HE.

Also extract chemistry, coagulation, urine, pathology, or other result rows if visible.

Flag rules:
- Use "High" if marked high or above range.
- Use "Low" if marked low or below range.
- Use "Abnormal" if clearly abnormal but direction unclear.
- Use "Normal" if normal or unclear.

Return this exact JSON shape:
{{
  "patient": {{
    "full_name": null,
    "date_of_birth": null,
    "age": null,
    "sex": null,
    "cnp": null,
    "patient_identifier": null
  }},
  "report": {{
    "report_name": null,
    "report_type": null,
    "lab_name": null,
    "sample_type": null,
    "referring_doctor": null,
    "test_date": null,
    "collected_on": null,
    "reported_on": null,
    "registered_on": null,
    "generated_on": null,
    "source_language": null
  }},
  "labs": [
    {{
      "raw_test_name": "WBC",
      "value": "4.49",
      "unit": "10^3/uL",
      "reference_range": "3.98 - 10.00",
      "flag": "Normal"
    }}
  ]
}}

OCR fallback text for this document:
{ocr_text[:12000]}
""".strip()

    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": prompt},
        {
            "type": "input_image",
            "image_url": _image_to_data_url(image_path),
            "detail": "high",
        },
    ]

    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
            temperature=0,
            max_output_tokens=16000,
        )
    except Exception as exc:
        print(f"AI page extraction request failed on page {page_number}: {exc}")
        return None

    raw = response.output_text
    payload = _safe_json_loads(raw)

    if not payload:
        print(f"AI page extraction returned non-JSON on page {page_number}: {raw[:1200]}")
        return None

    normalized = normalize_ai_extraction(payload)

    print(
        "AI page extraction success:",
        {
            "model": OPENAI_MODEL,
            "page": page_number,
            "labs": len(normalized.get("labs", [])),
            "patient_name": normalized.get("patient_name"),
            "report_name": normalized.get("report_name"),
        },
    )

    return normalized


def _merge_extractions(extractions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not extractions:
        return None

    merged: dict[str, Any] = {
        "patient_name": None,
        "date_of_birth": None,
        "age": None,
        "sex": None,
        "cnp": None,
        "patient_identifier": None,
        "lab_name": None,
        "sample_type": None,
        "referring_doctor": None,
        "report_name": None,
        "report_type": None,
        "source_language": None,
        "test_date": None,
        "collected_on": None,
        "reported_on": None,
        "registered_on": None,
        "generated_on": None,
        "labs": [],
        "ai_extraction_used": True,
    }

    for extraction in extractions:
        for key in merged.keys():
            if key in {"labs", "ai_extraction_used"}:
                continue

            if not merged.get(key) and extraction.get(key):
                merged[key] = extraction.get(key)

    seen_lab_keys: set[str] = set()

    for extraction in extractions:
        for lab in extraction.get("labs", []):
            raw = str(lab.get("raw_test_name") or "").strip().lower()
            value = str(lab.get("value") or "").strip().lower()
            unit = str(lab.get("unit") or "").strip().lower()
            key = f"{raw}::{value}::{unit}"

            if not raw or not value:
                continue

            if key in seen_lab_keys:
                continue

            seen_lab_keys.add(key)
            merged["labs"].append(lab)

    return merged


def extract_report_with_ai(file_path: Path, upload_dir: Path, ocr_text: str = "") -> dict[str, Any] | None:
    suffix = file_path.suffix.lower()
    temp_dir = upload_dir / f"_ai_pages_{file_path.stem}"

    try:
        if suffix == ".pdf":
            image_paths = render_pdf_pages(file_path, temp_dir)
        elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
            image_paths = [file_path]
        else:
            image_paths = []

        if not image_paths:
            print(f"AI extraction skipped: unsupported file type {suffix}")
            return None

        page_extractions: list[dict[str, Any]] = []

        for index, image_path in enumerate(image_paths):
            page_result = _extract_page_with_ai(
                image_path=image_path,
                page_number=index + 1,
                total_pages=len(image_paths),
                ocr_text=ocr_text,
            )

            if page_result:
                page_extractions.append(page_result)

        merged = _merge_extractions(page_extractions)

        if merged:
            print(
                "AI merged extraction:",
                {
                    "model": OPENAI_MODEL,
                    "pages": len(image_paths),
                    "labs": len(merged.get("labs", [])),
                    "patient_name": merged.get("patient_name"),
                    "report_name": merged.get("report_name"),
                },
            )

        return merged

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)