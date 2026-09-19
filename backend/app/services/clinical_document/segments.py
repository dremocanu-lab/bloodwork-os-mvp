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

from app.services.clinical_document.source_geometry import PageGeometry, TableGeometry
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
    # Source Geometry + Clinical Table Intelligence V3 — the stable id of
    # the REAL `TableGeometry` this data was extracted from (see
    # source_geometry.py), so downstream SourceEvidence can cite the
    # exact table (and, via field_bboxes_json, its cells) rather than
    # only the containing segment. None for table data that predates
    # real geometry extraction (kept optional, never backfilled/guessed).
    source_table_id: str | None = None
    # Parallel to `rows`: `cell_bboxes[i][j]` is the REAL normalized
    # bbox (as `{x,y,width,height}`) of `rows[i][j]`, taken verbatim from
    # `TableGeometry.cells` — never estimated from character width. Left
    # as an empty list when the table was reconstructed without matching
    # cell geometry (e.g. a future non-PyMuPDF provider that only offers
    # row text); a consumer must check length before indexing.
    cell_bboxes: list[list[dict | None]] = Field(default_factory=list)


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


def page_geometries_from_legacy_payload(payload: dict[str, Any]) -> dict[int, PageGeometry]:
    """Parses `page_payloads[*]["geometry"]` (populated by
    `discharge_summary_pipeline.py` since Source Geometry + Clinical
    Table Intelligence V3) into a page-number-keyed lookup. Malformed or
    absent geometry for a given page is simply omitted — never raised on
    — since geometry is enrichment, never required for a page to have a
    segment (see discharge_summary_pipeline.py's own "never fatal"
    handling of the same extraction)."""
    geometries: dict[int, PageGeometry] = {}
    for raw_page in payload.get("page_payloads") or []:
        if not isinstance(raw_page, dict):
            continue
        raw_geometry = raw_page.get("geometry")
        page_number = raw_page.get("page_number")
        if not raw_geometry or not isinstance(page_number, int):
            continue
        try:
            geometries[page_number] = PageGeometry.model_validate(raw_geometry)
        except Exception:  # noqa: BLE001 — enrichment only, never fatal
            continue
    return geometries


def _table_data_for_segment(table: TableGeometry, *, heading_context: str | None) -> SegmentTableData | None:
    """Classifies ONE real extracted table and — ONLY for the table types
    that route into existing candidate-extraction pipelines
    (laboratory/medication_list/prescription/administered_treatment) —
    returns typed `SegmentTableData` for it. Every other type (including
    `empty_template`) deliberately returns None: the geometry itself
    stays real, retrievable source structure (still present in
    `page_payloads[*]["geometry"]`), but is never turned into a
    fabricated clinical candidate (Part 20/55's 'source table retained,
    clinical fact suppressed')."""
    from .table_interpreter import classify_table_deterministic

    classification = classify_table_deterministic(table, heading_context=heading_context)
    if classification is None or classification.table_type in (
        "empty_template",
        "investigation",
        "diagnosis",
        "vital_signs",
        "encounter_history",
        "administrative",
        "other",
        "uncertain",
    ):
        return None
    rows = table.extract_rows()
    if not rows:
        return SegmentTableData(source_table_id=table.table_id)

    data_row_count = len(rows) - 1
    cell_bboxes: list[list[dict | None]] = [[None] * table.col_count for _ in range(data_row_count)]
    for cell in table.cells:
        data_row_index = cell.row_index - 1  # row 0 is the header row, excluded from `rows[1:]`
        if 0 <= data_row_index < data_row_count and 0 <= cell.col_index < table.col_count:
            cell_bboxes[data_row_index][cell.col_index] = cell.bbox.model_dump()

    return SegmentTableData(
        headers=rows[0], rows=rows[1:], source_table_id=table.table_id, cell_bboxes=cell_bboxes
    )


