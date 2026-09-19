# Source Geometry + Clinical Table Intelligence V3 — Handoff

**Status: complete, including real-browser verification — NOT merged.**
Branch `fix/source-geometry-table-intelligence-v3`, off `main` post Source
Intelligence + Provenance V2 (PR #10, `1801dbb`). A follow-up session ran
the backend work in this document through an ACTUAL browser against a
real, attached PDF file (see §9A) — this found and fixed two real bugs
that no backend-only test had caught, described below.

## 1. The gap this phase closes

Before this session, every clinical fact resolved to "correct document,
correct page" at best (`page_only` precision, from Source Intelligence +
Provenance V2). Nothing resolved to a real paragraph, table row, or cell —
`SourceEvidence.bbox_*`/`field_bboxes_json` existed on the schema but were
only ever populated for Reducto-sourced lab citations, never for the
discharge pipeline's own pages, and `SourceSegment.table_data` was a field
reserved since Clinical Document Intelligence V3 but never once populated.
This phase makes "here is the exact paragraph/row/cell" real wherever the
underlying extraction genuinely supports it — never fabricated.

## 2. Architecture decision: PyMuPDF-primary, Reducto evaluated and NOT
adopted for discharge geometry

The task explicitly required evaluating Reducto vs. the current pipeline
with real evidence, not assumption, before choosing. What was verified:

