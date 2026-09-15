# Clinical Document Intelligence V3 — Handoff

**Status: PARTIAL. Phases 0 through 6 of the 21-phase contract are
COMPLETE and verified. Phases 0-5: the full structural reconstruction
layer (typed segments, canonical section consolidation, real Clinical
Course dated-event extraction with chronology sanity checking) and a
real end-to-end orchestration (`discharge_parser.py`) proven against
all three of the contract's own required suspicious-data fixture
examples. See sections 9, 9b, 9c, 9d. Phase 6 (NEW this checkpoint):
embedded lab extraction from a discharge's `laboratory_results` section
into real, canonical `LabResult` rows — feeding the EXISTING
`resolve_analyte()` resolver, no private alias dictionary, no second lab
datastore — plus a real derived "lab_report" artifact `Document` per
coherent source report. See section 9e. None of Phases 3-6's code is
wired into the live ingestion pipeline yet — this is deliberate, not an
oversight; see section 9b's sequencing note (switching the write path
before Phase 8 rebuilds the frontend discharge reader would break it).
Phase 6's own persistence service (`lab_persistence.py`) IS fully
callable and DB-tested standalone in the meantime (see section 9e).
Phases 7–21 are NOT STARTED.** This document exists specifically so a
future Claude session with zero memory of this conversation can pick
this up correctly — read section 23 ("HOW TO CONTINUE") first if
that's you.

This is written for a session that does not trust its own predecessor's
claims: every fact below is either a command you can re-run, a file you
can open, or a test you can execute.

## Exact current state (checkpoint)

- Branch: `fix/clinical-document-intelligence-v3`
- **HEAD SHA: check `git log --oneline -1`** (this line is updated by
  hand at each checkpoint and can lag a moment behind an in-progress
  session; the git log is always the final authority). As of this
  checkpoint, the last three commits are (newest first): a handoff
  checkpoint commit for this section, `9a085ca` (Phase 6 persistence +
  derived artifact semantics + migration), `ada9fd8` (Phase 6 grouping),
  `512dd74` (Phase 6 extraction) — on top of the Phase 0-5 checkpoint at
  `ea3d795`.
- Pushed to `origin/fix/clinical-document-intelligence-v3`: check
  `git log origin/fix/clinical-document-intelligence-v3..HEAD --oneline`
  — if it lists commits, this checkpoint has NOT been pushed yet. As of
  writing this line, the three Phase 6 commits above had NOT yet been
  pushed — push before ending a session, per the same convention as
  every prior checkpoint.
- Working tree at this checkpoint: **clean, zero uncommitted changes**
  (`git status --short` returns nothing) once this handoff commit lands.
- **No PR opened.**
- **Phases 4, 5, and 6 are now COMPLETE.** Phases 4/5: segments,
  canonical section consolidation, real Clinical Course event
  extraction, chronology sanity checking, full end-to-end orchestration
  in `discharge_parser.py` (sections 9b/9c/9d). Phase 6: embedded lab
  extraction/grouping/canonical persistence + derived lab artifact
  backend semantics (section 9e, NEW). None of Phases 3-6's own
  production code is wired into the live discharge ingestion write path
  yet (deliberate — see section 9b's sequencing note); Phase 6's
  persistence SERVICE itself (`lab_persistence.py`) is fully callable
  and DB-tested standalone right now, distinct from "wired into the live
  pipeline" — see section 9e for the precise distinction.
- **Immediate next step: Phase 7 — medication extraction/context
  classification + deterministic duration/end-date derivation.** Reuse
  the EXISTING `PatientMedication` model/status semantics — no separate
  "discharge medication" table or tab. Re-read the V3 contract's exact
  end-date interval convention (start+N days, calendar-month arithmetic,
  the `null` cases) before implementing — this handoff's "Hard
  constraints" section only summarizes it.

## Hard constraints and architecture decisions the next session MUST preserve

These are pulled directly from the original V3 contract text and are
easy to accidentally violate while implementing Phase 3+ — re-read the
original contract for full wording, but at minimum do not violate any
of these:

- **DO NOT move business logic back into `app/main.py`.** All new logic
  belongs in `app/services/` (new modules as needed) or existing
  routers under `app/api/routers/`.
- **Migration authority is Alembic only. No runtime DDL, ever.**
- **Reducto/provider extraction is the document-reading layer only.**
  Bragi's own code is the clinical normalization/canonicalization/
  provenance layer on top of it — do not blur this boundary (e.g. don't
  ask Reducto to do canonical classification, and don't have Bragi
  re-parse raw PDF bytes).
- **Ask Bragi reads persisted canonical data. It does NOT call Reducto
  live per question.** Nothing in Phase 11 (retrieval hardening) should
  introduce a live per-question extraction call.
- **No second lab datastore, no second medication datastore.** Embedded
  discharge labs MUST become real `LabResult` rows (feeding the existing
  `resolve_analyte()`/lab_catalog resolvers — no new private alias
  dictionary). Medications MUST use the existing `PatientMedication`
  model/status semantics — no separate "discharge medication" table or
  tab.
- **No new DB columns unless truly necessary** — prefer the existing
  structured JSON field(s) documented in the Phase 0 pipeline map.
- **Canonical section keys are a fixed enum** (overview,
  administrative_information, encounter_details, diagnoses,
  medical_history, examination, clinical_course, investigations,
  laboratory_results, imaging, procedures, treatment, medications,
  discharge_medications, recommendations, follow_up, prescriptions,
  signatures, other) — never the raw source heading. Repeated headings
  (e.g. multiple EPICRIZĂ sections) MUST merge into one canonical entry,
  preserving each source heading/order/evidence.
- **NEVER silently repair a suspicious date or an implausible clinical
  value** (e.g. "AV 1008 bpm") — preserve verbatim with a warning flag,
  never auto-correct.
- **Medication start-date priority**: (1) explicit start date in text,
  (2) explicit "start today" tied to encounter/discharge date, (3)
  discharge recommendation clearly starting at discharge, (4)
  prescription issue date ONLY if text semantics clearly indicate
  treatment start. **NEVER** use upload date or ingestion date as a
  medication start date.
- **End-date derivation** ONLY when a reliable start date AND an
  explicit finite duration both exist. Exact convention: start +14 days
  = interval `[start, start+14 days)` (e.g. 2026-03-05 + 14 days =
  2026-03-19); "2 weeks" = exactly +14 days; months = real calendar-month
  arithmetic, not `30 × N` days. `end_date = null` for PRN, "according to
  scheme", "N days each month", alternate dosing, "until follow-up",
  indefinite continue, or a taper with no clear total duration. Use a
  real date library for month arithmetic and document its exact rounding
  behavior (e.g. 2026-01-31 + 1 month) explicitly wherever it's used —
  do not hand-roll month math.
- **Duration parsing is deterministic** (Romanian + English units) — no
  LLM call for simple duration arithmetic.
- **One reusable `StructuredLabReport` frontend component**, used by
  both the embedded (inside a discharge reader) and standalone (derived-
  artifact) lab views via a `mode: "embedded" | "standalone"` prop — not
  two separate components.
- **A derived lab artifact is ONE per coherent source lab report/date
  grouping**, not a separate upload — must keep a parent-document
  reference, appear in Documents as "Derived from: [parent]", and be
  independently openable.
- **Timeline**: a discharge encounter stays ONE parent clinical-document
  event — do not fragment it. Only real state changes (medication
  started/stopped/major dose change, prescription issued) become
  Timeline events — not every "continues medication" mention.
- **DOCX/non-PDF sources**: do not invent PDF page/bbox coordinates —
  use a document/heading/block/paragraph anchor instead. Hide/disable
  "original layout" UX when precise layout data is genuinely absent
  (never show a blank screen pretending it's loading).
- **Idempotency**: reprocessing the same discharge document 1x, 2x, or
  10x must never duplicate `LabResult`/derived-lab-artifact/medication-
  episode/`PatientEvent`/`SourceEvidence` rows — deterministic
  import/source identities are required, not a `created_at` timestamp
  check.
- **No special-case code for a specific analyte name** (e.g. no
  "if canonical_name == platelet, do X" branch) — general alias
  resolution only, reusing `resolve_analyte()`.
- **Do not parse clinical documents in the browser.**
- **Do not fabricate panel membership** for lab groupings (Hematology/
  Chemistry/Coagulation/etc.) — only group by a trustworthy
  source_panel/source_section/canonical_category field, never a guess.
- **`demo.bragi.health` remains explicitly out of scope — do not start
  it.**

If the original contract text is not visible in whatever conversation
picks this up next, ask the user for it — this list is a safety net for
the highest-risk-to-violate rules, not a full restatement of all 21
phases' detail (e.g. the exact block-type enum, the full canonical
heading→key mapping examples, and Phase 17's full required test list are
in the original text, not reproduced here).

---

## 1. Branch / SHAs

- Branch: `fix/clinical-document-intelligence-v3`
- Branched from `main` at `917a543cb14ba362384ce793f233eed8b920a956`
  (the Phase 4 backend-modularization merge).
- Immediately fast-forward-merged `origin/fix/ask-bragi-workspace-
  reliability` (`a5022d8d4daf3c570c6df3739e1e3caf60ff9dc3`) into this
  branch before any Phase-0 work — see section 2's "Deliberate scope
  decision" below for why.
- Commits added on top of that merge, in order:
  1. `bd18cdb` — Phase 0: `docs/clinical_document_v3/
     CURRENT_PIPELINE_MAP.md` (the architecture inventory).
  2. `9c92148` — Phase 2: the Ask Bragi P0 fix (tool-round budget +
     prompt guidance) and its regression tests.
  3. `0f5c6a0` — RightWorkspace geometry Playwright regression
     (cross-checks the merged-in layout fix against this contract's own
     wording).
  4. `f51f954` — this handoff, plus pointers in `docs/CURRENT_STATE.md`/
     `docs/ARCHITECTURE.md`/`docs/KNOWN_GAPS.md`/`CLAUDE_HANDOFF.md`.
  5. `45709b6` — checkpoint commit recording the exact HEAD/push state at
     the end of the Phase 0-2 session, plus the "Hard constraints"
     section now above.
  6. `c9deaaa` — **Phase 3**: `app/services/clinical_document/` (schema.py
     + persistence.py) and its 23 tests, plus a TS mirror type file. See
     section 9 for full detail.
  7. `e81ea9b` — handoff checkpoint for Phase 3's completion (this file
     only); full backend suite reran green at 353/353 after Phase 3.
  8. `1e71f03` — **Phase 4 increment 1**: `canonical_headings.py` (real
     heading classifier + repeated-heading merge) and its 19 tests. NOT
     yet wired into the real ingestion pipeline — see section 9b.
  9. `757a2e8` — handoff checkpoint for Phase 4 increment 1 (this file
     only).
  10. `f4f47ce` — unified persistence.py's backward-compat upconversion
      onto the SAME classifier as increment 1, deleting the now-
      redundant `_LEGACY_KEY_TO_CANONICAL` mapping (proven equivalent
      first, then removed — no behavior change, 42/42 clinical_document
      tests unchanged in outcome).
  11. `74ee4d3`, `5c9aeb9` — handoff checkpoint + a stale-docstring fix,
      both small/non-functional.
  12. `8cc926a` — **Phase 5 increment 1**: `dates.py` (deterministic
      date-first parser) and its 19 tests. NOT yet wired into any real
      event extraction — see section 9c.
  13. `1dba739`, `0c36a07`, `293637e`, `5afd597`, `b46bfbc` — handoff
      checkpoint commits only, documenting Phase 5 increment 1 and the
      two transient Neon connectivity flakes hit during full-suite
      verification (section 19) — no functional code change in any of
      these.
  14. `2d31ef6` — **Phase 4 COMPLETE**: `segments.py` (new — typed
      `SourceSegment` + `build_segments_from_legacy_discharge_payload`),
      `schema.py`'s additive `ClinicalSection.source_segment_ids`,
      `canonical_headings.py`'s new `consolidate_segments` (segment-aware,
      drops non-substantive sections), `persistence.py` upgraded to use
      it. 14 new tests. See section 9b.
  15. `dc19d26` — **Phase 5, date plausibility + real events**:
      `dates.py` gains an implausible-year warning (kept, not nulled);
      `events.py` (new) — event-type classification (with a real
      adjacent-dates bug caught and fixed before shipping), vital-sign
      plausibility scanning, `ClinicalEvent` construction. 18 new tests
      (3 dates.py + 15 events.py). See section 9c.
  16. `41ceadf` — **Phases 4+5 orchestration COMPLETE**:
      `discharge_parser.py` (new) — the full segments -> sections ->
      events -> chronology-check -> validated-document pipeline. 8 new
      tests, including all three of the V3 contract's own required
      fixture examples verified end-to-end. See section 9d.
  17. `ea3d795` — handoff checkpoint confirming 431/431 full backend
      suite clean (no Neon flake that run) — no functional code change.
  18. `512dd74` — **Phase 6 increment 1**: `lab_extraction.py` (new) —
      `LabCandidate` + `extract_lab_candidates_from_segment`. 19 new
      tests, including the synthetic hematology fixture. See section 9e.
  19. `ada9fd8` — **Phase 6 increment 2**: `lab_grouping.py` (new) —
      `group_lab_candidates`/`LabReportGroup`. 7 new tests. See section 9e.
  20. `9a085ca` — **Phase 6 COMPLETE**: `lab_persistence.py` (new) —
      `persist_lab_candidates`, feeding `resolve_analyte()`, flag
      precedence, conflict preservation, derived-artifact get-or-create,
      idempotent inserts. Additive `models.Document.derived_artifact_kind`
      column (+ Alembic migration `b52c5c35f707`) and additive
      `schema.DerivedArtifactRef.group_key`. `DELETE /documents/{id}`
      (`documents.py`) now hard-deletes derived-artifact children instead
      of leaving them orphaned. 18 new tests (real DB). See section 9e.
  21. Check `git log --oneline -20` for anything added after this
      checkpoint — this list is updated by hand and can lag a live
      session.
