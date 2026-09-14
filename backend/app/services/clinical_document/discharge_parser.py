"""Phase 4 + Phase 5 orchestration — Clinical Document Intelligence V3.

The real (not backward-compat-only) pipeline from the CURRENT
`discharge_summary_pipeline.py`'s raw payload shape to a validated
`StructuredClinicalDocument`:

    raw payload -> segments -> canonical sections -> Clinical Course
    dated events -> chronology sanity warnings -> assembled document

**NOT wired into `discharge_summary_pipeline.py`'s real write path
yet** — see `docs/handoffs/CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md`
section 9b's sequencing note (switching the live write path before
Phase 8 rebuilds the frontend discharge reader would break it). This
module is what a future dual-write increment would call; it is fully
usable and tested standalone in the meantime.
"""

from __future__ import annotations

from typing import Any

from app.services.document_taxonomy import DocumentType

from .canonical_headings import classify_canonical_heading, consolidate_segments
from .dates import parse_date_token
from .events import build_events_from_segment_text
from .schema import ClinicalEvent, DocumentMetadata, StructuredClinicalDocument
from .segments import build_segments_from_legacy_discharge_payload

PARSER_VERSION = "discharge-parser-phase4-5-v1"

# Clinical Course is where dated narrative events genuinely live.
# Restricting event extraction to these canonical keys (rather than
# every section) avoids inventing encounters from unrelated dates that
# happen to appear elsewhere (an identifier, a birth date in
# administrative_information) — a deliberate, narrow scope, not an
# oversight.
_EVENT_BEARING_CANONICAL_KEYS = frozenset({"clinical_course", "treatment", "procedures", "investigations"})


def parse_legacy_discharge_payload(payload: dict[str, Any]) -> StructuredClinicalDocument:
    """Builds a real, validated `StructuredClinicalDocument` from the
    CURRENT discharge pipeline's raw payload shape — the same shape
    `persistence.py`'s backward-compat upconversion reads, but here used
    as a genuine forward parse (`parser_version` reflects a real Phase
    4/5 parser, not the backward-compat label) with full Clinical
    Course event extraction on top of section consolidation."""
    segments = build_segments_from_legacy_discharge_payload(payload)
    sections = consolidate_segments(segments, review_state="auto")

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

    doc_warnings.extend(_chronology_warnings(dated_events, metadata))
    doc_warnings.extend(str(w) for w in (payload.get("warnings") or []))

    return StructuredClinicalDocument(
        parser_version=PARSER_VERSION,
        document_kind=DocumentType.DISCHARGE_SUMMARY,
        source_language=payload.get("source_language") or payload.get("language"),
        metadata=metadata,
        sections=sections,
        dated_events=dated_events,
        warnings=doc_warnings,
    )


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