def build_segments_from_legacy_discharge_payload(payload: dict[str, Any]) -> list[SourceSegment]:
    """Builds typed `SourceSegment`s from the CURRENT discharge
    pipeline's real, unchanged ad-hoc payload shape (`payload["sections"]`
    — each a `{key, title, body, ...}` dict, see
    CURRENT_PIPELINE_MAP.md §8) — one segment per raw section entry, in
    document order. A malformed (non-dict) entry is skipped, not raised
    on, matching this package's existing best-effort read-path
    convention (see persistence.py).
    """
    from .canonical_headings import classify_canonical_heading

    raw_sections = payload.get("sections") or []

    # Source Geometry + Clinical Table Intelligence V3 — which segment (by
    # index) OWNS its page's table, for table_data attachment below. A
    # page can carry more than one segment (e.g. a placeholder pointer
    # segment for a structured table PLUS a separate narrative segment
    # that happens to share the page — see the V3 PDF fixture's page 5:
    # a "Retete eliberate" segment and an unrelated dated narrative
    # segment both with page_start=5). Rather than requiring page-wide
    # segment uniqueness (too strict — it would wrongly exclude exactly
    # this case), ownership goes to the segment whose OWN canonical
    # heading classification is a table-routable kind
    # (laboratory_results/medications/discharge_medications/
    # prescriptions/treatment) — and ONLY when exactly one such
    # qualifying segment exists on the page, so two competing
    # table-routable segments on the same page still stay unenriched
    # (ambiguous, per the "never attach when ambiguous" contract).
    _TABLE_OWNER_CANONICAL_KEYS = frozenset(
        {"laboratory_results", "medications", "discharge_medications", "prescriptions", "treatment"}
    )
    qualifying_indices_by_page: dict[int, list[int]] = {}
    for index, raw in enumerate(raw_sections):
        if not isinstance(raw, dict):
            continue
        raw_page = raw.get("page_start")
        if not isinstance(raw_page, int) or raw_page <= 0:
            continue
        heading = raw.get("title") or raw.get("key") or None
        if classify_canonical_heading(heading) in _TABLE_OWNER_CANONICAL_KEYS:
            qualifying_indices_by_page.setdefault(raw_page, []).append(index)
    table_owner_index_by_page = {page: indices[0] for page, indices in qualifying_indices_by_page.items() if len(indices) == 1}

    page_geometries = page_geometries_from_legacy_payload(payload)
    segments: list[SourceSegment] = []
    for index, raw in enumerate(raw_sections):
        if not isinstance(raw, dict):
            continue
        heading = raw.get("title") or raw.get("key") or None
        text = raw.get("body") or ""
        # Source Intelligence + Provenance V2 — `page_start` has been
        # computed by discharge_summary_pipeline.py's per-page vision
        # extraction (and carried through _merge_sections/_clean_section)
        # since before this field existed on SourceSegment; it was simply
        # never read here. Threading it through is what upgrades every
        # narrative fact's provenance from "document_only" (no location
        # at all) to "page_only" (opens the correct page, honestly says
        # exact position is unavailable) — never a fabricated bbox. A
        # non-integer/missing value stays None rather than guessed.
        raw_page = raw.get("page_start")
        page = int(raw_page) if isinstance(raw_page, int) and raw_page > 0 else None

        # Source Geometry + Clinical Table Intelligence V3 — real table
        # structure, attached ONLY when this segment is its page's
        # unique table-owning segment (see table_owner_index_by_page
        # above) and exactly one of that page's real extracted tables
        # classifies into a routable clinical type. Ambiguous cases (0 or
        # 2+ qualifying tables, or no clear owning segment) deliberately
        # stay unenriched — geometry remains available on
        # `page_payloads[*]["geometry"]` regardless, per the "never
        # attach when ambiguous, fall back" contract.
        table_data = None
        if page is not None and table_owner_index_by_page.get(page) == index:
            page_geometry = page_geometries.get(page)
            if page_geometry is not None and page_geometry.tables:
                routable = [
                    td
                    for table in page_geometry.tables
                    if (td := _table_data_for_segment(table, heading_context=heading)) is not None
                ]
                if len(routable) == 1:
                    table_data = routable[0]

        segments.append(
            SourceSegment(
                segment_id=f"seg-{index:03d}-{_slugify_heading(heading)}",
                index=index,
                segment_type="heading_section",
                raw_heading=heading,
                raw_text=text,
                table_data=table_data,
                page=page,
                source_block_id=None,
            )
        )
    return segments
