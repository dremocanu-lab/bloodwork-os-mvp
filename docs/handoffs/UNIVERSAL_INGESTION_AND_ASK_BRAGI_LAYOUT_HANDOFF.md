# Handoff: Universal Document Ingestion + Ask Bragi Stable Layout

Branch: `fix/universal-ingestion-and-ask-bragi-layout`, from `main` @ `5a8f0ec`
(post CDI V3 merge + production Alembic bootstrap hotfix).

Full format-by-format detail lives in
`docs/ingestion/FORMAT_CAPABILITY_MATRIX.md` — this handoff summarizes the
session, the root causes, and the verification record.

## Part A — Production DOCX failure, reproduced and root-caused

A real upload, `BRAGI_EXTERNATION_EXAMPLE.docx` (a Romanian discharge
letter), was silently classified `document_type=other`,
`classification_source=reducto`, `confidence=1.0` instead of being
recognized as a discharge summary. Root cause (see the capability matrix
doc's own root-cause section for the full trace):

1. `google_document_ai_service.guess_mime_type()` had no `.docx` branch —
   it sent an unsupported MIME type to Google Document AI, which rejected
   it with `400 ... Unsupported mime type`.
2. `document_classification_service.resolve_final_classification()`
   treated the resulting empty extracted text as "nothing to classify
   from" and silently returned whatever pre-existing Reducto/legacy
   result there was (here, `other` at confidence 1.0) — with no way to
   distinguish "we understood this and it's genuinely other" from
   "extraction never actually happened."

Neither Reducto nor Google Document AI ever had a real per-format
capability check before this session — confirmed by an exhaustive trace
of the pipeline.

## Part E/F — Architecture introduced

`backend/app/services/ingestion/`:

- `capability_registry.py` — `FORMAT_CAPABILITIES`, the one source of
  truth for every extension Bragi accepts (extension, MIME(s), magic
  bytes, `supported`, extractor kind, OCR-required, structured-parser,
  viewer behavior, provenance quality, classification-supported).
  `app/api/routers/documents.py`'s `ALLOWED_UPLOAD_EXTENSIONS`/
  `UPLOAD_MAGIC_BYTES` are now DERIVED from it.
- `contract.py` — `ExtractionResult`/`ExtractionStatus`, the normalized
  contract every adapter returns (`LOCAL_TEXT` / `DEFER_TO_PROVIDER` /
  `UNSUPPORTED_FORMAT` / `EXTRACTION_FAILED` / `ENCRYPTED`).
- `router.py` — `route_extraction()`, the `DocumentExtractionRouter`.
  Classification is never responsible for file-format parsing — this is
  the one place that decides which adapter (if any) handles a file.
- `security.py` — decompression-bomb guard + macro detection for zip-
  based Office formats, DICOM/HL7 signature detection.
- `adapters/` — `text_adapter.py` (TXT/MD), `office_text_adapter.py`
  (DOCX/RTF/ODT), `spreadsheet_adapter.py` (CSV/TSV/XLSX/ODS),
  `structured_health_adapter.py` (JSON/XML, FHIR/CDA detection),
  `image_adapter.py` (EXIF rotation + HEIC/HEIF/BMP normalization before
  the EXISTING Google Document AI call).

**Wiring** (surgical, not a rewrite):

- `ocr_service.extract_text()` now consults the router FIRST — every
  existing call site (both OCR passes in `main.py`,
  `document_pipeline.py`'s final-extraction call) benefits automatically.
  PDF/image behavior is completely unchanged; it's simply never reached
  for a format that has a real local extractor now.
- `main.py::process_upload_job`'s `AUTO_CLASSIFY_SECTION` branch now
  checks `route_extraction()` before Reducto/Google Document AI. A
  `LOCAL_TEXT` result classifies directly from that real text (bypassing
  Reducto/OCR entirely for these formats — Part H: never pay for/depend
  on OCR for machine-readable text); a terminal status
  (`UNSUPPORTED_FORMAT`/`EXTRACTION_FAILED`/`ENCRYPTED`) sets a real,
  distinguishable `UploadJob.status` and returns immediately, never
  reaching classification. The existing Reducto/legacy/AI classification
  code for PDF/image is preserved **verbatim**, just nested one level
  deeper.
- `discharge_summary_pipeline.py::_render_pages_from_file` gained one new
  branch: a native-text format (DOCX/RTF/ODT/TXT/spreadsheet/structured-
  health) becomes a single synthetic "page" carrying the real extracted
  text as `native_text` (already preferred over the placeholder image
  whenever present — same "digital PDF has a text layer" code path this
  pipeline already had).
- `GET /upload/capabilities` (new endpoint) serializes the registry for
  the frontend.

## Part G — extraction failure never becomes "other"

`UploadJob.status` gains three new values —
`unsupported_format`/`extraction_failed`/`encrypted` — all plain strings
on an existing `String` column, **no migration**. Confirmed via
`python scripts/check_migration_drift.py` (clean) after this session's
changes.

## Part N — frontend upload UX

New `frontend/lib/upload-capabilities.ts` (`useUploadCapabilities()`)
fetches `GET /upload/capabilities` once (cached, fail-open to a fixed
fallback matching the backend's own list) and drives:

- `app/my-records/upload/page.tsx`
- `app/patients/[id]/upload/page.tsx`
- `app/care-partner/upload/page.tsx` (previously the only one with a
  hardcoded, narrower `accept` list — now consistent with the other two)

Support copy for both pages now describes what's actually supported
(PDF/Word/images/spreadsheets/health exports) instead of the previous
"PDFs, images, and scanned reports" text, which undersold what the
`<input>` itself already silently accepted.

## Part O — source viewer

Investigated in full. The Phase 8 clinical reader's `ReaderSourceAction`
(`components/clinical-reader/reader-source-action.tsx`) **already**
implements exactly the honesty pattern Part O asks for: a non-PDF
document's source action degrades to a "Source text" label instead of a
broken/blank PDF.js viewer — a deliberate, pre-existing "V3 contract"
rule, not something this session added. New formats (DOCX/spreadsheet/
JSON/XML) don't produce field-level `source_evidence` bboxes at all
(consistent with their `provenance_quality: document_only` in the
registry), so `sourceEvidenceId` is `null` for facts extracted from them
and the reader correctly shows "Source unavailable" — never a fake or
broken viewer.

**Known, pre-existing, separate gap NOT fixed this session**: the OLDER
shared `source-viewer-context.tsx`/`source-viewer-panel.tsx` (used by
older/non-Phase-8 lab citation flows) unconditionally assumes every
document is a PDF and feeds raw bytes straight to PDF.js — an image
opened this way would fail. This predates this session, is independent
of the new format work (images already went through Google Document AI
successfully before this session; this is a VIEWING gap, not an
extraction one), and building a real multi-format viewer into that
older component was judged out of scope for this pass (Part Q: no reader
redesign). Flagged here for a future, dedicated pass.

## Part P — Ask Bragi layout bug, root cause and fix

**Reported symptom**: the dedicated Ask Bragi page's conversation surface
is wide before submitting, collapses into a narrow card while pending
("Checking your record…"), then expands again once the answer arrives.

**First hypothesis (wrong, corrected via actual measurement)**: the
assistant bubble's own `alignSelf: "flex-start"` (shrink-to-fit) looked
like the obvious cause, and was fixed
(`components/ask-bragi/ask-bragi-chat.tsx`) — but an automated Playwright
measurement of the fix showed the container itself still collapsed to
251px (from 760px), proving the real bug was one level up.

**Real root cause**: `.b-stack`'s inline style
(`ask-bragi-chat.tsx`) set `maxWidth` + `margin: "0 auto"` but never an
explicit `width`. A flex/grid item with `width: auto` and horizontal
auto-margins is sized by CSS **shrink-to-fit** (its content's max-content
width, clamped by `maxWidth`) — not "stretch to the available track,
then clamp." The idle EmptyState's long description text has a wide
max-content width (hits the 760px cap, looks stable); the pending
state's only content is the short "Checking your record…" label, whose
tiny max-content width shrunk the WHOLE container down to it.

**Fix**: added `width: compact ? undefined : "100%"` alongside the
existing `maxWidth` — makes the box's width `min(760px, its grid track)`
regardless of content, eliminating shrink-to-fit entirely. Kept the
bubble-level `alignSelf: "stretch"` fix too (belt-and-suspenders — the
bubble itself no longer shrink-to-fits inside the now-stable container).

**Verified via a real Playwright measurement**
(`frontend/e2e/ask-bragi-layout-stability.spec.ts`, new): mocks the
streaming endpoint with `page.route()` and an artificial delay (no
OPENAI_API_KEY needed) to create a real, deterministic "pending, no
answer text yet" window, then compares bounding-box widths across idle/
pending/completed at both desktop (1440x900) and mobile (390x844)
viewports — within a 4px tolerance. Confirmed the naive bubble-only fix
was insufficient BEFORE landing the real fix (debug instrumentation
showed the exact 760px → 251px container collapse), then confirmed the
real fix resolves it. Existing `ask-bragi-workspace.spec.ts` and
`right-workspace-geometry.spec.ts` suites re-run clean (no regression to
the first-message lifecycle fix or the panel-height fix).

## Part Q — no regression

No reader redesign, no Phase 11, no Emergency V2, no narrative
highlighting. Existing CDI (StructuredClinicalDocument, Clinical Course,
embedded labs, medications, Timeline projection, source evidence, exact
field bboxes, document router, Romanian classification, manual type
selection, semantic AI classifier, upload status reliability, Ask Bragi,
authorization boundaries) untouched except where explicitly described
above (all additive/surgical).

## Bugs found and fixed during this session's OWN verification

- `image_adapter.normalize_image_for_ocr()`: `PIL.ImageOps.exif_transpose()`
  always returns a NEW image object (never the same instance) even when
  no rotation is needed — an `is` identity check incorrectly treated
  every image as needing normalization. Fixed to check the real EXIF
  orientation tag value instead. Caught by `test_ingestion_image_adapter.py`.
- `main.py::process_upload_job`: a pre-existing local `from
  app.services.extraction_provider import LegacyExtractionProvider`
  inside the `except ReductoError` block shadowed this session's new
  module-level import for the ENTIRE function (Python's function-level
  name scoping), causing `UnboundLocalError` on the new LOCAL_TEXT
  branch (which runs earlier in the function than that local import).
  Fixed by removing the now-redundant local import. Caught by
  `test_ingestion_docx_regression.py`.
- The Ask Bragi layout bug's real root cause (`.b-stack` shrink-to-fit,
  not the bubble's own alignment) was only found by building automated
  measurement into the fix loop rather than trusting the first
  (plausible-looking, CSS-spec-consistent, but WRONG) hypothesis.

## Test matrix (Part R)

| Format | Accepted? | Adapter | Extraction result | Classifier result | Notes |
|---|---|---|---|---|---|
| PDF (native text) | Yes | Reducto/Google Document AI (unchanged) | Deferred to provider | Unchanged | Not modified this session |
| PDF (scanned) | Yes | Reducto/Google Document AI (unchanged) | Deferred to provider | Unchanged | Not modified this session |
| DOCX (Romanian discharge fixture) | Yes | `office_text_adapter.extract_docx` | `LOCAL_TEXT`, real text | `discharge_summary`, source=`local_extraction`, confidence 1.0 | **The regression fixture** — `test_ingestion_docx_regression.py` |
| TXT | Yes | `text_adapter` | `LOCAL_TEXT` | Same as equivalent DOCX (cross-format test) | Bypasses OCR entirely |
| JPG/PNG/TIFF | Yes | Google Document AI (unchanged) | Deferred to provider | Unchanged | EXIF normalization added, untested against a real Document AI call (no credential in this environment) |
| Rotated JPEG | Yes | `image_adapter` (EXIF transpose) | Rotation baked into pixels, verified via `Image.open(...).size` | N/A | `test_ingestion_image_adapter.py` |
| CSV (lab-shaped) | Yes | `spreadsheet_adapter` | `LOCAL_TEXT`, real table | `laboratory_results` | `test_ingestion_router.py` |
| CSV (unrelated) | Yes | `spreadsheet_adapter` | `LOCAL_TEXT`, real table | NOT `laboratory_results` | Proves Part K |
| XLSX | Yes | `spreadsheet_adapter` (openpyxl) | `LOCAL_TEXT`, sheet name + rows | — | Formula cells proven never executed |
| JSON (FHIR Bundle) | Yes | `structured_health_adapter` | `LOCAL_TEXT`, `detected_format=fhir` | — | |
| JSON (generic) | Yes | `structured_health_adapter` | `LOCAL_TEXT`, `detected_format=generic_json` | — | Never assumed FHIR |
| XML (CDA) | Yes | `structured_health_adapter` | `LOCAL_TEXT`, `detected_format=cda` | — | |
| XML (generic) | Yes | `structured_health_adapter` | `LOCAL_TEXT`, `detected_format=generic_xml` | — | |
| `.exe`/`.dll`/`.bat`/`.js`/`.zip`/`.docm` | **No** | — | Rejected at upload door | — | Strict allowlist, never reaches the router |
| Corrupt DOCX (not a real zip) | Yes (upload), fails processing | `office_text_adapter` | `EXTRACTION_FAILED` | Never reached | |
| Mismatched extension (HL7 content as `.txt`) | Yes (upload), fails processing | router content-sniff | `UNSUPPORTED_FORMAT` | Never reached | |
| Encrypted (OLE-wrapped) `.docx` | Yes (upload), fails processing | `office_text_adapter` | `ENCRYPTED` | Never reached | |
| Legacy `.doc`/`.xls` | Yes (upload), fails processing | `router._handle_unsupported_stub` | `UNSUPPORTED_FORMAT` | Never reached | Clear re-save message |
| HL7 (`.hl7`/`.er7`) | Yes (upload), fails processing | stub | `UNSUPPORTED_FORMAT` | Never reached | Deferred, architecture permits a real adapter later |
| DICOM (`.dcm`) | Yes (upload), fails processing | stub | `UNSUPPORTED_FORMAT` | Never reached | Deliberately, permanently rejected |
| Zip-bomb-shaped DOCX | Yes (upload), fails processing | `security.safe_open_zip` | `EXTRACTION_FAILED` | Never reached | 250MB claimed uncompressed, refused before decompression |
| Macro-bearing `.docx` | Yes (upload), fails processing | `security.safe_open_zip` | `EXTRACTION_FAILED` | Never reached | `vbaProject.bin` present despite non-macro extension |

## Full verification results

- Backend: **see FINAL REPORT** (pytest/Bandit/migration-drift run
  fresh, after the `UnboundLocalError` fix, at the end of this session).
- Frontend: TypeScript clean, production build clean, ESLint 29/30
  baseline (unchanged).
- New Playwright suite: `ask-bragi-layout-stability.spec.ts` (2/2,
  desktop + mobile). Existing `ask-bragi-workspace.spec.ts` (3/3),
  `right-workspace-geometry.spec.ts` (2/2) re-run clean.

## Deferred (explicitly, per this task's own scope)

- Real HL7 v2 parsing (detection + clean rejection only — architecture
  has a named slot for a real adapter later).
- Real DICOM metadata/report extraction (deliberately, permanently
  rejected — Bragi does not perform diagnostic imaging interpretation).
- Legacy `.doc`/`.xls` real extraction (no safe pure-Python path without
  a new external system-binary dependency).
- The older shared PDF.js-only source viewer's lack of a real image
  rendering path (pre-existing, separate from this session's format
  work — see Part O above).
- No Phase 11, no reader redesign, no narrative highlighting, no
  Emergency V2 — untouched, per explicit instruction.
