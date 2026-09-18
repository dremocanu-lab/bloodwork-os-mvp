# Source Intelligence + Provenance V2 — Handoff

**Status: COMPLETE for the scope defined below.** Branch
`fix/source-intelligence-provenance-v2`, off `main` post Clinical
Reader Intelligence V2 squash-merge (PR #9, `fdfca4e`). Not merged —
see the PR itself.

This session closed the biggest remaining gap in Bragi's clinical
reader: **every fact the AI-organized reader shows — diagnoses,
investigations, anomalies, recommendations, current-hospitalization
events, Clinical Course timeline events, and treatment eras — now has a
real "View in original" action.** Before this session, only labs and
medications did; the newer Clinical Reader Intelligence V2 entity types
had a `source_evidence_ids` field declared on their schema but it was
always hardcoded to `[]`, and no UI component even offered the action.

## 1. Investigation first — what was actually true before this session

Two research passes (not assumptions) established the real starting
state:

- **Reducto is not "just a lab tool."** Its `/parse` call is already a
  real full-document, page+bbox extractor, and it already runs for both
  lab and "reader" narrative document types (imaging/pathology/
  prescription/etc.) as a secondary full-document call alongside the
  narrow-schema `/extract`. It is simply **never invoked at all for
  `discharge_summary`** — the most structurally complex, highest-page-
  count type, which instead uses a completely separate PyMuPDF + OpenAI
  vision pipeline (`discharge_summary_pipeline.py`) that renders and
  transcribes every page independently.
- That discharge pipeline **already processed every page** (bounded by
  `MAX_PAGES=90`) and **already computed** `page_start`/`page_end` for
  every extracted section. But by the time that payload reached
  `StructuredClinicalDocument`, the page anchor was silently dropped —
  `segments.py`'s `SourceSegment.page` field existed but nothing ever
  read `page_start` into it.
- Spreadsheet ingestion already processes **every worksheet** (not just
  the first/active one) — this was already correct, nothing to fix.
- The frontend already has **one canonical source-opening path**
  (`openSourceEvidence()` in `source-viewer-context.tsx`, used by every
  existing caller) — no per-component reimplementation to consolidate.
- `SourceEvidence.field_bboxes_json` already stored multiple real
  per-field citation rects for lab rows, but the renderer
  (`source-viewer-panel.tsx`) only ever drew the FIRST one — a real,
  confirmed bug, not a documented limitation.
- The `Diagnosis`/`Investigation`/`AnomalyFlag`/`RecommendationItem`
  Pydantic models already declared `source_evidence_ids: list[int]`,
  but `ai_interpreter.py::apply_interpretation` hardcoded it to `[]` —
  the field existed, nothing populated it, and nothing created a
  `SourceEvidence` row for these entity types at all.

## 2. What this session built

```
discharge_summary_pipeline.py (per-page vision, page_start already computed)
  -> segments.py (page_start now threaded into SourceSegment.page)
  -> reprocessing.py::_attach_segment_evidence (NEW)
       one idempotent, page_only-precision SourceEvidence row per segment
  -> ai_interpreter.py::apply_interpretation
       resolves each grounded item's source_segment_ids/source_event_ids/
       source_section_id into REAL SourceEvidence ids, precedence chain:
       segment > event > section (never a union across tiers)
  -> GET /documents/{id}/clinical-reader (unchanged endpoint, new fields
     flow through automatically via StructuredClinicalDocument.model_dump())
  -> reader components (DiagnosisList, InvestigationCards, AnomalyWarnings,
     RecommendationList, CurrentHospitalizationEvents, ClinicalCourseTimeline,
     TreatmentEraList) -> ReaderSourceAction / MultiSourceAction
  -> the SAME shared SourceViewerProvider/SourceViewerPanel every other
     part of the app already uses
```

No new datastore. `SourceEvidence` already had exactly the right shape
(its own docstring has said "meant to generalize... not just lab rows"
since Clinical Document Intelligence V3) — this session is that
generalization actually happening.

## 3. Full-document extraction

- **Reducto usage before**: full-document `/parse` capability already
  existed and was already used for lab/reader document types; never
  invoked for discharge_summary.
- **Lab-biased?** No — mixed. Capability-complete, usage-gated by
  document type.
- **All pages processed now?** Discharge documents already were
  (page-vision pipeline, `MAX_PAGES=90`). What changed: page-level
  FAILURES are now isolated per page (`_call_openai_for_page_safe`, one
  retry, then that page is recorded as failed rather than the exception
  propagating and losing every OTHER already-succeeded page's work) and
  reported through a new `ExtractionCoverage` block
  (`total_pages`/`attempted_pages`/`successful_pages`/`failed_pages`/
  `extraction_complete`) rather than only a loose warning string.
  `extraction_complete` is computed, never asserted — a document is
  never silently labeled fully extracted when pages actually failed.
  This is now surfaced in the reader UI itself (`DocumentHeader` shows
  a restrained warning banner when incomplete — see section 11).
- **Partial extraction behavior**: the deterministic document still
  renders everything that DID succeed; the coverage block and UI
  banner report what didn't, honestly, without blocking the reader.
- **Non-lab table behavior**: NOT rebuilt this session — deliberately
  out of scope (see section 13). The discharge pipeline transcribes
  tables as prose/markdown-in-text via its page-vision model, same as
  before; no new `ClinicalTableInterpreter`/generic table-semantic-
  classification pipeline was built.
- **Multi-page tables**: not applicable — no new table-geometry
  handling was added this session.
- **Spreadsheet all-sheet behavior**: unchanged, already correct
  (verified, not assumed) — every worksheet already gets processed.
- **Native parser vs. Reducto routing**: unchanged — the existing
  universal ingestion router (`backend/app/services/ingestion/`) still
  decides per format; this session did not touch that routing logic.
- **Source structure retained**: page-level anchoring for discharge
  narrative (new); no new geometry/bbox capture was added for any
  format — see section 13 for what this deliberately leaves for a
  future session.

## 4. Provenance

### 4.1 Root cause of "View in original sometimes doesn't work"

It didn't "sometimes" not work for the new entity types — it **never**
worked, because no `SourceEvidence` row existed for them at all
(`source_evidence_ids` was always `[]`) and no UI component offered the
action in the first place. For labs/medications, the existing pipeline
was already correct; the one real bug there was the multi-rect render
bug (section 4.4).

### 4.2 Canonical evidence-opening path

Unchanged, confirmed correct: `openSourceEvidence(sourceEvidenceId)` in
`source-viewer-context.tsx`, used by `ReaderSourceAction`,
`MultiSourceAction` (new — see 4.6), `SelectionSourceMenu`, Ask Bragi,
and the documents page. No new opening path was introduced.

### 4.3 Evidence precision model

Unchanged (already existed, already correct): `exact_bbox` / `page_only`
/ `text_only` / `document_only`, computed server-side in
`GET /source-evidence/{id}/view`, communicated to the frontend as a
`precision` field the viewer renders a distinct honest notice for. This
session's new segment-level evidence is always `page_only` (page known,
no bbox — the page-vision pipeline has no per-field geometry to offer)
or `text_only`/`document_only` for older documents with no page info.
**Never a fabricated bbox.**

### 4.4 Exact field/cell behavior

Fixed a real, confirmed bug: `source-viewer-panel.tsx` already computed
`highlightBoxes` (the full array of per-field citation rects) but the
JSX only ever rendered `highlightBox` (singular, the first one). Now
renders every rect in the array via `.map()`. Also added
`document_content_type` to `/source-evidence/{id}/view`'s response
(the frontend's PDF-vs-non-PDF check previously had to source this from
elsewhere).

### 4.5 Block-level (paragraph) precision — the new middle tier

This is the actual new precision model addition. Previously the AI
interpreter could only cite a `section_id` (the WHOLE canonical
section, which can merge a dozen+ narrative paragraphs — e.g. Clinical
Course) or an `event_id` (a specific dated event). Neither is precise
for a fact like "JAK2 V617F mentioned in historical narrative" — there
is no dated event for it (the narrative gives a year, not a full date),
so it could only ground at section level, resolving to that section's
ENTIRE aggregate evidence (every contributing segment) — a real bug
found via manual verification, not assumed away.

Fixed by exposing each section's own contributing **segments**
(paragraph id + text) to the interpreter whenever the segment-to-block
pairing is unambiguous (`_paragraph_segments()`, reusing the same
defensive 1:1-alignment check `reprocessing.py`'s own segment
reconstruction already used), adding `source_segment_ids` to the
model's JSON schema/grounding contract, and validating it exactly like
every other citation (dropped if fabricated, never rejects the whole
item for a bad segment id).

`_resolve_evidence_ids()` is now a **strict precedence chain, never a
union across tiers**: segment citation (most precise) → event citation
→ section citation (coarsest, only when nothing more precise was
given). Unioning would dilute a precise citation with a coarse one,
which is exactly the bug this replaces.

### 4.6 Multi-source AI summaries ("View sources (N)")

`TreatmentEra` gained a `source_evidence_ids` field (additive — the
union of real evidence already resolved for every event in `event_ids`)
and a reader UI it never had before (`TreatmentEraList`, new). A new
`MultiSourceAction` component (`reader-source-action.tsx`) degrades to
a plain single "View source" when there's exactly one evidence id, and
shows a "View sources (N)" button + "previous / N of M / next" cycler
(re-opening the SAME shared viewer at each real id in turn) when there
are several — never one fake "exact" source for a fact that's actually
a synthesis of several.

### 4.7 Runtime text-anchor fallback / page fallback / document fallback

Not newly built this session — already existed and already correct
(the `page_only`/`text_only`/`document_only` notices in
`source-viewer-panel.tsx`, and `ReaderSourceAction`'s honest
non-clickable label for a non-PDF document). This session's new
evidence rows are consumers of that existing, correct fallback
hierarchy, not a reimplementation of it.

### 4.8 Bbox coordinate normalization / page numbering

Unchanged — already normalized `[0,1]` page-relative fractions, origin
top-left, taken verbatim from Reducto's own citation format
(`BRAGI_REDUCTO_PLAN.md`), and page numbers are 1-based end to end
(Reducto citations, `SourceEvidence.page_number`, PDF.js's
`getPage(pageNumber)` all agree). This session's new page anchors
(`page_start` from the discharge vision pipeline) are ALSO 1-based
(page 1 = the first rendered page), consistent with this existing
contract — verified via the synthetic fixture's own page-1-through-6
layout resolving to the correct pages end to end.

### 4.9 Rotation handling

**Not touched this session** — no new bbox-producing code was added
(the new evidence is page-only, never bbox), so there was nothing new
to rotate-test. The existing lab-bbox rotation behavior (if any) is
unaffected. See section 13.

### 4.10 Source viewer state machine / repeated-click behavior

Not rewritten into a formal state machine this session — the existing
ref-based "latest request wins" approach in `SourceViewerProvider`
already prevents the cross-page-bleed race the research pass looked
for. Verified via Playwright: A → B → A selection correctly reopens the
viewer and shows the correct notice each time (the `data` object is
always freshly fetched on `openSourceEvidence`, so re-selecting the
same evidence id retriggers the render/scroll effect correctly, just
with one redundant metadata fetch — a known minor inefficiency, not a
correctness bug, and not addressed this session since it doesn't
break anything observable).

## 5. Non-PDF

**Not rebuilt this session** — the existing, already-correct, honest
behavior was verified (via direct code reading) rather than reimplemented:
`ReaderSourceAction` shows a non-clickable "Source text" label instead of
a broken button for a non-PDF fact-level action, and `DocumentHeader`
already offers a genuine, working "Open original file" button (fetches
the real bytes and opens them in a new tab) regardless of format — so
the document-level action was never a dead end even before this
session. No `SourceRenderer` per-format architecture (image/DOCX/
spreadsheet/structured-text renderers) was built — see section 13.

## 6. Clinical Reader integration — what got a "View in original" action

| Entity | Before | After |
|---|---|---|
| Diagnosis | none | `ReaderSourceAction` per diagnosis |
| Investigation | none | `ReaderSourceAction` per investigation card |
| AnomalyFlag | none | `ReaderSourceAction` per anomaly |
| RecommendationItem | none | `ReaderSourceAction` per recommendation |
| Current-hospitalization event | none | `ReaderSourceAction` per event |
| Clinical Course timeline event | none | `ReaderSourceAction` per event |
| TreatmentEra | none (no reader UI at all) | new `TreatmentEraList` + `MultiSourceAction` "View sources (N)" |
| Lab result | already worked | unchanged, multi-rect render bug fixed |
| Medication | already worked | unchanged |

## 7. Reprocessing

`_attach_segment_evidence` runs as a new step inside
`reprocess_discharge_document`, before the AI interpreter (so the
interpreter has real evidence ids to resolve against). Idempotent per
`(document_id, source_block_id)` via `ensure_segment_evidence` — a
second reprocess reuses existing rows rather than duplicating them
(`segment_evidence_reused` in the result), and never overwrites an
existing row's page with a possibly-worse reconstruction on a later
pass. Cross-document isolation verified: two documents built from
identical fixture content (same deterministic segment ids) get their
own, separate SourceEvidence rows, never bled together.

## 8. Security

No changes to the authorization model — `/source-evidence/{id}/view`
still uses the exact same `can_access_patient`/care-partner-exclusion
check as before; the new segment-evidence rows go through the identical
authorization path as lab/medication evidence always has. No new file-
path handling, no new HTML/text rendering surface, no new XML/JSON
parsing — this session added data (evidence rows + a coverage summary),
not new attack surface. Cross-patient access to the new evidence type
verified with a dedicated regression test.

## 9. Performance

No large payload was added to the reader response — `extraction_coverage`
is a handful of integers/booleans, and each new `SourceEvidence` row is
resolved to a bare integer id on the entity, never inlined content; the
actual evidence text/page is fetched lazily, on click, through the
existing `/source-evidence/{id}/view` endpoint exactly as labs/
medications already do. No raw Reducto/provider response is sent to the
browser (unchanged — was already true).

## 10. Tests

**Backend** (pytest, `DATABASE_URL`-gated DB tests skip gracefully
without one):
- `test_source_intelligence_provenance_v2.py` — 20 tests: page
  threading, extraction-coverage computation/reconstruction/reader-
  endpoint exposure, the evidence-id resolver's precedence chain
  (including the real over-broad-evidence bug this locks down), real-DB
  reprocessing attaching page-anchored evidence, idempotency,
  cross-document isolation, `/source-evidence/{id}/view`'s new
  `document_content_type` field and precision, cross-patient rejection.
- `test_discharge_summary_pipeline_coverage.py` — 4 tests: per-page
  failure isolation/retry, coverage computed from real success/failure
  data, never claims completeness when pages failed.
- Full `clinical_document`/`clinical_reader`/`source_evidence`/
  `source_intelligence`/`discharge_summary_pipeline`-scoped suite: 350
  passed, 0 failed (includes every pre-existing test in this area, run
  after all changes).

**Frontend**: `tsc --noEmit` clean; `eslint` clean on every changed
file; `next build` production build succeeds.

**Playwright**: `source-intelligence-provenance-v2.spec.ts` — 8 tests,
verified visually (screenshots) before writing the assertions: D45's
new "View source" action opens the viewer with the honest page-only
notice; JAK2's investigation card has its own action; both anomalies
(3036 and AV1008) are independently actionable; the Besremi treatment
era's "View sources (2)" cycler correctly shows "1 of 2"/"2 of 2" with
working prev/next; Current Hospitalization and Clinical Course events
each have their own action; A→B→A re-selection works; mobile opens the
full-screen sheet. Pre-existing related suites re-run for regression —
see the PR/final report for the exact pass count.

## 11. Known limitations / deliberately out of scope

Per the task's own explicit non-goals plus this session's own effort-
vs-scope judgment (documented honestly, not silently dropped):

- **Generic table semantic classification** (`ClinicalTableInterpreter`
  routing a table to lab/medication/prescription/investigation/etc.) —
  not built. The discharge pipeline doesn't extract tables as structured
  geometry at all today (it transcribes them as prose via page-vision);
  building this would mean either forcing discharge documents through
  Reducto (explicitly discouraged — "use the extractor that preserves
  the most faithful source structure, not send everything to Reducto")
  or building an entirely new table-geometry extraction path for the
  vision pipeline. Genuinely out of scope for one session on top of
  everything else here.
- **Per-cell exact highlighting for narrative facts** — deliberately not
  attempted; paragraph/block-level precision is what the product
  requirement explicitly allows ("we do NOT require fake word-level
  precision"), and is what this session delivers.
- **SourceRenderer per-format architecture** (dedicated image/DOCX/
  spreadsheet/structured-text renderers) — not built. The existing
  honest degrade-to-document-level-open behavior for non-PDF was
  verified correct and left as is.
- **Rotation handling** — not touched; no new bbox-producing code was
  added this session.
- **A dedicated source-evidence health-audit endpoint** — not built as a
  separate public endpoint (Part 41's literal ask); folded into the
  existing reprocessing result instead (`segment_evidence_created`/
  `segment_evidence_reused`/`segments_with_page`/`segments_without_page`
  /`extraction_complete`), which is a real, useful, much smaller
  surface than a new PHI-adjacent diagnostics endpoint would be.
- **Formal SourceViewerProvider state-machine rewrite** — not done; the
  existing ref-based race-prevention approach was verified correct via
  Playwright rather than replaced.
- **The redundant-refetch inefficiency on re-selecting the same
  evidence id** — noted, not fixed (not a correctness bug).

## 12. Deployment

No migration to run — `alembic heads` unchanged, single head. No new
environment variable required. Every new field is additive; a document
processed before this feature existed renders exactly as it did before
(empty `source_evidence_ids`, `null` `extraction_coverage`, no
provenance actions shown for it) until it's reprocessed via the
existing "Reorganize with AI" action, which now ALSO backfills segment-
level evidence as a side effect of the same call. Safe to deploy
read-only.
