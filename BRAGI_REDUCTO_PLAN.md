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
- **Phase 4 — Clinical readers.** Done.
- **Phase 5 — Longitudinal / Timeline / document organization.** Done.
- **Phase 6 — Chart system.** Done.
- **Phase 7 — Full integration / responsive QA.** Done — see §2f.
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

## 2d. Phase 5 — what was actually built

Inspection found more pre-existing groundwork here than the original
spec assumed: the "PCP timeline", "My Records timeline", and doctor
patient-timeline pages already group documents under hospital-admission
"parent" events by date range (an admission's CT/labs/discharge already
nest under it) — a real, working answer to "episodes of care" grouping,
just not named that. Phase 5 therefore focused on the actual gap:
**every document/timeline event was labeled only by the coarse legacy
`section` (6 buckets), never by Bragi's Phase-1+ `document_type`** (16
types) — so an imaging report and an operative report both just read
"Scan"/"Hospitalization".

- **`serialize_document_card`** (used by every document-list endpoint)
  and **`get_document_payload`** (Phase 3 already added it there) now
  both include `document_type`.
- **`frontend/components/clinical-timeline.tsx`** (the one shared
  timeline-row component used by 4 pages) gained an optional
  `documentType` field on `TimelineItem`; its category label now prefers
  `document_type` over the section-based fallback when present — a
  single change that improved every page using it at once.
- **`frontend/lib/document-taxonomy-labels.ts`** (new): EN/RO labels for
  all 16 taxonomy values, mirroring the backend's
  `DOCUMENT_TYPE_LABELS`. Used by the timeline component and by the "My
  Records" documents table's row subtitle.
- **Backend PCP-workspace timeline** (`_event_type_for` /
  `_DOC_SUMMARY_BY_EVENT_TYPE` in `main.py`): `event_type` now prefers
  `document.document_type` over the old `_SECTION_EVENT_TYPE` section
  map, with per-type summaries extended to cover the new taxonomy values
  (operative, pathology, prescription, consultation, etc.) that
  previously all fell through to a generic "source document" line.
- Every change here is **additive and backward-compatible**: documents
  uploaded before Phase 1 (no `document_type`) fall back to exactly the
  previous section-based label/behavior. No existing page's navigation,
  tabs, or grouping structure changed.

### Deferred from the original Phase 5 spec
- **Restructuring the top-level document organization** (grouping by
  the full 16-type taxonomy instead of the 6 legacy `section` buckets in
  tab/filter navigation, e.g. on "My Records"): not done. These are
  mature, heavily-used, 1700-line pages; re-plumbing their primary
  grouping/navigation model was judged higher-risk than the value it
  would add on top of the label-level fix already shipped, given the
  remaining phases still ahead. The finer-grained label is visible
  everywhere a document is shown or timelined — the deferred part is
  only the top-level tab/filter structure itself.
- **New cross-admission episode-of-care inference** (e.g. linking a
  discharge to a preceding ED visit that isn't part of the same
  admission record): not built, and the spec explicitly cautions against
  overbuilding this. The existing admission-parent grouping already
  covers the common case conservatively.
- Prescription/medication_list → `PatientMedication` linkage (noted in
  Phase 4) is still outstanding — the natural place for it, but not
  reached this phase either.

## 2e. Phase 6 — what was actually built

Inspection found the chart system already substantially matches the
spec's intent: `lib/chart-theme.ts` (a genuinely restrained, theme-aware
ECharts base — no rainbow palettes, no fake 3D, honest axis choices) and
`components/ui/trend.tsx` (`Sparkline` + `TrendChart`, hand-rolled SVG on
purpose for the per-row/table case to avoid mounting 50 ECharts
instances) were already in good shape, and "chart point → source"
already existed in outline (`TrendChart.onPointClick` already navigated
to the source document). Phase 6 closed the two real gaps found:

- **Reference-band honesty fix** (`TrendChart`): the bell/line honesty
  requirement — "do NOT apply one universal reference band if that would
  be misleading" — wasn't actually being followed. The band was drawn
  from a single caller-supplied `referenceRange` (the *latest* point's
  range) applied across the whole chart, even though every point already
  carries its own `reference_range`. Now the band only renders when every
  point in view agrees with that range; if any point's own range
  disagrees (different lab/assay/date), the band is omitted rather than
  misrepresenting older points. The per-point reference range still shows
  in the hover readout either way.
- **Chart-point → source, closed the loop to the exact row**: trend
  points now carry `lab_result_id` (backend: `/patients/{id}/bloodwork-
  trends`; frontend: `TrendPoint`). `TrendChart.onPointClick` passes it
  through (backward-compatible — existing callers that only read the
  first arg are unaffected). The two real chart pages
  (`my-records/page.tsx`, `patients/[id]/page.tsx`) now deep-link to
  `/documents/{id}?lab={labResultId}`; the document page reads that query
  param, scrolls the matching lab row into view, and auto-opens its
  Phase-3 source dialog — "select a point → see the exact source" now
  works end to end without the user hunting through the results table.

### Deferred from the original Phase 6 spec
- **The large ECharts-based analytics dashboard**
  (`app/patients/[id]/analytics/page.tsx`, ~2400 lines, many chart
  instances already built) was inspected but not modified — some
  instances use a hardcoded, non-theme-aware color (e.g. `#7c3aed` in the
  marker-relationship scatter) rather than the shared chart-theme tokens.
  A full consistency pass across every chart in that file was judged
  higher-risk than value to attempt in the time remaining across all
  seven phases; flagging it here rather than doing a rushed, partial
  edit across a file of that size.
- Sparklines, mobile touch interaction, and accessibility on the
  existing `TrendChart`/`Sparkline` were reviewed, not rebuilt — they
  already look reasonable (generous invisible hit targets, `role="img"`
  + `aria-label` on the SVG, `ResizeObserver`-driven width). No changes
  made since nothing unsafe or dishonest was found there.
- No new "BragiChart"/"BragiLabTrendChart" wrapper components were
  introduced — the existing `chart-theme.ts` + `trend.tsx` already serve
  that role for the parts of the app inspected this phase; introducing
  parallel naming would have been churn without changing behavior.

## 2f. Phase 7 — final integration verification

Every phase already ran its own tests/typecheck/lint/import-smoke-test
as it landed (see §2a-§2e and each phase's git commit); Phase 7 adds the
whole-project checks that only make sense once, at the end:

- **`next build`** (production build, not just `tsc --noEmit`): compiled
  successfully, including every route touched across all six phases
  (`/documents/[id]`, `/my-records`, `/my-records/upload`,
  `/my-records/timeline`, `/patients/[id]`, `/patients/[id]/timeline`).
  All 33 routes generated with no errors.
- **Real `uvicorn` boot** (not just `python -c "import app.main"`):
  started the FastAPI app under an actual ASGI server, confirmed the
  root endpoint responds and `/openapi.json` lists all 73 registered
  paths — including every endpoint added this project (`/upload/batch`,
  `/upload-jobs/{id}/confirm-type`, `/upload-jobs/{id}/confirm-identity`,
  `/documents/quarantined`, `/documents/{id}/identity-review`,
  `/lab-results/{id}/source`, `/document-types`) — proving every new
  Pydantic request model is well-formed and every route registered
  without conflict. Server stopped cleanly after.
- **Full-project `eslint .`** (not just changed files): surfaced 54
  pre-existing problems (mostly a repo-wide `react-hooks/set-state-in-
  effect` pattern in files this project never touched — theme
  providers, `account-menu.tsx`, `app-shell.tsx`, `lib/i18n.ts`, etc. —
  plus a couple of unrelated `no-explicit-any`/`ban-ts-comment` findings).
  None are in any file this project changed beyond what was already
  fixed or documented per-phase. Not fixed — a repo-wide lint debt
  cleanup is a separate effort from Bragi + Reducto, and touching ~15
  unrelated files this late would be pure risk for zero feature value.
- **Full backend suite**: 42 unit tests passing, `pyflakes` across every
  `backend/app/services/*.py` file clean except one pre-existing
  (`document_pipeline.py`, an unused import predating this project).
- **Full cumulative diff review** (`git diff main..HEAD`): 35 files
  changed, 3792 insertions / 301 deletions across all 6 feature phases.
  Scanned for API keys, private keys, and connection strings with
  embedded credentials — none found. The only CNP-shaped strings in the
  diff are synthetic values in `tests/test_patient_identity.py`
  (`1800101123456`-style fixtures invented for the identity-matching
  tests, not real patient data).
- **Not run**: the repo's own Playwright QA harness (`qa/flows.mjs`,
  `qa/a11y.mjs`, `qa/themes.mjs`) — it requires a live frontend + backend
  and a `BRAGI_TOKENS` file with real login tokens for several named
  accounts, which this session had no safe way to generate. Recommended
  as your own next step: `node qa/flows.mjs` and `node qa/a11y.mjs`
  against a locally running stack, particularly exercising the new
  multi-file upload, classification confirmation, identity-confirmation,
  and chart-point-to-source flows at the phone/tablet/desktop widths the
  original spec calls out (360/390/430/768/1280/1440px).

