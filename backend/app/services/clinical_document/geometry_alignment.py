"""Conservative alignment between the OpenAI vision pipeline's own
transcribed segment text and PyMuPDF's independently-extracted native
paragraph blocks (`source_geometry.py`) — Source Geometry + Clinical
Table Intelligence V3, Part 9.

Two different systems produced two different representations of the
SAME page: the vision model transcribed clinical prose into a segment
(narrative-quality, but with no geometry), and PyMuPDF extracted real
paragraph blocks from the PDF's own text layer (real geometry, but raw/
unformatted). This module answers, conservatively: "which of PyMuPDF's
own blocks, if any, correspond to this segment's text?" — and refuses
to answer at all when it isn't confident, per this task's own explicit
rule: "Never attach geometry to a clinical fact when alignment is
ambiguous... fall back to page-level."

This NEVER edits, re-derives, or "corrects" segment text using the
PyMuPDF block text — the vision transcription remains authoritative for
what the document SAYS; this module only ever attaches WHERE it is.
"""

from __future__ import annotations

from app.services.lab_catalog import normalize_text

from .source_geometry import BlockGeometry, PageGeometry

# A block covering less than this fraction of its own text actually
# found inside the segment is too weak a signal to trust — avoids a
# short, generic block (e.g. a lone "EPICRIZĂ" heading fragment)
# spuriously "matching" nearly any narrative segment that happens to
# contain a common word.
_MIN_BLOCK_CONTAINMENT_RATIO = 0.7

# The combined matched blocks must account for at least this fraction
# of the segment's own normalized length — otherwise the match is
# treated as too partial to be a confident paragraph-level citation.
_MIN_SEGMENT_COVERAGE_RATIO = 0.5


def align_segment_to_blocks(segment_text: str, page_geometry: PageGeometry | None) -> list[BlockGeometry]:
    """Returns the real PyMuPDF block(s) that together correspond to
    `segment_text`, in page (reading) order — empty when there is no
    confident match, INCLUDING when `page_geometry` itself is `None`
    (a scanned page with no native text layer, or a page geometry
    extraction was never attempted for it). Never raises, never
    fabricates a block that doesn't correspond to real text."""
    if not page_geometry or not page_geometry.blocks:
        return []

    normalized_segment = normalize_text(segment_text)
    if not normalized_segment:
        return []

    # Case 1: the segment text is (almost) entirely contained within
    # ONE PyMuPDF block (the common case — a segment is usually a single
    # paragraph that PyMuPDF also extracted as a single block, possibly
    # with a slightly different string due to transcription vs. raw
    # extraction differences in whitespace/OCR artifacts).
    best_single: BlockGeometry | None = None
    best_single_ratio = 0.0
    for block in page_geometry.blocks:
        normalized_block = normalize_text(block.text)
        if not normalized_block:
            continue
        if normalized_block in normalized_segment or normalized_segment in normalized_block:
            shorter = min(len(normalized_block), len(normalized_segment))
            longer = max(len(normalized_block), len(normalized_segment))
            ratio = shorter / longer if longer else 0.0
            if ratio > best_single_ratio:
                best_single_ratio = ratio
                best_single = block
    if best_single is not None and best_single_ratio >= _MIN_BLOCK_CONTAINMENT_RATIO:
        return [best_single]

    # Case 2: the segment is a longer narrative that PyMuPDF split
    # across SEVERAL consecutive blocks (e.g. multiple short lines that
    # render as separate blocks). Collect every block whose own text is
    # substantially contained within the segment, in page order, and
    # only accept the match if the blocks TOGETHER cover a real majority
    # of the segment — a scattering of a few incidentally-matching short
    # blocks never counts as a confident multi-block match.
    matched: list[BlockGeometry] = []
    covered_chars = 0
    for block in page_geometry.blocks:
        normalized_block = normalize_text(block.text)
        if not normalized_block:
            continue
        if normalized_block in normalized_segment:
            matched.append(block)
            covered_chars += len(normalized_block)

    if matched and covered_chars / len(normalized_segment) >= _MIN_SEGMENT_COVERAGE_RATIO:
        return matched

    return []
