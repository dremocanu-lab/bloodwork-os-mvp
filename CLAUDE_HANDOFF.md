# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale and §2f/§8 for the
final verification detail. This file is status only.

## CURRENT PHASE
None — all 7 phases from the original spec, a real Reducto integration
(§8), a full DB-backed production-readiness round (§9), a real
production-failure fix + classification-latency round (§10), a
normalization/source-viewer/popup-rework round (§11), a correction
round (§12: fixed a fabricated PSW clinical claim from §11, completed
the popup audit), and a visual/interaction correction pass (§13: upload
compaction, an Overview display bug, source-viewer route lifecycle,
full-lab-row PDF framing, PDF render quality, a blank-viewer layout
bug) are implemented and merged to `main`. See plan §2f, §8, §9, §10,
§11, §12, §13 for exactly what "done" means here and what's honestly
still deferred. `REDUCTO_ENABLED` is `true` in production (confirmed
via live traffic) — see §10 for the real production bug that was
blocking every upload there and is now fixed.

## COMPLETED PHASES
1. Reducto foundation + multi-file classification (rule-based
   "legacy_rules" classifier; Reducto itself never connected — no MCP/key
   available).
2. Identity / duplicates / canonical data / provenance.
3. Row-level source verification ("View original" per lab row).
4. Conservative clinical readers (6 document types with no prior
   pipeline).
5. Longitudinal timeline / document-organization labeling.
6. Chart system: reference-band honesty fix + chart-point → exact-row
   source deep link.
7. Full integration verification: `next build`, real `uvicorn` boot +
   OpenAPI route check, full-project `eslint`, full backend test suite,
   full cumulative diff review. See plan §2f.
8. Real Reducto integration (classify/split/extract, verified against the
   live API). See plan §8.
9. Full DB-backed production-readiness round (real Neon Postgres,
   multi-file batch, quarantine, duplicates, mixed-PDF split, Parse
   persistence). See plan §9.
10. Real production failure diagnosed and fixed (`documents.is_verified`
    schema drift blocking every upload, any provider — see plan §10),
    plus real classification-latency fixes (parallel Classify+Split,
    accurate stage messaging, bounded multi-file concurrency, error
    categorization).
11. Generic OCR-aware lab-analyte resolver (the PSV/PSW fix), a shared
    in-app source-verification viewer (PDF.js, replacing "open in a new
    tab"), and a global popup/dialog rework (no dark backdrops, anchored
    contextual UI). See plan §11.
12. Corrected §11: removed a fabricated "PSW = Platelet Distribution
    Width" catalog alias that had no real source, and rearchitected the
    resolver around two independent confidence axes (OCR-text-match vs.
    clinical-semantic) so PSW/PSV now honestly resolves unresolved rather
    than silently asserting an invented clinical meaning. Also completed
    the popup audit: converted every remaining routine/contextual
    centered dialog (revoke access, regenerate code, end assignment, both
    featured-analyte pickers) to an anchored popover, and documented the
    three that legitimately stay centered (emergency session-start,
    document deletion, account deletion). See plan §12.
13. Fixed five real product bugs reported via screenshots: the upload
    page's three stacked cards consolidated into one; a false "No
    bloodwork data yet" on Overview despite real Records/Bloodwork/Labs
    counts (a display-logic bug, not a caching one); the source viewer
    now closes automatically on Back/route change/patient switch instead
    of needing a separate close; the lab PDF highlight now frames the
    whole table row (real unioned+padded geometry, new `row_bbox_*`
    columns, additive to the existing per-field bbox) instead of just the
    value cell, with an outline-based, non-text-obscuring treatment; a
    layout-collapse bug that could leave the PDF viewer looking blank/
    tiny is fixed with a CSS floor size. Also added: a purple "selected"
    state on the lab row whose source is open, a restrained hover
    gradient, HiDPI-aware canvas rendering, and a little more restrained
    color (stat-card accents, nav active edge). See plan §13.

