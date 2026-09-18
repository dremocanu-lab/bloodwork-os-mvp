"""Reprocessing/enrichment orchestration — Clinical Reader Intelligence
V2. The one place that upgrades an EXISTING discharge `Document` (already
uploaded, already has a legacy `note_body` payload) to the full pipeline:
real Clinical Course event extraction, canonical `LabResult`/
`PatientMedication` persistence, Timeline projection, and the AI Clinical
Document Interpreter — all idempotent, all reusing the SAME deterministic
services this package already ships and tests standalone (see
discharge_parser.py, lab_extraction.py/lab_persistence.py,
medication_extraction.py/medication_persistence.py, timeline_projection.py,
ai_interpreter.py). No parallel implementation of any of these steps.

Idempotency: every write here is idempotent by construction, inherited
from the functions it calls —
`persist_lab_candidates`/`persist_medication_candidates`/
`project_clinical_document_to_timeline` all look up an existing row by a
deterministic identity key before inserting (see each module's own
docstring). The interpretation-derived fields
(`diagnoses`/`investigations`/`anomalies`/`recommendations`/
`treatment_eras`/`current_encounter`/`interpretation`) live entirely
inside the JSON payload this call REPLACES on `Document.note_body` —
running this twice does not accumulate duplicates there either, since
each run starts fresh from the immutable legacy payload, never from a
previous run's own output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import models
from app.core.utils import now_iso

from app.services.source_evidence import ensure_segment_evidence

from .ai_interpreter import interpret_structured_document
from .canonical_headings import classify_canonical_heading
from .discharge_parser import parse_legacy_discharge_payload
from .lab_extraction import extract_lab_candidates_from_segment
from .lab_persistence import persist_lab_candidates
from .medication_extraction import MEDICATION_BEARING_CANONICAL_KEYS, extract_medication_candidates_from_segment
from .medication_persistence import persist_medication_candidates
from .persistence import _looks_like_legacy_discharge_payload, serialize_structured_document
from .schema import StructuredClinicalDocument
from .segments import SourceSegment, build_segments_from_legacy_discharge_payload
from .timeline_projection import project_clinical_document_to_timeline


class ReprocessingError(Exception):
    """Raised when a document genuinely cannot be reprocessed (not a
    discharge-shaped document, no legacy payload to parse, etc.) — a
    caller-facing 4xx condition, never an internal crash."""


def _segments_from_structured_document(document: StructuredClinicalDocument) -> list[SourceSegment]:
    """Reconstructs `SourceSegment`-shaped objects from an
    ALREADY-PERSISTED `StructuredClinicalDocument`'s own sections — used
    on the SECOND (or later) reprocessing pass, once a prior run has
    already replaced `Document.note_body`'s original legacy payload with
    this schema, so there is no legacy payload left to re-derive segments
    from. One synthetic segment per contributing block, preserving each
    section's own `source_segment_ids` (so lab/medication re-extraction
    on this pass still lands on the SAME existing canonical rows via
    their own idempotency keys, which include `source_segment_id`)."""
    segments: list[SourceSegment] = []
    for section in document.sections:
        heading = section.source_headings[0] if section.source_headings else section.display_title
        segment_ids = section.source_segment_ids or [section.id]
        block_texts = [block.text for block in section.blocks if getattr(block, "type", None) == "paragraph"]
        if len(segment_ids) == len(block_texts) and block_texts:
            for segment_id, text in zip(segment_ids, block_texts):
                segments.append(SourceSegment(segment_id=segment_id, index=0, raw_heading=heading, raw_text=text))
        elif block_texts:
            # Contributor count doesn't line up 1:1 with block count
            # (rare — only when a segment contributed no block on the
            # original pass) — fall back to one segment carrying every
            # block's text, tagged with the FIRST segment id, so at
            # least the section's own content is still available for
            # re-extraction.
            segments.append(
                SourceSegment(segment_id=segment_ids[0], index=0, raw_heading=heading, raw_text="\n".join(block_texts))
            )
    return segments


@dataclass
class ReprocessingResult:
    document_id: int
    lab_results_created: int = 0
    lab_results_reused: int = 0
    medications_created: int = 0
    medications_reused: int = 0
    timeline_events_created: int = 0
    timeline_events_retracted: int = 0
    interpretation_status: str = "unavailable"
    interpretation_warnings: list[str] = field(default_factory=list)
    dated_events_count: int = 0
    diagnoses_count: int = 0
    investigations_count: int = 0
    anomalies_count: int = 0
    # Source Intelligence + Provenance V2 — a lightweight, non-PHI-heavy
    # provenance health summary (Part 41, scoped down to what this
    # reprocessing pass itself produces rather than a separate public
    # diagnostics endpoint). Counts, never raw evidence content.
    segment_evidence_created: int = 0
    segment_evidence_reused: int = 0
    segments_with_page: int = 0
    segments_without_page: int = 0
    extraction_complete: bool | None = None


def _attach_segment_evidence(
    db: Session,
    *,
    document: models.Document,
    structured_document: StructuredClinicalDocument,
    segments: list[SourceSegment],
    result: ReprocessingResult,
) -> StructuredClinicalDocument:
    """Creates (or reuses) one SourceEvidence row per source segment and
    resolves it onto every ClinicalSection/ClinicalEvent that references
    that segment — this is what upgrades diagnoses/investigations/
    anomalies/recommendations/treatment eras (via the AI interpreter,
    which runs AFTER this and only ever resolves already-real evidence
    ids, never invents its own — see ai_interpreter.py) from having NO
    provenance UI at all to a real "View in original" action. Block/page
    precision only — never a fabricated bbox (see
    source_evidence.py::ensure_segment_evidence)."""
    evidence_id_by_segment_id: dict[str, int] = {}
    for segment in segments:
        evidence, was_new = ensure_segment_evidence(
            db,
            document,
            source_block_id=segment.segment_id,
            page_number=segment.page,
            source_text=segment.raw_text,
        )
        evidence_id_by_segment_id[segment.segment_id] = evidence.id
        if was_new:
            result.segment_evidence_created += 1
        else:
            result.segment_evidence_reused += 1
        if segment.page is not None:
            result.segments_with_page += 1
        else:
            result.segments_without_page += 1

    new_sections = [
        section.model_copy(
            update={
                "source_evidence_ids": sorted(
                    {evidence_id_by_segment_id[sid] for sid in section.source_segment_ids if sid in evidence_id_by_segment_id}
                )
            }
        )
        for section in structured_document.sections
    ]

    def _event_segment_id(source_event_id: str) -> str:
        return source_event_id.rsplit("-event-", 1)[0]

    new_events = [
        event.model_copy(
            update={
                "source_evidence_ids": (
                    [evidence_id_by_segment_id[_event_segment_id(event.source_event_id)]]
                    if _event_segment_id(event.source_event_id) in evidence_id_by_segment_id
                    else []
                )
            }
        )
        for event in structured_document.dated_events
    ]

    if structured_document.extraction_coverage is not None:
        result.extraction_complete = structured_document.extraction_coverage.extraction_complete

    return structured_document.model_copy(update={"sections": new_sections, "dated_events": new_events})


def _load_note_body_json(document: models.Document) -> dict:
    import json

    if not document.note_body:
        raise ReprocessingError("This document has no content to reprocess.")
    try:
        payload = json.loads(document.note_body)
    except (TypeError, ValueError) as error:
        raise ReprocessingError("This document's stored content is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise ReprocessingError("This document is not a discharge-summary-shaped document — nothing to reprocess.")
    return payload


def _resolve_base_document_and_segments(payload: dict) -> tuple[StructuredClinicalDocument, list[SourceSegment]]:
    """Returns the deterministic base `StructuredClinicalDocument` (real
    Clinical Course events, no PREVIOUS interpretation output — always
    re-derived fresh, never compounded) plus the segments lab/medication
    extraction needs — handling BOTH a first-time reprocess (the OLD
    legacy 13-key payload is still in `note_body`) and a re-run (a PRIOR
    reprocess already upgraded `note_body` to this schema) with the SAME
    downstream logic either way."""
    if payload.get("schema_version"):
        try:
            previous = StructuredClinicalDocument.model_validate(payload)
        except Exception as error:  # noqa: BLE001
            raise ReprocessingError("This document's stored structured content is no longer valid.") from error
        # Strip any prior interpretation/scope output before re-deriving
        # — a re-run must produce a document exactly as if it were the
        # first run against the same underlying source, never layer a
        # second interpretation on top of the first.
        base = previous.model_copy(
            update={
                "diagnoses": [], "investigations": [], "anomalies": [], "recommendations": [],
                "treatment_eras": [], "current_encounter": None, "interpretation": None,
                "sections": [s.model_copy(update={"encounter_scope": None}) for s in previous.sections],
                "dated_events": [e.model_copy(update={"encounter_scope": None}) for e in previous.dated_events],
            }
        )
        return base, _segments_from_structured_document(base)

    if _looks_like_legacy_discharge_payload(payload):
        # The REAL forward parser (review_state="auto" — this is a
        # genuine, deliberate reprocessing action, not a passive
        # backward-compat read; see discharge_parser.py's own docstring
        # on the "auto" vs "needs_review" distinction).
        base = parse_legacy_discharge_payload(payload, review_state="auto")
        return base, build_segments_from_legacy_discharge_payload(payload)

    raise ReprocessingError("This document is not a discharge-summary-shaped document — nothing to reprocess.")


def reprocess_discharge_document(db: Session, *, document: models.Document, actor_user_id: int) -> ReprocessingResult:
    """Idempotent. Safe to call repeatedly on the same document — see
    module docstring. Ownership/authorization is the CALLER's
    responsibility (see the router endpoint) — this function only
    requires a real `Document` instance and does no access check of its
    own, matching this package's existing convention (persistence
    functions are pure of authz; routers own that)."""
    payload = _load_note_body_json(document)
    structured_document, segments = _resolve_base_document_and_segments(payload)

    result = ReprocessingResult(document_id=document.id, dated_events_count=len(structured_document.dated_events))

    # ── Source-evidence provenance (must run BEFORE the AI interpreter,
    # so it has real section/event source_evidence_ids to resolve — see
    # ai_interpreter.py::apply_interpretation) ──────────────────────
    structured_document = _attach_segment_evidence(
        db, document=document, structured_document=structured_document, segments=segments, result=result
    )

    # ── Canonical labs ──────────────────────────────────────────────
    lab_section_by_id = {s.id: s for s in structured_document.sections if s.canonical_key == "laboratory_results"}
    for segment in segments:
        if classify_canonical_heading(segment.raw_heading) != "laboratory_results":
            continue
        candidates = extract_lab_candidates_from_segment(segment)
        if not candidates:
            continue
        source_section_id = next(
            (sid for sid, section in lab_section_by_id.items() if segment.segment_id in section.source_segment_ids),
            None,
        )
        lab_result = persist_lab_candidates(db, document=document, candidates=candidates, source_section_id=source_section_id)
        result.lab_results_created += sum(1 for o in lab_result.observations if o.was_new)
        result.lab_results_reused += sum(1 for o in lab_result.observations if not o.was_new)

    # ── Canonical medications ───────────────────────────────────────
    med_section_by_id = {s.id: s for s in structured_document.sections if s.canonical_key in MEDICATION_BEARING_CANONICAL_KEYS}
    all_medication_candidates = []
    for segment in segments:
        canonical_key = classify_canonical_heading(segment.raw_heading)
        if canonical_key not in MEDICATION_BEARING_CANONICAL_KEYS:
            continue
        source_section_id = next(
            (sid for sid, section in med_section_by_id.items() if segment.segment_id in section.source_segment_ids),
            None,
        )
        all_medication_candidates.extend(
            extract_medication_candidates_from_segment(segment, canonical_key=canonical_key, source_section_id=source_section_id)
        )
    if all_medication_candidates:
        med_result = persist_medication_candidates(
            db,
            document=document,
            created_by_user_id=actor_user_id,
            candidates=all_medication_candidates,
            admission_date=structured_document.metadata.admission_date,
            discharge_date=structured_document.metadata.discharge_date,
        )
        result.medications_created += sum(1 for o in med_result.observations if o.was_new)
        result.medications_reused += sum(1 for o in med_result.observations if not o.was_new)

    db.flush()  # medications must be committed-visible before Timeline projection queries them

    # ── Timeline projection ─────────────────────────────────────────
    timeline_result = project_clinical_document_to_timeline(db, document)
    result.timeline_events_created = len(timeline_result.created)
    result.timeline_events_retracted = len(timeline_result.retracted)

    # ── AI Clinical Document Interpreter (never raises — see its own
    # docstring; a failure here still leaves the deterministic document
    # above fully intact) ───────────────────────────────────────────
    interpreted_document = interpret_structured_document(structured_document)
    result.interpretation_status = interpreted_document.interpretation.status if interpreted_document.interpretation else "unavailable"
    result.interpretation_warnings = interpreted_document.interpretation.warnings if interpreted_document.interpretation else []
    result.diagnoses_count = len(interpreted_document.diagnoses)
    result.investigations_count = len(interpreted_document.investigations)
    result.anomalies_count = len(interpreted_document.anomalies)

    document.note_body = serialize_structured_document(interpreted_document)
    document.last_edited_at = now_iso()

    from app.main import add_audit_log

    add_audit_log(
        db=db,
        document_id=document.id,
        action="clinical_structure_reprocessed",
        actor=str(actor_user_id),
        details=(
            f"labs: +{result.lab_results_created}/{result.lab_results_reused} reused; "
            f"medications: +{result.medications_created}/{result.medications_reused} reused; "
            f"timeline: +{result.timeline_events_created}/-{result.timeline_events_retracted}; "
            f"evidence: +{result.segment_evidence_created}/{result.segment_evidence_reused} reused "
            f"({result.segments_with_page} with page, {result.segments_without_page} without); "
            f"extraction_complete={result.extraction_complete}; "
            f"interpretation: {result.interpretation_status} "
            f"(diagnoses={result.diagnoses_count}, investigations={result.investigations_count}, anomalies={result.anomalies_count})"
        ),
    )
    db.commit()

    return result
