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

- **Phase 1 — Reducto foundation + multi-file classification.** Provider
  abstraction, taxonomy, rule-based classifier, `needs_confirmation`
  flow, `/upload/batch`, confirmation UI. Done.
- **Phase 2 — Identity / duplicates / canonical data / provenance.** Done.
- **Phase 3 — Analize + source verification.** Done.
- **Phase 4 — Clinical readers.** Done — see §2c.
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

Phase boundaries may still shift as Phase 3+ reveals more about the real
Reducto contract and current DB scale — update this file when they do.

## 2a. Phase 2 — what was actually built

- **SHA-256 exact-duplicate detection** (`app/services/file_hash.py`):
  computed on every upload before any OCR/AI cost is spent; an identical
  file already on the *same patient's* record short-circuits the job to
  `status="duplicate"` pointing at the existing document — no second
  Document/LabResult set is ever created. Verified against the local dev
  DB with a live functional test (temporary patient/file, cleaned up
  after).
- **Patient identity check** (`app/services/patient_identity.py`):
  conservative rule-based comparator (CNP/patient_identifier exact match,
  name via token-overlap, DOB exact match) producing `matched` /
  `needs_confirmation` / `mismatch` / `insufficient_identity`. Blank
  patient fields are now backfilled from an uploaded document **only**
  when the check comes back `matched`/`insufficient_identity`/
  `matched_override` — previously (pre-Phase-2) any extracted identity
  silently overwrote blank fields with no check at all.
  - `mismatch` → the document is quarantined: `patient_id` is left NULL
    (so it's invisible to every existing patient-scoped query without
    auditing all of them — see below) and `intended_patient_id` +
    `review_status="quarantined"` record what happened, for review via
    `GET /documents/quarantined` + `POST /documents/{id}/identity-review`.
  - `needs_confirmation` → job pauses as `needs_identity_confirmation`
    (nothing persisted yet, same reprocess-from-scratch shortcut as
    classification `needs_confirmation`); resolved via
    `POST /upload-jobs/{id}/confirm-identity`. Confirming sets
    `UploadJob.identity_override` (audited) so the next run skips the
    check for that one job.
- **`SourceEvidence`** table: `document_id` + `lab_result_id` (nullable —
  generalizes beyond labs later) + page/bbox (all null for now, never
  fabricated) + `source_text` + confidence/provider/parser_version. Every
  lab row created in Phase 2 gets one populated with the raw
  name/value/unit/range as `source_text` — the "View original" flagship
  feature (Phase 3) has something to render even before real bbox
  coordinates exist.
- **Level-3 duplicate-observation linking**: within the same patient, a
  new lab row with an *exact* match on canonical test + observation date
  + value + unit is linked via `LabResult.duplicate_of_lab_result_id`
  instead of inserted as a second independent point; `SourceEvidence` for
  it attaches to the original row (multiple sources, one observation).
  The bloodwork-trends endpoint excludes linked duplicates so they don't
  plot twice. Deliberately exact-match-only — see "false merging is worse
  than conservative duplication."
- **Canonical/provenance columns added directly to `LabResult`** rather
  than a new `ClinicalObservation` table: `observation_datetime`,
  `institution`, `specimen`, `accession_id`, `verification_state`,
  `extraction_confidence`, `normalization_confidence`. `LabResult`
  already had the raw/canonical split (`raw_test_name` vs.
  `canonical_name`/`display_name`/`category`); a new table would have
  required migrating every existing Analize query for no real benefit at
  this stage. `specimen`/`accession_id` are schema-ready but not
  populated yet — nothing currently extracts them.
- **Discovered and fixed a pre-existing bug**, unrelated to this phase:
  `Document.is_verified` was declared `Integer` in the model but the live
  Postgres column is `boolean` — found because a functional test failed
  on it. Fixed by changing the model to `Boolean` (no migration needed,
  the DB column was already correct; only the Python declaration and the
  two `is_verified=0/1` write sites were wrong). Worth a quick check that
  production has the same drift.

### Deferred from the original Phase 2 spec

- **Level-2 semantic document-level duplicate matching** (institution +
  collection date + accession/specimen ID fingerprint): not implemented.
  Nothing in the current pipeline reliably extracts accession/specimen
  IDs yet, so a Level-2 heuristic would be guessing on missing data —
  higher false-merge risk than benefit right now. Revisit once Phase 3/4
  extraction is richer.
- **A dedicated patient-facing quarantine review page**: the backend
  (`GET /documents/quarantined`, `POST /documents/{id}/identity-review`)
  is done and covers the far more common in-upload-flow
  `needs_identity_confirmation` pause (handled inline, same pattern as
  classification confirmation). A standalone review page for the rarer
  `mismatch`/quarantine case is not built this phase — worth adding
  alongside Phase 4/5 UI work rather than as a one-off.
- **Auditing every `Document.patient_id ==` query site** (9 in
  `main.py`) for quarantine-awareness: unnecessary — quarantined
  documents get `patient_id = NULL`, so they're automatically invisible
  everywhere without touching those sites.

## 2b. Phase 3 — what was actually built

Structured Analize stays exactly as it was — this phase is additive
only, no replacement, per the hard requirement.

