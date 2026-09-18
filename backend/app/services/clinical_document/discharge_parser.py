"""Phase 4 + Phase 5 orchestration — Clinical Document Intelligence V3.

The real (not backward-compat-only) pipeline from the CURRENT
`discharge_summary_pipeline.py`'s raw payload shape to a validated
`StructuredClinicalDocument`:

    raw payload -> segments -> canonical sections -> Clinical Course
    dated events -> chronology sanity warnings -> assembled document

**Not wired into `discharge_summary_pipeline.py`'s real WRITE path** —
that pipeline still writes the old 13-key legacy JSON shape into
`Document.note_body` (see docs/handoffs/
CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md section 9b's original
sequencing note). **This module IS reached on every READ**, though, as
of Clinical Reader Intelligence V2:
`persistence.py::parse_structured_document()` calls this exact function
(with `review_state="needs_review"`) to upconvert that legacy JSON in
memory, so `dated_events`/chronology warnings/anomaly flags are real for
every existing AND future discharge document without needing
reprocessing — see persistence.py's own docstring. The dedicated
`POST /documents/{id}/reprocess-clinical-structure` endpoint additionally
calls this with `review_state="auto"` when it ALSO wants to persist real
canonical `LabResult`/`PatientMedication` rows and a full AI
interpretation pass (see reprocessing.py).
"""

from __future__ import annotations

from typing import Any

from app.services.document_taxonomy import DocumentType

from app.services.lab_catalog import normalize_text

from .canonical_headings import classify_canonical_heading, consolidate_segments
from .dates import parse_date_token
from .events import build_events_from_segment_text
from .schema import ClinicalEvent, DocumentMetadata, ExtractionCoverage, StructuredClinicalDocument
from .segments import build_segments_from_legacy_discharge_payload

PARSER_VERSION = "discharge-parser-phase4-5-v1"

# Clinical Course is where dated narrative events genuinely live.
# Restricting event extraction to these canonical keys (rather than
# every section) avoids inventing encounters from unrelated dates that
# happen to appear elsewhere (an identifier, a birth date in
# administrative_information) — a deliberate, narrow scope, not an
# oversight.
_EVENT_BEARING_CANONICAL_KEYS = frozenset({"clinical_course", "treatment", "procedures", "investigations"})


def parse_legacy_discharge_payload(
    payload: dict[str, Any],
    *,
    parser_version: str = PARSER_VERSION,
    review_state: str = "auto",
) -> StructuredClinicalDocument:
    """Builds a real, validated `StructuredClinicalDocument` from the
    CURRENT discharge pipeline's raw payload shape — full Clinical
    Course event extraction (dates, anomaly warnings) on top of section
    consolidation, always.

    `parser_version`/`review_state` are overridable so `persistence.py`'s
    read-time backward-compat upconversion can reuse this SAME real
    parser (rather than maintaining a second, weaker implementation that
    silently drops event/anomaly extraction — a real gap this closes,
    see persistence.py's own comment) while still honestly labeling the
    result as a retroactive upconversion, never mistaken for a live
    Phase 4/5 parse."""
    segments = build_segments_from_legacy_discharge_payload(payload)
    sections = consolidate_segments(segments, review_state=review_state)

    dated_events: list[ClinicalEvent] = []
    doc_warnings: list[str] = []

    # Iterated over the ORIGINAL segments, not the merged sections'
    # blocks — this keeps each event's provenance tied to the exact
    # segment it came from (segment.segment_id), which stays correct
    # even when a canonical section merges multiple segments together
    # (some of which may have contributed no text at all and therefore
    # no block — see consolidate_segments) or is contributed to by
    # several source headings.
    for segment in segments:
        canonical_key = classify_canonical_heading(segment.raw_heading)
        if canonical_key not in _EVENT_BEARING_CANONICAL_KEYS:
            continue
        events, section_warnings = build_events_from_segment_text(segment.segment_id, segment.raw_text)
        dated_events.extend(events)
        doc_warnings.extend(f"[{canonical_key}] {w}" for w in section_warnings)

    metadata = DocumentMetadata(
        patient_name=payload.get("patient_name"),
        date_of_birth=payload.get("date_of_birth"),
        sex=payload.get("sex"),
        admission_date=payload.get("admission_date"),
        discharge_date=payload.get("discharge_date"),
        hospital_name=payload.get("hospital_name"),
    )

    dated_events = _mark_repeated_events(dated_events)

    doc_warnings.extend(_chronology_warnings(dated_events, metadata))
    doc_warnings.extend(str(w) for w in (payload.get("warnings") or []))

    return StructuredClinicalDocument(
        parser_version=parser_version,
        document_kind=DocumentType.DISCHARGE_SUMMARY,
        source_language=payload.get("source_language") or payload.get("language"),
        metadata=metadata,
        sections=sections,
        dated_events=dated_events,
        warnings=doc_warnings,
        extraction_coverage=_extraction_coverage_from_payload(payload),
    )