### What "done" means for this implementation

All 7 phases from the original spec have a real, working, tested
implementation in this repository — scoped down from the spec's full
ambition where doing so was the responsible choice given a single
implementation pass (see each phase's "deferred" list: outline/search/
30-second-read/conflicts UI, Level-2 semantic duplicate matching,
prescription → medication linkage, a full ECharts consistency pass, and
top-level document-organization restructuring are the main things
intentionally left for follow-up work, not overlooked). Nothing here
was faked to look complete: every "done" item above has a passing test,
a clean build, or a verified live check behind it, and every deferred
item is named as such rather than silently dropped.

**Update: Reducto itself is now really integrated — see §8.** At the end
of the original 7 phases, no Reducto MCP connector or API key was
available, so everything Reducto-shaped was scaffolding rather than a
working connection (the "legacy_rules" classifier and the existing
Google Document AI/OpenAI pipeline did the actual work). A follow-up
session was given a real `REDUCTO_API_KEY` and implemented
`ReductoExtractionProvider.classify()`, plus real Split and Extract,
against the live API — verified with synthetic documents, not guessed
from documentation. `REDUCTO_ENABLED` is still `false` by default
everywhere; see §8 for exactly what was and wasn't verified before
turning it on.

## 3. Reducto integration status (superseded — see §8)

**This section describes the state before the real integration.** A real
`REDUCTO_API_KEY` was later provided and Reducto Classify/Split/Parse/
Extract were implemented and verified against the live API — see §8 for
the current, accurate status. This section is kept for history.

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

## 8. The real Reducto integration (follow-up session)

A follow-up session was given a real `REDUCTO_API_KEY` (no Reducto MCP
was connected in that session either) and replaced the disabled stub
with a working integration, verified against the **live** Reducto API
(`https://platform.reducto.ai`) using synthetic Romanian medical
documents generated for testing — not inferred from documentation, per
the explicit instruction for this round. Every claim below was checked
live before being written down.

### What was verified against the live API (not just implemented)

- **Upload** (`POST /upload`): multipart file → `reducto://<uuid>.<ext>`
  file_id. Used for every synthetic document in every test below.
- **Classify** (`POST /classify`, synchronous): a 15-category
  `classification_schema` built from the existing 16-value taxonomy
  (`document_taxonomy.DocumentType`, minus `other` handled specially)
  correctly separated 6 distinct synthetic document types at confidence
  1.0/0.0, and — critically — correctly produced a genuine confidence
  **tie** (1.0/1.0 between `laboratory_results` and `discharge_summary`)
  for a document deliberately written to legitimately contain both (a
  discharge letter with an embedded lab table). Reducto's own
  `response_confidence.categories[]` gives a full per-category
  confidence breakdown, not just the winner — ambiguity detection
  (`reducto_extraction._decide_status`) compares the winner's confidence
  against the runner-up rather than using an invented single-number
  threshold, calibrated against this real tie.
- **Parse** (`POST /parse`, synchronous for the document sizes tested):
  returned page/bbox-tagged blocks (Table/Title/Section Header/Key
  Value/Text) with Romanian decimal-comma values intact in table markdown
  (`"13,2"`, `"12,0 - 16,0"`).
- **Extract** (`POST /extract`, synchronous for the sizes tested, with
  `settings.citations.enabled=true`): pulled all 7 lab rows from a
  2-page synthetic Romanian lab report (Hemoglobină, Eritrocite,
  Leucocite, Trombocite, Creatinină, Glucoză, CRP) with correct
  decimal-comma values and units, per-field bounding boxes (normalized
  0-1, with page/original_page), and per-field confidence. Narrative
  extraction (imaging report → modality/body_region/exam_date/technique/
  findings/impression) also verified, preserving Romanian text verbatim.
- **Split** (`POST /split`): a synthetic 9-page mixed PDF (pages 1-2 lab,
  page 3 imaging, pages 4-8 discharge, page 9 prescription) split into
  exactly those 4 sections at "high" confidence, using the same
  taxonomy-derived descriptions as Classify. A genuinely single-type
  2-page document correctly came back as *one* section spanning both
  pages (`is_mixed=False`) — confirming Split is safe to call on every
  Reducto-classified upload without false-positive-splitting normal
  documents.
- **Error shapes**: a bad file_id returns `404 {"error":{"code","name":
  "NOT_FOUND","message"}}`; a bad API key returns `401 {"error":{"code",
  "name":"AUTH_ERROR","message"}}` — both mapped to typed exceptions in
  `reducto_client.py`.

### What was implemented

- `app/services/reducto_client.py` — thin HTTP client (upload/classify/
  parse/extract/split/job polling), typed exceptions
  (`ReductoAuthError`/`ReductoNotFoundError`/`ReductoTimeoutError`/
  `ReductoServerError`/`ReductoRateLimitedError`/
  `ReductoMalformedResponseError`), and a fallback to polling
  `GET /job/{id}` for the (untested-here, since every document tried was
  small) case where a large document doesn't return `result` inline.
- `app/services/reducto_schemas.py` — the Classify taxonomy schema,
  lab/identity/reader-per-type Extract JSON schemas (reader schemas
  reuse the exact `structured_reader_service.SECTION_KEYS` used by the
  OpenAI fallback, so switching providers doesn't change the Reader's
  data contract), and the confidence thresholds derived from the live
  tie-detection test above.
- `app/services/reducto_extraction.py` — classification decision logic,
  response-to-`labs`-list mapping (reusing `synonyms.normalize_test_name`
  for canonical_name/category, exactly like the legacy bloodwork
  pipeline), reader-section mapping, identity-field mapping, and
  `build_pipeline_result_labs`/`build_pipeline_result_reader`, which
  produce the *exact same dict shape* `process_upload_job` already reads
  from `process_uploaded_document`/`process_uploaded_discharge_summary`
  — so the Document/LabResult/SourceEvidence creation code in `main.py`
  did not need to change to accept Reducto-sourced data.
- `app/services/pdf_split.py` — slices a page range out of a source PDF
  (PyMuPDF, already a dependency) for the mixed-document flow below.
- `extraction_provider.ReductoExtractionProvider.classify()` — real
  implementation (was `NotImplementedError`). The abstract `classify()`
  signature gained an optional `file_path` param (Reducto classifies the
  file directly, not OCR text — a real difference from the legacy
  classifier discovered by testing, not assumed); legacy provider is
  unaffected.
- **`main.py` wiring** (only inside the existing
  `AUTO_CLASSIFY_SECTION` multi-file batch-upload path —
  doctor/care-partner explicit-section uploads are untouched):
  - Reducto Classify replaces the OCR-then-classify step when enabled,
    falling back to `legacy_rules` on any `ReductoError`.
  - Reducto Split runs right after Classify (only in the Reducto path).
    If it finds more than one section, `_finish_mixed_reducto_upload`
    takes over: identity is checked **once** for the whole physical
    file (never bypassed by finding multiple sections in it), a parent
    `Document` row preserves the original upload untouched, and each
    section is sliced into its own PDF, uploaded separately, and run
    through the normal single-document Reducto extract path — producing
    child `Document` rows (new `parent_document_id`/`page_range_start`/
    `page_range_end` columns, migrated the same idempotent way as every
    other column in this project) whose `saved_to` still points at the
    **parent's** file and whose `SourceEvidence.page_number` is remapped
    back to the original document's real page numbers (not the slice's
    1-based numbering) — "View original" opens the real source file at
    the real page, never a throwaway slice.
  - For a non-mixed document, `laboratory_results` and the 6 narrative
    reader types get their extraction from Reducto (labs → the existing
    `LabResult`/`SourceEvidence` loop, now populated with **real**
    `page_number`/`bbox_x`/`bbox_y`/`bbox_width`/`bbox_height` instead of
    always-null; reader sections → reused directly at the existing
    Phase 4 call site instead of paying for a second OpenAI extraction
    of the same file). `discharge_summary` keeps its existing dedicated
    pipeline unchanged (not clearly broken, per this round's
    instructions) — Reducto handles the other 7 supported types.
  - Any `ReductoError` at any step falls back to the pre-existing legacy
    pipeline for that document rather than failing the upload.

### What was NOT verified (be honest about this before flipping `REDUCTO_ENABLED`)