- **`GET /lab-results/{id}/source`**: returns every `SourceEvidence` row
  for a lab result (usually one; more if Level-3 linking attached
  evidence from a second document to the same observation). Same
  authorization pattern as the existing `/documents/{id}/file` route
  (`can_access_patient`, no care-partner access).
- **Row-level "View original"** in `frontend/app/documents/[id]/page.tsx`
  (a `LabSourceAction` component next to each lab row's flag): opens a
  dialog showing the exact raw text Bragi extracted for that value
  (`SourceEvidence.source_text`), with a button to open the full source
  file. This reuses the page's pre-existing `openOriginal()` (a
  document-level "View original" already existed — Phase 3 makes it
  row-specific).
- **No bbox/page-highlight** — honest limitation, not a placeholder bug.
  Real coordinate-level highlighting needs a Reducto Parse integration
  that hasn't been built (see §3). The source-text quote is the current
  best verifiable stand-in and is explicitly documented as such in code.
- Chart-point → source (labs Trends view) is **not** wired this phase —
  that lives with the rest of the chart system work in Phase 6, so it's
  built once against the final shared chart component rather than twice.

### Deferred from the original Phase 3 spec
- Bbox/coordinate highlighting (needs Reducto Parse — see §3).
- Chart-point → source (Phase 6, see above).
- A DB-backed test for `/lab-results/{id}/source`'s authorization — the
  route reuses the same `can_access_patient` pattern as the existing,
  already-relied-upon `/documents/{id}/file`, but wasn't given its own
  integration test (this repo has no TestClient/test-DB fixture
  convention yet — worth adding in Phase 7 if time allows).

## 2c. Phase 4 — what was actually built

Only `discharge_summary`/`bloodwork` had a real structured pipeline
before this phase. The other 6 taxonomy types (imaging, operative,
pathology, prescription, medication_list, specialist_consultation) had
none — a document of one of these types stored only raw OCR text with
no structure at all.

- **`backend/app/services/structured_reader_service.py`**: a
  conservative structured extractor for those 6 types, following the
  *exact same convention* as the existing `openai_discharge_service.py`
  (reads the source file directly via OpenAI's vision-capable Responses
  API, temperature 0, explicit "do not infer/fabricate — null if not
  present" instruction, JSON-only output). Per-type section key lists
  live in `SECTION_KEYS`; labels (EN/RO) live in the frontend's
  `lib/reader-sections.ts`, keyed identically.
- Wired into `process_upload_job`: runs once, after the document is
  created, only for the 6 new types; stored as
  `Document.structured_sections` (JSON). Best-effort — a missing
  `OPENAI_API_KEY` or a failed call never fails the upload; the Reader
  always still has `extracted_text` to fall back to.
- `GET /documents/{id}` (via the shared `get_document_payload`) now
  returns `document_type` and the parsed `structured_sections` object.
- **Frontend**: a new branch in `documents/[id]/page.tsx`'s existing
  ternary (alongside the note/discharge/edit branches, not a new route)
  renders each populated section as a labeled card when
  `document_type` is one of the 6 reader types and at least one section
  was extracted. Falls through to the existing default view otherwise —
  zero behavior change for bloodwork/other/未-extracted documents.
- **Found and fixed a second pre-existing issue** (like Phase 2's
  `is_verified`): `openai_discharge_service.py` constructed its `OpenAI`
  client eagerly at *module import time*, which raised whenever
  `OPENAI_API_KEY` wasn't set — even for code that only needed its MIME-
  detection helpers. Changed to the same lazy `_client()` pattern
  `ai_extract.py` already uses elsewhere in this codebase. No behavior
  change when the key *is* set (the only path production actually
  exercises); makes the module importable/testable without one.

### Deferred from the original Phase 4 spec
- **Outline / section navigation, document search, "30-second read",
  "what changed", "what happens next", conflict/uncertainty display**:
  none of this is built yet. The mega-spec's Phase 4 is realistically
  its own multi-week effort; what shipped is the foundation (source-
  grounded structured extraction + a place to display it) rather than
  the full Reader experience. Recommend a dedicated follow-up phase for
  these rather than a rushed version now.
- **Section-level "View original"**: `SourceEvidence` is currently only
  populated for structured lab rows (Phase 2/3). The reader sections
  above have no per-section evidence rows yet, so they rely on the
  existing document-level "Original" button rather than a per-section
  link. Extending `SourceEvidence` to non-lab entities was explicitly
  named as future work in Phase 2's design (`lab_result_id` is nullable
  for exactly this reason) — worth doing alongside outline/search.
- **Prescription/medication_list → `PatientMedication` linkage**: not
  built. A prescription's extracted `medications` section is currently
  just display text, not parsed into the medication system. That's a
  longitudinal-record concern, more natural for Phase 5.
- **A separate route per document type** (`/documents/{id}/imaging`,
  etc., mirroring the existing dedicated `/documents/{id}/discharge`):
  not built. One parameterized branch in the existing page was chosen
  instead, given the shared card-based layout was already sufficient and
  6 near-duplicate page files would have been pure risk for no display
  difference at this stage.

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