def _extraction_coverage_from_payload(payload: dict[str, Any]) -> ExtractionCoverage | None:
    """Source Intelligence + Provenance V2, Part 5. Prefers the coverage
    block `discharge_summary_pipeline.py` computes directly (real
    per-page success/failure bookkeeping); for an OLDER document
    persisted before that field existed, falls back to a best-effort
    reconstruction from `page_count`/`page_payloads` so coverage is still
    honestly reported rather than silently absent — never asserts
    `extraction_complete=True` without real evidence either way."""
    raw_coverage = payload.get("extraction_coverage")
    if isinstance(raw_coverage, dict):
        try:
            return ExtractionCoverage.model_validate(raw_coverage)
        except Exception:  # noqa: BLE001 — malformed/legacy shape, fall through to reconstruction
            pass

    total_pages = payload.get("page_count")
    page_payloads = payload.get("page_payloads")
    if not isinstance(total_pages, int) or not isinstance(page_payloads, list):
        return None  # genuinely nothing to report — never fabricated

    successful_pages = sorted(
        {int(p.get("page_number")) for p in page_payloads if isinstance(p, dict) and p.get("page_number")}
    )
    all_pages = set(range(1, total_pages + 1))
    failed_pages = sorted(all_pages - set(successful_pages))
    return ExtractionCoverage(
        total_pages=total_pages,
        attempted_pages=len(successful_pages) + len(failed_pages),
        successful_pages=len(successful_pages),
        failed_pages=failed_pages,
        warning_pages=[],
        extraction_complete=not failed_pages,
    )


def _segment_id_of(event: ClinicalEvent) -> str:
    return event.source_event_id.rsplit("-event-", 1)[0]


def _mark_repeated_events(events: list[ClinicalEvent]) -> list[ClinicalEvent]:
    """Presentation-only duplicate detection (Part 16 / 1J) — deterministic
    and deliberately conservative: an event is only flagged when its ENTIRE
    raw_text is an exact normalized match of an event already seen from a
    DIFFERENT segment (never within the same segment, where sibling events
    sharing one segment's raw_text is expected and not a duplication at
    all). Nothing is removed or merged here — every event, and its own
    source_evidence_ids, survives untouched; this only sets a flag the
    reader can use to visually consolidate a repeated narrative block
    without deleting the second occurrence's provenance."""
    seen_in_segment: dict[str, str] = {}
    marked: list[ClinicalEvent] = []
    for event in events:
        key = normalize_text(event.raw_text)
        segment_id = _segment_id_of(event)
        first_segment = seen_in_segment.get(key) if key else None
        if key and first_segment is not None and first_segment != segment_id:
            marked.append(event.model_copy(update={"is_repeated_in_source": True}))
        else:
            marked.append(event)
            if key and first_segment is None:
                seen_in_segment[key] = segment_id
    return marked


def _chronology_warnings(events: list[ClinicalEvent], metadata: DocumentMetadata) -> list[str]:
    """Deterministic sanity check: an event dated clearly outside the
    known admission-discharge window is FLAGGED, never silently dropped
    or "corrected" into the window — see the V3 contract's own
    "chronologically misplaced" fixture example. Only runs when BOTH
    admission and discharge dates are themselves parseable to a real
    calendar date — with either bound unknown or itself invalid, no
    window comparison is attempted rather than guessing a missing
    bound."""
    admission = parse_date_token(metadata.admission_date) if metadata.admission_date else None
    discharge = parse_date_token(metadata.discharge_date) if metadata.discharge_date else None
    if not admission or not admission.normalized_date or not discharge or not discharge.normalized_date:
        return []

    warnings: list[str] = []
    for event in events:
        if not event.normalized_date:
            continue
        if event.normalized_date < admission.normalized_date or event.normalized_date > discharge.normalized_date:
            warnings.append(
                f"Event dated {event.normalized_date} (source: '{event.raw_date_text}') falls outside the "
                f"recorded admission-discharge window ({admission.normalized_date} to "
                f"{discharge.normalized_date}) — preserved as documented, not corrected."
            )
    return warnings