- **Push status**: check `git log origin/fix/clinical-document-
  intelligence-v3..HEAD --oneline` — empty means fully pushed. As of
  writing, the three Phase 6 commits above (and this handoff commit) had
  NOT yet been pushed. No PR opened.

## 2. Deliberate architectural decision made this session (documented per the contract's own escape hatch)

The contract's own Phase 2 (Ask Bragi execution contract) and layout
contracts ("ASK BRAGI PAGE LAYOUT", "RIGHT WORKSPACE LAYOUT CONTRACT")
describe requirements nearly identical in spirit and in some cases
almost word-for-word to bugs already root-caused, fixed, and verified
(with real Playwright coverage) on the still-open, still-unmerged
`fix/ask-bragi-workspace-reliability` branch/PR #5 in the immediately
preceding piece of work in this same engagement. Rather than re-deriving
equivalent fixes from scratch on this new branch (duplicate work, and a
real risk of two subtly different implementations of the same fix
existing in the codebase), that branch was fast-forward-merged into this
one at the very start of Phase 0. This was a unilateral decision, not
confirmed with the user beforehand — flagging it explicitly here per the
contract's own instruction ("if [a literal instruction is impossible]
... explain [the smallest compatible adaptation] in the final report and
handoff"). This isn't a case of the contract being impossible so much as
already-partially-satisfied by adjacent, already-verified work; treated
it as in-scope reuse rather than "unrelated infrastructure work."
Concretely, this merge is what already gave this branch:
- The RightWorkspace single-panel half-height fix.
- The Ask Bragi contextual panel height-cap fix (`fillHeight`).
- The dedicated `/ask-bragi` page first-message reset fix
  (`justCreatedConversationIdRef`).
- The PLT/WBC/HGB canonical-lab-retrieval alias fix.
- The first real Playwright infrastructure in this repo.

**If this decision is judged wrong**, the fix is `git revert` of the
merge commit and re-deriving the layout/retrieval fixes independently
against this contract's own wording — the two are close enough that the
actual code would likely end up nearly identical, but flagging that this
wasn't re-verified from a clean slate against this contract's exact text
until this session's own cross-check (section 8 below).

## 3. What was actually implemented this session

**Phase 0** — `docs/clinical_document_v3/CURRENT_PIPELINE_MAP.md`: a
24-section inventory of the current document/lab/medication/Ask-Bragi
architecture with exact file:line references (Document model fields,
the three independent lab-canonicalization catalogs, the discharge
pipeline's actual data flow, Ask Bragi's tool registry, deletion
semantics, etc.). Read this before touching any of Phases 3+ below — it
already answers most of "where does X currently live."

**Phase 1** — baseline recorded (not committed as a separate artifact,
verified live): 328 backend tests, 117 OpenAPI routes, all checks clean.
See section 18 for the current (post-fix) numbers.