- **The full HTTP/DB-backed upload flow.** This session had no local
  Postgres credentials (a Postgres instance was running locally but with
  credentials this session didn't have, and `run_migrations()` is
  Postgres-specific raw SQL, so a throwaway SQLite DB couldn't stand in).
  Verified instead: syntax/AST-checked every changed file, all 42
  pre-existing backend unit tests still pass unmodified, `app.main`
  imports cleanly up through the DB-connection step (fails only on
  Postgres auth, not on any Python/import error), and — most
  importantly — every new function in `reducto_extraction.py`
  (`classify_file`, `split_file`, `build_pipeline_result_labs`,
  `build_pipeline_result_reader`) was called directly against the real
  Reducto API and produced correct, verified output (see above). What
  was **not** exercised end-to-end: the actual `Document`/`LabResult`/
  `SourceEvidence` writes, identity-check integration, and duplicate
  detection running against a real database through the real
  `/upload/batch` endpoint. Run the multi-file/mixed-PDF scenarios in
  §13 of this doc against your own local Postgres before trusting this
  in any shared environment.
- **A non-contiguous split section's page mapping** (e.g. a section
  covering pages [1, 2, 5]) — implemented (`_original_page` in
  `main.py` maps slice-local pages back via an explicit sorted list, not
  a flat offset) but every live Split test happened to return contiguous
  ranges, so this specific edge case is reasoned-through, not observed.
- **A document large enough that Reducto doesn't return `result` inline**
  (Reducto's own docs say sync calls suit <100 pages; every test
  document here was 1-9 pages) — the job-polling fallback in
  `reducto_client._maybe_await_job` is implemented but never triggered.
- **The Playwright QA suite** — same blocker as every prior phase (no
  `BRAGI_TOKENS`), unrelated to this round's work.
- **Frontend changes** — none were needed or made. Split-created child
  documents surface through the existing generic `document_type`-based
  display (Phase 5) automatically; `parent_document_id`/
  `page_range_start`/`page_range_end` are now returned by
  `serialize_document_card`/`get_document_payload` but nothing in the
  frontend groups children under their parent yet or shows the page
  range — a reasonable, explicitly-named follow-up (see §14), not a
  silent gap.
- A **low-confidence** (`"conf": "low"`) Split section is still filed
  automatically as its detected type today; there is no per-section
  "needs confirmation" UI for an individual mixed-PDF section the way
  there is for a whole ambiguous single document. Scoped out given the
  size of the change already made — worth adding if low-confidence
  splits turn out to be common in practice.
- Split children skip Level-3 duplicate-observation linking (the
  same-patient/same-date/same-value/same-unit dedup that whole documents
  get) — scoped out for time; a child's lab rows are always inserted as
  new rows even if they duplicate an existing observation.

### Turning it on (`REDUCTO_ENABLED=true`) — superseded, see §9

§9 below is a full DB-backed verification round that closes most of the
gaps this section originally listed. Read §9 before following the
checklist that used to be here.

## 9. Production-readiness verification (follow-up round, real Postgres)

