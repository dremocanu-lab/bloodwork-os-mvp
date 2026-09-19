"""Source Geometry + Clinical Table Intelligence V3 — geometry
extraction tests. Pure PyMuPDF, no external API, no DB — every PDF used
here is generated on the fly with `fitz` itself (no binary fixture
committed), matching this repo's existing "no real patient files"
convention.
"""

from __future__ import annotations

import fitz
import pytest

from app.services.clinical_document.source_geometry import extract_page_geometry


def _build_simple_pdf() -> "fitz.Document":
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 in points
    page.insert_text((72, 100), "Diagnostic principal (DRG Cod 1)", fontsize=14)
    page.insert_text((72, 130), "D45 Policitemie vera", fontsize=11)
    page.insert_text((72, 200), "La internare, AV 1008/min, TA 120/80 mmHg, afebrila.", fontsize=11)

    rows = [
        ["Analiza", "Rezultat", "UM", "Interval"],
        ["ALT", "56", "U/L", "10-49"],
        ["WBC", "15.2", "10^3/uL", "4.0-10.0"],
    ]
    y = 400
    for row in rows:
        x = 72
        for cell in row:
            page.insert_text((x, y), cell, fontsize=10)
            x += 100
        y += 20
    for i in range(4):
        page.draw_line((72, 385 + i * 20), (472, 385 + i * 20))
    for j in range(5):
        page.draw_line((72 + j * 100, 385), (72 + j * 100, 445))
    return doc


def _build_scanned_page_pdf() -> "fitz.Document":
    """A page with no text at all — simulates a scanned/image-only page
    (no native text layer), the case that must degrade to empty
    geometry, never fabricated."""
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    return doc


def test_extract_page_geometry_returns_real_paragraph_blocks_with_normalized_bbox():
    doc = _build_simple_pdf()
    try:
        geometry = extract_page_geometry(doc[0], page_number=1)
        assert geometry.page_number == 1
        assert geometry.rotation == 0
        block_texts = [b.text for b in geometry.blocks]
        assert any("D45 Policitemie vera" in t for t in block_texts)
        assert any("AV 1008" in t for t in block_texts)

        d45_block = next(b for b in geometry.blocks if "D45 Policitemie vera" in b.text)
        # Real, sane, normalized coordinates — not fabricated, not
        # degenerate (a real width/height, within [0,1]).
        assert 0 <= d45_block.bbox.x <= 1
        assert 0 <= d45_block.bbox.y <= 1
        assert 0 < d45_block.bbox.width <= 1
        assert 0 < d45_block.bbox.height <= 1
        # The D45 text (y=130pt) should sit above the AV1008 text
        # (y=200pt) on the normalized [0,1] top-left-origin page.
        av_block = next(b for b in geometry.blocks if "AV 1008" in b.text)
        assert d45_block.bbox.y < av_block.bbox.y
    finally:
        doc.close()


def test_extract_page_geometry_returns_real_table_structure():
    doc = _build_simple_pdf()
    try:
        geometry = extract_page_geometry(doc[0], page_number=1)
        assert len(geometry.tables) == 1
        table = geometry.tables[0]
        assert table.row_count == 3
        assert table.col_count == 4
        rows = table.extract_rows()
        assert rows[0] == ["Analiza", "Rezultat", "UM", "Interval"]
        assert rows[1] == ["ALT", "56", "U/L", "10-49"]
        assert rows[2] == ["WBC", "15.2", "10^3/uL", "4.0-10.0"]

        # Every cell has real, sane normalized geometry of its own.
        assert len(table.cells) == 12
        for cell in table.cells:
            assert 0 <= cell.bbox.x <= 1
            assert 0 <= cell.bbox.y <= 1
            assert cell.bbox.width > 0
            assert cell.bbox.height > 0

        # A cell's geometry must actually match its TEXT's row/column,
        # not just be sane in isolation — a real bug (PyMuPDF's
        # `table.cells` is COLUMN-major, not row-major; a naive
        # `row_index = cell_index // col_count` formula silently
        # mislabels every cell whenever row_count > 1, pairing each
        # cell's real bbox with the WRONG grid position even though
        # `extract_rows()`'s TEXT output stays coincidentally correct —
        # caught only by visually inspecting a rendered highlight, not
        # by a text-only or bbox-sanity-only assertion) must never
        # regress silently again: every cell in the SAME row shares one
        # y (row band), and the row's cells sort left-to-right by x in
        # column order.
        by_row: dict[int, list] = {}
        for cell in table.cells:
            by_row.setdefault(cell.row_index, []).append(cell)
        for row_index, row_cells in by_row.items():
            row_cells.sort(key=lambda c: c.col_index)
            ys = [c.bbox.y for c in row_cells]
            assert max(ys) - min(ys) < 0.01, f"row {row_index} cells are not on the same y band: {ys}"
            xs = [c.bbox.x for c in row_cells]
            assert xs == sorted(xs), f"row {row_index} cells are not left-to-right by column: {xs}"
    finally:
        doc.close()


def test_scanned_page_with_no_native_text_yields_empty_geometry_never_fabricated():
    doc = _build_scanned_page_pdf()
    try:
        geometry = extract_page_geometry(doc[0], page_number=1)
        assert geometry.blocks == []
        assert geometry.tables == []
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_geometry_survives_page_rotation(rotation):
    """The core Part 8 requirement: evidence boxes must map correctly
    to rendered page coordinates at every supported rotation — verified
    directly against real PyMuPDF rotation transforms, not assumed."""
    doc = _build_simple_pdf()
    try:
        page = doc[0]
        page.set_rotation(rotation)
        geometry = extract_page_geometry(page, page_number=1)

        # Post-rotation page dimensions: width/height swap at 90/270.
        if rotation in (90, 270):
            assert geometry.width == pytest.approx(842, abs=1)
            assert geometry.height == pytest.approx(595, abs=1)
        else:
            assert geometry.width == pytest.approx(595, abs=1)
            assert geometry.height == pytest.approx(842, abs=1)

        assert geometry.rotation == rotation
        d45_block = next(b for b in geometry.blocks if "D45 Policitemie vera" in b.text)
        # The transformed bbox must land fully within the normalized
        # [0,1] page regardless of rotation — never negative, never
        # overflowing past 1.0 (the real bug this class of test catches:
        # normalizing rotated coordinates against the WRONG — pre-
        # rotation — page dimensions would push values outside [0,1]).
        assert 0 <= d45_block.bbox.x <= 1
        assert 0 <= d45_block.bbox.y <= 1
        assert 0 <= d45_block.bbox.x + d45_block.bbox.width <= 1.0001
        assert 0 <= d45_block.bbox.y + d45_block.bbox.height <= 1.0001

        table = geometry.tables[0]
        assert 0 <= table.bbox.x <= 1
        assert 0 <= table.bbox.y <= 1
        assert 0 <= table.bbox.x + table.bbox.width <= 1.0001
        assert 0 <= table.bbox.y + table.bbox.height <= 1.0001
    finally:
        doc.close()


def test_tiny_artifact_blocks_are_filtered_out():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), ".", fontsize=4)  # a single stray character — not real content
    page.insert_text((72, 150), "A real paragraph of actual clinical narrative text.", fontsize=11)
    try:
        geometry = extract_page_geometry(page, page_number=1)
        texts = [b.text for b in geometry.blocks]
        assert any("real paragraph" in t for t in texts)
        assert "." not in texts
    finally:
        doc.close()
