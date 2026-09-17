# Universal document ingestion — format capability matrix

This is the authoritative before/after record for the "BRAGI — UNIVERSAL
DOCUMENT INGESTION + ASK BRAGI STABLE LAYOUT" work. The single source of
truth for what Bragi accepts and how each format is handled is
`backend/app/services/ingestion/capability_registry.py`
(`FORMAT_CAPABILITIES`) — this document explains and records it, but the
registry itself is what the code actually consults.

## Root cause of the production DOCX failure

A real upload — `BRAGI_EXTERNATION_EXAMPLE.docx`, a Romanian hospital
discharge letter — was:

1. Accepted at the upload door (`.docx` was already in
   `ALLOWED_UPLOAD_EXTENSIONS`).
2. Sent, unchanged, to **Google Document AI** for OCR. `guess_mime_type()`
   (`app/services/google_document_ai_service.py`) had no `.docx` branch,
   so it fell through to `application/octet-stream` (or whatever
   `mimetypes.guess_type()` happened to return) — a MIME type Document
   AI's OCR/Form processors reject outright:
   `400 Request contains an invalid argument: raw_document.mime_type:
   Unsupported mime type`.
3. That failure returned `{"text": "", ...}` — silently, with only a
   `warnings` string never surfaced to classification.
4. `resolve_final_classification()` (`app/services/
   document_classification_service.py:95-96`) treated the empty string as
   "nothing to classify from" and returned the pre-existing Reducto/
   legacy fallback verbatim — in production, Reducto's own classification
   of the same file, which had also resolved to `other` at confidence
   `1.0`.

Net effect: `document_type=other`, `classification_source=reducto`,
`classification_confidence=1.0` — a value that looks like a confident,
deliberate semantic classification, but is actually the downstream
consequence of an extraction failure three layers away. Nothing in the
original code distinguished "we understood this document and it doesn't
match a canonical type" from "we never actually read it."

There was, and had never been, ANY per-format capability check before a
file reached Reducto or Google Document AI — confirmed by an exhaustive
grep of the pre-existing pipeline: it was "try Reducto (any file, any
format) → if needed, try Google Document AI (any file, any format) → if
needed, try the legacy keyword classifier (text only)," with real
branching only on document TYPE, never on document FORMAT.

## Format matrix — before this work

| Extension | Accepted at upload? | Extractor | OCR? | Structured parser? | Classification input |
|---|---|---|---|---|---|
| `.pdf` | Yes | Reducto / Google Document AI | Yes (scanned) | No | Real |
| `.png`/`.jpg`/`.jpeg`/`.webp`/`.tif`/`.tiff` | Yes | Google Document AI | Yes | No | Real |
| `.doc`/`.docx` | Yes | **None** — sent to Google Document AI anyway, which rejects it | Attempted, always fails | No | **Empty → silent "other"** |
| Everything else | No | — | — | — | — |

## Format matrix — after this work

One source of truth: `FORMAT_CAPABILITIES` in
`backend/app/services/ingestion/capability_registry.py`. Summarized:

