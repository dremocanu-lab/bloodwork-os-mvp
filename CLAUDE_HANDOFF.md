# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale. This file is
status only.

## CURRENT PHASE
Phase 7 — Full integration / responsive QA: starting (final phase).

## COMPLETED PHASES
1. Reducto foundation + multi-file classification.
2. Identity / duplicates / canonical data / provenance.
3. Row-level source verification.
4. Conservative clinical readers (6 new document types).
5. Longitudinal timeline / document organization labeling.
6. Chart system: reference-band honesty fix + chart-point → exact-row
   source deep link.

## NEXT PHASE
Phase 7 — final pass: run full test suite, tsc/eslint across the whole
frontend (not just changed files), re-review the full cumulative diff
for secrets/PHI, verify migrations one more time, then merge this
branch to `main` and push (per explicit instruction).

## Architecture decisions
- Phase 6 found the chart system already close to spec (restrained
  ECharts theme, honest per-point data) — fixed the one real honesty
  gap (single-band-across-differing-ranges) rather than rebuilding.
- Chart-point → source now carries `lab_result_id` end-to-end
  (backend trend endpoint → `TrendPoint` → `onPointClick` → query param
  → auto-opened source dialog), reusing Phase 2/3's `SourceEvidence`
  work rather than a new data path.

## Important files (new/changed this phase)
- `backend/app/main.py` — `lab_result_id` in trend points
- `frontend/components/ui/trend.tsx` — reference-band agreement check,
  `onPointClick` second arg
- `frontend/lib/analytes/types.ts` — `TrendPoint.lab_result_id`
- `frontend/app/my-records/page.tsx`, `patients/[id]/page.tsx` — deep-link
  navigation on point click
- `frontend/app/documents/[id]/page.tsx` — `?lab=` query param handling,
  auto-open + scroll-into-view

## Migrations
None this phase.

## Environment variables
Unchanged.

## Tests / status
- `cd backend && pytest -q` → **42 passed** (unchanged — this phase
  touched serialization/frontend, no new backend logic needing a unit
  test beyond what's already covered).
- Full `app.main` import succeeded against the local dev DB.
- `pyflakes`: same 4 pre-existing warnings, nothing new.
- Frontend: `tsc --noEmit` clean on all changed files. `eslint`: one new
  `react-hooks/set-state-in-effect` finding on the deep-link auto-open
  effect was fixed properly (moved the dialog-open state into `useState`
  initial value instead of setting it inside the effect) rather than
  suppressed; the one remaining disable-comment is for the effect's
  data-fetch call, matching the standard fetch-on-mount pattern already
  used elsewhere in this same file. All other findings across touched
  files confirmed pre-existing via `git diff --unified=0`.

## Known issues
- The large ECharts analytics dashboard (~2400 lines) has at least one
  hardcoded, non-theme color; a full consistency pass was not attempted
  this phase (see plan §2e).
- Everything else carried over from Phases 1-5 (see their sections in
  the plan) is still outstanding: no Reducto integration tested against
  the real API, no outline/search/30-second-read/conflicts UI, no
  prescription → PatientMedication linkage, no top-level document-
  organization restructure beyond label improvements.

## Manual configuration/authentication required
- None to keep everything working as-is.
- Reducto: unchanged — still need your own account/API key + current
  docs before any Reducto phase work can start for real.
