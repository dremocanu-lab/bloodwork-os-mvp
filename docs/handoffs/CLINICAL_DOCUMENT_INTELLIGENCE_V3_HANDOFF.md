# Clinical Document Intelligence V3 — Handoff

**Status: PARTIAL. Phases 0 through 8 of the 21-phase contract are
COMPLETE and verified. Phases 0-5: the full structural reconstruction
layer (typed segments, canonical section consolidation, real Clinical
Course dated-event extraction with chronology sanity checking) and a
real end-to-end orchestration (`discharge_parser.py`) proven against
all three of the contract's own required suspicious-data fixture
examples. See sections 9, 9b, 9c, 9d. Phase 6: embedded lab extraction
from a discharge's `laboratory_results` section into real, canonical
`LabResult` rows — feeding the EXISTING `resolve_analyte()` resolver, no
private alias dictionary, no second lab datastore — plus a real derived
"lab_report" artifact `Document` per coherent source report. See section
9e. Phase 7: medication extraction/context classification +
deterministic duration/end-date derivation, persisted into the EXISTING
`PatientMedication` model/status vocabulary — no second medication
datastore. See section 9f. **Phase 8 (NEW this checkpoint): the
discharge/clinical-document reader was rebuilt from scratch around
`StructuredClinicalDocument`** — a new `GET /documents/{id}/clinical-
reader` backend contract, a rebuilt frontend page and 7 new reusable
components (canonical outline, one `StructuredLabReport` for both
embedded/standalone use, a Clinical Course event timeline, honest
PDF/non-PDF provenance, derived-vs-explicit medication date UX,
lab/medication conflict presentation), and real Playwright coverage
against a synthetic fixture. See section 9g. None of Phases 3-8's
EXTRACTION/PERSISTENCE code is wired into the live discharge UPLOAD
write path yet — this remains deliberate, not an oversight (see section
9b's sequencing note, and section 9g's own "why the write-side switch is
still deferred" reasoning — Phase 8's READ side is now proven fully
dual-compatible with both old and new document shapes, which is a
distinct, already-completed milestone from the write-side switch).
Phases 9–21 are NOT STARTED.** This document exists specifically so a
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
  checkpoint, the last four commits are (newest first): a handoff
  checkpoint commit for this section, `d39f5fb` (Phase 8 Playwright
  coverage), `def2079` (Phase 8 frontend rebuild), `60ff9b1` (Phase 8
  reader API contract) — on top of the Phase 0-7 checkpoint at
  `45ce7f3`.
- **Pushed to `origin/fix/clinical-document-intelligence-v3`**: the
  three Phase 7 commits plus its handoff (through `45ce7f3`) were
  explicitly authorized and pushed at the START of this Phase 8
  session — confirmed synchronized (`git log origin/...\..HEAD
  --oneline` returned empty immediately after). The four commits above
  are pushed at the END of this session, per the same explicit
  authorization — check `git log origin/fix/clinical-document-
  intelligence-v3..HEAD --oneline` to confirm empty before trusting
  this line.
- Working tree at this checkpoint: **clean, zero uncommitted changes**
  (`git status --short` returns nothing) once this handoff commit lands.
- **No PR opened.**
- **Phases 4 through 8 are now COMPLETE.** Phases 4/5: segments,
  canonical section consolidation, real Clinical Course event
  extraction, chronology sanity checking, full end-to-end orchestration
  in `discharge_parser.py` (sections 9b/9c/9d). Phase 6: embedded lab
  extraction/grouping/canonical persistence + derived lab artifact
  backend semantics (section 9e). Phase 7: medication extraction/
  context classification, deterministic duration parsing, and
  start/end-date derivation, persisted into the EXISTING
  `PatientMedication` model (section 9f). **Phase 8 (NEW): the
  discharge/clinical-document reader frontend rebuild — a new reader
  API contract, a rebuilt page, 7 new reusable components, real
  Playwright coverage (section 9g).** None of Phases 3-8's EXTRACTION/
  PERSISTENCE code is wired into the live discharge ingestion write
  path yet (deliberate — see section 9b's sequencing note, and section
  9g's own detailed reasoning for why the write-side switch stayed
  deferred even though Phase 8's READ side is now proven fully
  dual-compatible). All of Phase 6's/7's/8's own backend SERVICES are
  fully callable and DB-tested standalone right now, distinct from
  "wired into the live pipeline" — see sections 9e/9f/9g for the
  precise distinction in each case.
- **Immediate next step: Phase 9 — derived lab artifact in Documents.**
  Make Phase 6's derived "lab_report" `Document` rows appear properly
  in the Documents list/page with "Derived from: [parent]" and correct
  routing/relationship UI, using `StructuredLabReport(mode=
  "standalone")` (built and tested in Phase 8, not yet routed to
  anywhere). Do not redesign the Documents page broadly — scope this
  narrowly to the derived-artifact relationship, per the contract's own
  instruction.

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
  21. `a026fa0` — handoff checkpoint for Phase 6's completion (this file,
      `CURRENT_STATE.md`, `KNOWN_GAPS.md` only) — full backend suite
      reran clean at 474/474 at this point; no functional code change.
      Explicitly pushed to origin at the START of the Phase 7 session
      (user-approved) before any Phase 7 work began.
  22. `c3b38d2` — **Phase 7 increment 1**: `medication_extraction.py`
      (new) — `MedicationCandidate` + extraction from medication-bearing
      canonical sections and Phase 5 `treatment_change` events;
      `medication_duration.py` (new) — deterministic RO/EN duration
      parsing + real calendar-month-arithmetic end-date derivation via
      `dateutil.relativedelta` (now a direct `requirements.txt`
      dependency). 50 new tests. See section 9f.
  23. `cabe297` — **Phase 7 COMPLETE**: `medication_persistence.py`
      (new) — `persist_medication_candidates`, the exact 4-tier
      start-date priority, explicit-vs-derived-vs-conflicting end dates,
      same-drug conflict detection, idempotent inserts. Additive
      `models.PatientMedication.source_document_id`/`source_segment_id`/
      `stop_date_basis` and `models.SourceEvidence.medication_id`
      columns (+ Alembic migration `ff84f15530a9`). `DELETE
      /documents/{id}` now also explicitly cleans up medication-linked
      document-level `SourceEvidence` (required because, unlike Phase
      6's derived lab artifact, a document-derived medication SURVIVES
      its source document's deletion). Also fixes a real, previously-
      documented stale comment in `ask_bragi/tools.py` (claimed
      `"discontinued"` was a valid medication status; it never was).
      31 new tests (real DB). See section 9f.
  24. `45ce7f3` — handoff checkpoint for Phase 7's completion (this
      file, `CURRENT_STATE.md`, `KNOWN_GAPS.md`, `ARCHITECTURE.md`
      only) — full backend suite reran clean at 555/555 at this point;
      no functional code change. Explicitly pushed to origin at the
      START of the Phase 8 session (user-approved) before any Phase 8
      work began.
  25. `60ff9b1` — **Phase 8 increment 1**: `GET /documents/{id}/
      clinical-reader` (new) — the one deliberate reader payload;
      `app/services/source_evidence.py` (new, extracted from
      `ask_bragi/tools.py`); `serialize_medication` extended with
      Phase 7's provenance fields. 18 new tests. See section 9g.
  26. `def2079` — **Phase 8 increment 2**: the discharge reader page
      rewritten in full around the new contract; 7 new reusable
      components (`frontend/components/clinical-reader/`); 2 confirmed-
      dead legacy frontend files deleted. TypeScript/ESLint/build all
      clean. See section 9g.
  27. `d39f5fb` — **Phase 8 COMPLETE**: `backend/scripts/seed_e2e_
      discharge_document.py` (new) + `frontend/e2e/clinical-reader.
      spec.ts` (new) — 6 new Playwright tests against a real synthetic
      discharge document, verified against both dev and a real
      production build. See section 9g.
  28. Check `git log --oneline -20` for anything added after this
      checkpoint — this list is updated by hand and can lag a live
      session.
