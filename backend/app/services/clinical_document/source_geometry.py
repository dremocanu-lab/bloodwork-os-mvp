"""Real source geometry extraction — Source Geometry + Clinical Table
Intelligence V3.

Extracts paragraph-block and table geometry DIRECTLY from a PDF's own
native text layer via PyMuPDF (`fitz`) — already a project dependency,
already opened once per discharge upload for page rendering
(`discharge_summary_pipeline.py::_render_pages_from_file`). This is
real, provider-independent, zero-external-API-cost geometry: no Reducto
call, no additional latency, available for every page that has a native
text layer (the same `has_native_text` check the discharge pipeline
already uses to decide whether a page needs OCR).

Two things this module deliberately does NOT do:
- It never re-transcribes clinical text. The OpenAI vision pipeline's
  own transcription remains the authoritative TEXT for the document;
  this module only ever supplies GEOMETRY (a bbox) for text that
  transcription already produced, via `geometry_alignment.py`'s
  confidence-gated matching — never the other way around.
- It never fabricates geometry for a scanned page with no native text
  layer. `extract_page_geometry` returns an empty `blocks`/`tables` list
  for such a page — callers must fall back to page-level evidence, the
  same honest fallback this whole system has used since Clinical
  Document Intelligence V3's `dates.py`/`events.py`.

Coordinate contract (matches the EXISTING SourceEvidence contract
exactly — see BRAGI_REDUCTO_PLAN.md and models.py's own field
docstrings): normalized `[0, 1]` page-relative fractions, origin
top-left. PyMuPDF's raw block/table coordinates are in PDF POINTS and
are NOT automatically corrected for a rotated page (`page.rotation`) —
`page.rotation_matrix` is applied here before normalizing, verified
directly (not assumed) against a real rotated PDF: the transformed
rect lands correctly within `page.rect`'s own (rotated) dimensions at
0/90/180/270 degrees. PDF.js on the frontend renders using the SAME
page rotation by default, so a normalized-in-rotated-space rect drawn
as a plain `left/top/width/height` percentage overlay on the rendered
canvas aligns correctly with no frontend-side rotation handling needed
at all.
"""

from __future__ import annotations

import fitz
from pydantic import BaseModel, Field


class NormalizedBBox(BaseModel):
    """A single rectangle, normalized `[0, 1]`, origin top-left — the
    EXACT same shape SourceEvidence.field_bboxes_json already stores for
    lab evidence (see models.py). Reusing this shape (not inventing a
    new one) is what lets the existing multi-rect viewer code render
    block/table/cell rects with no new frontend geometry math."""

    x: float
    y: float
    width: float
    height: float


class BlockGeometry(BaseModel):
    """One paragraph-shaped block of native PDF text, as PyMuPDF's own
    `page.get_text("blocks")` reports it — `text` is PyMuPDF's raw
    extraction, kept ONLY for alignment matching against the vision
    pipeline's own transcription (see geometry_alignment.py); it is
    never shown to a user or trusted as the canonical clinical text."""

    block_id: str
    bbox: NormalizedBBox
    text: str


class CellGeometry(BaseModel):
    row_index: int
    col_index: int
    bbox: NormalizedBBox
    text: str


class TableGeometry(BaseModel):
    """One table as PyMuPDF's `page.find_tables()` detected it — real
    row/column/cell structure with real per-cell text and geometry, an
    INDEPENDENT extraction from the vision pipeline's own prose
    transcription of the same table (no alignment step needed for
    tables — unlike paragraphs, PyMuPDF's table detection is used
    directly as the source of truth for table STRUCTURE; see
    table_interpreter.py for how this feeds classification/routing)."""

    table_id: str
    bbox: NormalizedBBox
    row_count: int
    col_count: int
    cells: list[CellGeometry] = Field(default_factory=list)

    def extract_rows(self) -> list[list[str]]:
        """Reconstructs the row-major text grid from `cells` — the same
        shape `find_tables().extract()` returns, but derived from the
        already-normalized cell list this class persists, so a caller
        never needs to hold onto the original PyMuPDF table object."""
        rows: list[list[str]] = [["" for _ in range(self.col_count)] for _ in range(self.row_count)]
        for cell in self.cells:
            if 0 <= cell.row_index < self.row_count and 0 <= cell.col_index < self.col_count:
                rows[cell.row_index][cell.col_index] = cell.text
        return rows


class PageGeometry(BaseModel):
    page_number: int
    width: float
    height: float
    rotation: int
    blocks: list[BlockGeometry] = Field(default_factory=list)
    tables: list[TableGeometry] = Field(default_factory=list)