- **PyMuPDF (`fitz`) is already a project dependency**, already opened once
  per discharge page (`discharge_summary_pipeline.py::_render_pdf_pages_
  as_data_urls`) purely to rasterize the page for the OpenAI vision call.
  `page.get_text("blocks")` and `page.find_tables()` give real, normalized,
  zero-latency, zero-cost paragraph and table/row/**cell** geometry from
  that SAME already-open page handle — no second extraction pass, no
  external API call, no added cost per document.
- **A live Reducto benchmark was run** (`REDUCTO_API_KEY` present in this
  environment) against the real 8-page synthetic fixture built for this
  phase: `upload()` + `parse(table_output_format="md")` completed in a few
  seconds (single observed run: ~2.1s upload, ~3.4s parse) and returned
  ~25 text blocks with bbox precision comparable to PyMuPDF's own — but
  its **table output gave exactly ONE whole-table bounding box per table,
  no per-row or per-cell geometry**. PyMuPDF's `find_tables()` gives real,
  separately-addressable cell bboxes (`table.cells`) directly.
- **Conclusion, evidence-based, not "replace because Reducto exists" nor
  "refuse Reducto because a pipeline exists":** for the discharge
  pipeline's PDFs specifically, PyMuPDF is strictly better for geometry
  (cell-level vs. whole-table) at zero cost, and the existing OpenAI-vision
  transcription remains authoritative for TEXT (it already correctly
  recovers semantics from scanned/rotated/low-quality pages PyMuPDF's raw
  text layer cannot). Reducto is not wired into the discharge geometry
  path. This does not touch Reducto's existing, unrelated use for lab/
  reader document types (`/parse`+`/extract`) — that is unchanged.
- **Final provider strategy**: PyMuPDF native text layer → geometry
  (blocks/tables/cells, this phase). OpenAI page-vision → semantic text
  transcription (unchanged, pre-existing). Bragi's own deterministic
  extractors + table classifier → structure and clinical meaning. A
  conservative text-alignment layer (`geometry_alignment.py`) is the only
  place geometry and vision-transcribed text ever meet, and it never lets
  one silently overwrite the other — see §4.

## 3. New modules (committed in earlier commits this branch, unchanged
this session)

- **`source_geometry.py`** — `extract_page_geometry(page, page_number)`:
  pure, deterministic, no external API. Returns normalized `[0,1]`,
  top-left-origin bboxes (the SAME contract `SourceEvidence.field_bboxes_
  json` already used) for real paragraph blocks and tables/cells.
  `page.rotation_matrix` is applied before normalizing — the previously-
  deferred rotation bug — verified at all four rotation angles (0/90/180/
  270°): page dimensions swap correctly, every bbox stays in `[0,1]`.
  A page with no real native text layer (scanned) yields empty geometry,
  never a fabricated one.
- **`geometry_alignment.py`** — `align_segment_to_blocks(text, page_
  geometry)`: conservative single-block-containment and multi-block-
  coverage matching between the vision pipeline's own transcribed text and
  PyMuPDF's independently-extracted blocks. Returns `[]` (never a guess)
  when the match isn't confident, including when geometry is unavailable.
  Never edits segment text — only ever attaches WHERE a fact is.
- **`table_interpreter.py`** — the generic Clinical Table Interpreter.
  14-value closed `ClinicalTableType` enum (laboratory, medication_list,
  prescription, administered_treatment, diagnosis, investigation,
  vital_signs, procedure, recommendation, administrative, encounter_
  history, empty_template, other, uncertain). Deterministic column-header/
  heading-context classification first (reusing Clinical Reader Intelligence
  V2's `is_template_placeholder_text` for empty-template detection — empty
  wins even over lab-shaped headers); a structured, mockable OpenAI
  Responses-API fallback only for genuinely ambiguous tables, never asked
  to regenerate cell values, and its output is validated server-side
  against the closed enum even though the JSON schema already constrains
  it (never trust the model's JSON merely because it parsed).
- **A real synthetic PDF fixture** (`tests/fixtures/clinical_reader_v3_pdf_
  fixture.py`) — 8 real pages built with PyMuPDF's own write API (D45 /
  phlebotomy+admission-anomaly / medication table / 4 distinct narrative
  paragraphs (ultrasound, JAK2, bone marrow, BCR-ABL) / prescription table
  + anomalous date / lab table with a real ALT row and two conflicting HGB
  rows / recommendations / two blank template tables) — used by every test
  below instead of hand-typed fake geometry.

## 4. This session's work: wiring geometry into the real extraction
pipeline

The previous commits built the geometry/classification primitives but
never connected them to anything that persists data. This session did:

- **`segments.py::build_segments_from_legacy_discharge_payload`** now
  parses `page_payloads[*]["geometry"]` and, for the segment that
  uniquely OWNS a page's table (its own canonical heading classifies as
  laboratory_results/medications/discharge_medications/prescriptions/
  treatment — not merely "the only segment on the page", since a table
  page can legitimately carry an unrelated narrative segment too, as the
  fixture's page 5 does), classifies that page's real table(s) and — ONLY
  for types that route into an existing canonical pipeline (laboratory,
  medication_list, prescription) — populates `SourceSegment.table_data`
  with real headers/rows AND per-cell bboxes (`SegmentTableData.cell_
  bboxes`, parallel to `rows`). `administered_treatment` is deliberately
  EXCLUDED from this routing (never auto-labeled a medication — an
  explicit V3 requirement); `empty_template` and every other
  non-routable type never populate `table_data` at all — the geometry
  stays real, retrievable source structure, but never becomes a
  fabricated clinical candidate. Two-or-more qualifying tables/segments on
  one page stay unenriched (ambiguous → fall back), never guessed.
- **`lab_extraction.py` / `medication_extraction.py`** — `_extract_from_
  table` now returns real per-row geometry alongside each reconstructed
  text line: a `primary_bbox` (the single most specific cell — the VALUE
  cell when a header confidently identifies it, else the row union),
  `row_bbox` (union of every real contributing cell), and `field_bboxes`
  (every real per-cell rect, labeled by field — `name`/`value`/`unit`/
  `reference_range`/`flag` for labs). This is real, verbatim `TableGeometry`
  cell data — never a character-width estimate. Both modules also gained a
  guard (reusing `template_detection.is_template_placeholder_text`) that
  stops a segment whose ENTIRE raw text is known template noise (bare
  "PRODUS"/"CANTITATE"/"EKG" placeholder words) from ever being read as a
  medication/lab candidate — a real, previously-latent bug this phase's
  own fixture caught (a blank-template segment's placeholder text was
  parsing "PRODUS" as a medication name).
- **`lab_persistence.py`** — `SourceEvidence.bbox_*`/`row_bbox_*`/`field_
  bboxes_json` are now populated from `LabCandidate.primary_bbox`/`row_
  bbox`/`field_bboxes` on first creation, AND a new `_upgrade_lab_evidence_
  bbox` upgrades an ALREADY-persisted lab row's evidence in place on a
  later reprocessing pass that now has real geometry (fills null fields
  only — never regresses an already-geometry-bearing row).
- **`reprocessing.py::_attach_segment_evidence`** — every section's own
  text is now run through `align_segment_to_blocks` against its page's
  real geometry; a confident match upgrades that segment's `SourceEvidence`
  bbox in place via `ensure_segment_evidence`'s new upgrade semantics.
  Separately, EACH `ClinicalEvent` is also aligned against its OWN raw
  text (not just its parent segment's) and gets its own, separate
  `SourceEvidence` row when a confident match exists — this is what
  prevents the explicitly-called-out failure mode of one whole Clinical
  Course section's evidence being shared by every narrative fact inside
  it (verified directly: JAK2/bone marrow/ultrasound/BCR-ABL — four facts
  the fixture places on the same page 4 — resolve to four genuinely
  distinct `SourceEvidence` rows with four distinct real bboxes).
- **`source_evidence.py::ensure_segment_evidence`** — extended with
  optional `bbox`/`field_bboxes` params and real upgrade-in-place
  semantics: an existing row with no bbox gets one filled in from a later
  pass's better geometry (same id, never a duplicate "View source" button
  for the same fact); a row that already has a bbox is left untouched.
- **`canonical_headings.py::consolidate_segments`** — a table-bearing
  segment's real headers/rows are now ALSO preserved as a `TableBlock` on
  the persisted `ClinicalSection` (the existing schema.py block type,
  previously unused for this) — this is what lets a SECOND reprocessing
  pass recover the table's TEXT (not geometry — only available on the
  first pass, from the legacy payload) via `reprocessing.py::_segments_
  from_structured_document`, so lab/medication idempotency matching still
  finds the same rows on re-run instead of silently losing every
  table-derived candidate after the first pass.

No new SQL tables, no Alembic migration — every geometry/evidence field
reused columns that already existed on `SourceEvidence`
(`bbox_*`/`row_bbox_*`/`field_bboxes_json`) or were added to Pydantic-only
intermediate models (`SegmentTableData.cell_bboxes`/`source_table_id`,
`LabCandidate.primary_bbox`/`row_bbox`/`field_bboxes`) — confirmed via
`alembic heads` (still a single head, unchanged).

## 5. Verified end to end (real reprocessing run, real DB, real fixture)

`tests/test_clinical_document_reprocessing_geometry_v3.py` runs the ACTUAL
`reprocess_discharge_document()` against the real 8-page fixture (not a
hand-typed JSON stand-in):

- The lab table produces 3 real `LabResult` rows (ALT + two conflicting
  HGB values, both preserved — never silently deduped); ALT's
  `SourceEvidence` has `bbox_x` set (`exact_bbox` precision, not
  `page_only`) and `field_bboxes_json` with exactly 4 real cells (name/
  value/unit/reference_range).
- The medication and prescription tables produce real `PatientMedication`
  rows.
- The four page-4 narrative facts (ultrasound/JAK2/bone marrow/BCR-ABL)
  each resolve to a distinct `SourceEvidence` row with a distinct real
  bbox — 4 rows, 4 rectangles, never one shared blob.
- The two page-8 blank template tables (PRODUS/CANTITATE, EKG/ECO/RX/
  ALTELE) never produce a `PatientMedication`/`LabResult` row.
- Running reprocessing twice produces the SAME row counts (no
  duplication) and the SAME evidence bboxes (no churn, no regression).

Plus the pre-existing suites for `source_geometry`/`geometry_alignment`/
`table_interpreter`/the fixture itself (28+10 tests from the earlier
commits) and the full `clinical_document`-scoped + broader regression
sweep (444 tests) all pass unchanged.

## 6. Precision hierarchy achieved

| Fact | Before this phase | After |
|---|---|---|
| ALT / HGB lab values | `page_only` | `exact_bbox`, 4 real cells each |
| Medication/prescription rows | `page_only` (or nothing — tables were invisible to extraction) | `exact_bbox`, real row cells |
| JAK2 / bone marrow / ultrasound / BCR-ABL | one shared `page_only` evidence per whole section | 4 distinct `exact_bbox` paragraph evidences |
| D45 diagnosis, recommendations | `page_only` | `exact_bbox` paragraph block (via segment-level alignment) |
| Empty/template tables | N/A (not tracked) | real geometry retained, clinically suppressed |

## 7. Security / cost / scope discipline maintained

- No new cross-patient access surface; every new geometry/evidence write
  goes through the SAME `document_id`-scoped queries the existing
  idempotent persistence functions already used.
- Table classification is done ONCE per table (never per-row); deterministic
  rules run first and are the ONLY path exercised by CI (no live OpenAI/
  Reducto call required — mocked in every test); the Reducto benchmark in
  §2 was a manual, one-off comparison run, not a CI dependency.
- Table cell content is treated as untrusted data by the classifier prompt
  (same discipline as `ai_interpreter.py`) — never given tool access.
- No PHI (raw paragraph/cell text) appears in this document or in any log
  line touched this session.

## 8. Non-goals honored

Ask Bragi Phase 11, Emergency V2, and a Clinical Reader IA redesign were
explicitly out of scope and untouched. The source viewer/highlight
frontend component was NOT modified — it already generically renders
`field_bboxes` (arbitrary label, arbitrary count) and gates on
`precision === "exact_bbox"`, exactly the contract this phase's backend
work now populates correctly; verified by reading `source-viewer-panel.tsx`
directly, not assumed.

## 9A. Real-browser verification (follow-up session)

A dedicated follow-up drove the ACTUAL reader UI in a real browser
against a REAL PDF file, using the real reprocessing pipeline end to end
— not mocked frontend evidence, not JSON-payload-only tests. This is the
first suite in the whole engagement to attach a real file to
`Document.saved_to` so the PDF.js-backed source viewer genuinely renders
pages and draws highlight rectangles.

**What was built**: `backend/scripts/seed_e2e_source_geometry_v3_document.py`
writes the real 8-page fixture PDF to disk, creates a `Document` row
pointing at it, and runs `reprocess_discharge_document` for real (AI
interpreter mocked, everything else real) — producing real canonical
`LabResult`/`PatientMedication` rows and real `SourceEvidence` bbox/
`field_bboxes_json`. `frontend/e2e/source-geometry-table-intelligence-v3.spec.ts`
(16 tests, all passing) drives the reader against this seeded document:
D45 diagnosis; historical phlebotomy; the four page-4 narrative facts
(ultrasound/JAK2/bone marrow/BCR-ABL) each proven to land on a distinct
rectangle; prescription and medication table row/cell highlighting;
ALT's 4-cell multi-rect; a recommendation paragraph; an anomaly with its
suspicious value kept verbatim; A→B→A and same-evidence-twice state
transitions; viewer-already-open; a resize sweep (1440/1280/1024/768)
checked for genuine geometric (not just DOM-existence) alignment; both
mobile breakpoints; dark mode; and the page-only precision fallback
(asserting zero rendered rectangles, not just a notice).

**Screenshots were generated AND actually inspected** (not just asserted
on) at each of these steps — this is what caught two real bugs no
backend-only or count-only assertion had caught:

1. **Table cell geometry was scrambled** (`source_geometry.py`).
   PyMuPDF's `table.cells` list is COLUMN-major (all rows of column 0,
   then all rows of column 1, ...); the code assumed row-major
   (`row_index = cell_index // col_count`), silently pairing every real
   cell bbox with the WRONG grid position whenever a table had more than
   one row. This never showed up as a text bug — `extract_rows()`
   re-derives text using that same wrong label for both the fetch and
   the placement, a self-cancelling bijection that left every text-only
   assertion (including this phase's own unit tests) passing. It only
   showed up as a geometry bug, and only visibly: the first ALT
   screenshot showed 4 highlighted rectangles as REQUIRED by the count
   assertion, but they were actually the "Rezultat" header cell plus
   the Result-column cell of ALL THREE lab rows (ALT + both HGB rows) —
   one column, not one row. Fixed to `col_index = cell_index //
   row_count`, `row_index = cell_index % row_count`; a new geometric
   (not text-only) regression test in `test_source_geometry.py` checks
   every cell in a row shares one y-band and sorts left-to-right by
   column — confirmed to fail against the old formula and pass against
   the fix. Re-verified visually after the fix: ALT's screenshot now
   shows exactly ALT/56/U/L/10-49, never a neighboring row's cells.
2. **Prescriptions had no reachable "View source" action at all**
   (`app/documents/[id]/discharge/page.tsx`). `canonical_key ===
   "prescriptions"` fell through to the generic block renderer, which
   draws a plain HTML table with no evidence wiring — invisible before
   this phase's work (no prescription table had ever produced a real
   canonical medication to show), surfaced only once table routing
   started actually populating them. Fixed by rendering `prescriptions`
   through the same `MedicationList` component `medications`/
   `discharge_medications` already use — no new rendering path.
3. **A latent extraction-precision bug**, caught earlier in this same
   verification pass before it reached the browser (via direct DB
   inspection of the seeded document): a table's own placeholder pointer
   sentence ("Vezi medicatia structurata de mai jos.") was being parsed
   as a medication NAMED that whole sentence. Fixed in
   `medication_extraction.py` — see the commit "Wire real per-cell
   geometry into medication candidates too" for detail; unrelated to the
   two bugs above but found in the same session and fixed alongside them.

**Regression suites re-run after the fixes, all green**: full backend
pytest (832 passed), the broader `clinical_document`/geometry-scoped
sweep (364 passed), and the frontend Playwright suites named in the
follow-up request — `source-intelligence-provenance-v2`,
`exact-provenance`, `clinical-reader-intelligence-v2`, `clinical-reader`,
`derived-lab-artifact`, `right-workspace-geometry`, `ask-bragi-workspace`,
`ask-bragi-layout-stability`, `upload-reliability`, `processing-indicator`,
`timeline-projection` (58 passed, 0 failed). Frontend `tsc --noEmit`
clean; ESLint baseline gate clean (29 errors, all pre-existing, baseline
allows 30 — zero new); production build succeeds; `alembic heads` still
a single head; migration drift clean.

## 9. Known limitations / explicitly NOT done this session

- **Event-level alignment only helps when `ClinicalEvent.raw_text` is
  itself narrow.** The current pipeline already produces one `SourceSegment`
  per semantic narrative unit for the discharge documents this fixture
  models, so segment-level alignment already gives each fact its own
  block in the common case; a document where several genuinely distinct
  dated facts get merged into ONE segment's `raw_text` (uncommon in
  current output, but architecturally possible) would still show them
  sharing one evidence rectangle until `events.py` is changed to extract a
  narrower per-event text window — not attempted this session, to avoid
  touching the tested, established `ClinicalEvent.raw_text` contract
  without a concrete failing case driving it.
- **Table-data reconstruction on a second reprocessing pass recovers text,
  not geometry** (§4, `consolidate_segments`) — by design: geometry
  evidence already exists in the DB after the first pass and is only ever
  reused, never regressed, so this is a deliberate, safe simplification,
  not an oversight — but a genuinely NEW table appearing only after a
  second pass (e.g. a corrected re-upload of the same document) would only
  get page-level fallback for that specific new table until a fresh
  first-time reprocess of a NEW document.
- **Non-PDF locators (DOCX/XLSX/CSV/JSON/XML) were not touched this
  session** — existing non-PDF evidence behavior is unchanged (no
  regression), but no new semantic-locator work for those formats was
  attempted.
- `docs/CURRENT_STATE.md` and related architecture docs were not updated
  this session.
- **Screenshot QA at every literal viewport/theme cell the original spec
  listed was not exhaustively captured as a permanent artifact** — the
  suite covers 1440/1280/1024/768 (resize) and 390/430 (mobile) plus
  dark mode, and every screenshot taken was inspected, but they were not
  archived outside `frontend/test-results/` (Playwright's own,
  gitignored output directory).

## 10. Files touched across both sessions on this branch

Backend wiring: `backend/app/services/clinical_document/segments.py`,
`lab_extraction.py`, `medication_extraction.py`, `lab_persistence.py`,
`medication_persistence.py`, `reprocessing.py`, `canonical_headings.py`,
`source_geometry.py`, `backend/app/services/source_evidence.py`.

Tests: `backend/tests/test_clinical_document_reprocessing_geometry_v3.py`
(new), `test_source_geometry.py`,
`backend/tests/fixtures/clinical_reader_v3_pdf_fixture.py`.

Browser verification (this follow-up session):
`backend/scripts/seed_e2e_source_geometry_v3_document.py` (new),
`frontend/e2e/source-geometry-table-intelligence-v3.spec.ts` (new),
`frontend/app/documents/[id]/discharge/page.tsx`.
