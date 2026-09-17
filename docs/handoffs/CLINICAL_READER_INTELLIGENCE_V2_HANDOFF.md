# Clinical Reader Intelligence V2 — Handoff

**Status: COMPLETE for the scope defined below.** Branch
`fix/clinical-reader-intelligence-v2`, off `main` post CDI V3 production
merge (PR #6/#7). Not merged — see section 11 (PR).

This session rebuilt the discharge/clinical-document reader on top of
the existing Clinical Document Intelligence V3 architecture
(`docs/handoffs/CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md`), adding a
server-side, grounded AI interpretation layer and a redesigned reader
information architecture — without introducing a second clinical
datastore, without a database migration, and without changing how a
document is classified or ingested.

## 1. What was actually wrong in production

Investigated first, before writing any code (per this task's own
instruction), via direct reading of `persistence.py`, `discharge_parser.py`,
the `GET /documents/{id}/clinical-reader` endpoint, and the existing
Phase 8 reader components (`ClinicalCourseTimeline`, `StructuredLabReport`,
`MedicationList` — all already real, tested, canonical-data-backed
components). The reader FRONTEND was already more sophisticated than the
symptom list assumed. **The actual root cause**: `persistence.py`'s
read-time upconversion of the legacy discharge JSON shape (which every
existing document goes through on every read) had its own reduced,
duplicate implementation that only did segmentation + canonical-heading
consolidation — it never called the real dated-event/chronology-warning
extraction that `discharge_parser.py`'s forward parser already had. So
every real discharge document was rendering as a flat, undated text dump
regardless of how good the underlying parser was, simply because the
read path never reached it.

Fixed in `persistence.py::_upconvert_legacy_discharge_payload` by making
it call `discharge_parser.parse_legacy_discharge_payload` directly
(labeled with its own `parser_version`/`review_state="needs_review"` so
it's honestly distinguishable from a live Phase 4/5 parse). This one
change is why every document — not just newly reprocessed ones — now
gets real `dated_events`, chronology warnings, and (once reprocessed)
grounded diagnoses/investigations/anomalies.

On top of that root-cause fix, this session addressed the rest of the
task's Part 1 reproduction list (giant text dump, current-vs-historical
conflation, blank-template diagnoses/investigations/treatment sections,
raw-prose labs, contradictory lab states, silent anomaly correction,
narrative duplication, split-view geometry) via the architecture below.

## 2. Architecture — no second datastore

```
original document
  -> deterministic extraction (segments.py / canonical_headings.py / dates.py / events.py)
  -> StructuredClinicalDocument (schema.py)  [always renderable on its own]
  -> AI Clinical Document Interpreter (ai_interpreter.py)  [additive, optional, versioned]
  -> grounded semantic fields on the SAME StructuredClinicalDocument
  -> Clinical Reader Projection (GET /documents/{id}/clinical-reader — unchanged endpoint)
  -> deterministic React reader (discharge/page.tsx)
```

`StructuredClinicalDocument` (schema.py) gained purely additive fields:
`diagnoses`, `investigations`, `anomalies`, `recommendations`,
`treatment_eras`, `current_encounter`, `interpretation` — plus
`encounter_scope`/`is_template_only` on `ClinicalSection` and
`encounter_scope`/`is_repeated_in_source` on `ClinicalEvent`. Every one
defaults to `[]`/`None`/`False`, so a document produced before this
existed (or one the AI interpreter never ran against, or one where the
interpreter failed) still validates and renders — it simply has empty
interpretation-derived fields, and the reader degrades to exactly the
canonical-section view it already had.

**Existing canonical objects remain the single source of truth**:
`LabResult` for structured labs, `PatientMedication` for medications,
`PatientEvent`/timeline projection for the Timeline, `SourceEvidence`
for provenance. Nothing in this session introduced a
`ReaderLabResult`/`ReaderMedication`/`ReaderTimeline` duplicate — the
new `Diagnosis`/`Investigation`/`AnomalyFlag`/`RecommendationItem`/
`TreatmentEra` models are lightweight, document-scoped, point ONLY at
`source_section_id`/`source_event_ids` (synthetic, in-document ids —
never a copy of canonical row data), and are persisted as part of the
SAME `note_body` JSON blob the rest of `StructuredClinicalDocument`
already lives in. **No database migration was needed or added** — this
was deliberate and verified (see section 9): the existing
`note_body`-backed JSON storage already safely holds additive schema
fields.

## 3. The AI Clinical Document Interpreter (`ai_interpreter.py`)

A server-side structured-output call, reusing the exact OpenAI Responses
API + JSON-schema pattern already established in
`ai_document_classifier.py` (`text.format.type="json_schema"`,
`strict: False` — real safety comes from server-side validation, not
schema strictness). It is **never called on a normal page load** — it
runs only during `reprocess_discharge_document` (an explicit,
authenticated action). The rendered reader page is deterministic from
whatever was last persisted.

**Versioning/audit** (`InterpretationMetadata`, stored on the document
itself): `schema_version` ("v1"), `prompt_version`
("clinical-reader-intelligence-v2-interpreter-v1"), `model` (from
`AI_CLINICAL_INTERPRETER_MODEL` env, falling back to `OPENAI_MODEL`,
default `gpt-4.1`), `generated_at`, `status`
("complete"/"partial"/"failed"/"unavailable"), `warnings`. This reuses
the existing derived-artifact/structured-document storage rather than
adding a new table, per this task's own migration-safety instruction.

**Failure/fallback**: `interpret_structured_document()` NEVER raises for
a normal failure (missing `OPENAI_API_KEY`, timeout, provider error,
malformed/empty JSON, non-JSON response) — every one of those is caught
internally and turned into `interpretation.status="unavailable"` with
the deterministic document otherwise completely unchanged. A document
whose AI interpretation has never run, or failed, renders exactly as
well as it did before this task — verified by dedicated tests
(`test_missing_api_key_falls_back_gracefully`,
`test_malformed_json_response_falls_back_gracefully`,
`test_provider_timeout_style_failure_falls_back_gracefully`).

## 4. The grounding contract — how hallucination is prevented

This is the actual safety mechanism, not a prompt instruction alone.
`build_interpreter_input()` sends the model a bounded, ID-tagged JSON
representation built ONLY from the document instance being processed —
real `section_id`s (`is_template_only` sections excluded) and real
`ClinicalEvent.source_event_id`s, nothing else. The system prompt
explicitly treats every "text" field as untrusted DATA extracted from a
patient document, never an instruction (Part 26's prompt-injection
requirement) — a document containing "ignore previous instructions..."
is quoted clinical text, not a command.

`validate_and_filter_interpretation()` is the enforcement: it rebuilds
`valid_section_ids`/`valid_event_ids` **fresh from the real document
instance** on every call, and drops (never trusts) any diagnosis /
investigation / anomaly / recommendation / treatment-era / encounter-
scope-assignment whose `source_section_id`/`source_event_ids` aren't in
those real sets — one bad citation drops only that one item, with a
rejection warning recorded, not the whole response. Because the
allow-list is built from THIS document's own data and the model was
never given any other document's ids to begin with, cross-document/
cross-patient hallucination is structurally impossible, not merely
discouraged — proven by `test_hallucinated_section_reference_rejected`,
`test_hallucinated_event_reference_rejected`,
`test_cross_document_style_id_rejected_same_as_any_other_unknown_id`,
`test_treatment_era_with_no_valid_events_rejected`,
`test_scope_assignment_to_unknown_target_rejected`, and (against the
full synthetic fixture) `test_ai_interpreter_current_encounter_excludes_
historical_events`.

There is **no schema field anywhere** for a "corrected" numeric value —
`Diagnosis`/`Investigation`/`AnomalyFlag`/`RecommendationItem` only ever
carry text the model asserts is IN the source, plus citations; the model
cannot restate or alter a lab value, date, or vital sign because there
is nowhere in the output contract for it to do so. `apply_interpretation()`
re-validates everything through Pydantic a second time when constructing
the final document — a doubly-enforced gate.

## 5. Current vs. historical encounter — how it's determined

Two independent layers, deliberately kept separate:

- **Demographics are NEVER derived from narrative.** `DocumentMetadata`
  (patient_name/date_of_birth/sex/admission_date/discharge_date/
  hospital_name) is built by `discharge_parser.parse_legacy_discharge_
  payload()` purely from the top-level administrative payload fields —
  it has no code path that reads narrative text at all. A historical
  narrative mentioning a much younger age genuinely cannot overwrite
  current demographics, because there is no mechanism connecting the
  two. Locked down by
  `test_historical_narrative_age_never_overwrites_current_administrative_demographics`.
- **Which sections/events belong to the CURRENT hospitalization** is an
  AI-interpreter judgment (`current_encounter.event_ids`/`section_ids`,
  plus per-item `encounter_scope_assignments`), grounded exactly like
  everything else — the model is told the admission/discharge dates and
  asked which real event/section ids belong to that window; anything
  ambiguous is left unassigned (`encounter_scope: null`), never guessed
  as "current" by default.

## 6. Laboratory results

No change to the extraction/persistence pipeline (`lab_extraction.py`/
`lab_persistence.py` — Phase 6, untouched). What changed is the READER:

- `StructuredLabReport` now receives a `rawSectionHasContent` flag (does
  the document's own `laboratory_results` section have real,
  non-template content?) and an `onViewOriginal` callback. Three
  distinguishable states, never more than one shown at once: (1)
  canonical `LabResult` rows exist → the real table; (2) the section has
  real content but zero canonical rows → an explicit "detected in source
  but could not be structured" warning with a link to Original
  narrative; (3) no lab section at all → nothing rendered here (the
  section simply isn't in the outline).
- **A real, reproduced bug fixed this session**: the reader previously
  rendered a laboratory_results section's raw blocks UNCONDITIONALLY and
  then separately appended the structured table below — so a document
  with lab prose but no parsed rows could show contradictory state (raw
  text AND a "no labs" message) simultaneously (violates Part 1G/8E).
  `EntryContent`'s dispatch for `laboratory_results` (and, for
  consistency, medications) now picks exactly one branch.
- Conflicting values for the same analyte (e.g. two different HGB
  readings) are preserved as separate rows, both flagged "Requires
  review" — this is existing Phase 6/8 behavior (`verification_state=
  "conflict"`), now proven against a genuine two-line-extraction
  conflict (not just a hand-built `LabCandidate` fixture) via
  `test_reprocessing_synthetic_fixture_preserves_conflicting_hgb_lab_values`.

## 7. Medications, prescriptions, procedures

Also unchanged extraction (Phase 7, `medication_extraction.py`/
`medication_persistence.py`). The interpreter layer does NOT touch
medication state — a "prescription issued" narrative mention is
represented as an ordinary Clinical Course event (`event_type` stays
whatever the deterministic classifier assigned — never promoted to
`"treatment_change"` or any other state just because a prescription
verb appears nearby), kept entirely separate from confirmed-administered
`PatientMedication` rows. Locked down by
`test_prescription_issued_mention_stays_distinct_narrative_not_an_administered_medication`.
`TreatmentEra` groups real dated events into a named era only when the
model can point at real event ids showing a sustained pattern (e.g. the
fixture's Hydrea→ruxolitinib→Besremi progression with a dose change) —
grounded exactly like every other interpreter output.

## 8. Investigations, empty templates, anomalies, duplication

- **Empty-template suppression is fully deterministic, not an AI
  judgment** (`template_detection.py`): a section is `is_template_only`
  only when every one of its text blocks is a known form label (a fixed,
  named set — "produs", "cantitate", "cod cerere", "eco"/"ekg"/"rx",
  etc.), a blank fill line (`____`), or known boilerplate instructional
  text — never inferred. Such a section is hidden from the intelligent
  reader's default outline but always remains visible in "Original
  narrative" mode — nothing is ever deleted.
- **Investigations buried in narrative** (JAK2 V617F, bone marrow
  biopsy, abdominal ultrasound, BCR-ABL in the fixture) are the
  interpreter's job precisely because they're NOT in an explicit
  investigations field — typed as `imaging`/`molecular`/`pathology`/
  `ecg`/`procedure`/`other`, grounded against the Clinical Course
  section/events they came from.
- **Anomalies** (`AnomalyFlag`) have no "corrected value" field — only
  `original_value` (verbatim) and a `message`. A suspicious date
  (year 3036) or vital sign (AV 1008) is preserved exactly as written in
  both the underlying event/section text AND the anomaly's
  `original_value` — proven end-to-end by
  `test_ai_interpreter_anomaly_flags_preserve_original_values_verbatim`
  and the deterministic-layer tests
  `test_suspicious_far_future_date_is_preserved_verbatim_and_flagged_not_corrected`
  / `test_implausible_vital_sign_is_preserved_verbatim_and_flagged_not_corrected`.
  Note: date/vital-sign anomaly detection itself is deterministic
  (`dates.py`/`events.py`, pre-existing from CDI V3) — the interpreter
  layer's anomaly detection is for anomaly TYPES a deterministic regex
  can't catch (conflicting values, demographic mismatches, chronology
  uncertainty), and both layers write into the same `warnings`/
  `AnomalyFlag` surfaces.
- **Duplicated narrative** (`is_repeated_in_source`): a NEW deterministic
  pass in `discharge_parser.py` (`_mark_repeated_events`) flags an event
  as repeated only when its entire `raw_text` exactly matches an earlier
  event from a DIFFERENT segment (never within the same segment, where
  sibling events sharing one segment's text is normal, not a
  duplication). Presentation-only — nothing is ever deleted or merged;
  both occurrences keep their own `source_event_id`/evidence.

## 9. Migration safety

**No Alembic migration was added.** Verified: `alembic heads` shows
exactly one head (`c7d2e91a4b6f`), unchanged from before this session;
`scripts/check_migration_drift.py` reports no drift. All new schema
surface lives inside the existing `note_body` JSON column via additive
Pydantic fields — the same pattern already used for every prior
Clinical Document Intelligence V3 phase.

## 10. Reprocessing existing documents

`POST /documents/{id}/reprocess-clinical-structure`
(`reprocessing.py::reprocess_discharge_document`) — same auth pattern as
the existing document update endpoint (ownership or care-partner-share
check), rate-limited (10/hour), audit-logged. Orchestrates: resolve base
document + segments → extract/persist labs → extract/persist medications
→ project Timeline → run the AI interpreter (never raises) → persist the
updated `StructuredClinicalDocument`. **Idempotent**: reprocessing twice
reuses existing canonical `LabResult`/`PatientMedication` rows rather
than duplicating them (`lab_results_reused`/`medications_reused` in the
result), and re-running the interpreter replaces (never accumulates)
the interpretation-derived fields. The trickier half of this — a SECOND
reprocess call must reconstruct segments from the ALREADY-upgraded
document (the first call replaced the legacy JSON), not fail because it
no longer looks "legacy-shaped" — is handled by
`_resolve_base_document_and_segments()`, which branches on
`payload.get("schema_version")` and, for an already-upgraded document,
strips prior interpretation output before re-deriving synthetic segments
from the persisted sections. Covered by
`test_reprocessing_twice_does_not_duplicate_canonical_rows`. The reader
page exposes this as a "Reorganize with AI" button.

## 11. Frontend

`discharge/page.tsx` was rewritten (full-file rewrite, per this
project's own convention for frontend pages) around a single
`OutlineEntry` list covering both real canonical sections and three new
synthetic entries: Overview (compact structured blocks — hospitalization
window, principal diagnosis, abnormal labs, key investigations,
recommendations, "Organized from source · Unverified" footer — never a
giant paragraph), Current Hospitalization (only events the interpreter
placed in `current_encounter`), and Original/Full source narrative
(every section, including template-only ones, unfiltered — the fidelity
fallback). `is_template_only` sections are hidden from the normal
outline. Diagnoses/Investigations/Recommendations sections prefer the
new structured cards (`interpretation-panels.tsx`:
`DiagnosisList`/`InvestigationCards`/`RecommendationList`/
`AnomalyWarnings`/`OverviewPanel`/`CurrentHospitalizationEvents`) when
the interpreter produced grounded items, falling back to the existing
raw-block rendering otherwise — a document that's never been reprocessed
loses nothing.

**Two real bugs found and fixed via this work, both confirmed by
Playwright, not just inferred**:

1. The lab-display contradiction in section 6.
2. A genuine race condition: the page's initial-load effect used to call
   `setActiveEntryId("overview")` unconditionally once the fetch
   resolved — if that resolution landed after the user had already
   clicked a different outline section (no StrictMode double-invoke
   needed to trigger it, just an ordinary slow initial load), the click
   was silently reverted back to Overview a moment later. Fixed by
   initializing `activeEntryId` to `"overview"` directly (removing the
   async reset entirely) plus a `cancelled` guard on the effect's other
   state writes for the StrictMode-double-invoke case.

**Split-view geometry** (Part 1K/19): `.app-shell-title` now clamps to 2
lines with a native tooltip fallback; `.b-app-split-main` has a real
480px minimum instead of 0 (the viewer already switches to a full-screen
sheet under 1024px, so this never causes horizontal overflow). A THIRD
real bug found via visual QA: `.app-shell-header-row` was `nowrap` with a
`flex-shrink: 0` actions block — when the title column got squeezed
narrow enough to 2-line-wrap but the actions still "fit" on the same
row, the vertically-centered single-line actions block visually
overlapped the title's second line. Fixed by making the header row wrap
(actions drop to their own row below the title when there truly isn't
room) plus giving the title block a real 200px minimum width so the wrap
decision triggers correctly. A fourth bug, mobile-only: the page's own
`rightContent` action buttons (Ask Bragi/Reorganize with AI/Share/
Delete/Back) were a single un-wrapped flex row nested inside the
already-wrap-capable shell container, so at narrow widths the last
button was clipped at the viewport edge instead of wrapping — fixed by
adding `flexWrap: "wrap"` to that inner row.

## 12. Testing

**Backend** (pytest, `DATABASE_URL`-gated real-DB tests skip gracefully
without one):
- `test_clinical_document_ai_interpreter.py` — 14 tests, the grounding
  gate in isolation (mocked model responses, never live OpenAI).
- `test_clinical_document_template_detection.py` — 8 tests.
- `test_clinical_document_reprocessing.py` — 5 tests, real DB.
- `test_clinical_document_persistence.py` — +1 regression test proving
  the root-cause fix.
- `test_clinical_reader_v2_regression.py` — 15 tests against the full
  synthetic fixture: demographics authority, blank-diagnosis suppression,
  template suppression, repeated-vs-duplicated events, anomaly
  preservation, prescription/administration distinction, typed
  investigation recognition, treatment-era grounding, current-encounter
  exclusion of historical events, and one real-DB lab-conflict-through-
  extraction test.
- Full `clinical_document`/`clinical_reader`-scoped suite: 318 passed, 0
  failed.
- Full repo `pytest tests/`: see the PR description / final report for
  the exact count from this session's run.
- Bandit (`bandit -r app -ll`, the CI gate): 0 Medium, 0 High.
- `scripts/check_migration_drift.py`: no drift.
- `alembic heads`: exactly one (`c7d2e91a4b6f`).

**Frontend**: `tsc --noEmit` clean; `eslint` on every changed file clean
(one pre-existing, unrelated lint error in `app-shell.tsx` at an
untouched line, confirmed via `git diff`); `next build` production build
succeeds. This codebase has no unit/component test framework configured
(no Jest/Vitest/RTL — only Playwright); component-level coverage for
the new `interpretation-panels.tsx`/lab-state components is therefore
delivered through Playwright assertions against real rendered DOM
(Part 31), not a new test framework — introducing one was judged out of
scope for this task.

**Playwright** (`e2e/clinical-reader-intelligence-v2.spec.ts`, 10 tests,
seeded via `backend/scripts/seed_e2e_clinical_reader_v2_document.py`
which runs the real reprocessing pipeline with only the AI model call
mocked — zero external API cost): Overview, Diagnoses (no fabricated
secondary), Current Hospitalization (excludes historical), empty-
template suppression, narrative-buried investigations, anomaly
preservation, lab table + conflict (no contradictory empty-state),
Original narrative (duplicated block visible, template sections
visible), split-view geometry, mobile. All 10 pass. Pre-existing related
suites (`clinical-reader.spec.ts`, `right-workspace-geometry.spec.ts`,
`ask-bragi-workspace.spec.ts`, `derived-lab-artifact.spec.ts`,
`romanian-discharge-classification.spec.ts`) re-run for regression — see
the final report for the exact pass count from this session.

**Visual QA**: screenshots taken at 1440/1280/1024/768/430/390px against
the seeded fixture (Overview, Laboratory results, split-view). Found and
fixed the header-wrap overlap bug (section 11) this way — not just DOM
assertions.

## 13. Deferred / explicitly out of scope

Per this task's own Part 34-36 boundaries: Ask Bragi retrieval
hardening (Phase 11), narrative citation architecture changes beyond
what reader provenance needed, Emergency V2, and universal file
ingestion were not touched. Additionally, not attempted this session:
- A frontend unit/component test framework (see section 12).
- `is_repeated_in_source`/anomaly detection for the FULL anomaly-type
  vocabulary (`ocr_uncertain`, `demographic_context_mismatch`) — the
  schema/validator support all 8 types, but only the two the fixture
  actually exercises (`impossible_or_unusual_date`,
  `physiologically_implausible_value`) have end-to-end test coverage in
  this session; the others are reachable through the same grounded
  contract whenever the model identifies one, just not yet regression-
  tested against a fixture example.
- Live-OpenAI manual integration test for the interpreter (Part 30
  allows this as optional/local-only; not added this session — the
  mocked test suite is the required, CI-safe coverage).

## 14. Deployment

No migration to run. No new environment variable is required — 
`AI_CLINICAL_INTERPRETER_MODEL` is optional (falls back to the existing
`OPENAI_MODEL`); `OPENAI_API_KEY` must be configured for the "Reorganize
with AI" reprocess action to produce a real interpretation (its absence
degrades gracefully to `interpretation.status="unavailable"`, not an
error). No change to the discharge upload/classification pipeline. Safe
to deploy read-only (every document renders at least as well as before);
the reprocess endpoint is opt-in per document.
