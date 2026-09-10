# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale. This file is
status only.

## CURRENT PHASE
Phase 4 — Clinical readers: starting.

## COMPLETED PHASES
- **Phase 1**: extraction-provider abstraction, taxonomy, classifier,
  `/upload/batch`, classification confirmation.
- **Phase 2**: SHA-256 dedup, patient identity check + quarantine,
  `SourceEvidence`, Level-3 duplicate-observation linking, canonical/
  provenance columns on `LabResult`. Fixed a pre-existing
  `is_verified` type-drift bug.
- **Phase 3**: `GET /lab-results/{id}/source` + row-level "View
  original" in the document detail page (source-text quote — no bbox
  yet, honestly documented as such). Structured Analize unchanged.

## NEXT PHASE
Phase 4 — Clinical readers: discharge/imaging/operative/pathology/
prescription/consultation. Only discharge has any real structured
pipeline today; the rest need a new (conservative, source-grounded)
extraction step before there's anything to read beyond raw OCR text.

## Architecture decisions
- (Phases 1-3 decisions unchanged — see plan §0-§2b.)
- Row-level source verification reuses the document-level
  `openOriginal()` already in the document detail page rather than a
  second file-fetch implementation.

## Important files (new/changed this phase)
- `backend/app/main.py` — `GET /lab-results/{id}/source`
- `frontend/app/documents/[id]/page.tsx` — `LabSourceAction` component,
  wired into the Results table's flag column

## Migrations
None this phase (no new columns/tables).

## Environment variables
Unchanged.

## Tests / status
- `cd backend && pytest -q` → **36 passed** (unchanged from Phase 2 —
  no new backend logic worth a unit test beyond what authorization
  patterns already cover; see plan §2b for why an integration test was
  deferred).
- Full `app.main` import succeeded against the local dev DB.
- Frontend: `tsc --noEmit` clean; `eslint` on the changed file shows only
  one **pre-existing** warning (`getFlagStyle` unused, predates this
  phase).

## Known issues
- No bbox highlighting (needs Reducto Parse — unchanged blocker).
- Chart-point → source deliberately deferred to Phase 6.
- `/lab-results/{id}/source` has no dedicated automated test (see plan
  §2b) — manually reviewed against the existing `/documents/{id}/file`
  authorization pattern it copies.

## Manual configuration/authentication required
- None to keep everything working as-is.
- Reducto: still unchanged from Phase 1 — you'll need your own account/
  API key + current docs before any Reducto phase work can start for
  real.
