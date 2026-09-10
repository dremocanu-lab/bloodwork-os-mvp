"""Regression tests for the page-number convention through the extraction
layer (see BRAGI_REDUCTO_PLAN.md's source-viewer page-isolation section).

Canonical convention, verified end to end against real Reducto API
responses for a real synthetic 2-page lab document: page numbers are
1-based everywhere — Reducto's own citation bbox ("page"/"original_page"),
the value stored as SourceEvidence.page_number, the frontend's
currentPage state, and PDF.js's getPage(pageNumber) all agree. No layer
converts to/from a 0-based index. These tests pin that down at the one
place page numbers first enter the system (`_field_evidence`) so a future
change can't silently introduce an off-by-one without a test failing.
"""

from app.services.reducto_extraction import _field_evidence


def _citation(page: int | None = None, original_page: int | None = None, **bbox_extra):
    bbox = {"left": 0.1, "top": 0.2, "width": 0.1, "height": 0.02}
    if page is not None:
        bbox["page"] = page
    if original_page is not None:
        bbox["original_page"] = original_page
    bbox.update(bbox_extra)
    return {"citations": [{"bbox": bbox, "content": "x", "confidence": "high"}]}


def test_page_number_passes_through_unchanged_no_arithmetic():
    # Real shape observed from a live Reducto Extract response (see the
    # commit message / plan doc for the captured transcript): both "page"
    # and "original_page" are 1 for a citation on the first page of a
    # document, never 0.
    evidence = _field_evidence(_citation(page=1, original_page=1))
    assert evidence is not None
    assert evidence.page == 1


def test_page_2_passes_through_as_2_not_1():
    evidence = _field_evidence(_citation(page=2, original_page=2))
    assert evidence is not None
    assert evidence.page == 2


def test_original_page_takes_priority_over_page():
    # original_page is what a split/multi-panel document's citation should
    # be trusted for (it's Reducto's own remapped value back to the source
    # document, distinct from a position within a temporary slice) - this
    # must never be silently overridden by a differing raw "page".
    evidence = _field_evidence(_citation(page=1, original_page=3))
    assert evidence.page == 3


def test_falls_back_to_page_when_original_page_absent():
    evidence = _field_evidence(_citation(page=5))
    assert evidence.page == 5


def test_no_citations_means_no_page_not_a_fabricated_zero():
    evidence = _field_evidence({"citations": []})
    assert evidence is None

    evidence2 = _field_evidence({"not_a_field": True})
    assert evidence2 is None
