"""The normalized extraction contract every adapter in
app/services/ingestion/adapters/ returns — see docs/ingestion/
FORMAT_CAPABILITY_MATRIX.md and DocumentExtractionRouter (router.py)'s own
module docstring for the full architecture this belongs to.

The downstream classifier/pipeline code should never need to know whether
`text` came from a PDF, a DOCX, a spreadsheet, or an OCR pass over a
JPEG — that is the entire point of this contract existing.

ExtractionStatus is the answer to the one thing this whole ingestion
rework exists to fix: "extraction failed" must never be silently
collapsed into "the classifier said other." Every adapter (and the
router itself) picks exactly one of these — never invents a new ad hoc
string — so every caller can `match`/compare against a fixed, small enum
instead of guessing at string values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExtractionStatus(str, Enum):
    # A local adapter (DOCX/RTF/ODT/TXT/MD/CSV/TSV/XLSX/ODS/detected
    # structured-health XML or JSON) ran and produced a normalized result
    # — `text` may still legitimately be empty (a genuinely blank
    # document), which is different from a FAILURE to extract.
    LOCAL_TEXT = "local_text"
    # This format needs a remote OCR/understanding provider (PDF, raster
    # images) — the router deliberately did nothing itself; the existing
    # Reducto/Google Document AI call sites remain responsible for it,
    # completely unchanged.
    DEFER_TO_PROVIDER = "defer_to_provider"
    # A real, named format this codebase does not (yet, or ever) extract
    # text from — legacy .doc, HL7 v2, DICOM, or any extension not in the
    # capability registry at all. Never attempted, never silently "other".
    UNSUPPORTED_FORMAT = "unsupported_format"
    # The file's format IS supported in general, but this specific file
    # could not be opened/parsed (corrupt zip, truncated file, malformed
    # XML, a zip-bomb-shaped Office file, a macro-bearing Office file,
    # content that doesn't match its extension, ...).
    EXTRACTION_FAILED = "extraction_failed"
    # The file is password-protected/encrypted and this codebase has no
    # credential to open it.
    ENCRYPTED = "encrypted"


@dataclass
class ExtractionResult:
    status: ExtractionStatus
    # Plain, flattened text — always populated for LOCAL_TEXT (possibly
    # empty for a genuinely blank document), always "" otherwise.
    text: str = ""
    # Ordered logical blocks (paragraphs/cells/lines), each a plain string
    # — coarser than `pages`/`tables`, useful for adapters that don't have
    # a real page concept (DOCX, spreadsheets, text files).
    blocks: list[str] = field(default_factory=list)
    # Populated only when the source format has a real page concept
    # (currently unused by the local adapters below; reserved for a future
    # PDF-adapter migration onto this same contract).
    pages: list[dict[str, Any]] = field(default_factory=list)
    # Spreadsheet/table adapters: list of {sheet, headers, rows}.
    tables: list[dict[str, Any]] = field(default_factory=list)
    # Section/heading hints an adapter could confidently detect (e.g. a
    # DOCX heading style, or a spreadsheet's sheet names) — best-effort,
    # never required downstream.
    sections: list[str] = field(default_factory=list)
    language_hint: str | None = None
    source_mime: str | None = None
    source_extension: str | None = None
    extraction_provider: str = "local_extraction"
    warnings: list[str] = field(default_factory=list)
    # Reserved for a source format with real page/box geometry — every
    # local adapter below leaves this empty; PDF/image OCR provenance is
    # untouched by this rework and keeps its own existing shape.
    page_geometry: list[dict[str, Any]] = field(default_factory=list)
    # Adapter-specific structured payload — the parsed workbook rows, the
    # detected FHIR/CDA document, etc. Never required downstream; a
    # forward-looking hook for a later phase, never inspected by
    # classification today.
    structured_payload: dict[str, Any] | None = None
    # A short, human-readable, non-PHI reason — set for UNSUPPORTED_FORMAT/
    # EXTRACTION_FAILED/ENCRYPTED, always safe to show the uploader.
    reason: str | None = None

    def to_legacy_ocr_dict(self) -> dict[str, Any]:
        """Shape-compatible with the dict `app.services.ocr_service.
        extract_text()` has always returned — see that module. Existing
        callers that only read `.get("text")`/`.get("warnings")` keep
        working unchanged; the new `status`/`reason` keys are additive."""
        return {
            "text": self.text,
            "plain_text": self.text,
            "lines_text": "\n".join(self.blocks) if self.blocks else self.text,
            "table_text": "",
            "tables": self.tables,
            "lines": [],
            "words": [],
            "method": self.extraction_provider,
            "warnings": self.warnings or [],
            "status": self.status.value,
            "reason": self.reason,
        }
