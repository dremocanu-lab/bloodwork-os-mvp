# Bragi + Reducto: Automatic Medical Record Organization

Living plan for turning Bragi from "pick a folder, upload a file" into
"upload everything, Bragi organizes it, every fact stays traceable to its
source." Adapted from the original spec to this repository's actual
architecture (FastAPI + SQLAlchemy + Postgres, Next.js App Router,
ECharts). See `CLAUDE_HANDOFF.md` for current status — this file is the
architecture and phase reference, not a log.

## 0. What already existed (inspected before Phase 1)

- **No formal migration tool.** Schema changes live in `run_migrations()`
  at the top of `backend/app/main.py`, executed on every app start:
  idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `CREATE TABLE
  IF NOT EXISTS` via raw SQL. This phase follows that convention rather
  than introducing Alembic — revisit only if migrations grow materially
  more complex.
- **Multi-file selection UI already existed.** `frontend/components/
  upload-provider.tsx` (`useUploadManager`) already uploads each
  selected file as its own request and tracks independent per-file
  status (queued/uploading/processing/done/error), polling
  `/upload-jobs`. What was missing was per-file *content-based*
  classification — the whole batch previously shared one manually-picked
  `section`.
- **No document classification of any kind.** `Document.section` /
  `UploadJob.section` is a fixed 6-value enum (`bloodwork,
  discharge_summary, medications, scans, hospitalizations, other`)
  chosen by the user via a dropdown before upload. Only `bloodwork` and
  `discharge_summary` have real structured pipelines
  (`document_pipeline.py`, `discharge_summary_pipeline.py`); everything
  else is stored with an empty parsed payload.
- **`LabResult` already separates raw vs. canonical** (`raw_test_name`
  vs. `canonical_name`/`display_name`/`category`) — a head start on the
  Phase 2 canonical-observation work.
- **No SourceEvidence / bbox provenance model at all.**
- **No SHA-256 or any duplicate detection.**
- **Patient identity handling is naive**: extracted metadata only fills
  *blank* patient fields; there is no mismatch/wrong-patient detection
  today. This is a real gap Phase 2 needs to close.
- **No backend test suite existed** (no pytest config, no tests
  directory). Phase 1 adds one (unit-only; DB-backed tests need Phase 2
  fixtures).
- **No Reducto MCP connector was available this session.** Everything
  Reducto-shaped in Phase 1 is an abstraction + disabled stub, not a
  tested integration. See "Reducto integration status" below.

## 1. Architecture

```
DocumentExtractionProvider (backend/app/services/extraction_provider.py)
    |-- LegacyExtractionProvider   "legacy_rules" keyword classifier — always on
    `-- ReductoExtractionProvider  disabled until REDUCTO_ENABLED=true + REDUCTO_API_KEY
```

`get_extraction_provider()` resolves `DOCUMENT_EXTRACTION_PROVIDER` (env,
default `legacy`), falling back to `DOCUMENT_EXTRACTION_FALLBACK` (default
`legacy`) when the requested provider isn't enabled — and reports whether
a fallback happened (`classification_source` becomes
`"<provider>_fallback"`), so a silent Reducto outage never masquerades as
a real Reducto result.

Taxonomy (`backend/app/services/document_taxonomy.py`) defines the 16
Bragi document types from the spec and maps each one to one of the
*existing* 6 legacy `section` values, so every current route, filter,
and page keeps working unchanged. `document_type` (new) rides alongside
`section` (unchanged) rather than replacing it. As dedicated pipelines
for more types appear (Phase 3+), only this mapping needs to change.

```
Upload (per file)
  -> AUTO_CLASSIFY_SECTION sentinel section
  -> OCR text pass (existing ocr_service.extract_text, reused)
  -> provider.classify(text) -> ClassificationResult
  -> status: classified | needs_confirmation | other
       classified/other -> map to legacy section, continue existing pipeline
       needs_confirmation -> UploadJob.status = "needs_confirmation", STOP
                              (resumes via POST /upload-jobs/{id}/confirm-type)
