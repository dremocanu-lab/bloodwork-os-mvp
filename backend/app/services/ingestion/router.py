"""DocumentExtractionRouter — the one place that decides, from a file's
real extension (never trusted MIME/Content-Type alone) and a registry
lookup, which extraction adapter handles an uploaded file.

    upload
      v
    security validation           (app/api/routers/documents.py — unchanged)
      v
    actual file-type detection    (Path(filename).suffix.lower(), same convention as _validate_upload_extension)
      v
    capability registry           (capability_registry.py)
      v
    extraction adapter            (route_extraction(), below)
         |- PDF / image     -> DEFER_TO_PROVIDER (existing Reducto/Google Document AI path, untouched)
         |- DOCX/RTF/ODT    -> adapters.office_text_adapter
         |- spreadsheet     -> adapters.spreadsheet_adapter
         |- text            -> adapters.text_adapter
         |- structured health -> adapters.structured_health_adapter
         `- unsupported     -> UNSUPPORTED_FORMAT (legacy .doc, HL7, DICOM, ...)
      v
    normalized extraction contract (contract.ExtractionResult)
      v
    semantic document classifier   (app/services/document_classification_service.py — unchanged)
      v
    canonical document pipeline    (unchanged)

Document CLASSIFICATION is never responsible for file-FORMAT parsing —
that split is the entire point of this module existing (see Part E of
the production-incident writeup this was built from: a `.docx` reaching
Google Document AI, which rejected its MIME type, used to silently
resolve to "the classifier says other" instead of a real, distinguishable
extraction failure).
"""

from __future__ import annotations

from pathlib import Path

from app.services.ingestion.capability_registry import ExtractorKind, get_capability
from app.services.ingestion.contract import ExtractionResult, ExtractionStatus
from app.services.ingestion.security import is_dicom, looks_like_hl7_v2


def route_extraction(file_path: Path, filename: str) -> ExtractionResult:
    """The router's single entry point. `filename` is the ORIGINAL
    uploaded name (used only to determine the extension — exactly the
    same `Path(filename).suffix.lower()` convention
    `_validate_upload_extension` already uses, never trusting a
    client-supplied Content-Type)."""
    extension = Path(filename).suffix.lower()
    capability = get_capability(extension)

    if capability is None:
        return ExtractionResult(
            status=ExtractionStatus.UNSUPPORTED_FORMAT,
            source_extension=extension,
            reason=f"'{extension or '(no extension)'}' is not a supported file type.",
        )

    mismatch_reason = looks_like_mislabeled_hl7_or_dicom(file_path, extension)
    if mismatch_reason:
        return ExtractionResult(status=ExtractionStatus.UNSUPPORTED_FORMAT, source_extension=extension, reason=mismatch_reason)

    if capability.extractor == ExtractorKind.OCR_PROVIDER:
        return ExtractionResult(status=ExtractionStatus.DEFER_TO_PROVIDER, source_extension=extension)

    if capability.extractor == ExtractorKind.UNSUPPORTED_STUB:
        return _handle_unsupported_stub(file_path, extension)

    if capability.extractor == ExtractorKind.OFFICE_TEXT:
        return _dispatch_office_text(file_path, extension)

    if capability.extractor == ExtractorKind.PLAIN_TEXT:
        from app.services.ingestion.adapters.text_adapter import extract_text_file

        return extract_text_file(file_path)

    if capability.extractor == ExtractorKind.SPREADSHEET:
        return _dispatch_spreadsheet(file_path, extension)

    if capability.extractor == ExtractorKind.STRUCTURED_HEALTH:
        return _dispatch_structured_health(file_path, extension)

    return ExtractionResult(
        status=ExtractionStatus.UNSUPPORTED_FORMAT,
        source_extension=extension,
        reason=f"'{extension}' is registered but has no handler — this is a configuration bug, not a real format limitation.",
    )


