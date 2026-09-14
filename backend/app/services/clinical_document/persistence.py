"""Reads/writes the versioned `StructuredClinicalDocument` payload
through the EXISTING `Document.note_body` field.

Why `note_body` and not a new column or `structured_sections`: see
`docs/clinical_document_v3/CURRENT_PIPELINE_MAP.md` OPEN QUESTION #1 and
§8. `structured_sections` is reserved for 6 unrelated Phase-4 reader
document types and has its own fixed `{language, sections: {key:
text}}` shape already consumed by `ask_bragi/tools.py::_tool_get_document`
and the frontend Reader — repurposing it would risk regressing those.
`note_body` is ALREADY the field `discharge_summary_pipeline.py` uses to
persist a full JSON payload for exactly this kind of document, so
formalizing/versioning that existing usage — rather than adding a new
column — is what the V3 contract's "prefer existing structured JSON
field if sufficient; no new DB columns unless truly necessary"
instruction asks for.

Backward compatibility: existing discharge_summary documents already
have a JSON payload in `note_body` using the OLDER, unversioned, ad-hoc
shape discharge_summary_pipeline.py has always produced (no
`schema_version` field, a fixed 13-key section vocabulary). This module
does NOT rewrite those rows in place. `parse_structured_document()`
upconverts that legacy shape into a valid `StructuredClinicalDocument`
IN MEMORY, on read, using a deterministic (not fuzzy/LLM) key mapping —
see `_LEGACY_KEY_TO_CANONICAL` below. This is a Phase 3 backward-
compatibility stopgap only: Phase 4's real canonical-heading classifier
(operating on raw OCR'd headings, not this closed 13-key set) supersedes
it for anything parsed going forward — see that phase's own module once
it exists.

`note_body` is ALSO used, for other document types, as a plain free-text
note (not JSON at all) — `parse_structured_document` returns `None` for
that case (and for anything else that isn't recognizable JSON), so
existing plain-note behavior is completely unaffected by this module's
existence.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.document_taxonomy import DocumentType

from .schema import (
    ClinicalSection,
    DocumentMetadata,
    ParagraphBlock,
    StructuredClinicalDocument,
)

# Distinct from CURRENT_SCHEMA_VERSION (schema.py) — this labels the
# *parser* that produced a given payload, not the shape it validates
# against. A payload upconverted by this stopgap is always honestly
# labeled as such, never mistaken for real Phase 4+ parser output.
LEGACY_UPCONVERSION_PARSER_VERSION = "legacy-discharge-upconversion-v1"

# discharge_summary_pipeline.py's fixed 13-key ALLOWED_SECTION_KEYS
# vocabulary -> the V3 contract's fixed CanonicalSectionKey enum.
# Deterministic and intentionally simple — a backward-compat safety net
# for OLD rows, not Phase 4's real classifier. Non-obvious choices:
#   - "discharge_status" -> "encounter_details": no exact enum match;
#     discharge status describes the encounter/discharge state.
#   - "epicriza" -> "clinical_course": explicit V3 contract example
#     (EPICRIZĂ -> clinical_course).
#   - "consults" -> "other": no clean 1:1 canonical match available.
#   - "laboratory_normal" AND "laboratory_abnormal" -> "laboratory_results":
#     explicit V3 contract example (EXAMENE DE LABORATOR ->
#     laboratory_results) — these two legacy keys deliberately MERGE into
#     one canonical section, which is exactly the "repeated headings
#     merge" rule this module's own tests exercise.
#   - "treatment_in_hospital" -> "treatment": in-hospital administered
#     treatment maps directly onto the "treatment" canonical key.
#   - "recommended_treatment" -> "recommendations": explicit V3 contract
#     example (TRATAMENT RECOMANDAT -> recommendations/
#     discharge_medications) — "recommendations" chosen as the safe
#     default since resolving actual discharge MEDICATIONS out of this
#     text is Phase 7's extraction job, not this upconversion's.
#   - "prescriptions_released" -> "prescriptions": explicit V3 contract
#     example (REȚETE ELIBERATE -> prescriptions).
_LEGACY_KEY_TO_CANONICAL: dict[str, str] = {
    "administrative_information": "administrative_information",
    "diagnoses": "diagnoses",
    "discharge_status": "encounter_details",
    "epicriza": "clinical_course",
    "investigations": "investigations",
    "consults": "other",
    "laboratory_normal": "laboratory_results",
    "laboratory_abnormal": "laboratory_results",
    "treatment_in_hospital": "treatment",
    "recommended_treatment": "recommendations",
    "prescriptions_released": "prescriptions",
    "recommendations": "recommendations",
    "other": "other",
}


def _looks_like_legacy_discharge_payload(payload: dict[str, Any]) -> bool:
    """Mirrors the frontend's own sniff
    (`frontend/app/documents/[id]/discharge/page.tsx::parseDischargePayload`)
    exactly, so both sides agree on what counts as "the old shape" —
    checked against the payload's OWN embedded `document_type` field,
    never the caller-supplied `Document.document_type` column (the two
    can disagree, e.g. during a re-classification)."""
    return payload.get("document_type") == "discharge_summary" and isinstance(payload.get("sections"), list)


def _upconvert_legacy_discharge_payload(payload: dict[str, Any]) -> StructuredClinicalDocument:
    raw_sections = payload.get("sections") or []
    merged: dict[str, ClinicalSection] = {}
    order_counter = 0

    for raw in raw_sections:
        if not isinstance(raw, dict):
            continue
        legacy_key = raw.get("key") or "other"
        canonical_key = _LEGACY_KEY_TO_CANONICAL.get(legacy_key, "other")
        heading = raw.get("title") or legacy_key
        body = (raw.get("body") or "").strip()

        existing = merged.get(canonical_key)
        if existing is None:
            merged[canonical_key] = ClinicalSection(
                id=f"legacy-{canonical_key}",
                canonical_key=canonical_key,  # type: ignore[arg-type]
                display_title=heading,
                source_headings=[heading],
                order=order_counter,
                blocks=[ParagraphBlock(text=body)] if body else [],
                confidence=None,  # never fabricated for an upconverted legacy row
                review_state="needs_review",
            )
            order_counter += 1
        else:
            if heading not in existing.source_headings:
                existing.source_headings.append(heading)
            if body:
                existing.blocks.append(ParagraphBlock(text=body))

    metadata = DocumentMetadata(
        patient_name=payload.get("patient_name"),
        date_of_birth=payload.get("date_of_birth"),
        sex=payload.get("sex"),
        admission_date=payload.get("admission_date"),
        discharge_date=payload.get("discharge_date"),
        hospital_name=payload.get("hospital_name"),
    )

    return StructuredClinicalDocument(
        parser_version=LEGACY_UPCONVERSION_PARSER_VERSION,
        document_kind=DocumentType.DISCHARGE_SUMMARY,
        source_language=payload.get("source_language") or payload.get("language"),
        metadata=metadata,
        sections=list(merged.values()),
        warnings=[str(w) for w in (payload.get("warnings") or [])],
    )


def parse_structured_document(note_body: str | None) -> StructuredClinicalDocument | None:
    """Best-effort READ path — never raises. Returns `None` for a plain-
    text `note_body` (nothing structured to parse), unparseable JSON, or
    a "new-shape" payload that fails validation (never silently trusted
    — see the V3 contract's "validate all persisted structured output"
    rule; callers see absence, not a crash, and not an unvalidated dict)."""
    if not note_body:
        return None
    try:
        payload = json.loads(note_body)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    if payload.get("schema_version"):
        try:
            return StructuredClinicalDocument.model_validate(payload)
        except Exception:
            return None

    if _looks_like_legacy_discharge_payload(payload):
        try:
            return _upconvert_legacy_discharge_payload(payload)
        except Exception:
            return None

    return None


def serialize_structured_document(document: StructuredClinicalDocument) -> str:
    """The only sanctioned way to write a `StructuredClinicalDocument`
    into `Document.note_body`. Takes a real, already-validated model
    instance (construction itself already ran every validator in
    schema.py) — never a hand-built dict — so what lands on the wire is
    always exactly what the schema allows."""
    return document.model_dump_json()
