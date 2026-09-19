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
from .geometry_alignment import align_segment_to_blocks
from .lab_extraction import extract_lab_candidates_from_segment
from .lab_persistence import persist_lab_candidates
from .medication_extraction import MEDICATION_BEARING_CANONICAL_KEYS, extract_medication_candidates_from_segment
from .medication_persistence import persist_medication_candidates
from .persistence import _looks_like_legacy_discharge_payload, serialize_structured_document
from .schema import ClinicalEvent, StructuredClinicalDocument
from .segments import (
    SegmentTableData,
    SourceSegment,
    build_segments_from_legacy_discharge_payload,
    page_geometries_from_legacy_payload,
)
from .source_geometry import BlockGeometry, PageGeometry
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

        # Source Geometry + Clinical Table Intelligence V3 — recover a
        # real table's TEXT (headers/rows — cell geometry is NOT
        # recoverable here; see consolidate_segments's own docstring on
        # why that's fine) so lab/medication re-extraction on a second+
        # pass still finds the SAME rows it found on the first pass,
        # rather than silently losing every table-derived candidate.
        # Scoped to the common, unambiguous case: exactly one
        # contributing segment and exactly one TableBlock — a section
        # with several contributors/tables has no reliable way to know
        # which segment a given table belongs to from persisted blocks
        # alone, so it deliberately stays unenriched here (never guessed).
        table_blocks = [block for block in section.blocks if getattr(block, "type", None) == "table"]
        reconstructed_table_data = (
            SegmentTableData(headers=table_blocks[0].headers, rows=table_blocks[0].rows)
            if len(table_blocks) == 1 and len(segment_ids) == 1
            else None
        )

        if len(segment_ids) == len(block_texts) and block_texts:
            for segment_id, text in zip(segment_ids, block_texts):
                segments.append(
                    SourceSegment(
                        segment_id=segment_id,
                        index=0,
                        raw_heading=heading,
                        raw_text=text,
                        table_data=reconstructed_table_data,
                    )
                )
        elif reconstructed_table_data is not None and not block_texts:
            # A section that is ONLY a table (no paragraph contribution
            # at all, e.g. a placeholder-free table-only segment).
            segments.append(
                SourceSegment(segment_id=segment_ids[0], index=0, raw_heading=heading, table_data=reconstructed_table_data)
            )
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


def _block_bbox_and_rects(blocks: list[BlockGeometry]) -> tuple[dict[str, float], list[dict]]:
    """Real, confidently-aligned PyMuPDF blocks (`align_segment_to_blocks`)
    -> (primary bbox, every supporting rect) — a union of one block is
    just that block's own bbox; several blocks union to their combined
    extent, with each individual block also kept in `field_bboxes` so the
    viewer can render every one (never just the first — Part 27)."""
    xs0 = [b.bbox.x for b in blocks]
    ys0 = [b.bbox.y for b in blocks]
    xs1 = [b.bbox.x + b.bbox.width for b in blocks]
    ys1 = [b.bbox.y + b.bbox.height for b in blocks]
    primary = {"x": min(xs0), "y": min(ys0), "width": max(xs1) - min(xs0), "height": max(ys1) - min(ys0)}
    rects = [{"label": "block", **b.bbox.model_dump()} for b in blocks]
    return primary, rects


def _event_evidence_source_block_id(source_event_id: str) -> str:
    return f"evt-{source_event_id}"