A further follow-up round ran the full `POST /upload/batch` path
end-to-end — real HTTP requests against a real running FastAPI server,
`REDUCTO_ENABLED=true`, backed by a real (non-production) Neon Postgres
dev database — closing the biggest gap named in §8 ("what was NOT
verified": the DB-backed HTTP flow had never actually run).

### What was verified live, against real Postgres, this round

All of the following are real HTTP calls through a real running server
to a real database, not function-level calls or mocks — see the test
script referenced in the commit for the full scenario list:

- **Multi-file batch independence**: 6 files (lab, discharge, imaging,
  prescription, consultation, a genuinely ambiguous one) uploaded in one
  `POST /upload/batch` call. 4 processed and completed correctly and
  independently; the ambiguous one correctly stopped at
  `needs_confirmation` without blocking the other 5; the 6th
  (`discharge_summary`) failed for a reason unrelated to Reducto (see
  "found and fixed" below).
- **Romanian lab → structured Analize → View original → bbox
  highlight**: a real 2-page synthetic lab report produced exactly 7
  `LabResult` rows with correct canonicalization (`"Hemoglobina"` →
  `canonical_name="hemoglobin"`), and `GET /lab-results/{id}/source`
  returned a real, non-null page number and bbox
  (`bbox_x/y/width/height`) with `provider="reducto"` — this is the
  actual coordinate data "View original" highlighting depends on,
  confirmed present in the database, not just in the Reducto API
  response.
- **Exact duplicate**: uploading the identical file twice → the second
  upload's job came back `status="duplicate"` pointing at the original
  `Document`.
- **Wrong-patient quarantine**: a synthetic lab document for a
  completely different (fictitious) patient, uploaded to the first
  patient's account → `status="quarantined"`, and the document appeared
  in `GET /documents/quarantined`.
- **Mixed-PDF split**: the same 9-page synthetic mixed PDF from §8
  (pages 1-2 lab / 3 imaging / 4-8 discharge / 9 prescription), this
  time run through the real database — produced exactly 1 parent +
  4 child `Document` rows with the correct `page_range_start`/
  `page_range_end` on each, the lab child's `LabResult`/`SourceEvidence`
  rows present and correct, and — critically — every child's `saved_to`
  equal to the **parent's** `saved_to` (confirmed by direct comparison),
  so "View original" opens the real original file, never a throwaway
  slice.
- **Non-contiguous split page remapping** (the specific edge case §8
  flagged as reasoned-through but not observed): a new synthetic 3-page
  document was built with laboratory content on pages 1 and 3 and
  imaging content on page 2 (nothing in §8's documents exercised this).
  Reducto Split genuinely returned one `laboratory_results` section with
  `pages=[1, 3]` — confirming Reducto itself merges non-adjacent same-
  category pages into one section, which is exactly the case the
  `_original_page` list-based mapping (rather than a flat offset) exists
  for. Verified end-to-end: the resulting lab child's `SourceEvidence`
  rows carry `page_number` values of exactly `{1, 3}` — the real
  original pages — never `2` (the imaging page) and never the slice-
  local `{1, 2}` a naive offset would have produced.
- **Reducto Parse persistence** (new this round — closes the other gap
  named in the original spec, "rather than relying only on Extract"):
  `parse_document()` (new in `reducto_extraction.py`) calls Reducto
  Parse and stores its full page/bbox-tagged blocks in a new
  `Document.parsed_content` column (JSON), and `extracted_text` is now
  the real parsed document text rather than a synthesized
  labs-list/sections-only reconstruction. Verified: `parsed_content`
  populated with real blocks carrying real page numbers, and
  `extracted_text` containing text that only a real parse (not the
  Extract schema) would have — e.g. the `"HEMOLEUCOGRAMA COMPLETA"`
  section header, which no Extract schema field asked for.

### Found and fixed this round

- **Real bug: overlapping Split sections were wrongly treated as a
  "mixed PDF."** The synthetic ambiguous document from §8 (one page
  legitimately readable as either `laboratory_results` or
  `discharge_summary` — the same case Classify's confidence-tie
  detection exists for) came back from Split as **two sections that
  both claimed page 1** — not two sections on different pages. The
  original code treated any `>1` non-empty Split section as "mixed" and
  short-circuited straight into the split/child-document path,
  bypassing Classify's `needs_confirmation` decision entirely and
  silently creating two overlapping child documents for one ambiguous
  page. Fixed: `ReductoSplitResult.is_mixed` now requires every
  section's pages to be disjoint from every other section's — only a
  genuine page-range split (no page claimed by more than one section)
  counts as "mixed." An overlapping result now correctly falls through
  to Classify's own `needs_confirmation` status, exactly as intended.
  Verified live both before the fix (wrong: silently split) and after
  (right: `needs_confirmation`, user asked to pick one).
- **Not a Reducto bug, but worth recording**: the `discharge_summary.pdf`
  batch file failed with `RuntimeError: OPENAI_API_KEY is not set.` —
  `discharge_summary` intentionally still uses its existing, unchanged
  OpenAI-based pipeline (a deliberate decision in §8, "not clearly
  broken"), and this test environment has no `OPENAI_API_KEY`
  configured. Reducto Classify correctly identified it as
  `discharge_summary` at confidence 1.0 before the (unrelated,
  pre-existing) pipeline failed on the missing key. Confirmed via the
  server's own traceback, not assumed.

### What still wasn't verified

- **The doctor/care-partner upload paths** — unchanged by design (only
  `POST /upload/batch`, the patient multi-file flow, uses Reducto), so
  not exercised this round either; they still use the legacy pipeline
  exactly as before.
- **`discharge_summary` end-to-end** — blocked by the missing
  `OPENAI_API_KEY` above; this exercises pre-existing, non-Reducto code,
  not this integration.
- **Playwright QA** — still not run (no `BRAGI_TOKENS`), same as every
  prior round.
- **Scale/performance**: Starlette's `BackgroundTasks` run sequentially
  in-process — 6 files in one batch took ~4 minutes end-to-end in this
  test (each file makes 2-5 real Reducto HTTP calls). This is correctness-
  verified, not load-tested; a much larger batch, or many users
  uploading concurrently, will queue up behind each other rather than
  parallelize. Worth watching in production, not a correctness concern.
- **Level-2 semantic duplicate matching, per-section split confirmation
  UI, and Level-3 dedup for split children** — still not implemented,
  as named in §8.

### Found and fixed while cleaning up test data (bonus, real)

Cleaning up the test patients created during this round's verification
surfaced a second real bug, unrelated to Reducto's classification logic
but directly caused by exercising this integration's new self-referential
`Document.parent_document_id` for the first time: `DELETE /my/account`
returned a real `500` (`ForeignKeyViolation`) for any patient who had a
split (parent/child) document, because nothing cleared child →
parent references before deleting rows. While fixing it, the exact same
class of bug was found in a **pre-existing, unrelated Phase 2 FK**
(`LabResult.duplicate_of_lab_result_id`, the Level-3 duplicate-observation
link) — meaning `DELETE /my/account` (and, latently, the single-document
`DELETE /documents/{id}` endpoint) could already 500 for any patient with
a linked duplicate lab result, Reducto or not.

Fixed at the schema level rather than patching each endpoint: both FKs
are now `ON DELETE SET NULL` (migrated idempotently, guarded so it only
actually runs once), so every current and future deletion path is safe
automatically. Verified live: a patient with a split document AND a
quarantined document 500'd before the fix and returned `200 {"deleted":
true}` after, with the account confirmed actually gone (`/auth/me` →
401).

### Is `REDUCTO_ENABLED=true` safe now? — superseded, see §10

## 10. Real production failure: root cause, fix, and latency work

The maintainer tested the real live upload experience (not dev/synthetic)
and reported a long wait on "Classifying document type..." followed by a
failure. Diagnosed against the actual live deployment (Render CLI, with
the maintainer's authorization) rather than assumed from dev results.

### Deployment reality check (do this before touching anything else)

Render's `bloodwork-os-api` service has `autoDeploy: commit` on `main` —
every commit pushed in the §8/§9 rounds had **already auto-deployed to
production**, including the full Reducto integration. Confirmed via
`render deploys list`: the live deploy at the time of the report was
commit `dfd0cf7` (the §9 account-deletion fix), status `live`. So this
was never a stale-deployment problem — the live server was running
current code the whole time.

### Root cause of "classification succeeded, then failed"

`render logs` surfaced the real production traceback immediately:

```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.DatatypeMismatch)
column "is_verified" is of type integer but expression is of type boolean
```

on a real `INSERT INTO documents ...` — for a document whose Reducto
classification and extraction had **already succeeded**
(`classification_source: reducto`, `document_type: laboratory_results`,
real Romanian lab values, real `parsed_content`). The insert failing at
the very last step is exactly what "spent a long time, then failed"
looks like from the outside.

**This is not a Reducto bug.** A much earlier phase (documented in §2a)
found `Document.is_verified` was declared `Integer` in the model but
"the live Postgres column is boolean" **in that session's dev DB**, and
changed the model to `Boolean` — with no migration to actually convert
the column, and without checking production. This production database's
real column was never converted and is still `integer`. Every single
`Document` insert — from any provider, not just Reducto, since
`is_verified=False` is passed at every `Document(...)` call site in this
file — has been failing on this production database. Given no one had
exercised the real end-to-end upload path against production since that
phase landed, this had likely been silently broken for uploads generally,
not something this round's work introduced.

**Fix**: an idempotent migration (`run_migrations()`, guarded via
`information_schema.columns` so it only actually runs the `ALTER` once)
converts the column to boolean, matching the model. Verified against the
dev Neon DB (already boolean there — confirmed the guard correctly
no-ops) and reasoned through against the exact production error text;
full production confirmation is in the "live verification" subsection
below once the fix is actually deployed.

### Real latency, found by benchmarking rather than assuming

Precise per-stage timing (new `REDUCTO_TIMING` log lines — safe, no PHI,
compares Bragi's wall-clock time against Reducto's own `duration` field)
against representative documents found:

| stage | 1-page prescription | 2-page lab | 9-page mixed |
|---|---|---|---|
| upload | 1.8s | 0.5s | 0.7s |
| classify | 4.3s | 3.7s | 7.5s |
| **split** | **7.7s** | **10.1s** | 21.2s |
| parse | 2.9s | 3.5s | 4.9s |

**Split cost ~7-10s even on a trivial single-page document that always
turned out non-mixed** (`split_sections: 1`) — a large fixed latency
floor, not proportional to content, paid on *every* auto-classified file
regardless of whether Split ever finds anything. Classify and Split are
independent calls (neither's input depends on the other's output), so
this was pure serial waste.

**Fix**: `reducto_extraction.classify_and_check_split()` runs Classify
and Split concurrently (`ThreadPoolExecutor`, 2 workers) against the same
uploaded file instead of sequentially. Verified live: prescription.pdf
went from ~12.6s (upload+classify+split serial) to 9.1s; lab_results.pdf
from ~15.9s to 11.4s — roughly 30% off just the "identifying document
type" wait, with Split's mixed-PDF detection fully preserved (still runs
on every file; only the *sequencing* changed, not what's checked).

### The "stuck on Classifying" UI bug

Backend: `job.message` was only updated at the *start* of classification
and again only once extraction had **already finished** ("Saving
structured record..." was set *after* the slow extract/parse/identity
work, not before) — so the frontend showed a stale message for the
entire extraction phase. For a **mixed-PDF split**, it was worse:
`_finish_mixed_reducto_upload` never set `job.document_type` at all (only
the single-document path does), and the frontend's upload page gated its
translated "Identifying document type..." label on `!task.documentType`
— meaning a split upload showed that label for its *entire* processing
duration, however long that took.

**Fix**: `job.message` now updates *before* each real stage starts
("Extracting results..." / "Reading document..." / "Processing
document..." → "Checking patient..." → "Organizing..."), and
`_finish_mixed_reducto_upload` sets `"Separating records..."` immediately
on detecting a real split. The frontend
(`app/my-records/upload/page.tsx`) now gates its translated label on the
backend message literally still being `"Identifying document type..."`,
not on `documentType` being set — so it naturally clears the moment the
backend moves on, for every path including split. Verified live (see
below): real message progression, no stuck label.

### Multi-file batch: real bounded concurrency

`POST /upload/batch` dispatched every file's `process_upload_job` via
FastAPI's `BackgroundTasks`, which runs tasks strictly one at a time in
the same process — confirmed live: a 6-file batch took ~4 minutes with
every file waiting for every earlier one to fully finish, however fast
the later file actually was on its own. Fixed: a fixed-size worker pool
(`UPLOAD_JOB_POOL`, `ThreadPoolExecutor`, default 3 workers, configurable
via `UPLOAD_JOB_CONCURRENCY`) — bounded, not unbounded, concurrent
Reducto requests. `process_upload_job` needed no changes to be safe to
call this way: it already opens its own `SessionLocal()` per call.

**Verified live** (5-file batch, dev DB): jobs started within ~0.5s of
each other in groups of 3 (confirmed via message-progression polling —
3 jobs hit "Identifying document type..." almost simultaneously, the
4th and 5th visibly queued and started the instant a worker freed up),
total batch wall time 63s vs. what would have been the *sum* of all 5
individual times (~185s) under the old strictly-sequential dispatch —
roughly 3x faster wall-clock for this batch, and confirmed the fast
files (imaging, prescription) finished well before the slower ones
rather than waiting behind them.

### Error categorization

The outer exception handler in `process_upload_job` previously set the
same generic `job.error` ("An error occurred... Please try again.") for
*every* failure — a Reducto auth failure, a database error, and a
missing `OPENAI_API_KEY` were all indistinguishable to anyone debugging
a failed job. Now categorized by exception type (`reducto_<ErrorType>`,
`database_error`, `missing_openai_config`, or `internal_error`), logged
server-side (`category=... exception_type=...`, never the raw traceback
text as user-facing `job.error`) — verified live: a real
`missing_openai_config` failure logged and categorized correctly,
distinct from a Reducto or database failure.

### What was NOT changed (per "do not redesign")

Split still runs on every file (preserved exactly — only made
concurrent, never skipped or removed, since a mixed PDF can be as short
as 2 pages); the classification confidence/ambiguity thresholds from §8
are untouched (still real, tested values, not re-tuned); `needs_confirmation`
vs `classification_failed` — in practice, a genuine Reducto Classify
failure always falls back to `legacy_rules` (itself always produces
*some* classification), so there is currently no path where classification
truly "fails" outright rather than degrading — this matches the existing
"controlled legacy fallback" design from §8 and was not changed.

### Is `REDUCTO_ENABLED=true` safe now? (current)

For the scope this integration covers (`POST /upload/batch`) — yes, with
the is_verified fix, now that the actual root cause of the reported
production failure is understood and fixed, and real latency/UI-accuracy
issues are fixed and verified. See the DEV/LIVE status split in the
handoff message for exactly what was and wasn't verified against the
live server itself versus the dev DB.

<!-- superseded-section-below, kept for history -->

For the scope this integration actually covers (`POST /upload/batch`,
the patient multi-file upload flow) — yes, with the caveats above. Every
core claim (classification, ambiguity handling, split, non-contiguous
page remapping, duplicate detection, identity quarantine, structured
Analize, source provenance, Parse persistence) has now been verified
against a real database, not just the live Reducto API in isolation.
The one real bug found this round (overlapping-split-as-ambiguity) is
fixed and re-verified. Recommended next step before flipping it in any
environment with real patients: a quick pass on the two things this
round couldn't reach — Playwright/manual QA of the actual upload UI, and
either an `OPENAI_API_KEY` in that environment or accepting that
`discharge_summary` uploads will fail until one is configured (true
regardless of Reducto).

## 11. Lab normalization, shared source viewer, and global popup rework

Three-part round: (A) generic OCR-tolerant lab-analyte resolution, (B) an
in-app source-verification viewer replacing "open PDF in a new tab", (C)
a global popup/dialog interaction rework. Full detail in this section;
CLAUDE_HANDOFF.md carries the status summary.

### 11a. PSV/PSW root cause and the generic resolver

**Root cause, traced layer by layer**: a real production document's
analyte the source visibly labels "PSW" was extracted by Reducto as
"PSV" — a single visually-confusable glyph misread inside Reducto's own
OCR/vision layer (Parse/Extract), not introduced by anything downstream.
Bragi's existing normalization (`synonyms.normalize_test_name`,
`lab_catalog.find_lab_definition`) does exact/substring matching only —
correctly, conservatively, left "PSV" unresolved rather than guessing,
but that also meant a genuine one-glyph OCR slip was never recovered:
the unresolved fallback echoes the raw string back as both
`raw_test_name` and the synthesized `display_name`, which is exactly
what "Bragi representing PSV" looks like from the outside. Reproduced
synthetically (a rendered PDF with a real "PSW" row goes through Reducto
and reads back correctly — confirming clean text isn't naturally
misread; the fix targets the resolution side, not Reducto's OCR itself,
which isn't ours to change) and exercised deterministically against the
exact confusion classes the product spec named (real OCR corruption
isn't reproducible on demand from clean synthetic renders, so the
resolver's behavior on a known corrupted input is the right thing to
test directly; live-verified end-to-end separately).

**Architecture** (`backend/app/services/lab_resolver.py`, new module —
extends rather than replaces the two existing catalogs):
1. `synonyms.normalize_test_name` (unchanged) — exact/alias match
   against the 39-entry CBC+chemistry catalog.
2. `lab_catalog.find_lab_definition` (unchanged) — scored substring
   match against the ~140-entry broader catalog.
3. Only if neither matches: OCR-confusion-aware weighted edit-distance
   scoring across BOTH catalogs' combined alias lists (V/W, I/l/1, O/0,
   S/5, B/8 as reduced-cost single-glyph substitutions; rn/m as a
   bigram-variant pre-pass) — resolves only above a confidence floor
   calibrated against the real psv-vs-psw case (one same-class
   substitution on a 3-character token scores 0.90), with contextual
   corroboration (category/section hint, a small explicitly-partial
   unit-compatibility table) as a real but narrow signal — not
   exhaustive, not claimed to be. Two genuinely different candidates
   scoring closely together stay unresolved (a real bug found by testing:
   the same concept existing as two separate candidate objects — one
   per source catalog — was initially mis-flagged as "ambiguous"; fixed
   to compare by normalized display name, not candidate identity).

**"PSW" itself — CORRECTED in §12, see there for the full story**: this
paragraph originally claimed "Platelet Size Width" as a real alternate
vendor abbreviation for PDW and added it to `synonyms.py` as a PDW
alias. That claim was fabricated (no invented justification, no actual
source) and has been removed; §12a explains the root-cause mistake and
the fix. What's still true from this round: "PSV" is never hardcoded
anywhere as an alias for anything (still enforced by
`test_no_hardcoded_psv_to_psw_mapping_exists`), and an OCR misread must
resolve through the generic scorer or not at all — §12a adds a second,
independent axis (text-match confidence vs. clinical-semantic
confidence) so a confident text match no longer has to silently imply a
confident clinical meaning.

**Wired into both extraction pipelines**: `reducto_extraction.py`'s
`extract_lab_results()` (the live path) and the legacy
`bloodwork_parser.py`'s `build_lab_result()` (after its existing
`KNOWN_TEST_ALIASES` pre-pass, unchanged). `raw_test_name` is never
modified by any of this; a new `LabResult.normalization_method` column
(`exact`/`alias`/`ocr_fuzzy`/`unresolved`) plus the already-existing
`normalization_confidence` column record provenance, migrated
idempotently. `document_pipeline.py`'s separate non-CBC path (via
`lab_catalog.find_lab_definition` directly) was left on its existing
matcher only — a reasonable follow-up, not done this round.

**Tests (as of this round, see §12a for the current count/assertions)**:
`backend/tests/test_lab_resolver.py` — the no-hardcode proof, every
CBC/metabolic term named in the spec confirmed unaffected (still exact,
confidence 1.0), OCR-confusion recovery on real terms, unrelated tokens
staying unresolved, the cross-catalog "same concept, two candidates"
fix. Live-verified: a synthetic document with a real "PSW" row, run
through the actual Reducto API, produces a raw_test_name of "PSW" (the
OCR-correction axis working — Reducto reads it cleanly, no PSV garbling
on clean input) with normalization_method="unresolved" (the correct,
honest outcome now that the fabricated PDW alias is gone — see §12a for
why this is right, not a regression).

### 11b. Shared Bragi source viewer

**Real stored bbox format** (checked against live SourceEvidence rows,
not assumed): bbox_x/bbox_y/bbox_width/bbox_height are already
normalized, page-relative fractions in [0, 1], origin top-left —
Reducto's own citation format (bbox.left/top/width/height), stored
as-is. This is already exactly the provider-independent,
resolution-independent representation the spec asks for — no geometry
normalization layer was needed; a highlight div positioned via
left/top/width/height: {value * 100}% inside a container sized to the
rendered PDF.js canvas stays aligned at any zoom/container size for
free. Rotation: PDF.js's own page.getViewport({scale}) already accounts
for the page's stored /Rotate value, so rotated pages are handled by not
overriding that — not independently tested against a real rotated
document this round (honest limitation, not silently assumed safe).

**Backend**: new `GET /source-evidence/{id}/view` (app/main.py) —
resolves SourceEvidence to Document to authorization via the same
can_access_patient check /documents/{id}/file already uses (no new
authorization logic), returns page/bbox/precision/document metadata,
never a bare or long-lived file URL — the actual PDF bytes still go
through the existing authenticated /documents/{id}/file route.
`precision` is one of exact_bbox / page_only / text_only /
document_only, computed from what's actually present — never a
fabricated bbox. Live-verified end-to-end (real Reducto lab upload to
real bbox returned to real PDF bytes fetched) plus IDOR checks
(cross-patient 403 on both the new endpoint and the existing file route,
unauthenticated 401, nonexistent-evidence 404) — all against the real
dev DB.

**Frontend** (frontend/components/source-viewer/): PDF.js
(pdfjs-dist, new dependency) via a Context (SourceViewerProvider /
useSourceViewer()) mounted once at the root layout, exposing
openSourceEvidence(sourceEvidenceId) globally — no PDF URL, patient ID,
page, or bbox ever passed around by callers, exactly the contract asked
for. SourceViewerPanel is the one shared rendering surface (canvas
render + percentage-based bbox overlay + auto-scroll-into-view on
render + page nav/zoom/fit-width controls), reused for both:
- Desktop (app-shell-with-source-viewer.tsx): a real CSS flex split at
  the root layout level — main content + viewer side by side
  (.b-app-split), not an overlay, so any page that calls
  openSourceEvidence gets the split for free, not just ones that
  specifically build a grid layout for it.
- Tablet (under 1025px) / mobile: full-screen local surface (nothing
  left to dim behind it, since it covers the screen itself) — the same
  SourceViewerPanel, different CSS wrapper class.

Same-document reuse (spec requirement): the loaded pdfjs document is
cached by document_id across openSourceEvidence calls, so clicking a
second row from the same PDF doesn't re-fetch/re-parse it.

**Analize integration** (highest priority, done): LabSourceAction in
documents/[id]/page.tsx — the old icon-only button + dialog-with-raw-
text is replaced with a visible "View in original" text action (never
icon-only, any viewport) that fetches the row's evidence id and calls
openSourceEvidence. The chart-point deep-link (?lab={id}) still
auto-opens the same way, now into the real viewer instead of the old
text-only dialog.

**Not done this round** (scoped out, documented rather than silently
dropped): AnalyticsDrilldownDrawer's "Open source document" still
navigates to the document page rather than calling openSourceEvidence
directly — the analytics data pipeline doesn't currently carry a
lab_result_id/source_evidence_id through to that drawer (only
document_id), and plumbing one through is a separate-scope backend and
type-chain change, not a viewer-architecture problem. Reader/Timeline/
Documents-list integration: not wired this round either — the shared
primitive (openSourceEvidence) is globally available for them to adopt
next, and the architecture was deliberately built so that's a small,
mechanical addition per surface (find/fetch a source_evidence_id, call
the hook) rather than new viewer work.

### 11c. Global popup rework

**Inventory** (see the commit for the full table): one shared overlay
system (components/ui/index.tsx's Dialog/ConfirmDialog/Drawer/Menu,
styled by globals.css's "OVERLAYS" section) plus six ad-hoc, one-off
overlays that bypassed it with their own inconsistent inline backdrop
styles (three different darkening colors/opacities, one pair using
backdrop-blur — explicitly prohibited by the spec). No Radix/shadcn/
Floating UI anywhere; Menu was already a correctly-anchored,
never-dimmed popover — the existing model the rest of the system now
follows.

**Centralized fix** (globals.css): .b-scrim (the shared backdrop element
used by Dialog/ConfirmDialog/Drawer, the mobile sidebar overlay, and the
bottom-nav sheet) changed from a darkening layer (rgba(15,23,42,.35) /
dark rgba(0,0,0,.55)) to fully transparent — kept only as an invisible
click-outside-to-close hit target, not a visual backdrop.
.b-dialog/.b-drawer/.b-sheet gained a stronger border (--border-strong)
to stay visually distinguishable without dimming anything behind them.
One CSS change, every current usage of the shared system fixed at once
— this is the highest-leverage part of the rework.

**Six ad-hoc overlays fixed individually** (their own inline
background/backdropFilter removed, role="presentation"/role="dialog"/
role="alertdialog" added, border+shadow strengthened to compensate): the
two near-duplicate delete-document confirmations (documents/[id]/page.tsx,
documents/[id]/discharge/page.tsx — the only two with backdrop-blur),
AnalyticsDrilldownDrawer, the emergency workspace's AddPatientModal, and
my-records/settings's regenerate-care-partner-code and delete-account
confirmations. The account-deletion confirmation deliberately kept its
larger, centered surface (a significant destructive action, per the
spec's own allowance) — only the dark dimming was removed, not its
safety mechanism (still requires the existing "type delete to confirm"
input).

**Upload classification confirmation** (explicitly named highest
priority): converted from a page-level centered Dialog to an inline
expansion directly inside the ambiguous file's own row
(my-records/upload/page.tsx) — the type picker + Confirm/Cancel appear
exactly at File C's row when File C alone needs confirmation; every
other file's row is completely unaffected, no page-level overlay at all.

**What still remains centered as of this round** (undimmed, but not
anchored to a specific trigger): the "featured analyte" picker
(Analize/patient-chart pages), the emergency session-start dialog, and
any other Dialog/ConfirmDialog call site not named above. **Superseded
by §12b**: the featured-analyte picker and every other case listed here
were audited and converted to trigger-anchored popovers in the next
round; §12b has the final, current list of every dialog that remains
centered and why. The general point still holds: the centralized
backdrop fix already satisfies "no dark backdrop" for 100% of current
Dialog/ConfirmDialog/Drawer usage regardless of anchoring.

### 11d. What wasn't safely completed this round

- Browser/Playwright QA of the actual popup positioning and
  source-viewer interactions — same longstanding blocker as every prior
  round (no BRAGI_TOKENS); verified instead via real backend E2E tests
  (Reducto to DB to API), tsc --noEmit, full production next build, and
  eslint on every changed file, all clean.
- Chart/Reader/Timeline/Documents-list source-viewer integration beyond
  Analize (see 11b).
- A real rotated-page PDF was not available to verify highlight
  alignment against; the underlying mechanism (PDF.js's own viewport
  rotation handling) is sound but untested end-to-end for that specific
  case.
- BRAGI_ASK_BRAGI_PLAN.md does not exist in this repository — nothing to
  update there. The architecture decision to record for whenever it's
  created: Ask Bragi citations should resolve through
  openSourceEvidence(sourceEvidenceId), the same contract Analize uses
  today, and any Ask Bragi contextual UI should follow this round's
  popup rule (no dark backdrop, anchored/contextual surface over a
  centered modal).

## 12. PSW semantic correction and popup audit completion

Two corrections to §11, requested after review found a real problem in
§11a and an incomplete audit in §11c.

### 12a. PSW: separating OCR-correction confidence from clinical-semantic confidence

**The mistake**: §11a's "PSW itself" paragraph added `"psw"` /
`"platelet size width"` to the `pdw` (Platelet Distribution Width) entry
in `synonyms.py` as a "real alternate vendor abbreviation," with no
actual source. It was invented to make the PSV-to-PSW demo case resolve
cleanly. This conflated two genuinely different claims:

1. **OCR-correction confidence** — is the raw text Reducto extracted
   ("PSV") a plausible misread of what the source document actually
   shows ("PSW")? This is well-supported: reproduced synthetically, and
   the OCR-confusion scorer (V/W as a same-glyph-class substitution)
   correctly identifies it as a high-confidence text match.
2. **Clinical-semantic confidence** — does "PSW," once recovered as the
   source text, mean Platelet Distribution Width? This is *not*
   supported. A web search turned up no analyzer, vendor, or hematology
   reference using "PSW" for PDW; the standard abbreviation everywhere
   is "PDW". Claim 1 being true says nothing about claim 2.

**The fix — two independent axes, not one confidence score**
(`backend/app/services/lab_resolver.py`, rewritten): `ResolvedAnalyte`
now separates `resolved_source_text` / `ocr_match_confidence` (axis 1:
what does the text say) from `canonical_name` / `resolved` /
`normalization_confidence` (axis 2: what does it mean). Each catalog
candidate carries a `clinically_verified: bool` flag. When the
best-scoring text candidate has `clinically_verified=False`, the
resolver now returns `normalization_method="text_matched_unverified"` —
axis 1 resolves (the text match is surfaced honestly), axis 2 stays
unresolved (`resolved=False`, no `canonical_name` asserted as fact,
`category="other"`). This is a real, load-bearing code path, not a flag
that's always true in practice today: the two axes can and do diverge,
proven with a test-local fictional fixture rather than a fabricated
real-catalog claim.

**PSW/PSV specifically**: the fabricated `pdw` alias is removed. No
global "PSW to PDW" mapping exists anywhere in the catalogs. "PSV"
resolves via the OCR-confusion scorer to the text candidate "PSW" (axis
1, high confidence) — but "PSW" itself has no `clinically_verified`
catalog entry, so the overall result is `normalization_method
="unresolved"`, `resolved=False`, `canonical_name=None`. Live-verified
against the real Reducto API with the synthetic `psw_lab.pdf` document:
Reducto reads the clean source text as "PSW" correctly (confirming the
document really does say PSW, not PSV — the original OCR-misread
premise), and the resolver leaves it fully unresolved on the clinical
axis. `raw_test_name`/`provider_extracted_name` is never mutated by any
of this, in either direction — the provider's literal "PSV" (or "PSW")
stays intact in the stored row regardless of resolution outcome.

**Vendor-specific escape hatch, unused by default**:
`VENDOR_SPECIFIC_ALIASES: dict[str, list[dict]] = {}` in
`lab_resolver.py` — empty, with a commented example showing the shape
real evidence would take (vendor name, source document reference,
analyte code). If institution-specific analyzer documentation is ever
found establishing what "PSW" means for a specific lab/vendor, it goes
here, scoped to that institution, not into the global synonym catalog.
Nothing currently populates it.

**Tests** (`backend/tests/test_lab_resolver.py`, 15 cases, all passing):
`test_no_psw_alias_in_real_catalog` (fails if `"psw"` or `"platelet
size width"` reappears anywhere in `synonyms.py`'s real catalog),
`test_psv_is_genuinely_unresolved_on_both_axes_without_evidence`
(replaces the old, wrong "PSV resolves to PDW" assertion),
`test_text_matched_unverified_candidate_resolves_text_but_not_clinical_meaning`
and `test_text_matched_unverified_vs_verified_same_similarity_different_outcome`
(prove the two-axis split with a fictional test-local fixture — same
similarity score, different `clinically_verified`, different outcome —
so the mechanism is independently exercised, not just asserted),
`test_provider_raw_text_is_never_mutated_regardless_of_outcome`,
`test_vendor_specific_mapping_is_empty_by_default`, plus every
pre-existing case from §11a re-verified against the rewritten resolver
(legitimate CBC/metabolic terms still resolve exactly at confidence
1.0, no hardcoded PSV mapping, cross-catalog dedup still correct).

**What this does NOT establish**: PSW does not have an independently
verified clinical meaning in this system. It is not mapped to PDW or
anything else. If a future document needs PSW resolved, that requires
either (a) real published vendor/analyzer documentation entered into
`VENDOR_SPECIFIC_ALIASES` with a cited source, or (b) a generically
justified, source-cited addition to the real catalogs — not another
guess.

### 12b. Popup audit completion

§11c's "what still remains centered" list was reviewed and closed out.

**Converted this round** (routine/contextual to anchored `Popover`, a
new primitive in `components/ui/index.tsx`: controlled, positioned off
a `RefObject` trigger, no backdrop, closes on outside-click/Escape,
becomes a bottom sheet under 640px via CSS media query):
- **Revoke doctor access** / **regenerate care-partner code**
  (my-records/access/page.tsx) — each row's action button gets its own
  anchored Popover; for the list case (revoke access, one button per
  row) the open target is tracked by id and compared per-row rather
  than a single shared ref, since any row can be the trigger.
- **End doctor-patient assignment** (admin/doctors/[id]/page.tsx) — the
  action lives inside a `DataTable` `render` callback where hooks can't
  be used directly, so it's a small local component
  (`EndAssignmentAction`) with its own `useState`/`useRef`, rendered
  once per row.
- **Featured-analyte picker**, both the patient's own view
  (my-records/page.tsx) and the doctor's view (patients/[id]/page.tsx)
  — was a page-level centered `Dialog`; now an anchored `Popover` off
  the "Change" trigger in `SectionHead`.

**Reviewed and kept centered, each with its reason documented in the
code itself (not just here)**:
- **Emergency session-start** (`emergency/search/page.tsx`'s `confirm`
  dialog, and `emergency/workspace/page.tsx`'s `AddPatientModal`) —
  granting read access to a real patient's record, written to the audit
  log: a genuine blocking/critical workflow, not routine. Also has no
  single stable anchor point (the trigger can be any row in a search
  result list, or either of two separate entry points in the
  workspace). No dark backdrop; the surface itself stays centered for a
  stable, predictable location during a time-pressured workflow.
- **Document deletion** (`documents/[id]/page.tsx`,
  `documents/[id]/discharge/page.tsx`) — permanently removes something
  from a patient's medical record; irreversible. Unlike revoke-access
  (reversible relationship change) or regenerate-code (reversible,
  non-destructive), this carries the same weight as account deletion,
  so it keeps the centered, more prominent confirmation surface rather
  than being downgraded to a lightweight anchored popover. No dark
  backdrop.
- **Account deletion** (`my-records/settings/page.tsx`) — irreversible,
  removes the user's access and data entirely; unchanged from §11c
  (comment reworded to match this section's framing), still requires
  typing a confirmation phrase. No dark backdrop.

**Full audit method, not just a targeted look**: grepped the entire
frontend for every remaining `Dialog`/`ConfirmDialog` usage (two hits:
the documented emergency-search exception, and the component
definitions themselves), every custom `role="alertdialog"` modal (the
three named above — nothing else in the codebase uses that pattern),
every `zIndex: 999`/`zIndex: 1000` overlay (same three files, no
others), and every `position: "fixed"` block across `app/` and
`components/` (the rest are theme/language-toggle corner widgets and
full-page loading spinners — not popups, not in scope). This accounts
for every centered surface in the application; there is no remaining
undocumented centered dialog.

**Verification**: `npx tsc --noEmit` clean across the frontend; `npm
run build` (Next.js/Turbopack) succeeds, all 33 routes compile; `eslint`
run on every touched file — the only pre-existing errors it surfaces
(`react-hooks/set-state-in-effect` in `patients/[id]/page.tsx`,
`my-records/page.tsx`, `emergency/workspace/page.tsx`) are confirmed via
`git stash` to be unrelated to this round's changes (present on
unmodified files, same line numbers); the two new unused-variable
warnings in `my-records/settings/page.tsx` are leftover dead state from
before this round's comment-only edit there, not introduced by it.
Backend: `pytest -q`, 57 passed.

## 13. Visual/interaction correction pass (upload compaction, bloodwork-state bug, viewer lifecycle, lab-row source framing, PDF quality)

Five screenshot-reported problems plus explicit design requirements (a
little more restrained color, no popup regressions). Root-caused and
fixed each; not a redesign of anything working.

### 13a. Upload page: one coherent workspace, not three stacked cards

**Root cause**: `my-records/upload/page.tsx` (and the doctor-side
`patients/[id]/upload/page.tsx`) rendered the dropzone, the file queue,
and the empty state as three separate `<section className="b-surface">`
cards, each with its own full padding — plus a redundant bottom-bar
"Continue" button that did nothing but `router.push("/my-records")`,
silently discarding any locally-picked-but-not-yet-uploaded files with
no confirmation. The queue's own `EmptyState` fallback duplicated what
the dropzone was already saying.

**Fix**: merged into one `<section>` — dropzone, queue, and the single
upload action all live inside it. A new `.b-drop-compact` CSS variant
(`app/globals.css`) collapses the dropzone to a single row once at
least one file is queued (icon + hint text + inline "Browse files"),
keeping it functional as a drop target without eating vertical space
the queue now needs; the full-height dropzone still renders when
nothing is queued yet, since there's nothing else to show. Removed the
separate `EmptyState` card entirely — the dropzone already communicates
"nothing selected." Removed "Continue": leaving via the header's
existing "Back" button already covers cancelling, and the one remaining
button ("Upload (N)") only appears once there's a local file to
actually send, so there's exactly one primary action at a time instead
of two competing ones. Applied identically to the doctor-side upload
page, additionally folding its previously-separate "document type"
section picker into the same card's header instead of its own white
card above the dropzone.

### 13b. Overview: false "No bloodwork data yet" despite real counts

**Root cause, found in `my-records/page.tsx`**: the `featuredTrend`
`useMemo` filtered `sortedTrends` down to only trends that are
abnormal AND have a second reading to compute a percentage delta
against, then returned `null` if nothing survived that filter — even
when `sortedTrends` itself was non-empty. `featuredPanel` renders the
empty state whenever `featuredTrend` is null, so a patient whose labs
are all currently in range (nothing "abnormal"), or who only has a
single reading per analyte so far, saw the real `Records: 3 / Bloodwork:
3 / Labs: 29` metrics right next to a false "No bloodwork data yet" —
exactly the contradiction in the screenshot. This was never a caching
or stale-data bug — every data source involved (`/my/profile`,
`/patients/{id}/bloodwork-trends`) was already being refreshed
correctly (see the existing `refreshRecordsSilently` triggered by both
the `bloodwork-upload-complete` window event and a 4s poll while an
upload is active — both pre-existing and correct, not touched here);
it was a display-logic bug in how "nothing to feature" was
distinguished from "no data."

**Fix**: when no trend qualifies as "abnormal and moved most," fall
back to `sortedTrends[0]` (already abnormal-first sorted) instead of
`null` — the same fallback pattern the manual `featuredOverride` picker
already used. The real "no bloodwork data yet" empty state now only
renders when `sortedTrends.length === 0`, i.e. when there genuinely
are no lab observations at all (case A in the spec's own state
breakdown). Added an honest single-reading state too: when the
featured analyte has exactly one point, the chart (which already
rendered a single dot safely — verified in `components/ui/trend.tsx`,
guarded against divide-by-zero) now shows "Only one reading so far — a
trend line needs at least two" instead of either a misleading empty
message or an unexplained flat dot. The doctor-side equivalent
(`patients/[id]/page.tsx`) already had the correct fallback
(`pool = abnormals.length ? abnormals : sortedTrends`) — this bug was
isolated to the patient-facing page.

### 13c. Source viewer lifecycle: now route-aware, closes on Back/navigation/patient switch

**Root cause**: `SourceViewerProvider` (`components/source-viewer/
source-viewer-context.tsx`) had no concept of route/context at all —
`isOpen` only ever changed via explicit `openSourceEvidence()`/`close()`
calls. Since the provider is mounted once at the root layout (by
design, so `openSourceEvidence` works from anywhere), the viewer
stayed open across any navigation, including pressing Back out of the
document page that opened it — the user had to close it as a separate
step, exactly the screenshot's complaint.

**Fix**: the provider now tracks `usePathname()` and closes the viewer
(and drops the cached PDF document — `loadedDocumentIdRef`/
`loadedPdfRef` — so the next `openSourceEvidence` on the new page can't
silently reuse a document left over from wherever the user came from)
whenever the pathname actually changes. Deliberately pathname-only, not
full-URL: query-string-only navigation — the `?lab=` chart deep link,
or clicking between two lab rows' "View in original" on the SAME
document page — does not change pathname, so switching evidence within
a page still works exactly as before (no unwanted close mid-comparison).
Pressing Back, moving to another top-level route, and switching patient
(`/patients/{id}/...` → `/patients/{otherId}/...`) all change pathname,
so all three are covered by one mechanism rather than three special
cases. The very first render is skipped (via a ref holding the initial
pathname) so mounting the provider on a page that's about to open a
viewer doesn't immediately close it.

### 13d. Selected lab row (purple) + restrained hover gradient

**New capability, real evidence-backed, not a visual-index toggle**:
`/source-evidence/{id}/view` now also returns `lab_result_id` (already
stored on `SourceEvidence`, previously just not exposed in this
response — `backend/app/main.py`). The document detail page
(`documents/[id]/page.tsx`, shared by both patient and doctor views)
reads the currently-open viewer's `data?.lab_result_id` and compares it
per-row to give the row a `source-open-row` class: a pale
`--brand-50` background plus the same 2px inset left-edge marker
language already used for abnormal rows, so it reads as "part of the
same design system," not a one-off. Selection deliberately wins over
hover (declared later in the stylesheet, more specific selector) and
clears automatically when the viewer closes (state is derived, not
separately tracked) or the evidence changes to a different row.
`LabSourceAction`'s own button also gets a matching subtle active tint
(`.b-source-action-active`) — not a bigger button, just enough to match
the row's own signal.

Hover: `.document-lab-table tbody tr:hover td` changed from a flat
`--surface-hover` fill to a left-to-right gradient tinted a few percent
toward `--brand-500`, gated behind `@media (hover: hover)` so a
touchscreen's synthetic, non-dismissable "hover" after a tap never
triggers it (per the spec's explicit "do not simulate hover on touch").

### 13e. Lab PDF highlight: full row, framed not painted-over

**Root cause of the too-small highlight**: `extract_lab_results()`
(`backend/app/services/reducto_extraction.py`) always picked exactly
one field's citation bbox per lab row (the value's, falling back to
the test name's) as that row's entire `SourceEvidence` geometry — so
the highlight was always a single cell, never the row.

**Fix — real geometry, a second axis, not a guess**: added
`row_bbox_x/y/width/height` columns to `SourceEvidence` (nullable,
additive migration in `main.py`) as a presentation-only region,
computed by a new pure function `_union_row_bbox()` in
`reducto_extraction.py`: it unions whichever field-citation bboxes
Extract actually returned for that row (test name, value, unit,
reference range — real, independently-returned geometry, filtered to
the row's majority page if Reducto ever split citations across a page
break), then pads the union outward — proportionally, in the same
normalized page-fraction coordinate space as the bboxes themselves, so
the padding scales correctly at any zoom/resize rather than needing a
fixed-pixel correction — before clamping to page bounds `[0, 1]`.
Requires at least two real field bboxes to union; with fewer than that
(nothing wider than the existing single-field bbox to compute) it
returns `None` and the frontend falls back to the raw `bbox_*`, so
non-lab evidence or a thin row is never given a fabricated region. The
original per-field `bbox_x/y/width/height` is never touched — it stays
exactly as before, the untouched provenance/debugging record; the row
region is additive, derived, presentation-only, and lives in its own
columns. Five new unit tests
(`backend/tests/test_reducto_row_bbox.py`) prove: the union spans both
input boxes with visible padding on every edge, padding clamps to page
bounds instead of pushing outside `[0, 1]`, fewer than two real boxes
correctly returns `None` rather than a guess, a stray citation on a
different page is excluded rather than unioned across the break, and
degenerate zero-size boxes don't produce a region. Full backend suite:
62 passed (57 + 5).

**Frontend — outline does the framing, fill stays out of the way**
(`components/source-viewer/source-viewer-panel.tsx`,
`app/globals.css`): the panel now prefers `row_bbox_*` when present,
falling back to `bbox_*` otherwise — same `showBbox`/highlight code
path either way, just a different source rectangle. `.b-source-highlight`
changed from a solid 2px border + 18%-opacity fill (visibly sitting
over the text) to a 1.5px border at the (already-padded, for lab rows)
region edge, a CSS `outline` 3px further out for extra breathing room
that doesn't touch the element's own painted background, and the fill
dropped to 6% — enough to read as "this region" without competing with
the printed characters underneath. `outline-offset` gives even
non-lab, non-row-padded single-field bboxes some frame-not-cover
behavior for free, without needing separate padding logic on the
frontend. A soft box-shadow adds a little presence without becoming a
heavy glow.

### 13f. Blank/tiny PDF viewer

**Root cause, found by tracing the actual CSS, not assumed**:
`.b-source-viewer-canvas-wrap` had no size of its own in `globals.css`
— its width/height came entirely from an inline style set by JS, and
only inside the async page-render effect, after `await
pdfDoc.getPage(currentPage)` resolved. Before that first successful
render (or if a render never completes), the wrapper had no definite
size, so it — and everything positioned against it in percentages,
including the loading overlay and the bbox highlight — collapsed
toward its content's intrinsic size, which for an unset `<canvas>` is
the HTML-default 300×150px. That collapse is what "no pdf bragi.png"
actually shows: a small box instead of a full-size page. A second,
independent contributor: `computeFitWidth()` measured
`containerRef.current.clientWidth` synchronously on mount, which can
be near-zero for a frame or two right after the split pane first
renders (before the flex layout has actually resolved) — committing
that measurement drove `fitWidthScale` down to `MIN_SCALE`, compounding
the collapse. Neither of these needed the PDF.js worker or the
authenticated file fetch to be broken at all (both were independently
confirmed intact — the production build correctly emits and references
`/_next/static/media/pdf.worker...mjs`, and the arraybuffer fetch path
through `lib/api.ts` has no interceptor that could corrupt binary
data) — this was purely a layout-collapse bug in a viewer that was
otherwise functioning.

**Fix**: `.b-source-viewer-canvas-wrap` now has a CSS floor
(`min-width: 280px; min-height: 360px`) so it never visually collapses
regardless of JS timing, before or after any render attempt.
`computeFitWidth()` now skips committing a measurement narrower than
80px rather than accepting a degenerate scale — the `ResizeObserver` it
already sets up fires again once the container has real layout, so this
just means "wait for a real measurement" instead of "commit a wrong
one." The page-render loading state (`pageRendering`) now shows an
actual spinner + "Rendering page…" text (previously just a bare
translucent tint with nothing in it) so an in-progress render is
visually distinguishable from a failed/blank one, and a page-render
failure (`renderError`) now gets its own visible retry button
(`.b-source-viewer-page-error`, wired to a `renderRetryKey` counter
that re-triggers the render effect) — previously only the document-load
failure path (`error`) had a retry button; a page-level render failure
just showed inert text with nothing the user could do about it.

### 13g. PDF render quality (devicePixelRatio)

`source-viewer-panel.tsx`'s render effect previously sized the canvas
buffer (`canvas.width`/`canvas.height`) exactly to the CSS-pixel
viewport, with no `devicePixelRatio` scaling — soft/blurry text on any
HiDPI/Retina display. Now the canvas buffer is sized at
`viewport.width/height * dpr` (dpr capped at 2 — real quality gain
beyond that is imperceptible for document text and not worth the extra
memory on a 3x+ device), while `canvas.style.width/height` and the
wrapper's inline size stay at the un-scaled viewport size — so this
only affects sharpness, never the percentage-based bbox highlight
alignment, and zoom already re-renders the page at the new PDF.js scale
(not a CSS stretch of the old bitmap) exactly as it did before this
round — that part was already correct and needed no change.

### 13h. A little more color (restrained)

Two additions, both reusing existing tokens rather than introducing new
ones: the four `stat-card-accent-*`/`stat-pill-*` classes
(`app/globals.css`) were previously inert placeholders — all four
shared identical neutral styling despite being separately named
violet/blue/green/orange. Gave each a real 2px tinted top border plus a
~4%-tinted background wash (`--brand-500`/`--info`/`--ok`/the existing
chart-3 orange as `--warning` fallback) and matching pill text color —
still just accenting existing surfaces, not new saturated cards. The
active sidebar/nav item (`.b-nav-item[aria-current="page"]`) gained a
2px inset left-edge marker in the same visual language as the abnormal-
row and selected-lab-row markers, for a touch more presence without
changing its existing background/text color treatment.

### 13i. Verification

- Backend: `pytest -q` → 62 passed (57 existing + 5 new
  `test_reducto_row_bbox.py` cases).
- Frontend: `tsc --noEmit` clean; `npm run build` (Turbopack) succeeds,
  all 33 routes compile; `eslint` on every touched file — the only
  pre-existing findings it surfaces (`react-hooks/set-state-in-effect`
  in `my-records/page.tsx`, two pre-existing unused-variable warnings)
  are confirmed via `git stash` to predate this round's changes,
  present on unmodified files at the same lines; one new warning this
  round introduced (an unnecessary `eslint-disable` comment left over
  from an earlier draft of the route-aware close effect) was found and
  removed.
- Real production build inspection (not assumed): confirmed the actual
  `.next` output correctly emits the PDF.js worker as a static asset
  and the client bundle references it at the correct absolute
  `/_next/static/media/...` path, ruling out worker-bundling as a
  contributor to the blank-PDF bug before attributing it to the CSS
  layout-collapse root cause above.
- Not run this round: live browser/Playwright QA of the actual pixel
  layout at each named breakpoint, or a live re-upload through the real
  Reducto API to visually confirm the new row-bbox highlight against a
  real rendered lab PDF — same longstanding blocker as every prior
  round (no `BRAGI_TOKENS`). The row-bbox geometry math itself is
  covered by the 5 new unit tests instead of a visual pass; the CSS/
  layout fixes (compact upload, viewer collapse, hover/selected states,
  color) were verified by direct source/build inspection and are
  architecturally sound, but were not visually confirmed in a live
  browser this round — an honest limitation, not a silently-assumed
  pass.
