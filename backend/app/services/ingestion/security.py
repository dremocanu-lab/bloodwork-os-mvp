"""Ingestion-specific security checks — see docs/ingestion/
FORMAT_CAPABILITY_MATRIX.md "Part M". Narrow, targeted checks for the NEW
format families this module adds; the pre-existing PDF/image checks
(size cap, magic bytes, the PDF-specific malware heuristic screen) in
app/api/routers/documents.py and app/services/security_scan.py are
untouched and still run first, before any of this.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

# A genuine clinical DOCX/XLSX/ODT/ODS is a small XML-in-zip document —
# tens of KB to a few MB uncompressed is normal. A zip that claims to
# uncompress to more than this is refused outright rather than parsed,
# regardless of what the outer file's compressed size was (the
# decompression-bomb shape: a tiny compressed file, an enormous claimed
# uncompressed size).
MAX_UNCOMPRESSED_ZIP_BYTES = 200 * 1024 * 1024  # 200MB
# A real clinical document's docx/xlsx/odt/ods has on the order of tens
# of internal zip entries (word/document.xml, styles, a few relationship
# files, maybe embedded images). An entry count far beyond that is itself
# a decompression-bomb/DoS shape (many tiny entries), independent of
# total uncompressed size.
MAX_ZIP_ENTRY_COUNT = 2000

# Real names inside an OOXML zip that indicate VBA macro content —
# present regardless of the file's own (non-macro) extension. A `.docx`/
# `.xlsx` that actually contains one of these is secretly macro-enabled
# and must be refused even though its extension claims otherwise —
# "Office files are effectively containers; do not trust their
# extension."
MACRO_INDICATOR_NAMES = frozenset({"word/vbaProject.bin", "xl/vbaProject.bin", "vbaProject.bin"})


class IngestionSecurityError(Exception):
    """Raised by these checks — always caught by the router and turned
    into ExtractionStatus.EXTRACTION_FAILED with a clean, non-alarming
    user-facing `reason`, never a raw stack trace."""


def safe_open_zip(file_path: Path) -> zipfile.ZipFile:
    """Opens a zip-based Office/ODF file (DOCX/XLSX/ODT/ODS) only after
    verifying it is not shaped like a decompression bomb and does not
    secretly contain a VBA macro project. Raises IngestionSecurityError
    (never a bare zipfile exception) on any violation."""
    try:
        archive = zipfile.ZipFile(file_path)
    except zipfile.BadZipFile as error:
        raise IngestionSecurityError("Not a valid Office/OpenDocument container (corrupt or not actually a zip).") from error

    infos = archive.infolist()

    if len(infos) > MAX_ZIP_ENTRY_COUNT:
        archive.close()
        raise IngestionSecurityError(f"Document contains an unreasonable number of internal parts ({len(infos)}).")

    total_uncompressed = sum(info.file_size for info in infos)
    if total_uncompressed > MAX_UNCOMPRESSED_ZIP_BYTES:
        archive.close()
        raise IngestionSecurityError(
            f"Document's uncompressed size ({total_uncompressed // (1024 * 1024)}MB) exceeds the safe limit "
            f"({MAX_UNCOMPRESSED_ZIP_BYTES // (1024 * 1024)}MB) — refusing to decompress further."
        )

    names = {info.filename for info in infos}
    if names & MACRO_INDICATOR_NAMES:
        archive.close()
        raise IngestionSecurityError("Document contains a macro project (VBA) — macro-bearing documents are not accepted.")

    return archive


def is_dicom(file_path: Path) -> bool:
    """DICOM's real signature: 128-byte preamble (any content, usually
    zeros), then the literal bytes "DICM" at offset 128 — never at the
    start of the file, so this can't be checked via the same simple
    prefix table documents.py uses for PDF/image formats."""
    try:
        with file_path.open("rb") as handle:
            handle.seek(128)
            return handle.read(4) == b"DICM"
    except OSError:
        return False


def looks_like_hl7_v2(sample: bytes) -> bool:
    """HL7 v2's segment-terminated ("pipe and hat") encoding always
    starts a message with an MSH segment — real messages may be preceded
    by a UTF-8 BOM or the (non-standard but seen in the wild) MLLP frame
    start byte (0x0b), so both are stripped before checking."""
    probe = sample.lstrip(b"\xef\xbb\xbf").lstrip(b"\x0b").lstrip()
    return probe.startswith(b"MSH|")
