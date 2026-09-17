"""Tests for `_union_row_bbox` — the presentation-only "whole row" region
derived for laboratory SourceEvidence (see BRAGI_REDUCTO_PLAN.md).

This is real geometry math on real per-field citation bboxes (never a
guessed/hardcoded region), so it's tested as a pure function: given a set
of field bboxes (page-fraction floats in [0, 1], as Reducto returns them),
does the union + padding behave correctly, and does it correctly decline
to produce a region when there isn't enough real geometry to union.
"""

from app.services.reducto_extraction import ReductoEvidence, _field_rects, _union_row_bbox


def _evidence(x, y, w, h, page=1):
    return ReductoEvidence(
        page=page,
        bbox_x=x,
        bbox_y=y,
        bbox_width=w,
        bbox_height=h,
        source_text="x",
        confidence=1.0,
    )


def test_union_of_two_real_field_boxes_spans_both_with_padding():
    # test_name cell and value cell, side by side on the same row.
    name = _evidence(0.10, 0.40, 0.20, 0.02)
    value = _evidence(0.45, 0.40, 0.08, 0.02)

    row = _union_row_bbox([name, value, None, None])

    assert row is not None
    left, top, width, height = row

    # Raw union (no padding) would be left=0.10, right=0.53, top=0.40,
    # bottom=0.42. The padded region must extend strictly outward on every
    # edge — that's the whole point (frame the row, don't hug it) — but
    # stay a modest expansion, not a guessed/arbitrary region.
    raw_left, raw_right, raw_top, raw_bottom = 0.10, 0.53, 0.40, 0.42
    assert left < raw_left
    assert left + width > raw_right
    assert top < raw_top
    assert top + height > raw_bottom
    # Padding stays modest (well under doubling the row's own size).
    assert width < (raw_right - raw_left) * 2
    assert height < (raw_bottom - raw_top) * 4


def test_union_clamps_to_page_bounds():
    # A field bbox flush against the page edge must not push the padded
    # region outside [0, 1] — that would misposition the highlight.
    name = _evidence(0.0, 0.0, 0.05, 0.02)
    value = _evidence(0.90, 0.0, 0.08, 0.02)

    row = _union_row_bbox([name, value, None, None])

    assert row is not None
    left, top, width, height = row
    assert left >= 0.0
    assert top >= 0.0
    assert left + width <= 1.0
    assert top + height <= 1.0


def test_fewer_than_two_real_boxes_returns_none():
    # Only one field actually has geometry (e.g. Extract only returned a
    # citation for the value, not the test name) — nothing meaningfully
    # wider than the existing single-field bbox to union, so this must NOT
    # fabricate a region.
    value = _evidence(0.45, 0.40, 0.08, 0.02)

    assert _union_row_bbox([None, value, None, None]) is None
    assert _union_row_bbox([]) is None
    assert _union_row_bbox([None, None]) is None


def test_boxes_on_a_different_page_are_excluded_not_unioned_across_break():
    # If Reducto ever cites two fields of the same row on different pages
    # (a row straddling a page break), union only the majority page rather
    # than spanning across the break into a meaningless region.
    name = _evidence(0.10, 0.40, 0.20, 0.02, page=1)
    value = _evidence(0.45, 0.40, 0.08, 0.02, page=1)
    stray = _evidence(0.10, 0.05, 0.20, 0.02, page=2)

    row = _union_row_bbox([name, value, stray])

    assert row is not None
    left, top, width, height = row
    # The page-2 stray box (top=0.05) must not have been unioned in — the
    # region should still sit near the page-1 boxes' own top (~0.40), not
    # stretch all the way up to 0.05.
    assert top > 0.1


def test_zero_size_boxes_do_not_produce_a_degenerate_region():
    zero = _evidence(0.5, 0.5, 0.0, 0.0)
    other = _evidence(0.5, 0.5, 0.0, 0.0)

    assert _union_row_bbox([zero, other]) is None


