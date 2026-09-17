"""Source segmentation — Clinical Document Intelligence V3, Phase 4
(second increment).

Defines the intermediate representation between raw provider extraction
(Reducto/OCR/the current per-page discharge-layout model call) and
canonical `ClinicalSection`s (schema.py). A `SourceSegment` is ONE
ordered, raw chunk of extracted content — before any canonical
classification or repeated-heading merging happens — with a STABLE id
so later phases (labs, medications, prescriptions, Ask Bragi citations)
can point back to the exact originating segment, not just a heading
string.

This module does NOT replace or re-implement provider/OCR extraction —
`build_segments_from_legacy_discharge_payload` below reads the CURRENT,
UNCHANGED output of `discharge_summary_pipeline.py` (see
`docs/clinical_document_v3/CURRENT_PIPELINE_MAP.md` §8) and reshapes it
into typed segments; it never re-parses a PDF or calls a model itself.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.lab_catalog import normalize_text

SegmentType = Literal["heading_section", "table"]


class SegmentTableData(BaseModel):
    """Raw tabular content, when the source segment is (or contains) a
    table — kept separate from `schema.py`'s `TableBlock`: this is the
    RAW, pre-canonical extraction: schema.py's block types are the
    canonical OUTPUT a later consolidation step produces from segments
    like this one, not the same concept."""

    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class SourceSegment(BaseModel):
    """One raw, ordered chunk of provider-extracted content, before any
    canonical classification/merging. `segment_id` is deterministic
    (derived from position + heading, not a random UUID) so reprocessing
    the SAME document produces the SAME ids — required for idempotency
    once ingestion actually persists these (Phase 13)."""

    segment_id: str
    index: int
    segment_type: SegmentType = "heading_section"
    raw_heading: str | None = None
    raw_text: str = ""
    table_data: SegmentTableData | None = None
    # Anchor fields — optional because the CURRENT discharge pipeline's
    # final, cross-page-merged sections don't carry a single page number
    # today (a merged section can legitimately span several pages; see
    # CURRENT_PIPELINE_MAP.md §8's page_payloads note). Left None rather
    # than fabricated; a future real per-page segmentation can populate
    # these once that granularity is actually threaded through.
    page: int | None = None
    source_block_id: str | None = None


def _slugify_heading(heading: str | None) -> str:
    normalized = normalize_text(heading) if heading else ""
    slug = normalized.replace(" ", "-")
    return slug[:40] if slug else "segment"


def build_segments_from_legacy_discharge_payload(payload: dict[str, Any]) -> list[SourceSegment]:
    """Builds typed `SourceSegment`s from the CURRENT discharge
    pipeline's real, unchanged ad-hoc payload shape (`payload["sections"]`
    — each a `{key, title, body, ...}` dict, see
    CURRENT_PIPELINE_MAP.md §8) — one segment per raw section entry, in
    document order. A malformed (non-dict) entry is skipped, not raised
    on, matching this package's existing best-effort read-path
    convention (see persistence.py).
    """
    raw_sections = payload.get("sections") or []
    segments: list[SourceSegment] = []
    for index, raw in enumerate(raw_sections):
        if not isinstance(raw, dict):
            continue
        heading = raw.get("title") or raw.get("key") or None
        text = raw.get("body") or ""
        segments.append(
            SourceSegment(
                segment_id=f"seg-{index:03d}-{_slugify_heading(heading)}",
                index=index,
                segment_type="heading_section",
                raw_heading=heading,
                raw_text=text,
                table_data=None,  # the current pipeline extracts table content inline as text, not as separate structure
                page=None,
                source_block_id=None,
            )
        )
    return segments
