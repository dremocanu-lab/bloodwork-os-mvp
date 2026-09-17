"""Structured healthcare export adapters: .json / .xml.

Detects whether content looks like FHIR, CDA/C-CDA, a generic health
export, or ordinary unrelated JSON/XML — NEVER assumes all JSON is FHIR
or all XML is CDA (Part C6's explicit requirement). This is intentionally
a separate, self-contained detector from the existing interoperability
subsystem (app/services/interop/ — FHIR *sync* from a connected external
system, gated by INTEROP_FHIR_ENABLED): that subsystem is a pull-based
connector integration, not a file-upload parser, and touching it here
would risk exactly the "don't accidentally enable an unfinished system"
mistake earlier sessions were explicitly warned against. This adapter
only produces classification-ready text (and preserves the raw
structured payload) — it does not write FHIR resources into Bragi's data
model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as DefusedET

from app.services.ingestion.adapters.text_adapter import decode_text_bytes
from app.services.ingestion.contract import ExtractionResult, ExtractionStatus

# Real, fixed FHIR namespace URIs — never guessed.
_FHIR_XML_NAMESPACE = "http://hl7.org/fhir"
_CDA_NAMESPACE = "urn:hl7-org:v3"
_CDA_ROOT_LOCAL_NAME = "ClinicalDocument"

MAX_JSON_SUMMARY_FIELDS = 200  # a safety cap on how much of a huge JSON blob gets flattened into text


def _looks_like_fhir_json(payload: Any) -> bool:
    if isinstance(payload, dict):
        if "resourceType" in payload:
            return True
    return False


def _flatten_json_for_text(payload: Any, prefix: str, out: list[str]) -> None:
    if len(out) >= MAX_JSON_SUMMARY_FIELDS:
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            _flatten_json_for_text(value, f"{prefix}.{key}" if prefix else str(key), out)
    elif isinstance(payload, list):
        for index, item in enumerate(payload[:50]):  # cap list fan-out too
            _flatten_json_for_text(item, f"{prefix}[{index}]", out)
    else:
        if payload is not None and payload != "":
            out.append(f"{prefix}: {payload}")


def _fhir_summary_lines(payload: dict) -> list[str]:
    lines: list[str] = []
    if payload.get("resourceType") == "Bundle":
        entries = payload.get("entry") or []
        lines.append(f"FHIR Bundle with {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}.")
        for entry in entries[:100]:
            resource = (entry or {}).get("resource") or {}
            resource_type = resource.get("resourceType", "Unknown")
            identifying = (
                resource.get("code", {}).get("text")
                or resource.get("status")
                or resource.get("id")
                or ""
            )
            lines.append(f"- {resource_type}: {identifying}".rstrip(": "))
    else:
        lines.append(f"FHIR {payload.get('resourceType')} resource.")
    return lines


def extract_json(file_path: Path) -> ExtractionResult:
    try:
        raw = file_path.read_bytes()
    except OSError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".json", reason=f"Could not read file: {error}")

    decoded = decode_text_bytes(raw)

    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".json", reason=f"Not valid JSON: {error}")

    is_fhir = _looks_like_fhir_json(payload)
    lines: list[str] = []

    if is_fhir and isinstance(payload, dict):
        lines.extend(_fhir_summary_lines(payload))
        lines.append("")

    flattened: list[str] = []
    _flatten_json_for_text(payload, "", flattened)
    lines.extend(flattened)

    text = "\n".join(lines).strip()

    return ExtractionResult(
        status=ExtractionStatus.LOCAL_TEXT,
        text=text,
        blocks=lines,
        source_extension=".json",
        source_mime="application/json",
        extraction_provider="local_structured_health",
        structured_payload={"detected_format": "fhir" if is_fhir else "generic_json", "raw": payload},
        warnings=[] if text else ["This JSON file has no readable content."],
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def extract_xml(file_path: Path) -> ExtractionResult:
    try:
        raw = file_path.read_bytes()
    except OSError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".xml", reason=f"Could not read file: {error}")

    try:
        root = DefusedET.fromstring(raw)  # XXE-safe (defusedxml)
    except Exception as error:  # noqa: BLE001 — malformed XML
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".xml", reason=f"Not valid XML: {error}")

    root_local_name = _local_name(root.tag)
    root_namespace = _namespace(root.tag)

    detected_format = "generic_xml"
    if root_local_name == _CDA_ROOT_LOCAL_NAME and root_namespace == _CDA_NAMESPACE:
        detected_format = "cda"
    elif root_namespace == _FHIR_XML_NAMESPACE:
        detected_format = "fhir_xml"

    text_parts: list[str] = []
    for element in root.iter():
        # Element.text only ever holds the raw text BEFORE the first
        # child (not itertext()'s full recursive join) — iterating every
        # element and taking just its own `.text` avoids duplicating a
        # parent's descendants' text multiple times.
        if element.text and element.text.strip():
            text_parts.append(element.text.strip())

    text = "\n".join(text_parts).strip()
    prefix = {
        "cda": "CDA/C-CDA clinical document detected.\n",
        "fhir_xml": "FHIR XML resource detected.\n",
        "generic_xml": "",
    }[detected_format]

    return ExtractionResult(
        status=ExtractionStatus.LOCAL_TEXT,
        text=(prefix + text).strip(),
        blocks=text_parts,
        source_extension=".xml",
        source_mime="application/xml",
        extraction_provider="local_structured_health",
        structured_payload={"detected_format": detected_format, "root_tag": root.tag},
        warnings=[] if text else ["This XML file has no readable text content."],
    )
