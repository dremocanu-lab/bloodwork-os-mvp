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

### Is `REDUCTO_ENABLED=true` safe now?

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