| Extension | MIME | Magic bytes | Supported | Extractor | OCR required? | Structured parser | Viewer behavior | Provenance | Classification |
|---|---|---|---|---|---|---|---|---|---|
| `.pdf` | application/pdf | `%PDF-` | Yes | Reducto/Google Document AI (unchanged) | Scanned only | No | pdfjs | exact_bbox | Yes |
| `.png` | image/png | PNG sig | Yes | Google Document AI, EXIF/normalize first | Yes | No | image | page_only | Yes |
| `.jpg`/`.jpeg` | image/jpeg | JFIF sig | Yes | Google Document AI, EXIF/normalize first | Yes | No | image | page_only | Yes |
| `.webp` | image/webp | RIFF/WEBP | Yes | Google Document AI, EXIF/normalize first | Yes | No | image | page_only | Yes |
| `.tif`/`.tiff` | image/tiff | II*/MM* | Yes | Google Document AI, EXIF/normalize first | Yes | No | image | page_only | Yes |
| `.bmp` | image/bmp | `BM` | Yes | **Converted to PNG**, then Google Document AI | Yes | No | image | page_only | Yes |
| `.heic`/`.heif` | image/heic(f) | — (ISO-BMFF) | Yes | **Converted to PNG** (pillow-heif), then Google Document AI | Yes | No | image | page_only | Yes |
| `.docx` | OOXML wordprocessingml | zip (`PK`) | Yes | **python-docx — real local extraction** | **No** | Yes (paragraphs/tables/headers/footers) | derived_view | document_only | Yes |
| `.doc` | application/msword | OLE/CFB | **No** | — | — | — | download_only | none | No |
| `.rtf` | application/rtf | `{\rtf1` | Yes | **striprtf** | No | No | derived_view | document_only | Yes |
| `.odt` | opendocument.text | zip (`PK`) | Yes | **Direct content.xml parse (defusedxml)** | No | Yes | derived_view | document_only | Yes |
| `.txt` | text/plain | — | Yes | **Decode + bypass OCR** | No | No | text_preview | document_only | Yes |
| `.md` | text/markdown | — | Yes | **Decode + bypass OCR** | No | No | text_preview | document_only | Yes |
| `.csv` | text/csv | — | Yes | **stdlib csv** | No | Yes | table_preview | document_only | Yes |
| `.tsv` | tab-separated | — | Yes | **stdlib csv** | No | Yes | table_preview | document_only | Yes |
| `.xlsx` | spreadsheetml | zip (`PK`) | Yes | **openpyxl** (`data_only=True`) | No | Yes | table_preview | document_only | Yes |
| `.xls` | application/vnd.ms-excel | OLE/CFB | **No** | — | — | — | download_only | none | No |
| `.ods` | opendocument.spreadsheet | zip (`PK`) | Yes | **Direct content.xml parse (defusedxml)** | No | Yes | table_preview | document_only | Yes |
| `.json` | application/json | — | Yes | **FHIR/generic detection** | No | Yes | structured_preview | document_only | Yes |
| `.xml` | application/xml | — | Yes | **CDA/FHIR-XML/generic detection (defusedxml)** | No | Yes | structured_preview | document_only | Yes |
| `.hl7`/`.er7` | application/hl7-v2 | `MSH\|` | **No (deferred)** | Detected, explicitly rejected | — | — | download_only | none | No |
| `.dcm` | application/dicom | `DICM` @ offset 128 | **No (deliberate)** | Detected, explicitly rejected | — | — | download_only | none | No |
| exe/dll/bat/cmd/ps1/js/msi/apk/sh/jar/com/scr | — | — | Never accepted | — | — | — | — | — | — |
| zip/rar/7z/tar/gz | — | — | Never accepted (no safe archive-ingestion design this pass) | — | — | — | — | — | — |
| docm/xlsm/xltm/dotm | — | — | Never accepted (macro-enabled, regardless of content) | — | — | — | — | — | — |

## Extraction adapter per supported type

See `backend/app/services/ingestion/router.py` (`route_extraction()`) and
its `adapters/` package:

- `adapters/text_adapter.py` — `.txt`/`.md`, with an explicit encoding
  fallback chain (`utf-8-sig` → `utf-8` → `cp1250` → `iso-8859-2` →
  `latin-1`) rather than a new dependency.
- `adapters/office_text_adapter.py` — `.docx` (python-docx: paragraphs,
  tables, section headers/footers, best-effort heading detection),
  `.rtf` (striprtf), `.odt` (direct `content.xml` parse via defusedxml —
  deliberately not odfpy, a much larger dependency for what's
  structurally a small task).
- `adapters/spreadsheet_adapter.py` — `.csv`/`.tsv` (stdlib `csv`),
  `.xlsx` (openpyxl, `data_only=True` — formulas are read as their last
  cached value or not at all; openpyxl has no formula engine and can
  never execute one), `.ods` (direct `content.xml` parse, same reasoning
  as ODT).
- `adapters/structured_health_adapter.py` — `.json` (FHIR Bundle/resource
  detection via `resourceType`, else generic JSON), `.xml` (CDA/C-CDA
  root-element+namespace detection, FHIR-XML namespace detection, else
  generic XML — defusedxml throughout, XXE-safe).
- `adapters/image_adapter.py` — not a classifier; normalizes EXIF
  rotation (baked into pixels via `PIL.ImageOps.exif_transpose`) and
  converts HEIC/HEIF/BMP to PNG **before** the existing Google Document AI
  call, which is otherwise completely unchanged.
- PDF and (post-normalization) images: unchanged — the existing Reducto/
  Google Document AI pipeline, now only ever reached for formats it
  actually supports.

## Deliberately unsupported, and why

- **Legacy `.doc`/`.xls`** — binary OLE/CFB containers. No safe,
  dependency-light pure-Python extractor exists (the realistic options —
  `textract`-style wrappers — need an external system binary like
  `antiword`, which is out of scope for this pass as a new Docker image
  dependency). Explicitly rejected with a clear message directing the
  uploader to re-save as `.docx`/`.xlsx`/PDF, never silently OCR'd or
  marked `other`.
