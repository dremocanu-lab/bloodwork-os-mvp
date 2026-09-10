# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale and §2f/§8 for the
final verification detail. This file is status only.

## CURRENT PHASE
None — all 7 phases from the original spec, a real Reducto integration
(§8), and a full DB-backed production-readiness verification round (§9)
are implemented and merged to `main`. See plan §2f, §8, and §9 for
exactly what "done" means here and what's honestly still deferred.
`REDUCTO_ENABLED` is still `false` everywhere in the repo — see §9's
"is it safe now" for the current answer and what's still worth doing
first.

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
- **Reducto is now really integrated and DB-verified (see plan §8, §9)**
  — classify, split, extract, and parse-persistence were implemented and
  verified against both the live Reducto API and a real non-production
  Postgres database end-to-end (multi-file batch, Romanian lab →
  Analize → bbox, duplicates, wrong-patient quarantine, mixed-PDF split
  including the non-contiguous page-mapping edge case). One real bug
  (overlapping Split sections wrongly treated as a mixed PDF instead of
  deferring to Classify's ambiguity handling) was found and fixed this
  round. See §9 for exactly what's still not covered before flipping
  `REDUCTO_ENABLED=true` anywhere real.
- Run the repo's own Playwright QA (`qa/flows.mjs`, `qa/a11y.mjs`)
  locally against the new upload/reader/chart flows at the responsive
  breakpoints the original spec named — this session couldn't safely
  generate the `BRAGI_TOKENS` file it needs (same blocker as before).
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
  → **42 passed**, unit-only (no DB fixtures convention exists yet).
- Frontend: `next build` succeeds (all 33 routes); `tsc --noEmit` clean;
  full-project `eslint .` shows only pre-existing findings unrelated to
  this work (see plan §2f). Not re-run after the Reducto integration
  (backend-only change; no frontend files touched — see plan §8).
- Live checks this session actually ran (not just described): a real
  SHA-256-duplicate functional test against the dev DB (temp rows
  cleaned up after, Phase 2), a real `uvicorn` boot with an OpenAPI route
  check, `run_migrations()` applied cleanly against the dev DB after
  every phase, **and the real Reducto integration (plan §8): live
  upload/classify/split/parse/extract calls against platform.reducto.ai
  with synthetic Romanian documents, plus function-level tests of the
  actual provider code (not just ad-hoc scripts)**.
- Not run: live OCR/AI calls through the legacy provider (real API
  cost), the repo's Playwright QA suite (needs live tokens this session
  couldn't generate), and — new this round — the full HTTP/DB-backed
  upload flow for the Reducto path (this session had no local Postgres
  credentials; see plan §8 "what wasn't verified").

## Known issues
See each phase's section in `BRAGI_REDUCTO_PLAN.md` for the full list;
the headline items are in this file's "Next steps" above, plus plan §8
for the Reducto-integration-specific ones.

## Manual configuration/authentication required
- **None** to keep the app working exactly as it did before this work —
  every new feature defaults to safe/off or additive/backward-compatible
  behavior; `REDUCTO_ENABLED` still defaults to `false`.
- **Reducto**: a real `REDUCTO_API_KEY` was used to build and verify this
  integration (see plan §8) and is in `backend/.env` (gitignored, local
  only) — rotate/replace it if you don't want that key used further.
  Before setting `REDUCTO_ENABLED=true` in any real environment, run the
  full upload flow against your own local Postgres first (this session
  couldn't) and read plan §8's "turning it on" checklist.
- **Playwright QA**: generate a `BRAGI_TOKENS` file (see `qa/flows.mjs`
  for the expected shape) if you want to run the existing QA harness
  against this work.