def _normalize_rect(rect: fitz.Rect, page_width: float, page_height: float) -> NormalizedBBox:
    x = max(0.0, min(1.0, rect.x0 / page_width))
    y = max(0.0, min(1.0, rect.y0 / page_height))
    width = max(0.0, min(1.0 - x, (rect.x1 - rect.x0) / page_width))
    height = max(0.0, min(1.0 - y, (rect.y1 - rect.y0) / page_height))
    return NormalizedBBox(x=x, y=y, width=width, height=height)


# A block/table with a genuinely tiny footprint (a stray artifact, a
# single decorative character) is never worth offering as clinical
# evidence — filtered out rather than surfaced as a confusing
# near-invisible highlight.
_MIN_BLOCK_AREA_FRACTION = 0.0002


def extract_page_geometry(page: fitz.Page, page_number: int) -> PageGeometry:
    """Pure, deterministic, no external API call. Returns empty
    `blocks`/`tables` for a page with no meaningful native text layer
    (a scanned page) — callers (discharge_summary_pipeline.py) already
    know this via their own `has_native_text` check and should skip
    calling this for such a page entirely rather than rely on this
    returning empty; this function itself doesn't special-case that so
    it stays a plain, independently-testable geometry primitive."""
    rect = page.rect
    rotation_matrix = page.rotation_matrix
    page_width, page_height = rect.width, rect.height

    blocks: list[BlockGeometry] = []
    for raw_block in page.get_text("blocks"):
        x0, y0, x1, y1, text, block_no, block_type = raw_block[:7]
        if block_type != 0:  # 0 = text block; 1 = image block — never treated as a paragraph
            continue
        cleaned_text = text.strip()
        if not cleaned_text:
            continue
        transformed = fitz.Rect(x0, y0, x1, y1) * rotation_matrix
        transformed.normalize()
        bbox = _normalize_rect(transformed, page_width, page_height)
        if bbox.width * bbox.height < _MIN_BLOCK_AREA_FRACTION:
            continue
        blocks.append(BlockGeometry(block_id=f"p{page_number}-b{block_no:02d}", bbox=bbox, text=cleaned_text))

    tables: list[TableGeometry] = []
    try:
        found = page.find_tables()
    except Exception:  # noqa: BLE001 — table-finding is a best-effort enrichment, never fatal to page processing
        found = None
    if found is not None:
        for table_index, table in enumerate(found.tables):
            table_rect = fitz.Rect(table.bbox) * rotation_matrix
            table_rect.normalize()
            table_bbox = _normalize_rect(table_rect, page_width, page_height)
            extracted = table.extract()
            cells: list[CellGeometry] = []
            for cell_index, cell_rect in enumerate(table.cells):
                if cell_rect is None:
                    continue
                # PyMuPDF's `table.cells` is COLUMN-MAJOR (all rows of
                # column 0, then all rows of column 1, ...) — verified
                # directly against real extracted rects (not assumed):
                # cells 0..row_count-1 share the same x0 and step through
                # increasing y0, then cell row_count starts the next
                # column at the next x0. A row-major `col_index =
                # cell_index % col_count` (the previous, WRONG formula)
                # silently mislabels every cell's row/col whenever
                # row_count != 1, pairing each cell's real geometry with
                # the wrong grid position — the text stayed correct only
                # because `extract_rows()` re-derives text using this
                # SAME (consistently wrong) label to both fetch from
                # `extracted[][]` and place into the output grid, a
                # self-cancelling bijection that never showed up as a
                # text bug, only as a geometry one (a browser check of
                # the actual rendered highlight caught it; a bbox/text
                # correctness assertion in isolation did not).
                col_index = cell_index // table.row_count if table.row_count else 0
                row_index = cell_index % table.row_count if table.row_count else 0
                cell_text = ""
                if row_index < len(extracted) and col_index < len(extracted[row_index]):
                    cell_text = (extracted[row_index][col_index] or "").strip()
                transformed_cell = fitz.Rect(cell_rect) * rotation_matrix
                transformed_cell.normalize()
                cells.append(
                    CellGeometry(
                        row_index=row_index,
                        col_index=col_index,
                        bbox=_normalize_rect(transformed_cell, page_width, page_height),
                        text=cell_text,
                    )
                )
            tables.append(
                TableGeometry(
                    table_id=f"p{page_number}-t{table_index:02d}",
                    bbox=table_bbox,
                    row_count=table.row_count,
                    col_count=table.col_count,
                    cells=cells,
                )
            )

    # Post-rotation dimensions — page.rect already reflects the rotated
    # page size (verified directly: width/height swap at 90/270), which
    # is what page_width/page_height above were computed from, so the
    # stored width/height here is consistent with the bbox normalization
    # just performed, not the pre-rotation mediabox.
    return PageGeometry(
        page_number=page_number,
        width=page_width,
        height=page_height,
        rotation=page.rotation,
        blocks=blocks,
        tables=tables,
    )
