# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale and §2f for the
final verification detail. This file is status only.

## CURRENT PHASE
None — all 7 phases from the original spec are implemented, tested, and
merged to `main`. See plan §2f for exactly what "done" means here and
what's honestly still deferred.

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

## NEXT STEPS (not a "phase" — your call on priority)
- Get a Reducto account/API key and current API docs, then implement
  `ReductoExtractionProvider` for real (see plan §3) — nothing Reducto-
  shaped has been tested against the live API yet.
- Run the repo's own Playwright QA (`qa/flows.mjs`, `qa/a11y.mjs`)
  locally against the new upload/reader/chart flows at the responsive
  breakpoints the original spec named — this session couldn't safely
  generate the `BRAGI_TOKENS` file it needs.
- Try a real end-to-end upload through live Google Document AI/OpenAI
  (classification + structured reader extraction) — every phase avoided
  spending real API quota; this is the one class of test only you can
  run cheaply.
- Pick up any of the explicitly-deferred items in each phase's plan
  section (outline/search/30-second-read/conflicts UI, Level-2 semantic
  duplicate matching, prescription → `PatientMedication` linkage, a full
  ECharts consistency pass on the analytics dashboard, top-level
  document-organization restructuring) whenever they become the
  priority.

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
  work: `Document.is_verified` Integer/Boolean schema drift (Phase 2),
  and `openai_discharge_service.py`'s eager `OpenAI()` client
  construction at import time (Phase 4).

## Migrations
All additive (`ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS`)
via `run_migrations()` in `backend/app/main.py` — applies automatically
on the next backend start in any environment, including production, on
deploy. Verified repeatedly against the local dev DB across every phase
(20 pre-existing `documents` rows untouched throughout).

## Environment variables
Added (all default to current behavior — no action needed):
```
DOCUMENT_EXTRACTION_PROVIDER=legacy   # only "legacy" actually works right now
DOCUMENT_EXTRACTION_FALLBACK=legacy
REDUCTO_API_KEY=                      # backend-only; never NEXT_PUBLIC_*
REDUCTO_ENABLED=false                 # leave false until Reducto is really wired up
```
No other new env vars — structured reader extraction (Phase 4) reuses
the existing `OPENAI_API_KEY`.

## Tests / status (final)
- Backend: `cd backend && pip install -r requirements-dev.txt && pytest -q`
  → **42 passed**, unit-only (no DB fixtures convention exists yet).
- Frontend: `next build` succeeds (all 33 routes); `tsc --noEmit` clean;
  full-project `eslint .` shows only pre-existing findings unrelated to
  this work (see plan §2f).
- Live checks this session actually ran (not just described): a real
  SHA-256-duplicate functional test against the dev DB (temp rows
  cleaned up after), a real `uvicorn` boot with an OpenAPI route check,
  and `run_migrations()` applied cleanly against the dev DB after every
  phase.
- Not run: live OCR/AI calls (real API cost), the repo's Playwright QA
  suite (needs live tokens this session couldn't generate), Reducto
  itself (no key/MCP available).

## Known issues
See each phase's section in `BRAGI_REDUCTO_PLAN.md` for the full list;
the headline items are in this file's "Next steps" above.

## Manual configuration/authentication required
- **None** to keep the app working exactly as it did before this work —
  every new feature defaults to safe/off or additive/backward-compatible
  behavior.
- **Reducto**: get your own account + API key, then implement
  `ReductoExtractionProvider.classify()` (and later `split`/`parse`/
  `extract`) against current Reducto docs before ever setting
  `REDUCTO_ENABLED=true` anywhere.
- **Playwright QA**: generate a `BRAGI_TOKENS` file (see `qa/flows.mjs`
  for the expected shape) if you want to run the existing QA harness
  against this work.
