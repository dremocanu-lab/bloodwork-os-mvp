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
`schema_version` field, a fixed 13-key section vocabulary, but a REAL
per-section `title` — the actual heading text as it appeared on the
page). This module does NOT rewrite those rows in place.
`parse_structured_document()` upconverts that legacy shape into a valid
`StructuredClinicalDocument` IN MEMORY, on read, by running it through
the SAME segmentation + consolidation pipeline Phase 4's real parsing
uses (`segments.build_segments_from_legacy_discharge_payload` +
`canonical_headings.consolidate_segments`) — there is deliberately no
second, separately-maintained classification/merge implementation for
this backward-compat path; an earlier version of this session kept one
(a coarse 13-key remap), proved it always agreed with the real
classifier on every real legacy title, then deleted it (commit
`f4f47ce`) once that agreement was established, which is what makes
sharing one implementation safe. The only thing that distinguishes this
path from a real Phase 4 parse is `parser_version`
(`LEGACY_UPCONVERSION_PARSER_VERSION` below, never mistaken for real
parser output) and `review_state="needs_review"` on every section it
produces (a human never reviewed sections built retroactively from an
old row, even though the classification itself is exactly as accurate
as it would be for a brand new document).

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

from .canonical_headings import consolidate_segments
from .schema import DocumentMetadata, StructuredClinicalDocument
from .segments import build_segments_from_legacy_discharge_payload

# Distinct from CURRENT_SCHEMA_VERSION (schema.py) — this labels the
# *parser* that produced a given payload, not the shape it validates
# against. A payload upconverted by this stopgap is always honestly
# labeled as such, never mistaken for real Phase 4+ parser output.
LEGACY_UPCONVERSION_PARSER_VERSION = "legacy-discharge-upconversion-v1"


def _looks_like_legacy_discharge_payload(payload: dict[str, Any]) -> bool:
    """Mirrors the frontend's own sniff
    (`frontend/app/documents/[id]/discharge/page.tsx::parseDischargePayload`)
    exactly, so both sides agree on what counts as "the old shape" —
    checked against the payload's OWN embedded `document_type` field,
    never the caller-supplied `Document.document_type` column (the two
    can disagree, e.g. during a re-classification)."""
    return payload.get("document_type") == "discharge_summary" and isinstance(payload.get("sections"), list)


def _upconvert_legacy_discharge_payload(payload: dict[str, Any]) -> StructuredClinicalDocument:
    segments = build_segments_from_legacy_discharge_payload(payload)
    sections = consolidate_segments(segments, review_state="needs_review")

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
        sections=sections,
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