def _handle_unsupported_stub(file_path: Path, extension: str) -> ExtractionResult:
    if extension == ".doc":
        return ExtractionResult(
            status=ExtractionStatus.UNSUPPORTED_FORMAT,
            source_extension=extension,
            reason="Legacy Word 97-2003 (.doc) documents are not supported for text extraction. Please re-save this file as .docx or PDF and re-upload.",
        )

    if extension == ".xls":
        return ExtractionResult(
            status=ExtractionStatus.UNSUPPORTED_FORMAT,
            source_extension=extension,
            reason="Legacy Excel 97-2003 (.xls) files are not supported. Please re-save this file as .xlsx or .csv and re-upload.",
        )

    if extension in (".hl7", ".er7"):
        return ExtractionResult(
            status=ExtractionStatus.UNSUPPORTED_FORMAT,
            source_extension=extension,
            reason="HL7 v2 messages are detected but automated parsing isn't supported yet. Please upload the corresponding human-readable report instead.",
        )

    if extension == ".dcm":
        return ExtractionResult(
            status=ExtractionStatus.UNSUPPORTED_FORMAT,
            source_extension=extension,
            reason="DICOM/medical imaging files are not supported for upload — Bragi does not perform diagnostic image interpretation. Please upload the written radiology/report document instead.",
        )

    return ExtractionResult(status=ExtractionStatus.UNSUPPORTED_FORMAT, source_extension=extension, reason=f"'{extension}' is not supported.")


def _dispatch_office_text(file_path: Path, extension: str) -> ExtractionResult:
    from app.services.ingestion.adapters.office_text_adapter import extract_docx, extract_odt, extract_rtf

    if extension == ".docx":
        return extract_docx(file_path)
    if extension == ".rtf":
        return extract_rtf(file_path)
    if extension == ".odt":
        return extract_odt(file_path)
    return ExtractionResult(status=ExtractionStatus.UNSUPPORTED_FORMAT, source_extension=extension, reason=f"'{extension}' is not supported.")


def _dispatch_spreadsheet(file_path: Path, extension: str) -> ExtractionResult:
    from app.services.ingestion.adapters.spreadsheet_adapter import extract_csv, extract_ods, extract_xlsx

    if extension == ".csv":
        return extract_csv(file_path, delimiter=",")
    if extension == ".tsv":
        return extract_csv(file_path, delimiter="\t")
    if extension == ".xlsx":
        return extract_xlsx(file_path)
    if extension == ".ods":
        return extract_ods(file_path)
    return ExtractionResult(status=ExtractionStatus.UNSUPPORTED_FORMAT, source_extension=extension, reason=f"'{extension}' is not supported.")


def _dispatch_structured_health(file_path: Path, extension: str) -> ExtractionResult:
    from app.services.ingestion.adapters.structured_health_adapter import extract_json, extract_xml

    # A .json/.xml extension is trusted for dispatch (matches every other
    # format here), but content that turns out to actually be HL7 or
    # DICOM-adjacent binary data (a mislabeled extension) still fails
    # closed inside the adapter itself (JSONDecodeError / XML parse
    # error) rather than being silently misread.
    if extension == ".json":
        return extract_json(file_path)
    if extension == ".xml":
        return extract_xml(file_path)
    return ExtractionResult(status=ExtractionStatus.UNSUPPORTED_FORMAT, source_extension=extension, reason=f"'{extension}' is not supported.")


def looks_like_mislabeled_hl7_or_dicom(file_path: Path, extension: str) -> str | None:
    """Defense-in-depth for Part D/M's "extension and actual MIME/content
    disagree" requirement: a file uploaded with an allowed extension
    (e.g. renamed to .txt) whose actual BYTES are HL7 v2 or DICOM is still
    caught here rather than silently treated as plain text. Returns a
    human-readable reason if so, else None. Only checked for formats
    where this mismatch is plausible and cheap to detect (text-like
    formats); never assumes malice, just refuses to guess wrong."""
    if is_dicom(file_path):
        return "This file's content looks like DICOM medical imaging data, not the format its extension suggests — Bragi does not perform diagnostic image interpretation."
    if extension in {".txt", ".csv", ".tsv", ".md", ".xml", ".json"}:
        try:
            sample = file_path.open("rb").read(64)
        except OSError:
            return None
        if looks_like_hl7_v2(sample):
            return "This file's content looks like an HL7 v2 message, not the format its extension suggests — automated HL7 parsing isn't supported yet."
    return None
