"""Plain-text adapters: .txt / .md. Never OCR'd — decoded directly, with
a small, explicit encoding-fallback chain (never a new dependency just
for this: real hospital/lab text exports in this codebase's target
locale are UTF-8, UTF-8 with a BOM, or a Windows/DOS code page)."""

from __future__ import annotations

from pathlib import Path

from app.services.ingestion.contract import ExtractionResult, ExtractionStatus

# Tried in order; the first that decodes without error wins. cp1250 is
# the classic Windows code page for Central/Eastern European languages
# (Romanian included) — a real risk for an export from an older hospital
# system that never adopted UTF-8. latin-1 always succeeds (it maps every
# byte to SOME character) and is deliberately last — a real fallback of
# last resort, not a first guess that would silently mangle valid UTF-8.
_ENCODING_FALLBACKS = ("utf-8-sig", "utf-8", "cp1250", "iso-8859-2", "latin-1")


def decode_text_bytes(data: bytes) -> str:
    for encoding in _ENCODING_FALLBACKS:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    # latin-1 above never actually raises, so this is unreachable in
    # practice — kept as an explicit, honest last resort rather than
    # silently returning an empty string.
    return data.decode("latin-1", errors="replace")


def extract_text_file(file_path: Path) -> ExtractionResult:
    try:
        data = file_path.read_bytes()
    except OSError as error:
        return ExtractionResult(
            status=ExtractionStatus.EXTRACTION_FAILED,
            source_extension=file_path.suffix.lower(),
            reason=f"Could not read file: {error}",
        )

    text = decode_text_bytes(data).strip()
    blocks = [line for line in text.splitlines() if line.strip()]

    return ExtractionResult(
        status=ExtractionStatus.LOCAL_TEXT,
        text=text,
        blocks=blocks,
        source_extension=file_path.suffix.lower(),
        source_mime="text/markdown" if file_path.suffix.lower() == ".md" else "text/plain",
        extraction_provider="local_text",
    )