```

## 2. Phases (adapted from the original 7-phase spec)

- **Phase 1 — Reducto foundation + multi-file classification (this
  phase).** Provider abstraction, taxonomy, rule-based classifier,
  `needs_confirmation` flow, `/upload/batch`, confirmation UI. Done —
  see status below.
- **Phase 2 — Identity / duplicates / canonical data / provenance.**
  SHA-256 exact-duplicate detection, patient identity mismatch +
  quarantine, `ClinicalObservation` (raw + canonical) evolving
  `LabResult`, `SourceEvidence` (document/page/bbox/text), audit
  expansion, DB-backed test fixtures (first tests that need a DB).
- **Phase 3 — Analize + source verification.** Wire the real Reducto
  Parse/Extract (once implemented) into the *existing* Analize pipeline
  without replacing it; persist full parsed content once per document
  (closes the Phase 1 double-OCR shortcut, see Known issues); "View
  original" + bbox highlight.
- **Phase 4 — Clinical readers.** Discharge/imaging/operative/pathology/
  prescription/consultation readers, responsive Reader/Original split,
  outline, document search, uncertainty/conflict display.
- **Phase 5 — Longitudinal / Timeline / organization.** Structured facts
  feed Timeline/medications; automatic grouping by medical meaning.
- **Phase 6 — Chart system.** Shared ECharts theme/components, honest
  reference ranges, chart-point → source.
- **Phase 7 — Full integration / responsive QA.**

Phase boundaries may still shift as Phase 2+ reveals more about the real
Reducto contract and current DB scale — update this file when they do.

## 3. Reducto integration status (important)

**No Reducto MCP connector was available in this environment**, and no
`REDUCTO_API_KEY` was provided, so:

- `ReductoExtractionProvider` is a **disabled stub** — `is_enabled()`
  is always `False` unless both `REDUCTO_ENABLED=true` and
  `REDUCTO_API_KEY` are set, and `classify()` raises `NotImplementedError`
  even then (no HTTP calls have been written or tested against Reducto's
  actual Classify/Split/Parse response shapes).
- Nothing in this phase was validated against the live Reducto API.
  Before flipping `DOCUMENT_EXTRACTION_PROVIDER=reducto` in any
  environment: (1) get a Reducto API key, (2) re-check current Reducto
  docs for the Classify/Split/Parse/Extract request+response contract,
  (3) implement `ReductoExtractionProvider.classify()` (and later
  `split`/`parse`/`extract`) against that contract, (4) test with the
  Reducto MCP if it becomes available, or directly against the API
  otherwise, (5) only then set `REDUCTO_ENABLED=true` in an environment
  you control.
- Until then, classification is done by `LegacyExtractionProvider` — a
  conservative keyword-rule classifier (`document_classifier.py`), which
  is deliberately named `"legacy_rules"` everywhere (env, DB, audit logs)
  so it is never confused with a real Reducto result.

## 4. Classification design

- Rule-based: RO+EN keyword/phrase lexicon per taxonomy type
  (`_KEYWORDS` in `document_classifier.py`), scored by weighted
  substring hits after accent-stripping/lowercasing (reuses
  `app.synonyms.normalize_text` for consistency with the rest of the
  codebase).
- `classified`: best score ≥ threshold and clearly ahead of the runner-up
  → auto-accept, no user interaction.
- `needs_confirmation`: real signal for 2+ plausible types with no clear
  winner → the *only* case that shows the confirm dialog. One ambiguous
  file never blocks the rest of a batch (each file is its own
  `UploadJob`/background task).
- `other`: no meaningful signal (empty/garbled OCR, or truly unrecognized
  content) → filed as `other` automatically, no popup. This is
  deliberately different from `needs_confirmation`: "we don't know but
  it's not urgent" vs. "we see real conflicting evidence."
- Confidence is a heuristic score in `[0, 1]`, **not a calibrated
  probability** — documented as such in code so it's never read as more
  precise than it is.

## 5. Multi-file batch upload

- `POST /upload/batch` (`files: list[UploadFile]`, optional
  `patient_id`) — one request, independent `UploadJob` + background task
  per file, no `section` accepted (always auto-classified). Existing
  single-file endpoints (`/upload/background`, `/upload`) are untouched
  and still require an explicit `section` — zero behavior change for
  doctor upload / care-partner upload / any other caller.
- `POST /upload-jobs/{id}/confirm-type` — the only way to resolve a
  `needs_confirmation` job; validates the chosen type against the
  taxonomy, sets `classification_source="user_confirmed"`, re-dispatches
  `process_upload_job` (which now sees an explicit `section` and skips
  re-classification).
- `GET /document-types` — taxonomy choices (value + EN/RO labels) for the
  confirmation UI.
- Frontend: `frontend/app/my-records/upload/page.tsx` rewritten (no
  manual "document type" selector); `upload-provider.tsx` gained
  `enqueueAutoClassifyUploads` / `confirmDocumentType` additively —
  `enqueueUploads` (used by doctor/care-partner upload pages) is
  unchanged.

## 6. Known issues / deliberate shortcuts (Phase 1)

- **Double OCR on auto-classified files.** Classification runs its own
  `ocr_service.extract_text()` pass on content that
  `process_uploaded_document`/`process_uploaded_discharge_summary` OCRs
  *again* right after. Accepted for Phase 1 to avoid restructuring the
  existing pipeline functions' signatures under time pressure; Phase 3
  ("persist parsed content once") is the natural point to fix this by
  threading one cached extraction through both steps.
- **No real Reducto testing** — see section 3.
- **Confirmation flow re-runs the whole job from scratch** (including a
  second OCR pass) rather than resuming from cached intermediate state.
  Simpler and safer than partial-state caching; revisit if reprocessing
  cost becomes material.
- **`/upload-jobs/{id}/confirm-type` authorization** is uploader-or-admin
  only for now (matches the single upload flow this phase touched);
  doctor/care-partner batch upload + confirmation is not wired up yet.
- Backend tests are unit-only (taxonomy/classifier/provider) — nothing
  DB-backed yet, since there's no fixture/test-DB convention in this repo
  yet. First DB-backed tests should land with Phase 2 (identity/dedup),
  which needs DB fixtures anyway.

## 7. Acceptance criteria — Phase 1

- [x] A patient can select multiple files in one picker action and
      upload once (`POST /upload/batch`).
- [x] Each file is classified independently from its *content* (not
      filename) using the legacy_rules classifier.
- [x] High-confidence files process automatically with no user
      interaction.
- [x] Only genuinely ambiguous files show a confirmation prompt; other
      files in the same batch are unaffected.
- [x] Files with no clear signal file as "Other" without blocking or
      prompting.
- [x] A meaningless (`scan001.pdf`) or misleading (`labs.pdf` containing
      a discharge summary) filename does not affect classification.
- [x] Existing single-file upload endpoints/pages (doctor upload,
      care-partner upload) are behaviorally unchanged.
- [x] Reducto stays fully disabled by default in every environment;
      flipping it on requires both an explicit flag and a key that isn't
      set anywhere in this repo.
- [x] No secrets or PHI fixtures committed (see `CLAUDE_HANDOFF.md`).
- [ ] Real end-to-end test through live OCR/AI providers (Google
      Document AI / OpenAI) — not run this phase; it would spend real
      API quota, and needs to be run locally by the maintainer. Unit
      tests + a full `app.main` import against the local dev DB (with
      the new `ADD COLUMN IF NOT EXISTS` migrations applied and
      verified) stand in for it this phase.