## NEXT STEPS (not a "phase" — your call on priority)
- **Production was actually broken for uploads before §10** — `documents.
  is_verified` was Boolean in the model but integer in production's real
  column, so every Document insert failed (any provider). Fixed via an
  idempotent migration, deployed, and confirmed via a real synthetic
  upload against the live server (`done` status, real Reducto
  classification + extraction). If you see upload failures again, check
  `render logs` for `psycopg.errors.DatatypeMismatch` first — that class
  of bug (a model type that doesn't match the live column) can recur for
  other columns if a future model change isn't paired with a migration.
- Chart/Reader/Timeline/Documents-list still don't use the new shared
  source viewer (`openSourceEvidence`) — only Analize does. See plan
  §11b for exactly what's blocking `AnalyticsDrilldownDrawer`
  specifically (needs a `lab_result_id`/`source_evidence_id` threaded
  through the analytics data pipeline, which doesn't carry one today).
- The popup audit is now complete (plan §12b) — every remaining centered
  dialog (emergency session-start, document deletion, account deletion)
  is a deliberate, documented exception for a genuine blocking/
  irreversible workflow, not a deferred conversion. Nothing left to
  revisit here unless a new dialog is added.
- If a future document needs "PSW" or a similarly uncertain analyte name
  resolved, do not add a global synonym without a real cited source —
  see plan §12a for the vendor-specific escape hatch
  (`VENDOR_SPECIFIC_ALIASES`) and why the global catalogs stayed clean.
- Run the repo's own Playwright QA (`qa/flows.mjs`, `qa/a11y.mjs`)
  locally against the new upload/reader/chart/source-viewer/popup flows
  at the responsive breakpoints the original spec named — this session
  couldn't safely generate the `BRAGI_TOKENS` file it needs (same
  blocker as every prior round).
- Try a real end-to-end upload through live Google Document AI/OpenAI
  (classification + structured reader extraction) for the legacy-provider
  path — every phase avoided spending real API quota; this is the one
  class of test only you can run cheaply.
- Pick up any of the explicitly-deferred items in each phase's plan
  section (outline/search/30-second-read/conflicts UI, Level-2 semantic
  duplicate matching, prescription → `PatientMedication` linkage, a full
  ECharts consistency pass on the analytics dashboard, top-level
  document-organization restructuring) whenever they become the
  priority.
- §13's fixes were verified by direct source/build/test inspection, not
  a live browser pass (same `BRAGI_TOKENS` blocker as every prior
  round) — if you get real QA tokens, the highest-value things to
  visually confirm are: the new full-lab-row PDF highlight against a
  real rendered report (does the frame actually sit clear of the
  glyphs at fit-width/zoomed/resized), and the previously-blank-PDF fix
  across a few real sessions (the CSS floor-size fix addresses the root
  cause found by inspection, but wasn't reproduced live before or after
  the fix).
- `care-partner/upload/page.tsx` is a third upload-page implementation
  (separate from the patient/doctor ones fixed in §13a) that was not
  touched this round — no screenshot named it, and it doesn't share the
  same three-stacked-cards structure, but it's worth a look if a future
  round revisits upload UX.

## Architecture decisions (cumulative — see plan for full detail per phase)
- `document_type` rides alongside the existing `section` column
  everywhere; nothing that filtered on `section` was changed.
- Migrations follow the repo's pre-existing `run_migrations()`
  convention (idempotent `ADD COLUMN IF NOT EXISTS`) — no Alembic
  introduced.
- Quarantine (identity mismatch) uses `patient_id = NULL` +
  `intended_patient_id` rather than touching 9 existing query sites.
- Canonical/provenance fields went onto the existing `LabResult`/
  `Document` tables, not new parallel tables, except `SourceEvidence`
  (genuinely new: no analogous data existed before).
- Two pre-existing bugs were found via testing and fixed as part of this
  work: `Document.is_verified` Integer/Boolean schema drift (Phase 2, the
  declaration; actually converting the live column happened in §10 after
  it was found still broken in production), and
  `openai_discharge_service.py`'s eager `OpenAI()` client construction at
  import time (Phase 4).
- Lab-analyte resolution (§11a) is a new stage layered on top of the two
  existing catalogs (`synonyms.py`, `lab_catalog.py`), not a replacement
  for either — see `lab_resolver.py`.
- The shared source viewer (§11b) resolves/authorizes via a new endpoint
  but reuses the existing `/documents/{id}/file` route and its exact
  authorization pattern for the actual PDF bytes — no new file-serving
  mechanism.

## Migrations
All additive (`ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS`)
via `run_migrations()` in `backend/app/main.py` — applies automatically
on the next backend start in any environment, including production, on
deploy. Verified repeatedly against the local dev DB across every phase
(20 pre-existing `documents` rows untouched throughout).

## Environment variables
```
DOCUMENT_EXTRACTION_PROVIDER=legacy   # "legacy" or "reducto" — see plan §8
DOCUMENT_EXTRACTION_FALLBACK=legacy
REDUCTO_API_KEY=                      # backend-only; never NEXT_PUBLIC_*
REDUCTO_ENABLED=false                 # leave false — see plan §8 "turning it on"
```
No other new env vars — structured reader extraction reuses the existing
`OPENAI_API_KEY` as the fallback when Reducto is disabled or fails.
`python-dotenv` is now a dependency and `backend/.env` (gitignored) is
loaded automatically on startup — previously `.env.example` documented a
file that was never actually read.

## Tests / status (final)
- Backend: `cd backend && pip install -r requirements-dev.txt && pytest -q`
  → **62 passed** (42 original + 15 `test_lab_resolver.py` cases after
  §12a's rewrite + 5 new `test_reducto_row_bbox.py` cases this round),
  unit-only (no DB fixtures convention exists yet).
- Frontend: `next build` succeeds (all 33 routes); `tsc --noEmit` clean;
  `eslint` on every file touched this round is clean (a few pre-existing
  `react-hooks` findings remain in files this round didn't otherwise
  touch — confirmed via `git stash` to predate this round — see plan
  §2f/§12b/§13i, not fixed, out of scope).
- Live checks this session actually ran (not just described): a real
  SHA-256-duplicate functional test (Phase 2), a real `uvicorn` boot with
  an OpenAPI route check, `run_migrations()` applied cleanly against the
  dev DB after every phase, the real Reducto integration (plan §8), a
  full DB-backed multi-scenario round against real Neon Postgres (plan
  §9), a real synthetic upload against the LIVE production server
  confirming the §10 fix (`done` status, real classification+extraction,
  cleaned up after), a real `/source-evidence/{id}/view` round-trip (real
  bbox, real PDF bytes, and IDOR checks — cross-patient 403 on both the
  new endpoint and the existing file route, unauthenticated 401,
  nonexistent-evidence 404) against the dev DB, and this round: a real
  synthetic "PSW" document through the live Reducto API, confirming
  Reducto reads the clean source text as "PSW" correctly and the resolver
  now honestly leaves it `normalization_method="unresolved"` (§12a — this
  is the corrected, truthful outcome, not a regression from §11a's
  claim).
- Not run: live OCR/AI calls through the legacy provider (real API
  cost), the repo's Playwright QA suite (needs live tokens no session has
  been able to generate yet), and any actual browser click-through of the
  new source viewer / popup positioning (verified via build/typecheck/
  lint + real backend E2E instead — see plan §11d).
- This round (§13): confirmed by direct inspection of the actual
  production build output that the PDF.js worker is correctly emitted
  and referenced at its real static-asset path (ruling it out as a
  contributor to the blank-PDF bug before attributing that bug to a CSS
  layout-collapse root cause instead — see plan §13f). The row-bbox
  union/padding geometry is covered by 5 new unit tests. Not run: a live
  browser pass confirming the fixed layout, the new hover/selected-row
  treatment, or the row-bbox highlight against a real rendered PDF —
  same `BRAGI_TOKENS` blocker as always; see plan §13i for exactly what
  that leaves unverified.

## Known issues
See each phase's section in `BRAGI_REDUCTO_PLAN.md` for the full list;
the headline items are in this file's "Next steps" above, plus plan §8
for the Reducto-integration-specific ones.

## Manual configuration/authentication required
- **None new this round.** No Render environment variables were changed
  or need changing; `frontend/package.json` gained one new dependency
  (`pdfjs-dist`, for the in-app PDF viewer) — a normal `npm install` on
  the next frontend deploy picks it up.
- **Reducto**: a real `REDUCTO_API_KEY` was used to build and verify the
  integration (see plan §8) and is in `backend/.env` (gitignored, local
  only) — rotate/replace it if you don't want that key used further.
  `REDUCTO_ENABLED=true` is confirmed live in production already.
- **Playwright QA**: generate a `BRAGI_TOKENS` file (see `qa/flows.mjs`
  for the expected shape) if you want to run the existing QA harness
  against this work — still nobody's been able to generate this safely.
