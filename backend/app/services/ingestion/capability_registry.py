"""FileCapabilityRegistry — the ONE source of truth for which upload
extensions Bragi accepts and how each is handled. See docs/ingestion/
FORMAT_CAPABILITY_MATRIX.md for the full before/after matrix this was
built from.

Every other piece of upload/extraction code should consult this registry
rather than hand-rolling its own extension list:

- `app/api/routers/documents.py`'s `ALLOWED_UPLOAD_EXTENSIONS` /
  `UPLOAD_MAGIC_BYTES` are DERIVED from this module (see that file) —
  never maintained as a second, independent list.
- `app/services/ingestion/router.py`'s `route_extraction()` looks up a
  `FormatCapability` by extension to decide which adapter (if any) to
  call.
- `GET /upload/capabilities` (documents.py) serializes this registry for
  the frontend, so the upload picker's allowed types and support copy can
  never silently drift from what the backend actually does.

Adding a new format means adding ONE entry here — never scattering a new
extension check across the router, the upload endpoint, and the
frontend independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExtractorKind(str, Enum):
    OCR_PROVIDER = "ocr_provider"  # PDF / raster image — existing Reducto/Google Document AI path, unchanged
    OFFICE_TEXT = "office_text"  # DOCX / RTF / ODT — local, real text extraction
    PLAIN_TEXT = "plain_text"  # TXT / MD — decode + bypass OCR entirely
    SPREADSHEET = "spreadsheet"  # CSV / TSV / XLSX / ODS — parse tabular structure directly
    STRUCTURED_HEALTH = "structured_health"  # XML / JSON — detect FHIR/CDA/generic, local parse
    UNSUPPORTED_STUB = "unsupported_stub"  # legacy .doc / HL7 / DICOM — detected, explicitly rejected
    NONE = "none"  # not accepted at all (should never reach a router lookup)


@dataclass(frozen=True)
class FormatCapability:
    extension: str  # includes leading "." — e.g. ".docx"
    mime_types: tuple[str, ...]
    magic_bytes: tuple[bytes, ...] | None  # None if this format has no simple prefix signature
    supported: bool  # False for formats we accept at the door but never extract from (legacy .doc, HL7, DICOM)
    extractor: ExtractorKind
    ocr_required: bool
    structured_parser: bool
    viewer_behavior: str  # short label — see docs/ingestion/FORMAT_CAPABILITY_MATRIX.md "viewer behavior" column
    provenance_quality: str  # "exact_bbox" | "page_only" | "document_only" | "none"
    classification_supported: bool
    notes: str = ""


# Zip-container signature shared by every OOXML/ODF format (DOCX, XLSX,
# ODT, ODS are all, structurally, a ZIP file with a particular internal
# XML layout) — see security.py's zip-bomb/macro checks, which run for
# every one of these before any real parsing.
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_MAGIC = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)  # legacy .doc/.xls (OLE/CFB container)
_DICOM_MAGIC = (b"DICM",)  # at byte offset 128 — checked specially, see security.py

FORMAT_CAPABILITIES: dict[str, FormatCapability] = {
    ".pdf": FormatCapability(
        extension=".pdf",
        mime_types=("application/pdf",),
        magic_bytes=(b"%PDF-",),
        supported=True,
        extractor=ExtractorKind.OCR_PROVIDER,
        ocr_required=True,  # only when the PDF is scanned/mixed — native-text PDFs already extract cheaply via the existing Reducto/PyMuPDF paths
        structured_parser=False,
        viewer_behavior="pdfjs",
        provenance_quality="exact_bbox",
        classification_supported=True,
        notes="Unchanged by this rework — existing Reducto/Google Document AI/PyMuPDF pipeline.",
    ),
    **{
        ext: FormatCapability(
            extension=ext,
            mime_types=mimes,
            magic_bytes=magic,
            supported=True,
            extractor=ExtractorKind.OCR_PROVIDER,
            ocr_required=True,
            structured_parser=False,
            viewer_behavior="image",
            provenance_quality="page_only",
            classification_supported=True,
            notes="EXIF-rotation-normalized before OCR — see adapters/image_adapter.py.",
        )
        for ext, mimes, magic in [
            (".png", ("image/png",), (b"\x89PNG\r\n\x1a\n",)),
            (".jpg", ("image/jpeg",), (b"\xff\xd8\xff",)),
            (".jpeg", ("image/jpeg",), (b"\xff\xd8\xff",)),
            (".webp", ("image/webp",), (b"RIFF",)),
            (".tif", ("image/tiff",), (b"II*\x00", b"MM\x00*")),
            (".tiff", ("image/tiff",), (b"II*\x00", b"MM\x00*")),
            (".bmp", ("image/bmp",), (b"BM",)),
            (".heic", ("image/heic",), None),  # ISO-BMFF box format — no simple fixed-offset prefix
            (".heif", ("image/heif",), None),
        ]
    },
    ".docx": FormatCapability(
        extension=".docx",
        mime_types=("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
        magic_bytes=_ZIP_MAGIC,
        supported=True,
        extractor=ExtractorKind.OFFICE_TEXT,
        ocr_required=False,
        structured_parser=True,
        viewer_behavior="derived_view",
        provenance_quality="document_only",
        classification_supported=True,
        notes="python-docx: paragraphs, tables, headers/footers.",
    ),
    ".doc": FormatCapability(
        extension=".doc",
        mime_types=("application/msword",),
        magic_bytes=_OLE_MAGIC,
        supported=False,
        extractor=ExtractorKind.UNSUPPORTED_STUB,
        ocr_required=False,
        structured_parser=False,
        viewer_behavior="download_only",
        provenance_quality="none",
        classification_supported=False,
        notes="Legacy binary OLE format — no safe pure-Python extraction available; explicitly rejected with a clear message, never silently 'other'.",
    ),
    ".rtf": FormatCapability(
        extension=".rtf",
        mime_types=("application/rtf", "text/rtf"),
        magic_bytes=(b"{\\rtf1",),
        supported=True,
        extractor=ExtractorKind.OFFICE_TEXT,
        ocr_required=False,
        structured_parser=False,
        viewer_behavior="derived_view",
        provenance_quality="document_only",
        classification_supported=True,
        notes="striprtf.",
    ),
    ".odt": FormatCapability(
        extension=".odt",
        mime_types=("application/vnd.oasis.opendocument.text",),
        magic_bytes=_ZIP_MAGIC,
        supported=True,
        extractor=ExtractorKind.OFFICE_TEXT,
        ocr_required=False,
        structured_parser=True,
        viewer_behavior="derived_view",
        provenance_quality="document_only",
        classification_supported=True,
        notes="Minimal direct content.xml parse (defusedxml) — no odfpy dependency.",
    ),
    ".txt": FormatCapability(
        extension=".txt",
        mime_types=("text/plain",),
        magic_bytes=None,
        supported=True,
        extractor=ExtractorKind.PLAIN_TEXT,
        ocr_required=False,
        structured_parser=False,
        viewer_behavior="text_preview",
        provenance_quality="document_only",
        classification_supported=True,
    ),
    ".md": FormatCapability(
        extension=".md",
        mime_types=("text/markdown", "text/plain"),
        magic_bytes=None,
        supported=True,
        extractor=ExtractorKind.PLAIN_TEXT,
        ocr_required=False,
        structured_parser=False,
        viewer_behavior="text_preview",
        provenance_quality="document_only",
        classification_supported=True,
    ),
    ".csv": FormatCapability(
        extension=".csv",
        mime_types=("text/csv",),
        magic_bytes=None,
        supported=True,
        extractor=ExtractorKind.SPREADSHEET,
        ocr_required=False,
        structured_parser=True,
        viewer_behavior="table_preview",
        provenance_quality="document_only",
        classification_supported=True,
    ),
    ".tsv": FormatCapability(
        extension=".tsv",
        mime_types=("text/tab-separated-values",),
        magic_bytes=None,
        supported=True,
        extractor=ExtractorKind.SPREADSHEET,
        ocr_required=False,
        structured_parser=True,
        viewer_behavior="table_preview",
        provenance_quality="document_only",
        classification_supported=True,
    ),
    ".xlsx": FormatCapability(
        extension=".xlsx",
        mime_types=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
        magic_bytes=_ZIP_MAGIC,
        supported=True,
        extractor=ExtractorKind.SPREADSHEET,
        ocr_required=False,
        structured_parser=True,
        viewer_behavior="table_preview",
        provenance_quality="document_only",
        classification_supported=True,
        notes="openpyxl, data_only=True (formula results, never formula execution).",
    ),
    ".xls": FormatCapability(
        extension=".xls",
        mime_types=("application/vnd.ms-excel",),
        magic_bytes=_OLE_MAGIC,
        supported=False,
        extractor=ExtractorKind.UNSUPPORTED_STUB,
        ocr_required=False,
        structured_parser=False,
        viewer_behavior="download_only",
        provenance_quality="none",
        classification_supported=False,
        notes="Legacy binary OLE spreadsheet — same reasoning as .doc; not accepted (not previously advertised either, so no backward-compat reason to accept it).",
    ),
    ".ods": FormatCapability(
        extension=".ods",
        mime_types=("application/vnd.oasis.opendocument.spreadsheet",),
        magic_bytes=_ZIP_MAGIC,
        supported=True,
        extractor=ExtractorKind.SPREADSHEET,
        ocr_required=False,
        structured_parser=True,
        viewer_behavior="table_preview",
        provenance_quality="document_only",
        classification_supported=True,
        notes="Minimal direct content.xml parse (defusedxml) — no odfpy dependency.",
    ),
    ".json": FormatCapability(
        extension=".json",
        mime_types=("application/json",),
        magic_bytes=None,
        supported=True,
        extractor=ExtractorKind.STRUCTURED_HEALTH,
        ocr_required=False,
        structured_parser=True,
        viewer_behavior="structured_preview",
        provenance_quality="document_only",
        classification_supported=True,
        notes="Detects FHIR (resourceType/Bundle) vs. generic JSON — never assumes all JSON is FHIR.",
    ),
    ".xml": FormatCapability(
        extension=".xml",
        mime_types=("application/xml", "text/xml"),
        magic_bytes=None,
        supported=True,
        extractor=ExtractorKind.STRUCTURED_HEALTH,
        ocr_required=False,
        structured_parser=True,
        viewer_behavior="structured_preview",
        provenance_quality="document_only",
        classification_supported=True,
        notes="defusedxml (XXE-safe). Detects CDA/C-CDA (ClinicalDocument root) vs. FHIR-XML vs. generic XML.",
    ),
    ".hl7": FormatCapability(
        extension=".hl7",
        mime_types=("application/hl7-v2", "text/plain"),
        magic_bytes=(b"MSH|",),
        supported=False,
        extractor=ExtractorKind.UNSUPPORTED_STUB,
        ocr_required=False,
        structured_parser=False,
        viewer_behavior="download_only",
        provenance_quality="none",
        classification_supported=False,
        notes="DEFERRED, not implemented — detected and explicitly rejected rather than OCR'd or silently 'other'. Architecture (this registry + router) already has a slot for a real HL7 v2 adapter later.",
    ),
    ".er7": FormatCapability(
        extension=".er7",
        mime_types=("application/hl7-v2", "text/plain"),
        magic_bytes=(b"MSH|",),
        supported=False,
        extractor=ExtractorKind.UNSUPPORTED_STUB,
        ocr_required=False,
        structured_parser=False,
        viewer_behavior="download_only",
        provenance_quality="none",
        classification_supported=False,
        notes="Same as .hl7 — ER7 is HL7 v2's pipe-and-hat encoding, just a different conventional extension.",
    ),
    ".dcm": FormatCapability(
        extension=".dcm",
        mime_types=("application/dicom",),
        magic_bytes=_DICOM_MAGIC,  # checked at byte offset 128, not the start — see security.py
        supported=False,
        extractor=ExtractorKind.UNSUPPORTED_STUB,
        ocr_required=False,
        structured_parser=False,
        viewer_behavior="download_only",
        provenance_quality="none",
        classification_supported=False,
        notes="Explicitly rejected — Bragi does not perform diagnostic imaging interpretation. Never sent to any LLM/OCR provider.",
    ),
}

# Formats NEVER accepted at the upload door at all — executables, scripts,
# installers, generic archives, macro-enabled Office formats. Extensions,
# not full capability entries: these never reach the router because
# `_validate_upload_extension` (documents.py) rejects them before any file
# is even saved. Listed here (rather than only implicitly by omission)
# so there is one explicit, auditable, named list of what's deliberately
# excluded — see docs/ingestion/FORMAT_CAPABILITY_MATRIX.md "Part D".
EXPLICITLY_REJECTED_EXTENSIONS = frozenset(
    {
        ".exe", ".dll", ".bat", ".cmd", ".ps1", ".js", ".msi", ".apk", ".sh", ".jar", ".com", ".scr",
        ".zip", ".rar", ".7z", ".tar", ".gz",  # no deliberate safe archive-ingestion design in this pass
        ".docm", ".xlsm", ".xltm", ".dotm",  # macro-enabled Office — never accepted regardless of content
    }
)


def get_capability(extension: str) -> FormatCapability | None:
    """extension must already be lowercased with a leading dot (see
    Path(filename).suffix.lower(), the same convention documents.py's own
    `_validate_upload_extension` uses)."""
    return FORMAT_CAPABILITIES.get(extension)


def allowed_upload_extensions() -> frozenset[str]:
    """Every extension the upload door should accept — derived from this
    registry alone. Includes `supported=False` entries (legacy .doc, HL7,
    DICOM): those are accepted at the door but cleanly rejected during
    processing with a real explanation (Part C7/C8's explicit
    requirement), never a generic 400 at upload time."""
    return frozenset(FORMAT_CAPABILITIES.keys())


def capability_matrix_for_api() -> list[dict]:
    """Serializable form for GET /upload/capabilities — see
    documents.py. Never includes magic byte values (implementation
    detail, not useful to a client) or anything secret."""
    return [
        {
            "extension": cap.extension,
            "mime_types": list(cap.mime_types),
            "supported": cap.supported,
            "ocr_required": cap.ocr_required,
            "structured_parser": cap.structured_parser,
            "viewer_behavior": cap.viewer_behavior,
            "classification_supported": cap.classification_supported,
        }
        for cap in FORMAT_CAPABILITIES.values()
    ]
