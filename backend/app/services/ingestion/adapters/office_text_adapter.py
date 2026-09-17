"""Word-processing document adapters: .docx (python-docx), .rtf
(striprtf), .odt (a minimal, dependency-light direct content.xml parse —
see its own docstring below for why not odfpy).

DOCX/ODT are zip containers — every extraction here goes through
security.safe_open_zip() first (decompression-bomb size/entry-count
guard, macro-project detection) before any real parsing, and a file that
turns out to be an OLE/CFB container despite its .docx/.odt extension
(exactly how MS Office password-protects a document — it re-wraps the
real zip in an encrypted OLE structure) is reported as ENCRYPTED, not a
generic parse failure.
"""

from __future__ import annotations

from pathlib import Path

from defusedxml import ElementTree as DefusedET

from app.services.ingestion.contract import ExtractionResult, ExtractionStatus
from app.services.ingestion.security import IngestionSecurityError, safe_open_zip

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _looks_encrypted_office(file_path: Path) -> bool:
    try:
        with file_path.open("rb") as handle:
            return handle.read(8) == _OLE_MAGIC
    except OSError:
        return False


def extract_docx(file_path: Path) -> ExtractionResult:
    if _looks_encrypted_office(file_path):
        return ExtractionResult(
            status=ExtractionStatus.ENCRYPTED,
            source_extension=".docx",
            reason="This Word document appears to be password-protected — Bragi cannot open encrypted documents. Please remove the password and re-upload.",
        )

    try:
        safe_open_zip(file_path).close()  # bomb/macro guard only; python-docx does its own real parsing below
    except IngestionSecurityError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".docx", reason=str(error))

    try:
        import docx  # python-docx
    except ImportError:
        return ExtractionResult(
            status=ExtractionStatus.EXTRACTION_FAILED,
            source_extension=".docx",
            reason="DOCX text extraction is not available in this environment.",
        )

    try:
        document = docx.Document(str(file_path))
    except Exception as error:  # noqa: BLE001 — any of python-docx's own parse errors, surfaced cleanly
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".docx", reason=f"Could not read this Word document: {error}")

    blocks: list[str] = []
    sections: list[str] = []

    for section in document.sections:
        for paragraph in section.header.paragraphs:
            if paragraph.text.strip():
                blocks.append(paragraph.text.strip())

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        blocks.append(text)
        # Heading styles (python-docx exposes the style name, e.g.
        # "Heading 1") are the only reliable, low-effort structural signal
        # available without a much deeper OOXML walk — best-effort only.
        style_name = (paragraph.style.name if paragraph.style else "") or ""
        if style_name.lower().startswith("heading"):
            sections.append(text)

    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                blocks.append(" | ".join(cells))

    for section in document.sections:
        for paragraph in section.footer.paragraphs:
            if paragraph.text.strip():
                blocks.append(paragraph.text.strip())

    text = "\n".join(blocks).strip()

    return ExtractionResult(
        status=ExtractionStatus.LOCAL_TEXT,
        text=text,
        blocks=blocks,
        sections=sections,
        source_extension=".docx",
        source_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extraction_provider="local_docx",
        warnings=[] if text else ["No text content found in this Word document."],
    )


def extract_rtf(file_path: Path) -> ExtractionResult:
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        return ExtractionResult(
            status=ExtractionStatus.EXTRACTION_FAILED,
            source_extension=".rtf",
            reason="RTF text extraction is not available in this environment.",
        )

    try:
        raw = file_path.read_bytes().decode("latin-1")  # RTF is ASCII-structured; non-ASCII text is \uNNNN-escaped
    except OSError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".rtf", reason=f"Could not read file: {error}")

    try:
        text = rtf_to_text(raw).strip()
    except Exception as error:  # noqa: BLE001 — a genuinely malformed RTF control-word stream
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".rtf", reason=f"Could not parse this RTF document: {error}")

    blocks = [line.strip() for line in text.splitlines() if line.strip()]

    return ExtractionResult(
        status=ExtractionStatus.LOCAL_TEXT,
        text=text,
        blocks=blocks,
        source_extension=".rtf",
        source_mime="application/rtf",
        extraction_provider="local_rtf",
        warnings=[] if text else ["No text content found in this RTF document."],
    )


# ODF text namespace — real, fixed URI from the OpenDocument spec, never
# guessed; matched by local-name (`}p`) below so a document declaring the
# same namespace under a different prefix is still handled correctly.
_ODF_TEXT_LOCAL_NAMES = {"p", "h"}  # <text:p> paragraphs, <text:h> headings


def extract_odt(file_path: Path) -> ExtractionResult:
    """A minimal, direct content.xml parse — deliberately NOT odfpy (a
    much larger, less-audited dependency for what's structurally a small
    task: ODT/ODS are just a zip with one real XML file to read text
    out of). defusedxml guards against XXE the same way the structured-
    health XML adapter does."""
    if _looks_encrypted_office(file_path):
        return ExtractionResult(
            status=ExtractionStatus.ENCRYPTED,
            source_extension=".odt",
            reason="This OpenDocument file appears to be password-protected — Bragi cannot open encrypted documents.",
        )

    try:
        archive = safe_open_zip(file_path)
    except IngestionSecurityError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".odt", reason=str(error))

    try:
        with archive:
            try:
                content_xml = archive.read("content.xml")
            except KeyError:
                return ExtractionResult(
                    status=ExtractionStatus.EXTRACTION_FAILED,
                    source_extension=".odt",
                    reason="This file doesn't contain a recognizable OpenDocument content.xml — it may not really be an ODT file.",
                )
    except Exception as error:  # noqa: BLE001 — a corrupt member inside an otherwise-valid zip
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".odt", reason=f"Could not read this document: {error}")

    try:
        root = DefusedET.fromstring(content_xml)
    except Exception as error:  # noqa: BLE001 — malformed XML
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".odt", reason=f"Could not parse this document's contents: {error}")

    blocks: list[str] = []
    sections: list[str] = []

    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1] if "}" in element.tag else element.tag
        if local_name not in _ODF_TEXT_LOCAL_NAMES:
            continue
        text = "".join(element.itertext()).strip()
        if not text:
            continue
        blocks.append(text)
        if local_name == "h":
            sections.append(text)

    text = "\n".join(blocks).strip()

    return ExtractionResult(
        status=ExtractionStatus.LOCAL_TEXT,
        text=text,
        blocks=blocks,
        sections=sections,
        source_extension=".odt",
        source_mime="application/vnd.oasis.opendocument.text",
        extraction_provider="local_odt",
        warnings=[] if text else ["No text content found in this OpenDocument file."],
    )