def _attach_segment_evidence(
    db: Session,
    *,
    document: models.Document,
    structured_document: StructuredClinicalDocument,
    segments: list[SourceSegment],
    page_geometries: dict[int, PageGeometry],
    result: ReprocessingResult,
) -> tuple[StructuredClinicalDocument, dict[str, int]]:
    """Creates (or reuses) one SourceEvidence row per source segment and
    resolves it onto every ClinicalSection/ClinicalEvent that references
    that segment — this is what upgrades diagnoses/investigations/
    anomalies/recommendations/treatment eras (via the AI interpreter,
    which runs AFTER this and only ever resolves already-real evidence
    ids, never invents its own — see ai_interpreter.py) from having NO
    provenance UI at all to a real "View in original" action.

    Source Geometry + Clinical Table Intelligence V3 (Part 14/58):
    additionally attempts REAL paragraph-block alignment for each
    section's own text (upgrading its evidence's bbox in place — see
    ensure_segment_evidence's upgrade semantics) and, separately, for
    EACH individual `ClinicalEvent` (so distinct narrative facts sharing
    one Clinical Course section — e.g. the JAK2 result vs. the bone
    marrow biopsy vs. the ultrasound finding — each resolve to their OWN
    distinct block, never one shared whole-section evidence; Part 61's
    explicit 'unacceptable' example). Falls back to block/page precision
    exactly as before whenever alignment isn't confident or no page
    geometry exists for that page."""
    segment_by_id = {segment.segment_id: segment for segment in segments}
    evidence_id_by_segment_id: dict[str, int] = {}
    for segment in segments:
        page_geometry = page_geometries.get(segment.page) if segment.page is not None else None
        matched_blocks = align_segment_to_blocks(segment.raw_text, page_geometry)
        bbox, field_bboxes = (_block_bbox_and_rects(matched_blocks) if matched_blocks else (None, None))

        evidence, was_new = ensure_segment_evidence(
            db,
            document,
            source_block_id=segment.segment_id,
            page_number=segment.page,
            source_text=segment.raw_text,
            bbox=bbox,
            field_bboxes=field_bboxes,
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

    def _event_evidence_id(event: ClinicalEvent) -> int | None:
        parent_segment_id = _event_segment_id(event.source_event_id)
        parent_segment = segment_by_id.get(parent_segment_id)
        fallback_id = evidence_id_by_segment_id.get(parent_segment_id)
        if parent_segment is None:
            return fallback_id

        page_geometry = page_geometries.get(parent_segment.page) if parent_segment.page is not None else None
        matched_blocks = align_segment_to_blocks(event.raw_text, page_geometry)
        if not matched_blocks:
            return fallback_id

        bbox, field_bboxes = _block_bbox_and_rects(matched_blocks)
        evidence, was_new = ensure_segment_evidence(
            db,
            document,
            source_block_id=_event_evidence_source_block_id(event.source_event_id),
            page_number=parent_segment.page,
            source_text=event.raw_text,
            bbox=bbox,
            field_bboxes=field_bboxes,
        )
        if was_new:
            result.segment_evidence_created += 1
        else:
            result.segment_evidence_reused += 1
        return evidence.id

    new_events = [
        event.model_copy(update={"source_evidence_ids": ([eid] if (eid := _event_evidence_id(event)) is not None else [])})
        for event in structured_document.dated_events
    ]

    if structured_document.extraction_coverage is not None:
        result.extraction_complete = structured_document.extraction_coverage.extraction_complete

    updated = structured_document.model_copy(update={"sections": new_sections, "dated_events": new_events})
    return updated, evidence_id_by_segment_id


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


def _resolve_base_document_and_segments(
    payload: dict,
) -> tuple[StructuredClinicalDocument, list[SourceSegment], dict[int, PageGeometry]]:
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
        # No legacy payload survives past the first reprocess pass, so
        # there is nothing left to re-derive page geometry from on a
        # second+ pass — the evidence rows a first pass already upgraded
        # to real bbox precision are simply reused as-is (idempotent,
        # never downgraded); see ensure_segment_evidence's own docstring.
        return base, _segments_from_structured_document(base), {}

    if _looks_like_legacy_discharge_payload(payload):
        # The REAL forward parser (review_state="auto" — this is a
        # genuine, deliberate reprocessing action, not a passive
        # backward-compat read; see discharge_parser.py's own docstring
        # on the "auto" vs "needs_review" distinction).
        base = parse_legacy_discharge_payload(payload, review_state="auto")
        return base, build_segments_from_legacy_discharge_payload(payload), page_geometries_from_legacy_payload(payload)

    raise ReprocessingError("This document is not a discharge-summary-shaped document — nothing to reprocess.")


def reprocess_discharge_document(db: Session, *, document: models.Document, actor_user_id: int) -> ReprocessingResult:
    """Idempotent. Safe to call repeatedly on the same document — see
    module docstring. Ownership/authorization is the CALLER's
    responsibility (see the router endpoint) — this function only
    requires a real `Document` instance and does no access check of its
    own, matching this package's existing convention (persistence
    functions are pure of authz; routers own that)."""
    payload = _load_note_body_json(document)
    structured_document, segments, page_geometries = _resolve_base_document_and_segments(payload)

    result = ReprocessingResult(document_id=document.id, dated_events_count=len(structured_document.dated_events))

    # ── Source-evidence provenance (must run BEFORE the AI interpreter,
    # so it has real section/event source_evidence_ids to resolve — see
    # ai_interpreter.py::apply_interpretation) ──────────────────────
    structured_document, evidence_id_by_segment_id = _attach_segment_evidence(
        db,
        document=document,
        structured_document=structured_document,
        segments=segments,
        page_geometries=page_geometries,
        result=result,
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
    interpreted_document = interpret_structured_document(structured_document, evidence_id_by_segment_id)
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