def _row(top, height=0.012, x=0.10, width=0.60, page=1):
    """One lab row's 4 field citations (test_name/value/unit/
    reference_range), laid out side by side on the same line — the shape
    `extract_lab_results` actually passes to both `_union_row_bbox` and
    `_field_rects` as `confidence_parts`.
    """
    field_width = width / 4
    return [
        _evidence(x + i * field_width, top, field_width * 0.9, height, page=page)
        for i in range(4)
    ]


class TestAdjacentDenseRowsFixture:
    """Reproduces the reported coarse-highlight bug: a dense differential/
    hemogram panel (PCT, NRBC#, NRBC%, NEUT# stacked tightly, unlike the
    sparse 6-row CBC panel `_union_row_bbox`'s padding was validated
    against). Proves (a) the historical row_bbox union+pad DOES bleed into
    a neighboring row here — confirming the root cause — and (b) the new
    `_field_rects` output never does, since it applies no padding at all.
    """

    # Four stacked rows, each 0.012 tall with a 0.002 gap — dense enough
    # that a fixed-ratio pad (height * 0.35) bleeds into the next row.
    PCT_TOP = 0.500
    NRBC_COUNT_TOP = 0.514
    NRBC_PCT_TOP = 0.528
    NEUT_COUNT_TOP = 0.542
    ROW_HEIGHT = 0.012

    def test_row_bbox_union_bleeds_into_neighboring_row(self):
        # This assertion documents the CONFIRMED root cause: on a dense
        # table, the padded union for NEUT# extends above its own row's
        # top far enough to overlap NRBC%'s row — exactly the reported bug.
        neut_hash = _row(self.NEUT_COUNT_TOP, height=self.ROW_HEIGHT)
        row = _union_row_bbox(neut_hash)
        assert row is not None
        _left, top, _width, _height = row
        nrbc_pct_bottom = self.NRBC_PCT_TOP + self.ROW_HEIGHT
        assert top < nrbc_pct_bottom, (
            "expected the historical padded union to bleed upward into the "
            "NRBC% row above — if this fails, the padding formula changed "
            "and this fixture's own premise needs revisiting"
        )

    def test_field_rects_for_neut_hash_never_reach_neighboring_rows(self):
        neut_hash = _row(self.NEUT_COUNT_TOP, height=self.ROW_HEIGHT)
        rects = _field_rects(neut_hash)
        assert rects is not None
        nrbc_pct_bottom = self.NRBC_PCT_TOP + self.ROW_HEIGHT
        for rect in rects:
            assert rect["y"] >= self.NEUT_COUNT_TOP
            assert rect["y"] >= nrbc_pct_bottom

    def test_field_rects_for_nrbc_count_do_not_overlap_nrbc_percent(self):
        nrbc_count = _row(self.NRBC_COUNT_TOP, height=self.ROW_HEIGHT)
        rects = _field_rects(nrbc_count)
        assert rects is not None
        nrbc_pct_top = self.NRBC_PCT_TOP
        for rect in rects:
            assert rect["y"] + rect["height"] <= nrbc_pct_top

    def test_field_rects_labels_are_present_and_ordered(self):
        row = _row(self.PCT_TOP, height=self.ROW_HEIGHT)
        rects = _field_rects(row)
        assert rects is not None
        assert [r["label"] for r in rects] == ["test_name", "value", "unit", "reference_range"]

    def test_field_rects_none_when_no_geometry(self):
        assert _field_rects([None, None, None, None]) is None
        assert _field_rects([]) is None

    def test_field_rects_excludes_stray_page_and_missing_fields(self):
        name = _evidence(0.10, 0.40, 0.20, 0.02, page=1)
        value = _evidence(0.45, 0.40, 0.08, 0.02, page=1)
        stray = _evidence(0.10, 0.05, 0.20, 0.02, page=2)

        rects = _field_rects([name, value, stray, None])
        assert rects is not None
        assert len(rects) == 2
        assert all(r["y"] >= 0.40 for r in rects)