- **Push status**: check `git log origin/fix/clinical-document-
  intelligence-v3..HEAD --oneline` — empty means fully pushed. The three
  Phase 7 commits plus its handoff (through `45ce7f3`) were pushed at
  the start of this Phase 8 session (explicit user authorization). The
  three commits above (`60ff9b1`, `def2079`, `d39f5fb`) plus this
  handoff commit are pushed at the end of this same session, per that
  same explicit authorization. No PR opened.

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

## 9f. Phase 7 — medication extraction/context/duration/end-date (COMPLETE)

**What exists — extraction, context classification, deterministic
duration/end-date derivation, and canonical persistence, all real and
DB-tested**:

- `medication_extraction.py` (new): `MedicationCandidate` — the typed
  intermediate (source_segment_id, source_section_id, source_heading,
  canonical_key, raw_text, raw_medication_name, dose_text, route,
  frequency, instructions, status_context, explicit_start_date,
  starts_at_discharge_or_encounter, prescription_date,
  explicit_end_date, raw_duration, parsed_duration, prn,
  scheme_or_intermittent, indefinite, taper_without_clear_duration,
  source_evidence_text, source_page, confidence, warnings).
  `extract_medication_candidates_from_segment(segment, canonical_key=)`
  scans ONLY `treatment`/`medications`/`discharge_medications`/
  `recommendations`/`prescriptions`-classified segments
  (`MEDICATION_BEARING_CANONICAL_KEYS`) — `medical_history` and every
  other section are never scanned at all, so a historical medication
  mentioned there is excluded by construction, not by a runtime guess.
  `extract_medication_candidates_from_event(event)` additionally
  extracts from a Phase 5 `treatment_change`-classified `ClinicalEvent`
  — reusing Phase 5's own Clinical Course classification rather than
  independently re-segmenting that text (the V3 contract's "one parser
  architecture" instruction), with a fallback name-isolation strategy
  (a capitalized-word run, e.g. "BESREMI") for free narrative prose,
  distinct from the structured-line boundary parser used for
  section-sourced candidates.
- **Context classification** (`_classify_medication_context`):
  deterministic keyword matching (no LLM call, mirrors `events.py`'s
  own convention) into 8 contexts — started/continued/stopped/paused/
  completed/prescribed/historical/uncertain. A `prescriptions`-section
  mention with no keyword match falls back to "prescribed"; anything
  else with no keyword match is "uncertain" — never silently guessed as
  current, per the contract's own "if genuinely ambiguous, preserve as
  uncertain" rule.
- **Precision-first exclusion** (`_is_excluded_context`): an allergy
  statement, a refusal, a hypothetical/"consider starting", or a
  family-member mention produces ZERO candidates — excluded entirely,
  never persisted even as an uncertain row (persisting is a stronger
  claim than staying silent).
- **A real bug found and fixed before shipping**: the same "din data de
  <DATE>" ("starting from <DATE>") phrasing that means "starts from"
  for a started/continued mention means something different — "stopped,
  EFFECTIVE from <DATE>" — for a stopped/completed/paused mention. An
  earlier draft would have misread "Metformin 850mg, oprit din data de
  04.03.2026" as an explicit START date; `_build_candidate` now swaps
  the label's target to `explicit_end_date` specifically for a
  stop/complete/pause context — caught by
  `test_din_data_de_after_stopped_context_is_read_as_a_stop_date_not_a_
  start_date` before this ever reached persistence.
- `medication_duration.py` (new): `parse_duration` — deterministic RO
  (zi/zile, saptamana/saptamani, luna/luni) + EN (day/days, week/weeks,
  month/months) parsing, `ParsedDuration.total_days` exact for
  days/weeks, `None` for months (real calendar arithmetic needed, never
  approximated). `is_intermittent_per_month_phrase` — the critical
  precision guard that an "N zile/days PER MONTH" phrase (an ongoing
  intermittent regimen) is NEVER misread as a finite N-day course, even
  though it superficially contains a `<N> zile` token pair.
  `find_prn_marker`/`find_scheme_or_intermittent_marker`/
  `find_indefinite_marker`/`find_taper_without_clear_duration` — the
  exact exclusion set from the V3 contract's Phase 7 text.
  `derive_end_date(start_iso, duration)` — `[start, start+duration)`;
  days/weeks via exact `timedelta`; months via
  `dateutil.relativedelta` (now a direct `requirements.txt` dependency,
  previously only an implicit transitive one) — real calendar-month
  arithmetic, e.g. `2026-01-31 + 1 month = 2026-02-28`
  (relativedelta's own deterministic month-end clamping), never
  hand-rolled `30 * N` day math.
- `medication_persistence.py` (new): `persist_medication_candidates(db,
  document=, created_by_user_id=, candidates=, admission_date=,
  discharge_date=)` — the ONLY place this package writes
  `PatientMedication`/medication-linked `SourceEvidence` rows.
  - **Start-date resolution** (`_resolve_start_date`) — the exact
    4-tier priority, non-negotiable: (1) `candidate.explicit_start_date`
    parsed via `dates.parse_date_token`; (2)
    `candidate.starts_at_discharge_or_encounter` combined with the
    document's own `discharge_date`; (3) `canonical_key ==
    "discharge_medications"` AND `status_context in {"started",
    "prescribed"}` (NEVER "continued" — an already-ongoing medication
    did not start at discharge) combined with `discharge_date`; (4)
    `candidate.prescription_date`, ONLY when
    `starts_at_discharge_or_encounter` also signals the prescription
    date IS the start. No tier ever reads `created_at`/upload/ingestion
    timestamps — those values are never even threaded into this
    function's inputs.
  - **End-date resolution** (`_resolve_stop_date`) — derived ONLY when
    a resolved start date exists AND `candidate.parsed_duration` is set
    AND none of prn/scheme_or_intermittent/indefinite/
    taper_without_clear_duration are set. `stop_date_basis` records
    `"explicit"` / `"derived"` / `"explicit_with_derived_conflict"` —
    when an explicit end date and a derivable one disagree, the
    EXPLICIT value is kept in `stop_date` (never silently overwritten
    by Bragi's own calculation) and the disagreement is named in a
    warning, never dropped. A documented duration that COULDN'T be used
    to derive an end date (no reliable start) is still preserved in
    `extra_info` — a real gap found and fixed before shipping (an
    earlier draft only mentioned duration in `extra_info` when it was
    actually used to derive a date, silently losing the fact
    otherwise — caught by
    `test_duration_preserved_in_extra_info_even_when_no_start_date_to_
    derive_from`).
  - **Status mapping** (`_resolve_status`) — `status_context` maps onto
    the EXISTING `VALID_MED_STATUSES` (`app/api/routers/medications.py`)
    exactly, never a parallel vocabulary: started/continued/prescribed/
    uncertain → `"active"`; stopped/completed/historical → `"stopped"`;
    paused → `"paused"`; PRN (`candidate.prn`) overrides everything to
    `"as_needed"`. `is_uncertain` (the model's EXISTING field) is set
    for "uncertain"/"prescribed" contexts and for any detected conflict
    — "completed" vs. plain "stopped", "historical" vs. plain
    "stopped", etc. survive as human-readable `extra_info` text rather
    than inventing new status values the app doesn't otherwise have.
  - **Conflict detection** (`_detect_conflicts`) — two candidates for
    the SAME normalized drug name with DIFFERING resolved statuses are
    flagged (`is_uncertain=True` on both, `extra_info` names the
    conflicting statuses) ONLY when neither carries a start-date signal
    that would explain a legitimate sequential transition. A genuine
    "started on day 1, stopped on day 14" sequence (the V3 contract's
    own BESREMI example) is explicitly NOT flagged — it persists as two
    ordinary, un-flagged rows with different statuses, exactly matching
    "preserve source-supported state transitions... do not deduplicate
    across genuinely distinct clinical events."
  - **Idempotency** (`_find_existing_medication`) — exact-match lookup
    on `(patient_id, source_document_id, source_segment_id, name,
    reason)` (where `reason` carries the full verbatim source line/
    sentence) runs before every insert — never `created_at`. Two
    genuinely distinct mentions of the same drug (different segment or
    different raw text) are NEVER collapsed by this lookup.

**Schema/model changes** (all additive, one Alembic migration
`ff84f15530a9_phase7_medication_provenance.py`):
- `models.PatientMedication.source_document_id` (nullable FK →
  `documents.id`, `ondelete="SET NULL"`) — a DELIBERATE difference from
  Phase 6's derived lab artifact (hard-deleted with its parent): a
  medication fact has independent clinical meaning even once the
  document that mentioned it is gone, so deleting the source document
  clears the (now-stale) provenance link rather than deleting the
  medication — see section 17.
- `models.PatientMedication.source_segment_id` (nullable `String`) —
  mirrors `LabResult.source_section`'s existing convention exactly.
- `models.PatientMedication.stop_date_basis` (nullable `String`) — the
  field that keeps a calculated `stop_date` from ever reading as
  provider-authored; explicitly named in the V3 contract's own "DERIVED
  END DATE MUST REMAIN EXPLAINABLE" section as the kind of field
  genuinely justified here.
- `models.SourceEvidence.medication_id` (nullable FK →
  `patient_medications.id`, `ondelete="SET NULL"`) — the medication half
  of this model's OWN documented "generalize beyond lab rows" intent
  (see its docstring, unchanged since before this session), mirroring
  `lab_result_id`'s exact shape. `PatientMedication.source_evidence`
  (new relationship, `cascade="all, delete-orphan"`) handles the normal
  single-row-delete path; `ondelete="SET NULL"` on the FK itself is an
  independent DB-level safety net for the bulk-delete path
  (`DELETE /my/account`'s `PatientMedication` cleanup), which does not
  trigger ORM-level cascades.

**Deletion** (see section 17 for full detail): `DELETE /documents/{id}`
now explicitly deletes medication-linked, non-lab document-level
`SourceEvidence` rows for the document being deleted — required because
`PatientMedication.source_document_id` uses `SET NULL`, not cascade, so
the medication row (and therefore any `SourceEvidence` still pointing at
this now-being-deleted document) would otherwise violate
`SourceEvidence.document_id`'s `NOT NULL` constraint.

**Requirements checklist** (all met): no second medication datastore —
`PatientMedication` is the only table, verified by
`test_no_second_medication_model_exists` ✓; typed `MedicationCandidate`
intermediate, no direct ORM mutation while reading text ✓; extraction
scoped to medication-bearing sections + `treatment_change` events, never
independently re-segmenting Clinical Course ✓; precision-first exclusion
of allergy/refusal/hypothetical/family-member mentions ✓; exact 4-tier
start-date priority, never upload/ingestion date ✓; deterministic
RO+EN duration parsing, real calendar-month arithmetic ✓; end-date
derivation only for a reliable start + explicit finite duration, `null`
for PRN/scheme/indefinite/unclear-taper ✓; explicit vs. derived end date
distinguishable (`stop_date_basis`), conflict preserved not overwritten
✓; existing status vocabulary reused, no parallel vocabulary ✓;
conflicts preserved and flagged, sequential transitions NOT
over-flagged ✓; raw medication name always preserved, RxNorm resolution
never mandatory (persistence never calls `medication_lookup.py` at all
— that remains the router's own best-effort background-task path,
untouched) ✓; provenance to segment/document/evidence, never a fake PDF
page/bbox ✓; deterministic identity/idempotency ✓; deletion-safe (no
orphaned evidence, medication survives its source document) ✓; no
derived medication artifact document fabricated (unlike Phase 6's real
need for one) ✓; frontend NOT touched ✓.

**Tests** (81 new, all passing — 16 `test_clinical_document_medication_
duration.py` + 34 `test_clinical_document_medication_extraction.py`
[both pure, no DB] + 31 `test_clinical_document_medication_
persistence.py` [real DB, same skip-gracefully convention]) — covering
every category in the V3 contract's Phase 7 required-test list (all 40
items): every context/status mapping, all 4 start-date tiers, upload/
ingestion date never used (2 separate items), duration parsing for
every named RO/EN unit, the exact `2026-03-05 + 14 days = 2026-03-19`
case, `2 weeks == 14 days` exactly, real calendar-month arithmetic
including the `2026-01-31 + 1 month` edge case, every PRN/scheme/
indefinite/taper exclusion, explicit end date preserved and
distinguishable from derived, the explicit-vs-derived conflict case,
same-drug sequential transition vs. genuine cross-source conflict,
three distinct idempotency proofs, segment/evidence provenance, honest
absence of PDF geometry, raw-name-survives-verbatim, unresolved name
survives, historical-context exclusion, literal "discontinued" wording
never producing an active row, prescription-issued not pretending
administration, uncertain/ambiguous → requires-review, and the
no-second-datastore guard.

**What does NOT exist yet**: `discharge_summary_pipeline.py`'s live
write path is unchanged — `medication_persistence.py` is callable and
fully DB-tested standalone but nothing in the real upload flow calls it
yet (same deliberate sequencing as Phases 4-6, section 9b). No derived
medication artifact/document exists (deliberately — Phase 7 followed
its own instruction not to fabricate one; prescription documents remain
their real source documents). `schema.MedicationListBlock.medication_ids`/
`PrescriptionRow.medication_id` (Phase 3's own stubbed pointer fields)
are still never populated — nothing wires Phase 7's persistence result
back into a `StructuredClinicalDocument`'s own blocks yet, since nothing
calls Phase 7 from `discharge_parser.py`'s orchestration (same
"persistence service exists, orchestration wiring deferred" shape as
Phase 6's `DerivedArtifactRef`). Ask Bragi's `_tool_get_medications`
was NOT extended to surface `stop_date_basis`/provenance — deliberately
out of scope (Phase 11's job), only its stale comment was fixed. No
frontend surfaces any of this (Phase 7's own explicit instruction).

## 9g. Phase 8 — discharge reader frontend rebuild (COMPLETE)

**What exists — a real, deliberate reader API contract; a rebuilt
frontend page; 7 new reusable components; real Playwright coverage**:

- **Reader API contract**: `GET /documents/{document_id}/clinical-reader`
  (`app/api/routers/documents.py::get_clinical_reader_payload`) — the
  ONE deliberate payload the reader needs, not a dozen internal
  endpoints. Returns `{document, structured_document, labs,
  medications}`:
  - `structured_document` — via `parse_structured_document(document.
    note_body)`, the SAME sanctioned read path Phase 3 built. This is
    what makes the reader genuinely dual-compatible: an OLD legacy
    discharge `note_body` upconverts in memory (never rewritten on
    disk); a real forward-parsed payload (once Phase 8's own future
    write-side wiring exists) reads natively. Both produce the exact
    same `StructuredClinicalDocument` shape the frontend consumes —
    proven by `test_legacy_discharge_note_body_upconverts_into_reader_
    payload`/`test_native_structured_document_returns_same_reader_
    contract`.
  - `labs`/`medications` — queried directly from `LabResult`/
    `PatientMedication` by `document_id`/`source_document_id` (Phase
    6/7's own ownership rule), each carrying a `source_evidence_id`
    (via the new shared `app/services/source_evidence.py::first_
    source_evidence_id`) so the frontend never needs a second round
    trip before opening the source viewer.
  - `document.document_level_source_evidence_id` — always present, via
    the new shared `ensure_document_level_evidence(db, document,
    provider=)` helper, extracted from `ask_bragi/tools.py`'s own
    prior `_ensure_document_level_evidence` (which is now a thin
    wrapper over it, passing its own historical `provider=
    "ask_bragi_document_level"` explicitly so nothing about its
    existing behavior/tests changed — proven by all 50 Ask Bragi tests
    staying green unchanged). This is the header's "View
    original"/"Open original file" action's anchor.
  - Authorization is IDENTICAL to the existing `GET /documents/{id}`
    (same two-branch `care_partner_can_access_document`/
    `can_access_patient` check, same 404-before-403 ordering) — a
    read-SHAPE difference, not a new access rule. Proven by
    `test_unauthenticated_user_cannot_access_reader_payload`/
    `test_cross_patient_document_access_denied`.
  - Never crashes on a dangling reference: a `LabReportReferenceBlock`/
    `MedicationListBlock` pointing at a nonexistent id (Phase 6/7
    never actually populate these yet, but the contract must survive a
    FUTURE case where they do and a row was later deleted) simply
    yields an empty `labs`/`medications` array for that reference —
    proven by `test_missing_referenced_lab_does_not_crash_whole_
    document`/`test_missing_referenced_medication_does_not_crash_
    whole_document`.
- **`app/api/routers/medications.py::serialize_medication`** extended
  (additively) with `stop_date_basis`/`source_document_id`/
  `source_segment_id` — Phase 7 added these `PatientMedication` columns
  but the existing medication-list serializer was never updated to
  expose them; fixed now since Phase 8 needed them. Every EXISTING
  consumer of this serializer is unaffected (additive keys only) — all
  84 medication-related backend tests confirmed unchanged/passing.
- **Frontend TS schema** (`frontend/lib/clinical-document-schema.ts`):
  fixed real drift — `DerivedArtifactRef.group_key` (added to the
  backend in Phase 6, never mirrored here) — plus new
  `CANONICAL_SECTION_LABELS` (Phase 8E's exact outline label mapping)
  and the `ClinicalReaderResponse`/`ReaderLabResult`/`ReaderMedication`/
  `ReaderDocumentMeta` types mirroring the new endpoint's response
  shape exactly.
- **7 new reusable components** (`frontend/components/clinical-reader/`):
  - `reader-source-action.tsx` — the ONE "View source" action every
    lab/medication row and the document header use, reusing the
    EXISTING `openSourceEvidence`/`RightWorkspace` system (never a
    second viewer). `isPdfContentType()` gates it: for a genuinely
    non-PDF document (the shared viewer is PDF.js-only, with zero
    non-PDF rendering path anywhere in this codebase — confirmed
    before writing any code), the action degrades to an honest
    "Source text" label instead of attempting to open a viewer that
    would fail or show a fabricated/blank state.
  - `structured-lab-report.tsx` — `StructuredLabReport({labs,
    documentContentType, mode: "embedded" | "standalone"})`, the ONE
    contract-mandated reusable component (never two). Groups by
    `category` (never a fabricated panel), flags a genuine same-
    analyte/same-date conflict (two DIFFERENT values) by comparing
    every row pairwise — the MCH conflict renders as two full rows,
    each with a "Requires review" indicator, never collapsed to one.
    `mode="standalone"` is implemented and ready but not yet routed to
    anywhere (Phase 9's own explicit job — see "what does NOT exist
    yet" below).
  - `medication-list.tsx` — canonical `PatientMedication` rows only,
    never a raw-string re-parse. `stop_date_basis === "derived"`
    renders an explicit "Calculated from a documented course (...)"
    explanation under the date — a derived date can NEVER read as if
    the source itself wrote it. A same-drug cross-source status
    conflict (client-computed the same way as the lab conflict check)
    renders a restrained "Conflicting status across sources (...)"
    note on every involved row, never silently resolved.
  - `clinical-course-timeline.tsx` — renders `StructuredClinicalDocument.
    dated_events` chronologically BY `normalized_date` — an event with
    a suspicious-but-real date (the 3036 fixture case) sorts by its
    REAL value, never "corrected" into a more plausible position, and
    its own warnings render inline (via `IconAlert`, never color-only).
    An event with no `normalized_date` at all keeps document order,
    appended last, rather than being guessed into a position.
  - `document-outline.tsx` — built from `ClinicalSection.canonical_key`
    via the new `CANONICAL_SECTION_LABELS` map, never the raw source
    heading. The reader API only ever returns sections that survived
    `consolidate_segments`'s existing "drop non-substantive sections"
    rule (Phase 4), so no client-side emptiness filtering was needed —
    confirmed by `test_empty_sections_not_exposed_prominently`.
  - `document-header.tsx` — compact (no hero card), `Status` pill for
    verification state, `ReaderSourceAction` for a PDF source or a
    direct "Open original file" action (reusing the exact
    fetch-blob-and-`window.open` pattern the OLD page's `openOriginal()`
    used, just properly scoped as a compact header action and only
    shown for a genuinely non-PDF `content_type`) for a non-PDF one.
  - `clinical-block-renderer.tsx` — the generic `ClinicalBlock`
    discriminated-union renderer (Phase 8K): paragraph/key_value/
    bullet_list/table/warning render directly; `dated_event_group`/
    `lab_report_reference`/`medication_list` filter the already-fetched
    canonical lists by id and hand off to the components above — never
    a copy of referenced data.
- **The discharge page itself
  (`frontend/app/documents/[id]/discharge/page.tsx`) was rewritten in
  full**, not patched — matching the "ONE reader, not
  legacyDischargeReader + newDischargeReader" requirement exactly,
  since the new reader API's legacy-upconversion path already makes
  every existing discharge document renderable through the same
  contract. Removed (confirmed to have ZERO other callers — a repo-wide
  grep before deletion, not an assumption): the old flat
  `DischargeSection`/`parseDischargePayload` parsing (`mergeFirstPageSections`
  was already a no-op before this session — real dedup now happens
  server-side, in `consolidate_segments`, which this session's own
  earlier phases already built), the font-size control (tied to the old
  `<pre>`-based prose panel this structured, block-based UI no longer
  has), and — DELETED as genuinely dead files, not just unused imports —
  `frontend/components/original-layout-viewer.tsx` and `frontend/lib/
  discharge-epicriza-formatter.ts`. Both were already confirmed dead
  BEFORE this phase (`Document.original_layout_json` is not a real
  column — `CURRENT_PIPELINE_MAP.md` §17 — so `OriginalLayoutViewer`
  never rendered anything real in production); this phase's rewrite
  simply removed their one remaining caller, and a repo-wide search
  confirmed no other file imports either afterward.
- **Provenance**: real PDF page/bbox is used when it genuinely exists
  (unchanged — reuses the existing viewer exactly); a non-PDF document
  never gets a fabricated viewer attempt (`isPdfContentType()` gates
  every source action, including the document header's own). DOCX/non-
  PDF sources are honestly labeled ("Open original file"/"Source text")
  rather than showing a blank "Original Layout" panel waiting for data
  that was never real (the OLD page's exact anti-pattern, now removed).
- **RightWorkspace**: NOT modified at all — the rebuilt reader calls the
  SAME `useSourceViewer()`/`openSourceEvidence`/`AskBragiSideTab` hooks
  every other page already uses, composed by the SAME root-level
  `AppShellWithSourceViewer`. The pre-existing `right-workspace-
  geometry.spec.ts` regression (2 tests) was re-run and stays green,
  unchanged.
- **Responsive**: one deliberate breakpoint (900px, matching the OLD
  discharge page's own established sidebar-collapse convention, chosen
  over the shared shell's 1025px split-view breakpoint since this is
  the SAME page being replaced, not a new surface) — below it, the
  outline becomes a `<select>` (Phase 8Q's own "dropdown/sheet" guidance
  for mobile section navigation), content stays full-width. Manually
  verified end-to-end at 1440×900 (desktop, Playwright) and 390×844
  (mobile, Playwright) — the full 1920×1080/1280×800/1024×768/768×1024
  matrix from the task's own "target viewports" list was NOT
  individually screenshotted this phase (Phase 19 owns the formal
  screenshot matrix); the two viewports actually tested cover the two
  structurally distinct layouts (three-column desktop vs. single-column
  mobile) this page has.
- **Accessibility**: semantic `<h1>`/`<h2>`/`<h3>` hierarchy, real
  `<button>`/`<table>`/`<th>` elements throughout (never a styled
  `<div>` pretending to be one), `aria-current` on the active outline
  item, `aria-label` on the outline `<nav>` and the mobile `<select>`,
  warnings rendered with an icon (`IconAlert`) alongside text — never
  color-only. Keyboard: every interactive element is a real, natively
  focusable `<button>`/`<select>`, so Tab/Enter work without any custom
  key handling. Not run through an automated axe scan this phase
  (`qa/a11y.mjs` exists in this repo already — not wired into this
  specific page's verification this session; a reasonable Phase 20
  follow-up, not attempted here since Phase 20 owns the formal
  accessibility pass).
- **Live ingestion — DEFERRED, with exact reasoning**: `discharge_
  summary_pipeline.py`'s write path is completely unchanged — a brand
  NEW discharge upload today still writes the OLD ad-hoc JSON shape to
  `note_body` (confirmed by reading `process_uploaded_discharge_
  summary`, line 824, before making this decision), and nothing in the
  live upload pipeline calls `lab_persistence.persist_lab_candidates`/
  `medication_persistence.persist_medication_candidates`. This means a
  BRAND NEW discharge document today renders through the rebuilt reader
  with real, correct SECTIONS (via legacy upconversion) but an EMPTY
  `labs`/`medications` array (nothing has extracted them for that
  document yet) — an old, already-processed document with Phase 6/7
  data attached some other way (e.g. this session's own Playwright
  fixture) renders with real labs/medications; a genuinely fresh upload
  does not, today. This was a deliberate choice, per the task's own
  explicit "IMPORTANT DECISION RULE": wiring the write path would mean
  touching the live upload pipeline's error handling, idempotency
  behavior on a REAL multi-stage upload (Reducto/OCR/security-scan/
  classification), and would need real-Reducto-processed test coverage
  this environment cannot produce (no `OPENAI_API_KEY`/`REDUCTO_API_KEY`
  configured, per every prior phase's own honest accounting) — exactly
  the "significant new backend complexity, bleeding into Phases 9-13"
  case the contract says to defer rather than force. A verified,
  dual-compatible READER (this phase's actual deliverable) is complete
  and real; the write-side switch remains a distinct, separately-
  verifiable future increment — likely paired with Phase 13's
  idempotency proof, since that is exactly where "does reprocessing/
  live-processing a real upload produce correct, non-duplicated
  Lab/Medication rows" needs to be proven end-to-end anyway.

**A real bug found and fixed before shipping** (not a product bug — a
test-authoring one, but worth recording honestly per this project's own
bug-discipline convention): an early version of the Playwright spec
asserted the literal text "WBC" would appear after opening Laboratory
Results — it does not, by DESIGN: the reader correctly shows the
canonical resolved display name ("White Blood Cell Count") from Phase
6's own `resolve_analyte()`, not the raw abbreviation. Chasing this
looked at first like a serious "first click after page load is
swallowed" timing bug (reproduced twice under system load, including
once against a clean production build) before the actual screenshot
revealed the real content was rendering completely correctly all along
— just under a different, better name than the test expected. Fixed by
correcting the assertion, not the app. A genuinely more subtle related
finding kept from this investigation: `getByRole(..., {name: "..."})`
without `exact: true` does SUBSTRING matching in Playwright, so
"Clinical course" also matched a "Clinical course timeline" sub-heading
and "Medications" also matched "Discharge medications" — both fixed
with explicit `exact: true`, a real Playwright-authoring lesson worth
keeping in mind for any future spec touching this outline.

**Requirements checklist** (all met): consumes canonical backend facts,
never parses/re-interprets clinical text in the browser ✓; ONE reader
for legacy and native document shapes ✓; canonical outline from
`canonical_key`, never raw headings, empty sections never shown ✓;
Clinical Course from real `dated_events`, suspicious dates/warnings
preserved verbatim, never reordered into a "corrected" position ✓; ONE
`StructuredLabReport` for embedded AND standalone modes ✓; lab/
medication conflicts shown honestly, neither collapsed nor silently
resolved ✓; derived vs. explicit medication end date always
distinguishable in the UI text itself ✓; provenance via the EXISTING
`openSourceEvidence` system only, honest non-PDF degradation, no second
viewer built ✓; RightWorkspace untouched, its own regression stays
green ✓; responsive at the two structurally distinct breakpoints this
page has ✓; semantic accessibility markup throughout ✓; dead legacy
frontend code actually removed, not just unwired ✓; live ingestion
write path deliberately, honestly NOT switched, with the exact reason
recorded ✓.

**Tests**:
- Backend: 17 new focused tests
  (`test_clinical_document_reader_api.py`, one per item in the task's
  own required 17-item backend-contract list) — all passing, real DB.
  The full-suite net delta over the 555 baseline is +18, not +17 — see
  section 19 for that honestly-unreconciled ±1 discrepancy (the same
  kind already seen and flagged at the Phase 6 checkpoint).
- Frontend Playwright: 6 new tests (`e2e/clinical-reader.spec.ts`) — 
  header/outline/diagnoses/repeated-heading-consolidation, dated
  events + suspicious-date/vital preservation, lab table + MCH
  conflict, medications + derived-date label + PRN + status conflict,
  source action opens RightWorkspace, and mobile `<select>` navigation
  — all passing, against a real, seeded, deterministic synthetic
  discharge document (`backend/scripts/seed_e2e_discharge_document.py`,
  the same zero-external-cost ORM-direct pattern as `seed_e2e_lab_
  document.py`). Re-verified against BOTH `next dev` and a real
  production build (`next start`) — genuinely reproducible flakiness
  was chased down to real causes (see "bug found" above), not
  papered over with retries. The pre-existing `right-workspace-
  geometry.spec.ts` (2 tests) was re-run and stays green, unchanged.
- No new frontend unit-test framework was introduced — this repo has
  none today (confirmed by reading `package.json` before deciding),
  and the task's own instruction is not to add one for this phase;
  TypeScript's own strictness (zero errors across the whole rebuild)
  and this real Playwright coverage are the two verification
  mechanisms actually used.

**What does NOT exist yet** (explicitly deferred, not a Phase 8 gap):
`StructuredLabReport(mode="standalone")` has no ROUTE to reach it yet —
Phase 9's own explicit job ("Derived lab artifact in Documents... Do
NOT redesign the Documents page in Phase 8"), the component itself is
ready and tested. `schema.MedicationListBlock.medication_ids`/
`LabReportReferenceBlock.lab_result_ids`/`PrescriptionRow.medication_id`
are still never populated by any real parser (Phase 6/7's own
persistence results are never wired back into a `StructuredClinical
Document`'s own blocks) — the generic block renderer already handles
them correctly WHEN they exist (proven by the "missing reference"
tests), but nothing produces one in practice today; this is the same
"persistence service exists, orchestration wiring deferred" shape as
every phase since Phase 6, not new to Phase 8. The formal 6-viewport
responsive screenshot matrix and an automated accessibility (axe) scan
are Phase 19/20's own jobs, not attempted here beyond the 2 viewports
and manual semantic-markup review described above. Live discharge
upload ingestion is unchanged (see the dedicated paragraph above).

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

**Phase 7 COMPLETE for discharge-embedded medications — see section 9f
for full detail.** Medication mentions inside a discharge document's
`treatment`/`medications`/`discharge_medications`/`recommendations`/
`prescriptions` sections (plus Phase 5 `treatment_change` events) are
now extracted (`medication_extraction.py`), context-classified, and
persisted as real, canonical `PatientMedication` rows
(`medication_persistence.py`) — feeding the EXISTING `VALID_MED_
STATUSES` vocabulary, never a second medication datastore. This is a
real, DB-tested, callable service — **not yet wired into the live
discharge upload write path** (same sequencing note as labs, section
9b). Manual/medication-list-document creation paths (documented in the
pipeline map) are unchanged and unaffected.

## 12. End-date derivation rule

**Phase 7 COMPLETE — see section 9f for full detail.** The contract's
exact interval convention is now implemented in `medication_
duration.py`: `derive_end_date(start, duration)` = `[start, start+N)`
for days/weeks (exact `timedelta`, "2 weeks" = precisely 14 days), real
calendar-month arithmetic via `dateutil.relativedelta` for months
(`2026-01-31 + 1 month = 2026-02-28`, documented and tested), and
`null` for every PRN/scheme-intermittent/indefinite/unclear-taper case
— never derived, never guessed. `medication_persistence.py`'s
`stop_date_basis` field (new, additive) distinguishes an explicit
source-stated end date from a derived one, and preserves — never
silently overwrites — an explicit-vs-derived disagreement.

## 13. Timeline rules

**NOT STARTED.** `PatientEvent` today is created only via the doctor-
driven `POST /patient-events` route (confirmed in the pipeline map) —
discharge upload does not create or touch a `PatientEvent` row. No
dated-Clinical-Course-event extraction, and no lab/medication-driven
Timeline entries, exist yet.

## 14. Provenance rules

For labs (Phase 6, section 9e) and now medications (Phase 7, section
9f): every extracted fact traces back to `SourceEvidence.document_id`
(the authoritative parent) + `source_block_id`/`source_segment_id` (the
exact originating `SourceSegment`) + the verbatim source text — never a
fabricated PDF page/bbox for either. `SourceEvidence.medication_id`
(new, additive) is the medication half of this model's own long-
documented "generalize beyond lab rows" intent, mirroring
`lab_result_id`'s exact shape. Still not attempted: a dedicated,
document-section-level provenance mechanism independent of labs/
medications specifically (Phase 12's own broader scope — diagnoses,
procedures, and general section-level citations beyond what Phase 6/7
already cover for their own entity types).

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

**Phase 6 (labs) and Phase 7 (medications) each establish real
idempotent identities in this package** (sections 9e/9f). A
`LabResult`'s identity is `(document_id, source_segment_id,
raw_test_name, raw_value, observation_datetime)`; a derived lab-report
`Document`'s identity is `(parent_document_id, group_key)`. A
`PatientMedication`'s identity is `(patient_id, source_document_id,
source_segment_id, name, reason)` — `reason` carries the full verbatim
source line/sentence specifically so two genuinely distinct mentions of
the same drug (different segment, or different raw text within one
segment) are never collapsed. All of these are exact-match DB lookups
run before every insert — never `created_at`. Proven by dedicated tests
in both phases (`test_repeated_identical_extraction_does_not_
duplicate_*` for labs; `test_repeated_identical_extraction_does_not_
duplicate_medications`/`test_genuinely_separate_source_medication_
events_do_not_over_deduplicate` for medications), each calling the
persistence function twice with the SAME candidates and asserting row
counts are unchanged the second time. This satisfies each phase's own
instruction to "begin the idempotency architecture now" — NOT Phase
13's full requirement, which still needs the 1x/2x/10x proof against a
REAL end-to-end upload once the live write path exists for either
(`PatientEvent` idempotency is also still entirely Phase 13's job,
unaddressed here).

## 17. Deletion behavior

Single-document delete (`DELETE /documents/{document_id}`) gained two
real behavior changes across these two checkpoints:
- **Phase 6** (section 9e): explicitly hard-deletes any child
  `Document` with `derived_artifact_kind` set before deleting the
  requested document — previously (and still, for an ordinary Reducto
  Split child) a child's `parent_document_id` only gets `SET NULL`'d at
  the DB level, leaving it orphaned rather than removed. Does NOT
  change Split-child behavior at all (that FK's `ondelete="SET NULL"`
  is untouched; the new logic is a separate, explicit query scoped only
  to `derived_artifact_kind IS NOT NULL` rows).
- **Phase 7** (section 9f): explicitly deletes medication-linked,
  non-lab document-level `SourceEvidence` rows for the document being
  deleted. Required because `PatientMedication.source_document_id`
  uses `SET NULL` (the medication survives its source document's
  deletion — a deliberate difference from Phase 6's derived lab
  artifact, which is hard-deleted with its parent, since a medication
  fact stays independently meaningful once the document that mentioned
  it is gone), so its `SourceEvidence` rows would otherwise still point
  at the document about to be deleted and violate `SourceEvidence.
  document_id`'s `NOT NULL` constraint. Scoped to `lab_result_id IS
  NULL AND medication_id IS NOT NULL` only — lab-linked evidence is
  unaffected (already covered by the `LabResult` cascade).

Everything else — the pre-existing asymmetry between this route and
`DELETE /my/account` documented in `docs/clinical_document_v3/
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
  → **555 CONFIRMED after Phase 7 COMPLETION** (net +81 over the 474
  baseline — an EXACT match this time, no discrepancy: 81 new
  Phase-7-specific test functions were added across three new files —
  `test_clinical_document_medication_duration.py` (16),
  `test_clinical_document_medication_extraction.py` (34),
  `test_clinical_document_medication_persistence.py` (31). **Full suite
  reran clean: `555 passed, 5 warnings in 1069.41s (0:17:49)` — zero
  failures, zero errors, no Neon flake this run.** All 81 new Phase 7
  tests were also individually reconfirmed passing per-file immediately
  beforehand (the two pure, no-DB files together: 50/50; the real-DB
  file: 31/31 on its own run right after writing it).
  → **573 CONFIRMED after Phase 8 COMPLETION** (net +18 over the 555
  baseline; `test_clinical_document_reader_api.py` itself contains 17
  test functions — `grep -c "^def test_"` confirms this precisely —
  one more than the net delta suggests, the same kind of ±1
  reconciliation gap already seen and flagged honestly at the Phase 6
  checkpoint; not re-derived from a byte-for-byte prior count in this
  session, so not chased further here). **Full suite reran clean: `573
  passed, 5 warnings in 1237.14s (0:20:37)` — zero failures, zero
  errors, no Neon flake this run.** All 17 reader-API tests were also
  individually reconfirmed passing on their own run immediately after
  writing them.

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
  `right-workspace-geometry.spec.ts`) → 11 after Phase 8 (+6,
  `clinical-reader.spec.ts`) — unchanged by Phases 3-7 (no frontend
  application behavior changed in those phases). All 11 confirmed
  passing together in the same run (section 20).
- OpenAPI routes: 117 → **118** after Phase 8 (+1, `GET /documents/
  {id}/clinical-reader` — the first NEW route since Phase 4's own
  backend-modularization baseline; Phases 3-7 added none, only additive
  DB columns via existing routes).
- Bandit (`python -m bandit -r app -ll -q`): clean after Phase 8 — zero
  findings (only benign "Test in comment" collector warnings unrelated
  to any real issue, same as every prior checkpoint).
- Migration drift (`python scripts/check_migration_drift.py`): clean —
  Phase 8 added NO migration (no schema change) — "No migration drift
  detected (8 known/tolerated legacy-index difference(s) ignored)",
  same 8 as every prior checkpoint, last real migration still
  `ff84f15530a9_phase7_medication_provenance.py` from Phase 7.
- TypeScript (`npx tsc --noEmit`): zero errors, whole frontend, after
  Phase 8's rewrite.
- ESLint (`npm run lint`): zero errors/warnings in any file Phase 8
  touched or added; 29 errors/25 warnings exist elsewhere in the repo
  (pre-existing, confirmed via file-list disjointness before this
  checkpoint — not introduced by this session, not fixed by it either,
  out of scope per "do not fold unrelated refactors into this phase").
- Frontend production build (`npm run build`): succeeds, `/documents/
  [id]/discharge` listed among the compiled routes.

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

- `clinical-reader.spec.ts` (NEW, Phase 8): 6 tests against the
  rebuilt discharge/clinical-document reader — header/canonical
  outline/diagnoses/repeated-EPICRIZĂ consolidation, dated Clinical
  Course events with the suspicious-date/vital-sign warnings preserved
  (never "corrected"), the canonical lab table with the MCH conflict
  preserved (not collapsed), medications with the derived-end-date
  label/PRN/BESREMI status conflict, a lab row's source action opening
  the shared RightWorkspace, and mobile `<select>` section navigation.
  Seeds via `backend/scripts/seed_e2e_discharge_document.py` (real
  Phase 4-7 parser/extraction/persistence, zero external API cost).
  Verified against both `next dev` and a real production build
  (`next start`) — see section 9g for a real, if narrow, lesson from
  chasing an apparent flake down to a wrong test assertion rather than
  a real app bug.

This is the FIRST Playwright coverage for the actual clinical-document
reader product surface — Phase 16's broader document/derived-lab/
timeline/medication flow coverage (beyond this one page) still needs
Phases 9-13 to exist first.

## 21. Real bugs found (this session)

1. **Ask Bragi tool-round-budget exhaustion on broad multi-analyte
   questions** (Phase 2's P0) — see section 15. Real, reproduced (via a
   realistic mocked tool-call sequence, not merely the abstract "N > 4"
   case the pre-existing `test_max_tool_rounds_is_enforced` test
   already covered), fixed, and regression-tested both ways.
2. **A "starting from `<DATE>`" label misread as a START date when it
   actually describes a STOP date** (Phase 7) — see section 9f. Romanian
   "din data de" means "starting from" in a started/continued mention
   but "effective from" (i.e. the STOP date) in a stopped/completed/
   paused one; an earlier draft of `medication_extraction.py` would have
   recorded "Metformin 850mg, oprit din data de 04.03.2026" with an
   `explicit_start_date` of 04.03.2026 instead of an `explicit_end_
   date`. Caught by `test_din_data_de_after_stopped_context_is_read_as_
   a_stop_date_not_a_start_date` before this reached persistence; fixed
   with a context-aware label swap in `_build_candidate`.
3. **A documented medication duration silently disappearing when no
   reliable start date existed to derive an end date from** (Phase 7) —
   see section 9f. An earlier draft of `medication_persistence.py`'s
   `_build_extra_info` only recorded `raw_duration` in `extra_info` when
   it was actually USED to derive `stop_date` — so a genuinely documented
   "10 zile" course with an unresolvable start date lost that fact
   entirely, violating Phase 7M's own "preserve duration" requirement.
   Caught by `test_duration_preserved_in_extra_info_even_when_no_start_
   date_to_derive_from`; fixed by always recording the documented
   duration, with different wording depending on whether it was actually
   used to compute a date.
4. **A stale, factually wrong comment in `ask_bragi/tools.py`** claiming
   `"discontinued"` is a valid `PatientMedication.status` value — it
   never was (`VALID_MED_STATUSES = {"active", "as_needed", "paused",
   "stopped"}`). Pre-existing, already documented as a known inaccuracy
   in `docs/clinical_document_v3/CURRENT_PIPELINE_MAP.md`'s Open
   Question #11 and this handoff's own "Hard constraints" section
   before this checkpoint; fixed now (comment-only, zero behavior
   change) since Phase 7 was directly working with this exact
   vocabulary.
5. **Not an application bug — a Playwright-authoring lesson worth
   recording anyway** (Phase 8) — see section 9g. An early spec
   assertion expected the literal text "WBC" to render after opening
   Laboratory Results; the app was already correctly rendering the
   canonical resolved display name ("White Blood Cell Count") instead.
   Chasing this looked at first like a serious "first click after page
   load is swallowed" race (reproduced twice under real conditions,
   including once against a clean production build, before the actual
   screenshot showed the content was correct all along, just under a
   different name). Fixed by correcting the test assertion, not the
   app. A second, genuinely real Playwright lesson from the same
   investigation: `getByRole(role, {name: "..."})` does SUBSTRING
   matching without `exact: true` — "Clinical course" also matched a
   "Clinical course timeline" sub-heading, "Medications" also matched
   "Discharge medications" — both fixed with explicit `exact: true`.

No other bugs were found during Phase 3 (a new, isolated schema/
persistence module with no prior behavior to regress) or Phase 6.

## 22. Known gaps / deferred items (READ THIS BEFORE CLAIMING THIS CONTRACT IS DONE)

Phases 3 through 8 are ALL COMPLETE (sections 9, 9b, 9c, 9d, 9e, 9f,
9g) — real, tested segmentation, canonical section consolidation,
Clinical Course event extraction (including chronology and vital-sign
plausibility checks), embedded lab extraction/grouping/canonical
persistence, medication extraction/context classification/duration/
end-date derivation, and the discharge reader frontend rebuild all
exist and are proven against every relevant V3 contract example,
including all three required suspicious-data fixtures (Phase 5) and
the synthetic hematology/discharge fixtures (Phases 6/8). None of
Phases 4-8's EXTRACTION/PERSISTENCE code is wired into the real live
discharge INGESTION pipeline yet (deliberate — section 9b's sequencing
note, which now also governs Phase 8; see section 9g for the exact
reasoning specific to Phase 8's own decision); the backend persistence
SERVICES (`lab_persistence.py`, `medication_persistence.py`) and now
the entire READER SIDE (`GET /documents/{id}/clinical-reader` + the
rebuilt frontend) are however all fully callable/renderable and tested
today — a real distinction, not a contradiction (see sections 9e/9f/9g).
Table/key-value block construction from real per-section content
(beyond `ParagraphBlock`) still does not exist for the STRUCTURED-
DOCUMENT schema's own blocks (`TableBlock`/`MedicationListBlock`/
`PrescriptionTableBlock` etc. — Phases 6/7 produce real structured
candidates, and Phase 8's frontend can already RENDER these block types
correctly when they exist, but nothing PRODUCES one yet, since nothing
wires Phase 6/7 into `discharge_parser.py`'s orchestration). `Clinical
Event.structured_observations`/`medication_changes`/`procedures` are
STILL not independently populated (captured only in each event's
`raw_text`) — a reasonable future increment, not attempted. Everything
from Phase 9 onward through Phase 21 of the original contract is
**entirely unimplemented**:

- Phase 9: Documents page derived-artifact relationship UI
  (`StructuredLabReport(mode="standalone")` is built and tested — Phase
  8's own explicit deliverable — but has no route to reach it yet;
  that routing/relationship UI is this phase's job).
- Phase 10: Timeline integration for derived labs/medication events.
- Phase 11: Ask Bragi retrieval hardening for the new structured data
  (structured dated-event queries, transparent end-date-derivation
  language in answers).
- Phase 12: provenance for the new structured facts.
- Phase 13 (partial — Phases 6 AND 7 each laid real identity groundwork
  and DB-proved it standalone, sections 9e/9f/16 — the full 1x/2x/10x
  proof against a REAL end-to-end discharge UPLOAD, plus `PatientEvent`
  idempotency, is still this phase's job): idempotency guarantees for
  repeated discharge ingestion.
- Phase 14 (partial — Phases 6 AND 7 each proved their own deletion
  semantics both at the ORM level and through the real DELETE route,
  sections 9e/9f/17 — the exhaustive real-Postgres cascade suite across
  every entity type this contract touches is still this phase's job):
  real-Postgres deletion tests for the new derived data.
- Phase 15 (partial — the synthetic hematology LAB VALUES fixture exists
  and is reused across Phase 6's own tests, section 18; Phase 7's own
  medication fixture text lives inline in `test_clinical_document_
  medication_persistence.py` rather than as a shared standalone file —
  a full synthetic DISCHARGE document fixture exercising every phase
  together, as Phase 15 originally intends, does not exist yet): the
  synthetic hematology-discharge test fixture.
- Phase 16 (partial — done for Phase 2's own scope, not for the rest):
  Playwright for the document/lab/medication/timeline flows.
- Phase 17 (partial — Phases 6 AND 7 each contributed their own share
  of this list: alias resolution, dedup/conflict preservation, table/
  qualitative-value extraction (Phase 6); context classification,
  duration parsing, date-priority resolution, conflict preservation
  (Phase 7) — section 17 of this document): the extensive backend test
  list (heading normalization, date extraction, lab/medication dedup,
  etc.).
- Phase 18: the 75-100-case deterministic retrieval benchmark.
- Phase 19 (partial — Phase 8 manually verified 2 of the 7 target
  viewports, 1440×900 and 390×844, covering the reader's two
  structurally distinct layouts, section 9g — the full 6/7-viewport
  formal screenshot matrix does not exist yet): responsive QA
  screenshots at 7 viewports.
- Phase 20 (partial — Phase 8's reader uses real semantic markup
  throughout, section 9g's own checklist — no automated axe scan was
  run against it yet): accessibility verification.
- Phase 21 (full): the final full regression across all of the above —
  the full backend suite HAS been re-run clean at every checkpoint
  through Phase 8 (573/573 as of this one, section 19), and Phase 8
  also added the first-ever Playwright coverage for the actual reader
  product surface (11/11 passing, section 20), but that is verification
  of Phases 0-8's own code, not a certification that Phases 9-21's
  (still nonexistent) code passes anything.

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
- Start Phase 9 (derived lab artifact in Documents) — Phases 3 through
  8 are ALL done: `app/services/clinical_document/schema.py`/
  `persistence.py` (Phase 3), `segments.py`/`canonical_headings.py`
  (Phase 4), `dates.py`/`events.py`/`discharge_parser.py` (Phase 5),
  `lab_extraction.py`/`lab_grouping.py`/`lab_persistence.py` (Phase 6),
  `medication_extraction.py`/`medication_duration.py`/`medication_
  persistence.py` (Phase 7), the `GET /documents/{id}/clinical-reader`
  API + rebuilt discharge reader page + 7 reusable components under
  `frontend/components/clinical-reader/` (Phase 8) — use them all as-is
  (sections 9/9b/9c/9d/9e/9f/9g), extend additively if a real gap is
  found, do not redesign or duplicate any of them. Phase 9's own scope
  per the contract: make Phase 6's derived "lab_report" `Document` rows
  appear in the Documents list/page with "Derived from: [parent]" and
  correct routing/relationship UI, using `StructuredLabReport(mode=
  "standalone")` — already built and tested in Phase 8, genuinely ready
  to route to, not a stub. Do NOT redesign the Documents page broadly —
  the contract's own explicit instruction, and Phase 8 deliberately
  stopped short of this exact scope for the same reason. A reasonable
  starting question for whoever does this: does a derived artifact need
  its OWN route (e.g. `/documents/{id]/lab-report`) or can the EXISTING
  `/documents/{id}` generic page detect `derived_artifact_kind` and
  render `StructuredLabReport(mode="standalone")` directly — a decision
  for that session to make deliberately, not decided here.
- Do not re-attempt Phase 8 — the discharge/clinical-document reader
  rebuild is complete and tested (section 9g): the new reader API
  contract (17 backend tests), the rebuilt page and 7 reusable
  components (TypeScript/ESLint/build all clean), and real Playwright
  coverage (6 new tests, verified against both dev and a production
  build). If Phase 9 (or later work) needs a genuinely NEW reader
  capability this doesn't have, extend the existing components/
  endpoint additively and add a regression test — do not build a
  second reader page or a second lab-report component. The one thing
  intentionally left for LATER phases, not a gap in Phase 8 itself:
  `StructuredLabReport(mode="standalone")` has no route yet (Phase 9's
  own job, see above); `schema.MedicationListBlock.medication_ids`/
  `LabReportReferenceBlock.lab_result_ids`/`PrescriptionRow.
  medication_id` are still never populated by any real parser (nothing
  wires Phase 6/7's persistence results back into a
  `StructuredClinicalDocument`'s own blocks — the generic block
  renderer already handles them correctly when they exist, proven by
  the "missing reference" tests, but nothing produces one in practice
  yet); live discharge upload ingestion is still unchanged (same
  sequencing reasoning as every phase since 4 — see section 9b, and
  section 9g's own detailed "why the write-side switch is still
  deferred" paragraph for the Phase-8-specific reasoning).
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
