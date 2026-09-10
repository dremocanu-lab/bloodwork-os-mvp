"""Tests for `_union_row_bbox` — the presentation-only "whole row" region
derived for laboratory SourceEvidence (see BRAGI_REDUCTO_PLAN.md).

This is real geometry math on real per-field citation bboxes (never a
guessed/hardcoded region), so it's tested as a pure function: given a set
of field bboxes (page-fraction floats in [0, 1], as Reducto returns them),
does the union + padding behave correctly, and does it correctly decline
to produce a region when there isn't enough real geometry to union.
"""

from app.services.reducto_extraction import ReductoEvidence, _union_row_bbox


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
