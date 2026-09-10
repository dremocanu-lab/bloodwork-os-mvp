# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale. This file is
status only.

## CURRENT PHASE
Phase 6 — Chart system: starting.

## COMPLETED PHASES
- **Phase 1**: extraction-provider abstraction, taxonomy, classifier,
  `/upload/batch`, classification confirmation.
- **Phase 2**: SHA-256 dedup, patient identity check + quarantine,
  `SourceEvidence`, Level-3 duplicate-observation linking.
- **Phase 3**: row-level "View original" for lab rows.
- **Phase 4**: conservative structured extraction for the 6 document
  types with no prior pipeline.
- **Phase 5**: `document_type` now flows through `serialize_document_card`,
  `get_document_payload`, the shared `ClinicalTimeline` component, and
  the PCP-workspace timeline's event-type/summary derivation — every
  timeline/document list shows the finer-grained Bragi type instead of
  just the coarse legacy section, additively (falls back cleanly for
  pre-Phase-1 documents).

## NEXT PHASE
Phase 6 — Chart system: centralize the existing ECharts usage
(`lib/chart-theme.ts`, `components/ui/trend.tsx` already exist) into a
shared Bragi chart theme/components, honest reference-range handling,
chart-point → source (using Phase 2/3's `SourceEvidence`).

## Architecture decisions
- Phase 5 found that "episodes of care" grouping already existed
  (admission-parent nesting in the timeline pages) — treated as done,
  not rebuilt.
- Chose to enhance labels within the existing 6-bucket section
  navigation/grouping rather than restructure it — see plan §2d for the
  risk/value reasoning.

## Important files (new/changed this phase)
- `backend/app/main.py` — `document_type` in `serialize_document_card`,
  `_event_type_for`/`_DOC_SUMMARY_BY_EVENT_TYPE` in the PCP timeline
- `frontend/components/clinical-timeline.tsx` — `documentType` field +
  label preference
- `frontend/lib/document-taxonomy-labels.ts` (new)
- `frontend/app/my-records/page.tsx`, `my-records/timeline/page.tsx`,
  `patients/[id]/page.tsx`, `patients/[id]/timeline/page.tsx` — pass
  `documentType` through to timeline items

## Migrations
None this phase.

## Environment variables
Unchanged.

## Tests / status
- `cd backend && pytest -q` → **42 passed** (unchanged — this phase was
  read/label plumbing, no new backend logic needing its own unit test).
- Full `app.main` import succeeded against the local dev DB.
- `pyflakes`: same 4 pre-existing warnings, nothing new.
- Frontend: `tsc --noEmit` clean. `eslint` on all 6 changed files shows
  only **pre-existing** issues, confirmed via `git diff --unified=0` to
  be nowhere near any line I touched (a handful of long-standing
  `setState`-in-`useEffect` findings in two large pages, and two
  pre-existing `exhaustive-deps` warnings).

## Known issues
- Top-level document organization (tabs/filters) still groups by the 6
  legacy `section` values, not the full 16-type taxonomy — see plan §2d.
- Prescription/medication_list → `PatientMedication` linkage still not
  built (carried over from Phase 4).

## Manual configuration/authentication required
- None to keep everything working as-is.
- Reducto: unchanged — still need your own account/API key + current
  docs before any Reducto phase work can start for real.