- **HL7 v2 (`.hl7`/`.er7`)** — detected (content starting with `MSH|`,
  after stripping a possible BOM/MLLP framing byte) and explicitly
  rejected with a message pointing at the human-readable report instead.
  The registry + router already have a named slot
  (`ExtractorKind.UNSUPPORTED_STUB`) for a real HL7 v2 adapter later —
  implementing real parsing now was judged likely to destabilize
  production for a format with no current real-world upload volume in
  this product; the architecture permits adding it cleanly without
  touching anything else.
- **DICOM (`.dcm`)** — detected via its real signature (`DICM` at byte
  offset 128) and explicitly, deliberately rejected. Bragi does not
  perform diagnostic image interpretation; imaging pixels are never sent
  to an LLM. A written radiology report is the correct upload instead.
- **Executables/scripts/installers/archives/macro-enabled Office
  formats** — never accepted at the upload door at all (see
  `EXPLICITLY_REJECTED_EXTENSIONS`); a strict allowlist, not a blocklist,
  so nothing new needs to be added to keep them out.

## Security (Part M)

- **Decompression-bomb guard** for every zip-based format (DOCX/XLSX/
  ODT/ODS): `app/services/ingestion/security.py::safe_open_zip()` refuses
  to parse further if total uncompressed size exceeds 200MB or the zip
  has more than 2000 internal entries — checked from the zip's own
  central directory, before any real decompression.
- **Macro detection**: the same function refuses any zip containing
  `word/vbaProject.bin` / `xl/vbaProject.bin` regardless of the file's
  own (non-macro) extension — "Office files are effectively containers;
  do not trust their extension."
- **Encrypted-document detection**: MS Office password-protection
  re-wraps the real zip in an OLE/CFB container — a `.docx`/`.xlsx`/`.odt`/
  `.ods` whose real first bytes are the OLE signature is reported as
  `ENCRYPTED` (a distinguishable status), never attempted as a corrupt
  zip.
- **Content/extension mismatch**: `router.looks_like_mislabeled_hl7_or_dicom()`
  checks any text-like upload's real bytes against HL7/DICOM signatures
  regardless of its claimed extension.
- **XXE prevention**: every direct XML parse in this module (ODT/ODS/
  CDA/generic-XML) goes through `defusedxml`, never the stdlib
  `xml.etree.ElementTree` directly.
- **Spreadsheet formulas**: openpyxl has no formula engine at all — a
  formula cell's value is either its last cached computed result or
  nothing; it is structurally impossible for this codebase to execute
  one.
- **Filename sanitization / path traversal**: already fully handled
  before this work — `_save_incoming_file()` (`app/api/routers/
  documents.py`) never uses the client-supplied filename on disk; every
  upload is stored under a fresh `uuid4().hex` + validated extension.
  Verified, not re-implemented.

## Never turn extraction failure into "other" (Part G)

`ExtractionStatus` (`app/services/ingestion/contract.py`) is the fixed,
small set every adapter and the router itself return:

- `LOCAL_TEXT` — a real local adapter ran; `text` may legitimately be
  empty (a genuinely blank document) — this is the ONLY status that
  reaches classification.
- `DEFER_TO_PROVIDER` — PDF/image; the existing Reducto/Google Document
  AI flow is entirely unchanged.
- `UNSUPPORTED_FORMAT` — a real, named format this codebase does not
  extract from (legacy `.doc`/`.xls`, HL7, DICOM, a content/extension
  mismatch) — a new `UploadJob.status` value (`"unsupported_format"`),
  never silently "other".
- `EXTRACTION_FAILED` — the format is supported in general but this
  specific file didn't parse (corrupt zip, malformed XML, a
  decompression-bomb shape, a macro project) — `UploadJob.status =
  "extraction_failed"`.
- `ENCRYPTED` — password-protected — `UploadJob.status = "encrypted"`.

None of these three terminal statuses ever reaches
`resolve_final_classification()` — `process_upload_job` (`app/main.py`)
returns immediately with the real status, message, and reason, before
Reducto/Google Document AI/the classifier are even considered for a
format they were never going to handle.

## No database migration

`UploadJob.status` and `Document`'s classification columns are already
plain `String` columns (see `app/models.py`) — the new status values
(`unsupported_format`, `extraction_failed`, `encrypted`) are additive
string values, not a schema change. No Alembic migration was needed or
added.
