"""Slice a page range out of a source PDF into its own file.

Used for mixed-PDF handling: once Reducto Split (see `reducto_extraction.
split_file`) finds that a single upload actually contains several logical
documents, each section's pages are sliced into a standalone PDF and
uploaded to Reducto independently, reusing the exact same single-document
classify/extract code path already verified for a normal upload — rather
than guessing at an unverified "restrict extraction to a page range"
request parameter.

The ORIGINAL uploaded file is never modified or deleted — slices are
written as new files alongside it. Each child Document still points at
the original parent file for `saved_to` (see main.py), so "View original"
always opens the real source; the slice only exists to get Reducto a
clean single-section input.
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF — already a dependency (see discharge_summary_pipeline.py)


def slice_pdf_pages(source_path: Path, pages: list[int], output_dir: Path, suffix: str) -> Path:
    """`pages` is a 1-indexed, not-necessarily-contiguous list of page
    numbers (as returned by Reducto Split). Returns the path to a new PDF
    containing exactly those pages, in order."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{source_path.stem}__{suffix}.pdf"

    src = fitz.open(str(source_path))
    try:
        dest = fitz.open()
        try:
            for page_number in sorted(pages):
                dest.insert_pdf(src, from_page=page_number - 1, to_page=page_number - 1)
            dest.save(str(output_path))
        finally:
            dest.close()
    finally:
        src.close()

    return output_path