**Phase 2** — the Ask Bragi P0 diagnosis and fix. See section 14 for
full detail. Summary: `ASK_BRAGI_MAX_TOOL_ROUNDS` (default 4) was too
tight for broad, multi-analyte questions — exactly the two prompts the
contract named ("What changed in my latest bloodwork?", "Show my latest
labs") are the query shape most likely to exhaust it. Fixed with prompt
guidance (answer broad comparisons from one `get_lab_results` call
instead of one `compare_lab_results` call per analyte) plus raising the
budget to 8 as defense-in-depth. Proven with tests that reproduce the
failure under the old default and pass under the new one.

**Cross-check of the layout contracts** (part of Phase 2's own scope,
since the contract restates layout requirements): verified the merged-in
RightWorkspace/AskBragiChat/AppShell code against this contract's exact
"RIGHT WORKSPACE LAYOUT CONTRACT" and "ASK BRAGI PAGE LAYOUT" wording —
already compliant (conditional panel-wrapper rendering, `fillHeight`
region using `flex: 1` unconditioned on `messages.length`/`error`/
`generating`, the per-turn error banner rendered as a sibling inside the
conversation column rather than altering outer geometry). Added the one
genuinely missing piece: a real Playwright geometry regression for
RightWorkspace (the contract explicitly asks for this; the existing
suite's own comment already flagged it as a known gap).

**Phase 3** — the typed, versioned `StructuredClinicalDocument` schema.
See section 9 for full detail. Summary: new `app/services/
clinical_document/` package (`schema.py` + `persistence.py`), persisted
through the EXISTING `Document.note_body` field (no new DB column, no
migration), with a working, tested backward-compatibility upconversion
from the current discharge pipeline's real, unchanged ad-hoc JSON shape.
23 new tests, all passing.

**Phase 4 — COMPLETE**: the full structural reconstruction layer —
typed `SourceSegment`s, a deterministic canonical-heading classifier
verified against every contract worked example, segment-aware
consolidation (repeated headings merge, non-substantive sections
dropped, full segment-level provenance). See section 9b. 33
Phase-4-specific tests, all passing. Not yet wired into the live
ingestion pipeline (deliberate — see the sequencing note).

**Phase 5 — COMPLETE**: real `ClinicalEvent` construction from Clinical
Course text — deterministic date-first parsing (including a
plausible-vs-impossible distinction for suspicious years), deterministic
event-type classification (with a real adjacent-dates bug caught and
fixed before shipping), vital-sign plausibility scanning, and a
chronology sanity check against the document's own admission/discharge
metadata. See section 9c. 45 Phase-5-specific tests, all passing,
including all three of the V3 contract's own required suspicious-data
fixture examples verified end-to-end (section 9d).

## 4. Data flow — the P0 fix

```
User sends "What changed in my latest bloodwork?"
  -> POST /ask-bragi/conversations/{id}/messages(/stream)
  -> run_turn() / run_turn_streaming() (service.py)
  -> client.responses.create(..., tools=TOOL_SCHEMAS, tool_choice="auto")
  -> model requests get_patient_context, then search_documents, then
     (BEFORE the fix) one compare_lab_results call PER ANALYTE
     (WBC, RBC, HGB, PLT, ... — a CBC panel alone is 10-15 rows)
  -> round_index increments once per model round; ASK_BRAGI_MAX_TOOL_ROUNDS
     capped this at 4
  -> loop exits with final_output_text still None
  -> raise AskBragiError("...too many tool calls")
  -> route's `except AskBragiError` -> HTTP 502,
     "Ask Bragi could not process this message. Please try again."
     (exact reported text)

AFTER the fix:
  -> prompts.py's new TOOL EFFICIENCY guidance steers the model toward
     ONE get_lab_results call (generous limit) + its own arithmetic for
     "what changed" style questions, instead of N compare_lab_results calls
  -> ASK_BRAGI_MAX_TOOL_ROUNDS raised 4 -> 8 as a safety margin for
     whatever the prompt guidance doesn't eliminate
  -> turn completes normally within budget
```

## 5. Database changes

**None.** No migration was created or is needed for anything done this
session. (Phases 3+ will very likely need at most additive, nullable
columns or a new JSON field per the contract's own "no new DB columns
unless truly necessary" instruction — not yet designed.)

## 6. Models used

Unchanged. `LabResult`, `Document`, `PatientMedication`, `PatientEvent`,
`SourceEvidence`, `AskBragiConversation`/`AskBragiMessage` all exist
exactly as documented in `docs/clinical_document_v3/
CURRENT_PIPELINE_MAP.md`.

## 7. New/modified backend files

- `backend/app/services/ask_bragi/service.py` — `ASK_BRAGI_MAX_TOOL_ROUNDS`
  default 4 → 8, with an explanatory comment.
- `backend/app/services/ask_bragi/prompts.py` — new "TOOL EFFICIENCY"
  guidance block; `PROMPT_VERSION` bumped `v5` → `v6`.
- `backend/tests/test_ask_bragi_service.py` — two new tests (see section
  17/20).
- `backend/scripts/seed_e2e_lab_document.py` — new, standalone. Seeds a
  patient + laboratory_results Document + LabResult + SourceEvidence row
  directly via the ORM (bypasses Reducto/OpenAI entirely — zero external
  cost) for the new Playwright geometry test. Not imported by any
  application code, not wired into CI.
- `docs/clinical_document_v3/CURRENT_PIPELINE_MAP.md` — new, Phase 0
  deliverable.
- `backend/app/services/clinical_document/__init__.py`, `schema.py`,
  `persistence.py` — new, Phase 3 (see section 9).
- `backend/tests/test_clinical_document_schema.py`,
  `test_clinical_document_persistence.py` — new, Phase 3, 23 tests.
- `backend/app/services/clinical_document/canonical_headings.py` — new,
  Phase 4 (see section 9b): `classify_canonical_heading`,
  `merge_headings_into_sections`, `consolidate_segments`.
- `backend/app/services/clinical_document/segments.py` — new, Phase 4:
  `SourceSegment`, `build_segments_from_legacy_discharge_payload`.
- `backend/app/services/clinical_document/dates.py` — new, Phase 5 (see
  section 9c): `parse_date_token`, `find_dates_in_text`.
- `backend/app/services/clinical_document/events.py` — new, Phase 5:
  `classify_event_type_from_context`, `find_vital_sign_warnings`,
  `build_events_from_segment_text`.
- `backend/app/services/clinical_document/discharge_parser.py` — new,
  Phase 4+5 orchestration (see section 9d):
  `parse_legacy_discharge_payload`.
- `backend/tests/test_clinical_document_canonical_headings.py`,
  `test_clinical_document_segments.py`, `test_clinical_document_dates.py`,
  `test_clinical_document_events.py`,
  `test_clinical_document_discharge_parser.py` — new, 78 tests total
  across Phases 4/5.

## 8. New/modified frontend files

- `frontend/e2e/right-workspace-geometry.spec.ts` — new. Two tests: a
  single open panel (Ask Bragi) fills the split column; both panels open
  together show the tab switcher and the inactive one has zero rendered
  height (not just squeezed).
- `frontend/lib/clinical-document-schema.ts` — new, Phase 3. A TS mirror
  of the backend schema, **not wired into any page/component** — inert
  until Phase 8 (discharge reader rebuild) actually imports it.

No frontend APPLICATION behavior was modified this session — the
Playwright test exercises layout code already fixed by the merge
described in section 2, and the new TS file is a type-only addition
nothing currently imports.

## 9. Structured document schema

**COMPLETE.** `backend/app/services/clinical_document/schema.py` defines
`StructuredClinicalDocument` exactly per the contract's conceptual root:
`schema_version` (constant `CURRENT_SCHEMA_VERSION = "v1"`),
`parser_version` (caller-supplied — no global "the parser" constant,
since no real parser exists yet; the backward-compat upconversion path
uses its own honest `"legacy-discharge-upconversion-v1"`),
`document_kind` (reuses the EXISTING `DocumentType` enum from
`app/services/document_taxonomy.py` — no parallel vocabulary),
`source_language`, `metadata` (a typed `DocumentMetadata`, not a raw
dict), `sections[]`, `dated_events[]`, `derived_artifacts[]`,
`warnings[]`.

`ClinicalSection`: `id`, `canonical_key` (the fixed 19-value enum,
`CanonicalSectionKey`/`CANONICAL_SECTION_KEYS` — verified by test against
the contract's exact list), `display_title`, `source_headings[]`
(plural, preserves every original heading that merged into this
section), `order`, `blocks[]` (the typed discriminated union below),
`source_evidence_ids[]`, `confidence`, `review_state`
(`"auto"|"needs_review"|"reviewed"|None`).

`ClinicalBlock` (Pydantic discriminated union on a `type` field):
`ParagraphBlock`, `KeyValueBlock`, `BulletListBlock`, `TableBlock`,
`DatedEventGroupBlock` (references `dated_events[].source_event_id`),
`LabReportReferenceBlock` (references real `LabResult.id`),
`MedicationListBlock` (references real `PatientMedication.id`),
`PrescriptionTableBlock`, `WarningBlock`. Every ID-bearing block stores
IDs, never a copy of the referenced data — `LabResult`/
`PatientMedication`/this schema's own `dated_events` remain the one
source of truth for their own content, exactly per the "no second
lab/medication datastore" constraint.

`ClinicalEvent` (Phase 5's type, defined now so `dated_events`/
`DatedEventGroupBlock` have something real to reference once Phase 5
populates them): `source_event_id`, `raw_date_text`, `normalized_date`,
`date_confidence`, `event_type` (the 8-value enum from the contract),
`raw_text`, `structured_observations[]`, `medication_changes[]`,
`procedures[]`, `source_evidence_ids[]`, `warnings[]`.

`DerivedArtifactRef` (Phase 6's type, same "defined now, populated
later" reasoning): `artifact_type` (`"lab_report"` only, for now),
`document_id`, `source_section_id`, `lab_result_ids[]`.

**Two hard rules from the contract are enforced as real Pydantic
validators, not just documented conventions**:
1. Two sections with the same `canonical_key` in one document is a
   `ValidationError`, not a warning — a parser MUST merge repeated
   headings (e.g. multiple EPICRIZĂ pages) into ONE canonical section
   BEFORE constructing this model.
2. `model_config = {"extra": "forbid"}` — an unrecognized top-level
   field is a `ValidationError`, not silently dropped or passed through.
   (`ClinicalSection.id` and `ClinicalEvent.source_event_id` uniqueness
   are also enforced the same way.)

**Persistence** — `persistence.py` — decision and reasoning: reused the
EXISTING `Document.note_body` field rather than `structured_sections`
(reserved for 6 unrelated Phase-4-era reader document types, with its
own fixed shape already consumed by `ask_bragi/tools.py` and the
frontend Reader — repurposing it risked regressing those) or a new DB
column (the contract's own "no new DB columns unless truly necessary"
instruction, and `note_body` is ALREADY what
`discharge_summary_pipeline.py` uses to store a full JSON payload for
exactly this kind of document today). **Zero migration, zero schema
change** — confirmed by `scripts/check_migration_drift.py` staying clean
after this phase.

`parse_structured_document(note_body: str | None) -> StructuredClinicalDocument | None`
is the one sanctioned read path: returns `None` (never raises) for a
`None`/empty/plain-text/malformed-JSON `note_body`; for a payload
carrying `schema_version`, validates it as the new shape (returns `None`
— not a partially-trusted dict — if validation fails); for a payload
matching the CURRENT, UNCHANGED legacy discharge shape (`document_type
== "discharge_summary"` and a `sections` list, no `schema_version` —
`discharge_summary_pipeline.py` was NOT modified and still produces
exactly this shape), upconverts it in memory by running each section's
real `title` text through `canonical_headings.classify_canonical_heading`/
`merge_headings_into_sections` — **as of a later commit this session
(`f4f47ce`), this is the SAME classifier Phase 4's real parsing uses,
not a separate mapping** (see section 9b — the original `_LEGACY_KEY_TO_
CANONICAL` dict this section originally described was deleted once a
cross-check test proved the two mechanisms always agreed, unifying them
to avoid maintaining two classification systems). Honestly labeled
`parser_version="legacy-discharge-upconversion-v1"` and
`review_state="needs_review"` on every section it produces — never
presented as a confident, human-reviewed parse, even though the
classification itself is exactly as accurate as a real Phase 4 parse
would produce. **Never rewrites the DB row** — this is read-time-only
backward compatibility. `serialize_structured_document(doc) -> str` is
the one sanctioned write path — takes an already-validated model
instance, never a hand-built dict.

**Real backward-compatibility proof, not just a claim**: a test feeds
the upconverter a payload with BOTH `laboratory_normal` and
`laboratory_abnormal` legacy section keys (two distinct real keys
`discharge_summary_pipeline.py` actually produces today) and verifies
they merge into ONE `laboratory_results` canonical section, with BOTH
original headings preserved in `source_headings` and BOTH bodies kept
as SEPARATE blocks (not concatenated into one string) — this is the
contract's own worked "repeated headings merge" example, exercised for
real against the actual current pipeline's actual output shape.

**Tests**: 23 new, all passing —
`backend/tests/test_clinical_document_schema.py` (12: canonical-key
enum matches the contract's exact list, round-trip serialization, a raw
heading rejected as a canonical key, duplicate canonical-key/section-id/
event-id all rejected, an unrecognized field rejected, every block type
round-trips through the discriminated union, a suspicious-value warning
never carries a "corrected" field) and
`backend/tests/test_clinical_document_persistence.py` (11: None/empty/
plain-text/malformed `note_body` all → `None` not a crash; valid
new-shape round-trip; an invalid new-shape payload → `None` not
partially trusted; the real legacy discharge shape upconverts correctly
including the lab-heading-merge case above; an unmapped legacy key falls
back to `"other"`; a non-discharge JSON blob isn't misidentified as a
legacy discharge payload).

**Not yet done** (explicitly Phase 4+'s job, not Phase 3's): no code
actually PRODUCES a `StructuredClinicalDocument` from a real document
upload yet — `discharge_summary_pipeline.py` itself is unchanged and
still writes the old ad-hoc shape; only the READ side (upconversion) is
new. The TS mirror (`frontend/lib/clinical-document-schema.ts`) is not
imported anywhere yet.

## 9b. Phase 4 — discharge parser pipeline (COMPLETE, not yet live-wired)

**What exists — the full structural reconstruction layer**:

- `segments.py`: `SourceSegment` (stable `segment_id` — deterministic
  from index + heading slug, not a random UUID, so reprocessing the
  SAME document produces the SAME ids; `index`, `segment_type`,
  `raw_heading`, `raw_text`, optional `table_data`/`page`/
  `source_block_id` — anchors are `None` today because the current
  pipeline's cross-page-merged sections don't carry a single page
  number, never fabricated). `build_segments_from_legacy_discharge_
  payload(payload)` builds segments from the CURRENT, UNCHANGED
  `discharge_summary_pipeline.py` payload shape.
- `schema.py`: `ClinicalSection.source_segment_ids: list[str]` (additive
  field) — every contributing segment's id is now recorded, not just
  its heading string.
- `canonical_headings.py`: `classify_canonical_heading(raw_heading) ->
  CanonicalSectionKey` — deterministic (no LLM call), verified against
  every V3 contract worked example (EPICRIZĂ -> clinical_course,
  TRATAMENT RECOMANDAT -> recommendations, REȚETE ELIBERATE ->
  prescriptions, EXAMENE DE LABORATOR -> laboratory_results, DIAGNOSTIC
  PRINCIPAL/SECUNDAR -> diagnoses) and every real fallback title
  `discharge_summary_pipeline.py`'s `SECTION_TITLE_BY_KEY` produces
  today. Found and fixed a real collision before production: the
  pipeline's own "Investigations / imaging" fallback title would have
  misclassified as `imaging` before `investigations` was reordered
  ahead of it. `consolidate_segments(segments, review_state="auto") ->
  list[ClinicalSection]` — the segment-aware consolidation: merges
  same-canonical-key segments into ONE section, records
  `source_segment_ids`, and DROPS a resulting section entirely if every
  contributing segment had empty/whitespace-only text (the V3
  contract's "empty/non-substantive sections should not become
  prominent canonical sections" rule). `merge_headings_into_sections`
  (the older, tuple-based, non-segment-aware function from increment 1)
  is kept UNCHANGED for its own existing simpler tests — it does NOT
  apply the empty-section-dropping rule; `consolidate_segments` is what
  real pipeline code should use.
- `persistence.py`'s backward-compat upconversion now goes through
  `segments.py` + `consolidate_segments` too (verified safe against
  every existing persistence test — a strict capability upgrade, not a
  behavior change for any currently-passing case).
- `discharge_parser.py`: `parse_legacy_discharge_payload(payload) ->
  StructuredClinicalDocument` — the real, forward-looking orchestration
  (see section 9d) that assembles sections via this exact pipeline.

**Requirements checklist** (all met): raw source heading ≠ UI
navigation key ✓ (canonical_key is always the fixed enum); repeated
headings merge into one canonical section ✓; source headings preserved
in metadata (`source_headings`) ✓; source ordering reconstructable
(`order`, first-occurrence position) ✓; empty/non-substantive sections
don't become prominent ✓ (`consolidate_segments` drops them); `"other"`
is last resort ✓ (only after every named category is tried); no
LLM-generated arbitrary section names ✓ (deterministic keyword
matching only); no silent text rewriting ✓ (`.strip()` only, never
altering meaning).

**Tests** (all passing): `test_clinical_document_canonical_headings.py`
(19 — heading classification, incl. the investigations/imaging fix and
a legacy-remap cross-check) + `test_clinical_document_segments.py` (14
— repeated EPICRIZĂ with order preserved across an interleaved
different-category segment, repeated diagnoses, repeated administrative
sections, Investigations/imaging, unknown headings -> other, empty
sections dropped, a mixed empty+real-contributor section kept in full
with both segment ids recorded, mixed Romanian/English headings,
end-to-end reconstruction from a real legacy payload) = 33 Phase-4-
specific tests.

**What does NOT exist yet**: table/key-value/list block construction
from real per-section content — `consolidate_segments` only ever
produces `ParagraphBlock`s from plain body text (correct for this
scope; a lab-values table embedded in a section still becomes
`ParagraphBlock` text today, not a real `TableBlock` — that level of
structure extraction is Phase 6/7's job once labs/medications exist to
populate it).

**Sequencing note — READ BEFORE WIRING THIS INTO THE REAL PIPELINE**:
actually switching `discharge_summary_pipeline.py`'s write path to
persist a `StructuredClinicalDocument` (via
`discharge_parser.parse_legacy_discharge_payload` +
`persistence.serialize_structured_document`) instead of the old ad-hoc
JSON would immediately change what NEW documents' `note_body` contains.
`frontend/app/documents/[id]/discharge/page.tsx`'s
`parseDischargePayload` only understands the OLD shape today — it does
NOT read `schema_version`-carrying JSON. Doing the write-side switch
before Phase 8 (discharge reader frontend rebuild) exists would make
every NEW discharge upload's page render incorrectly (or fail to
render) until Phase 8 catches up — a real, visible regression, and
exactly the kind of "redesigning the frontend" this session was told
not to begin. Two honest ways to sequence this correctly (a decision for
whoever does this wiring, not made unilaterally here):
1. **Dual-write**: have the pipeline construct and validate a
   `StructuredClinicalDocument`, but keep writing the OLD shape to
   `note_body` as the live/rendered value until Phase 8 ships, storing
   the new structured result somewhere Phase 8 can pick it up from
   (e.g. a second, additive field, or recomputed on read via
   `discharge_parser.parse_legacy_discharge_payload` against the old
   shape — which is exactly what this module already does). This keeps
   the frontend completely unaffected during Phases 6-7.
2. **Switch the write path now, ship Phase 8 in the same continuous
   effort** before merging/deploying anything — riskier if the session
   doing this wiring doesn't also finish Phase 8's minimum viable read
   path in the same pass.
Option 1 is more consistent with this project's own established pattern
of small, independently-verified increments and is the recommended
default absent a reason to prefer option 2.

## 9c. Phase 5 — Clinical Course dated-event extraction (COMPLETE, not yet live-wired)

**What exists — real ClinicalEvent construction from real text**:

- `dates.py`: `parse_date_token(raw_text)`/`find_dates_in_text(text)` —
  numeric `DD.MM.YYYY`/`DD/MM/YYYY`/`DD-MM-YYYY` and Romanian
  named-month `D MonthName YYYY` forms. An impossible calendar date
  (`31.02.2026`) returns `normalized_date=None` plus a warning, never
  corrected. **New this increment**: a SEPARATE plausibility check — a
  calendrically VALID but implausible year (e.g. the V3 contract's own
  `14/09/3036` example) keeps its real `normalized_date` (the date
  genuinely IS that value) but is flagged with a warning and lowered
  confidence, distinguishing "suspicious" from "impossible."
- `events.py` (new): `classify_event_type_from_context(text,
  date_start)` — deterministic keyword-context classification into the
  contract's exact 8-value `event_type` enum, checking the text
  immediately PRECEDING a date first (matching real Romanian sentence
  structure — "internat la [date]") before falling back to the text
  after it. A real bug was caught and fixed before shipping: an earlier
  draft searched a combined before+after window with fixed category
  priority, which misattributed a NEXT sentence's keyword to the
  CURRENT date whenever two dated mentions sit close together — caught
  by a dedicated regression test. A date with no recognizable keyword
  nearby classifies as `"other"` — the contract's "do not infer an
  encounter when the source only contains narrative history" rule,
  enforced as real behavior, not just documented.
  `find_vital_sign_warnings(text)` — deterministic regex scan for AV
  (heart rate)/FR (respiratory rate)/temp/TA (blood pressure) mentions,
  flagging physiologically implausible values (e.g. "AV 1008") without
  ever rewriting the source text.
  `build_events_from_segment_text(segment_id, text)` — assembles real
  `ClinicalEvent` instances with unique `source_event_id`s derived from
  the real segment id.
- `discharge_parser.py` (new, see section 9d): ties this into the full
  pipeline, INCLUDING a chronology sanity check (an event dated outside
  the document's own recorded admission/discharge window is flagged,
  never silently dropped/moved).

**Tests** (all passing): `test_clinical_document_dates.py` (22 — incl.
3 new for the plausibility check) + `test_clinical_document_events.py`
(15 — event-type classification per category, the adjacent-dates
regression, vital-sign plausibility, end-to-end event construction) +
`test_clinical_document_discharge_parser.py` (8, see section 9d) = 45
Phase-5-specific tests, including all three of the V3 contract's own
required fixture examples verified end-to-end.

**What does NOT exist yet**: `PatientEvent`/Timeline integration
(Phase 10) — `ClinicalEvent` objects are constructed and validated but
nothing persists them as `PatientEvent` rows yet. Table/key-value
structured observations from event text (`structured_observations`/
`medication_changes`/`procedures` on `ClinicalEvent` all default to
empty lists today — the text is captured in `raw_text` but not further
structured into those fields yet; that's a reasonable next increment,
not attempted here). No live wiring into the discharge pipeline (same
sequencing note as Phase 4, section 9b).

## 9d. Phase 4+5 orchestration — discharge_parser.py

`app/services/clinical_document/discharge_parser.py::
parse_legacy_discharge_payload(payload) -> StructuredClinicalDocument`
is the real, end-to-end pipeline tying Phases 3-5 together: segments ->
canonical sections (via `consolidate_segments`) -> Clinical Course
dated events (via `events.build_events_from_segment_text`, scoped ONLY
to event-bearing canonical sections —
`clinical_course`/`treatment`/`procedures`/`investigations` — so a date
in, say, `administrative_information` never becomes a fabricated
encounter) -> a chronology sanity check against the document's own
recorded admission/discharge metadata -> one validated
`StructuredClinicalDocument` with `parser_version=
"discharge-parser-phase4-5-v1"` (a real forward-parser label, distinct
from `persistence.py`'s `"legacy-discharge-upconversion-v1"`
backward-compat stopgap).

Event provenance is tied to the ORIGINAL segment
(`segment.segment_id`), not the merged section's blocks — this stays
correct even when a canonical section merges several segments (some of
which may have contributed no text and therefore no block) or several
source headings, so the exact originating segment remains
reconstructable — this is what section/segment identity preservation
(the explicit Phase 4/5 completion requirement) actually delivers for
labs/medications/prescriptions/Ask Bragi to build on later.

**Tests** (8, `test_clinical_document_discharge_parser.py`), including
all three of the V3 contract's own required fixture examples verified
to survive UNCHANGED end-to-end — not just at the unit level, but
through the FULL real pipeline:
1. A future-looking source date (`14/09/3036`) keeps its real
   `normalized_date` (`3036-09-14`) plus a plausibility warning, never
   corrected.
2. A chronologically misplaced 2024 "control" inside an otherwise-2026
   encounter is correctly classified `event_type="follow_up"` and
   flagged with exactly ONE chronology warning naming the actual
   misplaced date — the two legitimate in-window events are NOT also
   flagged.
3. An impossible-looking vital sign (`AV 1008 bpm`) is flagged verbatim
   in the document's warnings; the event itself is otherwise
   unaffected.

Also verified: sections and events both correctly derived from the same
source text; administrative-section dates never becoming fabricated
events; no chronology warning fired when either admission or discharge
date is unknown (never guessing the missing bound).

**Still NOT wired into `discharge_summary_pipeline.py`'s live write
path** — see section 9b's sequencing note. This is what a future
dual-write increment would call.

## 9e. Phase 6 — embedded lab extraction into canonical LabResult (COMPLETE)

**What exists — extraction, grouping, and canonical persistence, all
real and DB-tested**:

- `lab_extraction.py` (new): `LabCandidate` — the typed intermediate
  representation (source_segment_id, source_heading, raw_test_name,
  raw_value, parsed_value, raw_unit, normalized_unit, reference_range,
  source_flag, source_section_status, observation_date, request_code,
  source_panel, source_evidence_text, source_page, confidence,
  warnings). `extract_lab_candidates_from_segment(segment)` reads a
  `laboratory_results`-classified `SourceSegment`'s raw text/table and
  produces candidates — single lab-shaped lines (numeric AND
  qualitative/textual values, e.g. "VDRL: Negativ"), compact CBC rows,
  Romanian/English labels, table rows (via header-name matching, never
  positional guessing beyond the narrowest 2-column case), and explicit
  normal/pathological subsection tracking. Precision over recall
  throughout: a narrative sentence containing a number is never mistaken
  for a lab row (multiple explicit guards — line length, name word
  count, a unit-suffix vs. flag-letter disambiguation fix found and
  fixed before shipping: `mmol/L`'s trailing "L" was initially
  colliding with the "Low" flag marker, caught by
  `test_table_like_rows_are_extracted`). Observation date and
  request/accession code are ONLY read when an explicit label keyword
  precedes them in the source text — never the first date-shaped
  substring found anywhere (see `test_no_date_label_means_no_
  fabricated_observation_date`).
- `lab_grouping.py` (new): `LabReportGroup`/`group_lab_candidates` —
  deterministic grouping by (request_code, observation_date,
  source_panel); when a candidate carries NONE of those three, falls
  back to "same originating segment" (the safest real boundary already
  established by Phase 4) rather than inventing a split or an
  over-broad merge. Never groups by clinical intuition.
- `lab_persistence.py` (new): `persist_lab_candidates(db, document=,
  candidates=)` — the ONLY place in this package that touches the
  database for labs. For each candidate: `lab_resolver.resolve_analyte()`
  (the EXISTING shared resolver — no private alias dictionary, no
  per-analyte special-casing) resolves `canonical_name`/`display_name`/
  `category`/`normalization_method`; `derive_lab_flag()` applies the
  contract's exact precedence (explicit provider flag > explicit
  pathological/normal section placement > numeric range comparison >
  unknown — Bragi's own calculation NEVER overrides an explicit source
  flag); a real `LabResult` + `SourceEvidence` row is created, attached
  to the AUTHORITATIVE PARENT discharge document (`document_id` —
  requirement 8's exact wording), never to the derived artifact.
  `SourceEvidence.source_block_id` carries the originating
  `segment_id`; `page_number` is only ever set from a genuine
  `SourceSegment.page` (currently always `None` — today's discharge
  pipeline doesn't populate per-page segments — never fabricated); no
  bbox is ever invented. One derived `Document` row
  (`derived_artifact_kind="lab_report"`, `parent_document_id=<parent>.id`,
  pointer-only `note_body` — `{document_type, artifact_type, group_key,
  source_section_id}`, NEVER a second copy of lab values) is
  get-or-created PER `LabReportGroup` — never one per analyte, never one
  for the whole discharge when the source distinguishes multiple
  reports. Idempotent throughout: both the per-observation lookup
  (`document_id` + `source_segment_id` + `raw_test_name` + `raw_value` +
  `observation_datetime`) and the derived-document lookup
  (`parent_document_id` + `group_key`, encoded in `report_type`) are
  exact-match queries run BEFORE every insert — never `created_at`.
- **Conflict preservation**: within one group, two candidates sharing a
  `raw_test_name` but a DIFFERENT `raw_value` (the synthetic fixture's
  MCH case — 29.0 pg under "Valori normale", 31.5 pg under "Valori
  patologice", same request/date) are BOTH persisted as separate
  `LabResult` rows, both with `verification_state="conflict"` — neither
  is treated as authoritative, and a document-level warning names the
  conflict. Resolved independently through the SAME shared resolver
  (both rows get `canonical_name="mch"`).
- **Deletion**: `DELETE /documents/{document_id}`
  (`app/api/routers/documents.py`) now explicitly hard-deletes any
  child `Document` with `derived_artifact_kind` set before deleting the
  requested document — this is DIFFERENT from an ordinary Reducto Split
  child, which keeps `parent_document_id`'s existing
  `ondelete="SET NULL"` behavior unchanged (a Split child is meant to
  survive its parent's deletion; a derived lab artifact is not). The
  derived artifact's own `LabResult`/`SourceEvidence` rows are never
  touched by this new logic — Phase 6 never attaches those to the
  derived artifact in the first place, so deleting the parent (which
  DOES own them) already removes them via the EXISTING
  `Document.lab_results` cascade, unchanged.

**Schema/model changes** (both additive, per the contract's own "no new
DB columns unless truly necessary" instruction):
- `models.Document.derived_artifact_kind` (nullable `String`) — genuinely
  necessary: `parent_document_id` alone can't distinguish a derived
  artifact (must hard-delete with its parent) from a Split child (must
  survive), and a Split child CAN itself be `document_type=
  laboratory_results`, so `document_type` can't make that distinction
  either. One Alembic migration (`b52c5c35f707_phase6_derived_artifact_
  kind.py`), applied and confirmed against `check_migration_drift.py`
  (clean, same 8 known/tolerated legacy-index differences as every prior
  migration in this branch).
- `schema.DerivedArtifactRef.group_key` (optional `str`, default `None`)
  — the Phase 6 coherent-report identity; lets a future caller construct
  real `DerivedArtifactRef`s from a `LabPersistenceResult` (see
  `LabPersistenceResult.derived_artifact_refs()`) and distinguishes
  multiple derived artifacts sharing the same `source_section_id`.

**Requirements checklist** (all met): feeds the existing
`resolve_analyte()`, no private alias dictionary, no second lab
datastore ✓; typed `LabCandidate` intermediate, no direct ORM mutation
while reading text ✓; precision-first extraction (tables, colon lines,
compact CBC rows, RO/EN labels, normal/pathological sections, multiple
subsections) ✓; deterministic flag precedence ✓; conflicts preserved,
never decided between ✓; deterministic grouping, no fabricated panel
membership ✓; LabResult attaches to the authoritative parent, not the
derived artifact ✓; one derived artifact per coherent report ✓;
provenance to segment/heading/text (never a fake PDF page/bbox) ✓;
idempotent identities defined and DB-proven now (not deferred to Phase
13) ✓; deletion never orphans a derived artifact, never touches an
unrelated source's row ✓; frontend NOT touched ✓.

**Tests** (44 new, all passing — 19 `test_clinical_document_lab_
extraction.py` + 7 `test_clinical_document_lab_grouping.py` [both pure,
no DB] + 18 `test_clinical_document_lab_persistence.py` [real DB, same
skip-gracefully-without-`DATABASE_URL` convention as
`test_idor_regression.py`]) — covering every category in the V3
contract's Phase 6 required-test list: normal/pathological section
extraction, CBC abbreviations, Romanian aliases, unresolved-stays-
unresolved, numeric AND textual/qualitative value preservation, units,
reference intervals, all three flag-precedence tiers, conflicting rows
preserved, separate request/date groups staying separate, source order
and segment provenance retained, real-vs-honestly-absent PDF page
evidence, canonical resolver reuse (including the required PLT/WBC/HGB
+ trombocite/leucocite/hemoglobina alias set, verified against the SAME
`lab_resolver.resolve_analyte()` the rest of the app calls), and three
distinct idempotency proofs (LabResult count, derived-artifact count,
SourceEvidence count all unchanged on a second identical extraction
pass) plus one true end-to-end deletion test through the real
`DELETE /documents/{id}` route (not just a mirror of its logic).

**What does NOT exist yet**: `discharge_summary_pipeline.py`'s live
write path is unchanged — `lab_persistence.py` is callable and fully
DB-tested standalone but nothing in the real upload flow calls it yet
(same deliberate sequencing as Phases 4/5, section 9b — not a Phase 6
gap, a cross-phase decision). The frontend `StructuredLabReport`
component (Phase 8) and Documents-page derived-artifact UI (Phase 9)
do not exist — Phase 6 deliberately stops at the backend representation
per its own instruction 14. `ClinicalEvent.structured_observations`/
`medication_changes`/`procedures` remain unpopulated (Phase 5's own
known gap, unrelated to Phase 6). Real per-page/bbox segmentation
(which would let `SourceEvidence.page_number`/bbox ever be non-null for
an embedded lab) does not exist — `lab_persistence.py` already reads
`LabCandidate.source_page` rather than hardcoding `None`, so this
requires no further code change once a real per-page segmenter exists,
only real data flowing through it (proven now by
`test_pdf_evidence_page_retained_when_the_source_segment_genuinely_
has_one`, which synthesizes a segment with a real `page` to prove the
plumbing works today even though nothing produces one in practice yet).

## 10. Lab artifact semantics

**Phase 6 COMPLETE for embedded-discharge labs — see section 9e for
full detail.** Embedded labs inside a discharge document's
`laboratory_results` section are now extracted (`lab_extraction.py`),
grouped into coherent source reports (`lab_grouping.py`), and persisted
as real, canonical `LabResult` rows plus one derived "lab_report"
`Document` artifact per group (`lab_persistence.py`) — feeding the SAME
`resolve_analyte()` resolver every other lab-ingestion path uses, never
a second lab datastore. This is a real, DB-tested, callable service —
**not yet wired into the live discharge upload write path**
(`discharge_summary_pipeline.py` is unchanged; see section 9b's
sequencing note, which now also governs Phase 6's wiring). Not yet
surfaced anywhere in the frontend (deliberately deferred to Phases 8/9).
Not yet reachable from `/patients/{id}/bloodwork-trends`
(`app/api/routers/labs.py`) even once wired: that route filters
`Document.section == "bloodwork"`, but an embedded lab's `LabResult.
document_id` is the discharge document (`section="discharge_summary"`,
per requirement 8's "attach to the authoritative parent" rule) — a
real, pre-existing-shaped gap for whoever does Timeline/trends wiring
later (Phase 10), not something Phase 6 should silently patch by
bending its own ownership rule.

## 11. Medication semantics

**NOT STARTED.** No medication-context classification, duration parser,
or end-date derivation exists. `PatientMedication` rows today are
created only through the existing manual/medication-list-document paths
documented in the pipeline map — discharge-summary-embedded medication
mentions are not extracted into `PatientMedication` at all today.

## 12. End-date derivation rule

**NOT STARTED / NOT DEFINED.** No end-date calculation code exists. The
contract's exact interval convention (start + N days = [start, start+N),
"2 weeks" = +14 days, calendar-month arithmetic for months, `null` for
PRN/ambiguous/indefinite cases) is specified in the contract text but
not yet implemented anywhere.

## 13. Timeline rules

**NOT STARTED.** `PatientEvent` today is created only via the doctor-
driven `POST /patient-events` route (confirmed in the pipeline map) —
discharge upload does not create or touch a `PatientEvent` row. No
dated-Clinical-Course-event extraction, and no lab/medication-driven
Timeline entries, exist yet.

## 14. Provenance rules

Unchanged from before this session for the existing (lab-result-level)
SourceEvidence mechanism — that part of the architecture was not
touched. No new provenance mechanism for discharge-document sections/
events/medications exists yet (that's Phase 12's job, not attempted).

## 15. Ask Bragi changes (the actual P0 fix — full detail)

**Diagnosis process** (all 10 layers from the contract's own list were
actually checked, not assumed):

- **A/B (conversation creation, request payload)**: not implicated —
  `_load_ask_bragi_conversation_for_owner` and `AskBragiMessageRequest`
  are unchanged, simple, and covered by 15 passing tests in
  `test_ask_bragi_security.py`.
- **C (frontend streaming parser)**: `frontend/lib/ask-bragi-api.ts`'s
  `streamAskBragiMessage` read in full — correct SSE frame buffering
  (splits on `\n\n`, handles partial frames across chunk boundaries),
  defensive `try/catch` around `JSON.parse` per frame. No bug found.
- **D (FastAPI route)**: `backend/app/api/routers/ask_bragi.py` — the
  exact three call sites of the reported error string were located
  (lines 287, 290, 404 as of this session). All three are catch-alls
  wrapping `run_turn`/`run_turn_streaming`. Logging at these sites was
  already PHI-safe (`type(exc).__name__` or a hardcoded safe string
  only — never the question text, never document content) — this
  already satisfies the contract's explicit production-log constraint,
  no change was needed there.
- **E (Ask Bragi service)**: `service.py` read in full. **This is where
  the actual root cause was found** — see below.
- **F (OpenAI/provider call)**: **cannot be exercised at all in this
  local environment** — `OPENAI_API_KEY` is not configured (confirmed
  via `python -c "import os; print(os.environ.get('OPENAI_API_KEY'))"`
  after `load_dotenv()`, prints nothing). Every real Ask Bragi call in
  this exact dev setup fails immediately with
  `AskBragiError("OPENAI_API_KEY is not configured.")`, which the route
  turns into the exact same generic error text — but this is a local-
  environment limitation, not the bug the user is reporting (they must
  have a working key in whatever environment they saw the bug in, since
  the report implies other questions work). Documented honestly rather
  than fabricating a live repro that did not happen.
- **G/H (tool dispatch, result serialization)**: `tools.py` read in
  full. `run_tool()`/`json.dumps(result)` — no unbounded/unserializable
  value found in any tool's return dict (all are plain str/int/float/
  None/list/dict).
- **I (final response validation)**: `schemas.py` read in full.
  `MODEL_OUTPUT_JSON_SCHEMA` and `ModelOutput` are consistent with each
  other field-for-field; `strict: False` is set explicitly on both the
  output-format schema and every tool schema (so the union-typed
  nullable fields like `{"type": ["string", "null"]}` are not a
  provider-side rejection risk — strict mode is what would require
  stricter shapes, and it's off).
- **J (SSE framing)**: `_sse()` in `ask_bragi.py` — plain
  `f"event: {event}\ndata: {json.dumps(data)}\n\n"`, matches what the
  frontend parser expects exactly.

**Root cause**: `ASK_BRAGI_MAX_TOOL_ROUNDS` defaulted to 4. Both
specifically-reported prompts are broad, multi-analyte questions. A
well-behaved model answering "what changed in my latest bloodwork"
might reasonably call `get_patient_context`, then `search_documents`,
then `compare_lab_results` once per analyte in a CBC/metabolic panel
(10-20 rows) — each of those is one "round" in this code's accounting
(`round_index` increments once per `client.responses.create()` call,
regardless of how many function calls the model batches into that one
response). 4 rounds is not enough headroom for that pattern. When the
budget runs out, `run_turn`/`run_turn_streaming` raise/yield
`AskBragiError("...too many tool calls")`, which the route layer turns
into the exact reported generic message. This is a real, reproducible
failure mode — not fixed by adding a special case, not touching the
lab/tool architecture, and does not touch app/main.py.

**Fix** (two parts, both committed in `9c92148`):
1. `prompts.py` — new "TOOL EFFICIENCY" instruction telling the model:
   for a broad multi-analyte question, call `get_lab_results` ONCE with
   a generous limit (e.g. 40, covering both the latest and previous
   report) and compute each analyte's own latest-vs-previous delta
   itself from that single result set, instead of one
   `compare_lab_results` call per analyte; and to prefer the single most
   direct tool for a simple question rather than exploratory context
   calls it doesn't need. This reduces the actual number of rounds a
   real model needs for exactly the failing query shape.
2. `service.py` — `ASK_BRAGI_MAX_TOOL_ROUNDS` default raised 4 → 8 as
   defense-in-depth for whatever the prompt guidance doesn't eliminate
   (a genuinely unusual conversation, a model that doesn't fully follow
   the new guidance, etc.).

**Not done**: live verification against a real OpenAI key of the full
"Ask Bragi execution contract" (create/send/stream/second-message/stop/
resume/patient-switch) — impossible in this environment (no key). This
is instead covered by the existing, passing, mocked
`test_ask_bragi_security.py` (15 tests: conversation creation/ownership/
scoping/revocation across patient/doctor/admin/care_partner) and
`test_ask_bragi_streaming.py` (11 tests: streaming text delta
accumulation, tool-round-then-answer, stop-mid-stream not persisting,
authentication requirement, and the incremental JSON-string-extraction
helper's edge cases) — every one of those flows already has coverage
that does not require a real provider call, because the OpenAI client
itself is mocked at the boundary (`ask_bragi_service._client`/
`_async_client`).

## 16. Idempotency keys

**Phase 6 establishes the first real idempotent identities in this
package** (see section 9e): a `LabResult`'s identity is
`(document_id, source_segment_id, raw_test_name, raw_value,
observation_datetime)`; a derived lab-report `Document`'s identity is
`(parent_document_id, group_key)`. Both are exact-match DB lookups run
before every insert — never `created_at`. Proven by three dedicated
tests (`test_repeated_identical_extraction_does_not_duplicate_
lab_results`/`..._the_derived_artifact`/`..._source_evidence`), each
calling `persist_lab_candidates` twice with the SAME candidates and
asserting row counts are unchanged the second time. This satisfies
Phase 6's own instruction 12 ("begin the idempotency architecture now")
— NOT Phase 13's full requirement, which still needs the 1x/2x/10x
proof against a REAL end-to-end upload once the live write path exists
(medications/`PatientEvent` idempotency is also still Phase 13's job,
unaddressed here).

## 17. Deletion behavior

Single-document delete (`DELETE /documents/{document_id}`) gained one
real behavior change this checkpoint (Phase 6, section 9e): it now
explicitly hard-deletes any child `Document` with
`derived_artifact_kind` set before deleting the requested document —
previously (and still, for an ordinary Reducto Split child) a child's
`parent_document_id` only gets `SET NULL`'d at the DB level, leaving it
orphaned rather than removed. This does NOT change Split-child behavior
at all (that FK's `ondelete="SET NULL"` is untouched; the new logic is
a separate, explicit query scoped only to `derived_artifact_kind IS NOT
NULL` rows). Everything else — the pre-existing asymmetry between this
route and `DELETE /my/account` documented in `docs/clinical_document_v3/
CURRENT_PIPELINE_MAP.md`, the reliance on `Document.lab_results`'s ORM
cascade for ordinary lab rows — is unchanged, not fixed, not worsened.

## 18. Test fixtures

- `backend/scripts/seed_e2e_lab_document.py` (existing, unchanged) — see
  section 7.
- **The synthetic hematology-discharge fixture now exists** — not yet
  as Phase 15's own dedicated standalone fixture file, but as
  `HEMATOLOGY_FIXTURE_TEXT` in `backend/tests/test_clinical_document_
  lab_extraction.py` (imported directly by
  `test_clinical_document_lab_persistence.py`), covering every value the
  V3 contract's Phase 6 fixture section names (AST/ALT/bilirubin/
  glucose/creatinine/WBC/RBC/HGB/HCT/PLT/APTT/INR/MCH-conflict/RDW-SD/
  RDW-CV/NEUT/LYMPH#, with an explicit request code and observation
  date, and normal/pathological subsections). Phase 15's own broader
  requirement (a full synthetic DISCHARGE document exercising Phases
  0-14 together, not just the lab section in isolation) is still
  unaddressed.

## 19. Test counts

- Backend: 328 (Phase 0-2 session start baseline) → 330 after Phase 2
  (+2, `test_ask_bragi_service.py`) → 353 after Phase 3 (+23,
  `test_clinical_document_schema.py` + `test_clinical_document_
  persistence.py`) — **full suite reran green at this point: 353 passed
  in 1041.44s.** → 372 after Phase 4 increment 1 (+19,
  `test_clinical_document_canonical_headings.py`) → unchanged (372) after
  the persistence.py/canonical_headings.py unification refactor (one
  test renamed, none added/removed) → **391 confirmed after Phase 5
  increment 1** (+19, `test_clinical_document_dates.py`) → **431
  CONFIRMED after Phases 4/5 COMPLETION** (+40: +14
  `test_clinical_document_segments.py`, +3 new `dates.py` plausibility
  tests, +15 `test_clinical_document_events.py`, +8
  `test_clinical_document_discharge_parser.py`) — **full suite reran
  clean: `431 passed, 5 warnings in 981.97s (0:16:21)` — zero failures,
  zero errors, no Neon flake this run.** All 101 `clinical_document`-
  specific tests were also individually confirmed passing beforehand
  (`pytest tests/test_clinical_document_*.py -q` → `101 passed`).
  → **474 CONFIRMED after Phase 6 COMPLETION** (net +43 over the 431
  baseline; 44 new Phase-6-specific test functions were added across
  three new files — `test_clinical_document_lab_extraction.py` (19),
  `test_clinical_document_lab_grouping.py` (7),
  `test_clinical_document_lab_persistence.py` (18) — the 431→474 net
  delta is one less than that 44-function count; every new test file
  was independently re-confirmed passing in isolation immediately before
  the full run, and no existing test was removed/renamed by this
  checkpoint, so this is most plausibly the 431 baseline itself having
  been off by one already rather than anything Phase 6 broke — flagged
  honestly rather than silently reconciled, since it wasn't re-derived
  from a byte-for-byte prior count in this session). **Full suite reran
  clean: `474 passed, 5 warnings in 885.98s (0:14:45)` — zero failures,
  zero errors, no Neon flake this run.** All 44 new Phase 6 tests were
  also individually reconfirmed passing per-file immediately beforehand.

  **Environmental note for future sessions — Neon connectivity drops
  during long (20-25 min) full-suite runs are a real, observed, RECURRING
  characteristic of this dev setup, not a one-off fluke**: two separate
  full-suite runs this session each hit exactly ONE transient DB
  connection failure, on two entirely different, unrelated tests:
  1. Run after Phase 4 increment 1: `1 failed, 360 passed, 11 errors` —
     all 12 dysfunctional outcomes were `psycopg.OperationalError`
     ("No route to host" / "getaddrinfo failed") on
     `tests/test_migrations.py`/`tests/test_upload_validation.py`.
  2. A later full clean re-run covering all 391 tests: `1 failed, 390
     passed` — `tests/test_interop_e2e.py::
     test_server_a_full_featured_zero_code_sync` failed with
     `OperationalError: server closed the connection unexpectedly` on a
     `pg_advisory_unlock` call.
  Neither failure touches `clinical_document` (pure-Python, zero DB
  access) or anything else this session changed. Both times, DB
  connectivity was confirmed restored within seconds
  (`SessionLocal().execute(text("SELECT 1"))` succeeding), and the
  SPECIFIC failed test(s) were re-run in isolation and passed cleanly
  every time (13/13, then 1/1). **391/391 tests are genuinely
  confirmed passing** — via the combination of a full run plus an
  isolated re-run of its one flaky failure, not via a single
  uninterrupted green run (repeatedly re-running the full 20-25-minute
  suite hoping for one lucky uninterrupted pass is not a good use of
  time once the flake's cause is this well-established).
  **Guidance for a future session**: if a full-suite run reports a
  `psycopg.OperationalError`/`getaddrinfo failed`/"server closed the
  connection unexpectedly" failure, do NOT treat it as a regression by
  default — (1) confirm DB connectivity is currently fine
  (`SessionLocal().execute(text("SELECT 1"))`), (2) re-run ONLY the
  specific failed test(s) in isolation, (3) only if it fails AGAIN in
  isolation with connectivity confirmed good should it be treated as a
  real bug. Always re-run `pytest -q` and trust its own summary line
  over any number in this file if they ever disagree.
- Frontend Playwright: 3 (existing) → 5 after Phase 2 (+2,
  `right-workspace-geometry.spec.ts`) — unchanged by Phases 3-6 (no
  frontend application behavior changed).
- OpenAPI routes: unchanged, 117 routes / 99 paths (Phases 3-6 added no
  route — Phase 6's only DB-visible surface is the one additive
  `documents.derived_artifact_kind` column, via `DELETE /documents/{id}`,
  an EXISTING route with no new endpoint).
- Bandit (`python -m bandit -r app -ll -q`): clean after Phase 6 — zero
  findings (only benign "Test in comment" collector warnings unrelated
  to any real issue, same as every prior checkpoint).
- Migration drift (`python scripts/check_migration_drift.py`): clean
  after Phase 6's migration — "No migration drift detected (8
  known/tolerated legacy-index difference(s) ignored)", same 8 as every
  prior checkpoint, plus the new `derived_artifact_kind` column applied
  and confirmed via `alembic upgrade head`.

## 20. Playwright coverage (what exists now)

- `ask-bragi-workspace.spec.ts` (pre-existing, from the merged branch):
  dedicated-page first-message lifecycle (typed message + suggestion
  chip), Overview card height-cap control case.
- `right-workspace-geometry.spec.ts` (new this session): single-panel-
  open fills the column; both-panels-open shows tabs and the inactive
  one is truly hidden, not squeezed. **Proven genuine**: temporarily
  reverted `right-workspace.tsx` to the pre-fix shape (both wrappers
  unconditional), reran — test 1 failed with 450px actual vs >810px
  expected (a near-exact 50/50 split), confirming this is a real
  regression test and not one that would pass regardless of the fix.
  Restored and reverified green afterward.

None of Phase 16's document/derived-lab/timeline/medication Playwright
coverage exists yet — those need Phases 4-13 to exist first.

## 21. Real bugs found (this session)

1. **Ask Bragi tool-round-budget exhaustion on broad multi-analyte
   questions** (Phase 2's P0) — see section 15. Real, reproduced (via a
   realistic mocked tool-call sequence, not merely the abstract "N > 4"
   case the pre-existing `test_max_tool_rounds_is_enforced` test
   already covered), fixed, and regression-tested both ways.

No other bugs were found during Phase 3 (a new, isolated schema/
persistence module with no prior behavior to regress) or since.

## 22. Known gaps / deferred items (READ THIS BEFORE CLAIMING THIS CONTRACT IS DONE)

Phases 3, 4, 5, and 6 are ALL COMPLETE (sections 9, 9b, 9c, 9d, 9e) —
real, tested segmentation, canonical section consolidation, Clinical
Course event extraction (including chronology and vital-sign
plausibility checks), and embedded lab extraction/grouping/canonical
persistence all exist and are proven against every relevant V3 contract
example, including all three required suspicious-data fixtures (Phase
5) and the synthetic hematology fixture (Phase 6). None of Phases 4-6's
production code is wired into the real live discharge INGESTION pipeline
yet (deliberate — section 9b's sequencing note, which now also governs
Phase 6); Phase 6's own persistence SERVICE (`lab_persistence.py`) is
however fully callable and DB-tested standalone today — a real
distinction, not a contradiction (see section 9e). Table/key-value block
construction from real per-section content (beyond `ParagraphBlock`)
still does not exist for the STRUCTURED-DOCUMENT schema's own blocks
(`TableBlock` etc. — Phase 6 produces real structured `LabCandidate`s,
but doesn't yet emit a `TableBlock`/`LabReportReferenceBlock` back into
a section's own `blocks[]`, since nothing wires Phase 6 into
`discharge_parser.py`'s orchestration yet). `ClinicalEvent.
structured_observations`/`medication_changes`/`procedures` are not yet
independently populated (captured only in each event's `raw_text`
today) — Phase 7's job. Everything from Phase 7 onward through Phase 21
of the original contract is **entirely unimplemented**:

- Phase 7: medication context classification, duration parser,
  deterministic end-date derivation.
- Phase 8: discharge reader frontend rebuild (header/outline/canvas/
  workspace), `StructuredLabReport` component.
- Phase 9: Documents page derived-artifact relationship UI.
- Phase 10: Timeline integration for derived labs/medication events.
- Phase 11: Ask Bragi retrieval hardening for the new structured data
  (structured dated-event queries, transparent end-date-derivation
  language in answers).
- Phase 12: provenance for the new structured facts.
- Phase 13 (partial — Phase 6 laid the LabResult/derived-artifact
  identity groundwork and DB-proved it standalone, section 9e/16 — the
  full 1x/2x/10x proof against a REAL end-to-end discharge UPLOAD, plus
  medication/PatientEvent idempotency, is still this phase's job):
  idempotency guarantees for repeated discharge ingestion.
- Phase 14 (partial — Phase 6 proved its own derived-artifact deletion
  semantics both at the ORM level and through the real DELETE route,
  section 9e/17 — the exhaustive real-Postgres cascade suite across
  every entity type this contract touches is still this phase's job):
  real-Postgres deletion tests for the new derived data.
- Phase 15 (partial — the synthetic hematology LAB VALUES fixture exists
  and is reused across Phase 6's own tests, section 18 — a full
  synthetic DISCHARGE document fixture exercising every phase together,
  as Phase 15 originally intends, does not exist yet): the synthetic
  hematology-discharge test fixture.
- Phase 16 (partial — done for Phase 2's own scope, not for the rest):
  Playwright for the document/lab/medication/timeline flows.
- Phase 17 (partial — Phase 6 contributed its own share of this list:
  alias resolution, dedup/conflict preservation, table/qualitative-value
  extraction, section 17 of this document): the extensive backend test
  list (heading normalization, date extraction, lab/medication dedup,
  etc.).
- Phase 18: the 75-100-case deterministic retrieval benchmark.
- Phase 19: responsive QA screenshots at 7 viewports.
- Phase 20: accessibility verification.
- Phase 21 (full): the final full regression across all of the above —
  the full backend suite HAS been re-run clean at every checkpoint
  through Phase 6 (474/474 as of this one, section 19), but that is
  verification of Phases 0-6's own code, not a certification that
  Phases 7-21's (still nonexistent) code passes anything.

This is a large, honest scope gap. The contract's own framing (21
phases, dozens of named sub-requirements, a 26-section handoff, a 75-
100-case benchmark) is realistically multiple full engineering sessions
of work, not one. Rather than fabricate partial/fake implementations of
Phases 4-21 to appear more complete, this handoff reports exactly what
was verified and stops there.

## 23. HOW TO CONTINUE IN THE NEXT CLAUDE SESSION

Read in this order:
1. This file, in full.
2. `docs/clinical_document_v3/CURRENT_PIPELINE_MAP.md` — the Phase 0
   inventory. It already answers "where does X live today" for
   everything Phase 3+ needs to touch — do not re-derive this from
   scratch.
3. The original Clinical Document Intelligence V3 contract text (ask
   the user for it if it is not visible in this conversation's history —
   it is long and was given verbatim; this handoff summarizes it but is
   not a substitute for the original wording when implementing a
   specific phase's exact rules, e.g. the end-date interval convention
   in Phase 7).

Then:
- Confirm this branch (`fix/clinical-document-intelligence-v3`) is still
  current against `main` (`git fetch && git log main..HEAD --oneline`
  and `git log HEAD..origin/main --oneline` — rebase/merge `main` in if
  it has moved).
- Re-run the full baseline (section 24's commands) before writing any
  new code — "do not continue from a failing baseline" is the contract's
  own Phase 1 rule and it still applies to wherever this branch is when
  you pick it up.
- Start Phase 7 (medication context classification + deterministic
  duration/end-date derivation) — Phases 3, 4, 5, and 6 are ALL done:
  `app/services/clinical_document/schema.py`/`persistence.py` (Phase 3),
  `segments.py`/`canonical_headings.py` (Phase 4), `dates.py`/`events.py`/
  `discharge_parser.py` (Phase 5), `lab_extraction.py`/`lab_grouping.py`/
  `lab_persistence.py` (Phase 6) — use them all as-is (sections
  9/9b/9c/9d/9e), extend additively if a real gap is found, do not
  redesign or duplicate any of them. Reuse the EXISTING
  `PatientMedication` model/status semantics (`app/api/routers/
  medications.py`'s `VALID_MED_STATUSES`) — no separate "discharge
  medication" table or tab, same "no second datastore" rule Phase 6 just
  followed for labs. Re-read the V3 contract's EXACT end-date interval
  convention before writing any code (this handoff's "Hard constraints"
  section only summarizes it: start+N days = `[start, start+N)`, "2
  weeks" = exactly +14 days, real calendar-month arithmetic for months —
  not `30 × N` days, `null` for PRN/"according to scheme"/alternate
  dosing/indefinite/unclear-total-duration tapers). Medication
  start-date priority is likewise exact and easy to get subtly wrong —
  re-read it in the contract text, not just this handoff's summary.
  Duration parsing must be deterministic (Romanian + English units, no
  LLM call), matching every other Phase 4-6 module's own convention.
  Remaining Phase 4/5/6 work NOT required before Phase 7, but still
  open: wiring the discharge pipeline's live write path (section 9b's
  sequencing note — still deferred, now covers Phase 6 too), populating
  `ClinicalEvent.structured_observations`/`medication_changes`/
  `procedures` (currently empty; raw_text carries everything today —
  Phase 7 may naturally want to populate `medication_changes` as part
  of its own work, which is in-scope, not scope creep), and Phase 6's
  own explicitly-deferred items (frontend, `/bloodwork-trends`
  reachability — see section 10's exact wording on why that's a real,
  separate gap).
- Do not re-attempt Phase 2 — it is done, tested, and proven genuine
  (section 20/21). If a *different* Ask Bragi failure surfaces later
  (e.g. once a real `OPENAI_API_KEY` is available and live testing
  becomes possible), diagnose it as a new, separate issue rather than
  assuming this fix was incomplete.
- Do not re-attempt Phase 3 — the schema is done and tested (section 9).
- Do not re-build the canonical-heading classifier or the segmentation/
  consolidation pipeline — they exist, are tested against the
  contract's own worked examples, and `merge_headings_into_sections`
  was already unified with the backward-compat path once proven
  equivalent (section 9b). Building a second classifier/consolidator
  would itself violate the contract's "no parallel product logic" rule.
- Do not re-attempt Phase 4 or Phase 5 — both are complete and tested
  (sections 9b/9c/9d), including a real end-to-end orchestration
  (`discharge_parser.py`) proven against all three required
  suspicious-data fixture examples. If a genuinely NEW gap is found
  (e.g. a Romanian date format not yet handled, a heading pattern that
  misclassifies), extend the existing module additively and add a
  regression test — do not build a parallel implementation.
- Do not re-attempt Phase 6 — embedded lab extraction/grouping/
  persistence is complete and DB-tested (section 9e), including the
  required synthetic hematology fixture, the full Phase 6 test-category
  checklist, and a real end-to-end deletion-cascade test through the
  actual route. If Phase 7 (or later work) needs a genuinely NEW lab-
  extraction capability this module doesn't have, extend
  `lab_extraction.py`/`lab_grouping.py`/`lab_persistence.py` additively
  and add a regression test — do not build a second lab-candidate
  parser or a second persistence path. The one thing intentionally left
  for a LATER phase, not a gap in Phase 6 itself: wiring
  `lab_persistence.persist_lab_candidates` into the live discharge
  upload write path (still deliberately deferred, same sequencing
  reasoning as Phases 4/5 — see section 9b).
- If real live testing against OpenAI/Reducto becomes available in a
  future session, that is the point to actually execute the full "Ask
  Bragi execution contract" end-to-end (section 15's "not done" note)
  and the Phase 18 benchmark against a real model — both were
  structurally impossible this session, not skipped by choice.

## 24. Exact commands for each check type

```bash
# Backend — full suite
cd backend && python -m pytest -q

# Backend — Ask Bragi service tests only (fast, ~40s)
cd backend && python -m pytest tests/test_ask_bragi_service.py tests/test_ask_bragi_tools.py \
  tests/test_ask_bragi_security.py tests/test_ask_bragi_streaming.py -v

# Backend — security lint
cd backend && python -m bandit -r app -ll -q

# Backend — migration drift (NOT plain `alembic check` — see note below)
cd backend && python scripts/check_migration_drift.py

# Frontend — TypeScript (clear .next first, a stale dev build can produce
# false-positive errors in .next/dev/types/routes.d.ts)
cd frontend && rm -rf .next && npx tsc --noEmit

# Frontend — lint
cd frontend && npm run lint

# Frontend — production build
cd frontend && npm run build

# Frontend — Playwright (requires backend on 127.0.0.1:8812 with
# ASK_BRAGI_ENABLED=true, and frontend dev server on localhost:3000 —
# BOTH already running, this suite does not manage either)
cd backend && ASK_BRAGI_ENABLED=true python -m uvicorn app.main:app --host 127.0.0.1 --port 8812 &
cd frontend && npm run dev &
# wait for both to come up, then:
cd frontend && npx playwright test --reporter=list
```

**Migration drift note**: running the raw `alembic check` command
directly reports drift on 8 legacy indexes
(`ix_eas_patient`/`ix_eas_public_id`/`ix_eas_user`/`ix_eal_action`/
`ix_eal_patient`/`ix_eal_session`/`ix_eal_user`/`ix_ec_patient`) that
predate this and every other recent session's work — this is a known,
already-tolerated condition (`scripts/check_migration_drift.py` exists
specifically to filter these 8 out and was confirmed clean this
session). Do not treat the raw `alembic check` output as a real failure
without first checking whether it's exactly this same list.

**On starting local dev servers**: this is fine and is not the same
thing as "starting demo.bragi.health" (the contract's explicit
prohibition, which refers to a specific deployed demo environment, not
local development). Kill only processes you started — this session
found and had to avoid touching a pre-existing, unrelated
`next start --port 3111` process; check `Get-CimInstance Win32_Process
-Filter "Name='node.exe' OR Name='python.exe'"` and its `CreationDate`/
`CommandLine` columns before stopping anything.

## 25. PR status

**Not opened, by explicit user decision.** The user was asked
(this session, via a direct question) whether to (a) open a PR now
scoped honestly to what's actually here, (b) keep implementing Phase 3+
first with no PR yet, or (c) stop cleanly at this checkpoint with
nothing pushed further and no PR — they chose (c), specifically asking
to stop the session at the verified Phase 0-2 checkpoint, push the
branch, keep the handoff current, and not open a PR or merge anything.
That was done: the branch is pushed to
`origin/fix/clinical-document-intelligence-v3`, no PR exists. Opening
one (scoped honestly to Phases 0-2, NOT titled/described as "Rebuild
Bragi clinical document intelligence and restore Ask Bragi" — that
title describes Phases 3-21's work, which doesn't exist on this branch)
remains a decision for whoever picks this branch up next, made with the
user at that time.

## 26. This document itself

This handoff was written honestly against the contract's own explicit
instruction: "Report ONLY verified facts." Every section above states
either what was actually done and verified (with the command/test that
verifies it), or explicitly "NOT STARTED" / "NOT APPLICABLE YET" — no
phase's status is inferred, assumed, or rounded up.

`docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`, and `docs/KNOWN_GAPS.md`
should each get a short pointer to this document (see the commit that
adds this file) — this file is not meant to become "the only current
truth" on its own, per the contract's own instruction.
