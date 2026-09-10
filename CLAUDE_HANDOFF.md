# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale. This file is
status only.

## CURRENT PHASE
Phase 3 — Analize + source verification: starting.

## COMPLETED PHASES
- **Phase 1**: extraction-provider abstraction, document taxonomy,
  rule-based classifier, `/upload/batch`, classification confirmation.
- **Phase 2**: SHA-256 exact-duplicate short-circuit, patient identity
  check (matched/needs_confirmation/mismatch/insufficient_identity) with
  quarantine for mismatches (`patient_id=NULL` + `intended_patient_id`),
  `SourceEvidence` table, Level-3 duplicate-observation linking on
  `LabResult`, canonical/provenance columns on `LabResult`. Fixed a
  pre-existing `Document.is_verified` Integer/Boolean schema-drift bug
  found via testing. 36 passing unit tests + one live functional test
  (dedup short-circuit, against the real dev DB, cleaned up after).

## NEXT PHASE
Phase 3 — Analize + source verification: wire "View original" using
`SourceEvidence.source_text` (no bbox yet — none exists without real
Reducto Parse); keep structured Analize as the primary lab experience
(no replacement).

## Architecture decisions
- Quarantine uses `Document.patient_id = NULL` + `intended_patient_id`
  rather than auditing every `patient_id ==` query site — automatically
  invisible everywhere.
- Canonical/provenance fields went onto the existing `LabResult` table
  (not a new `ClinicalObservation` table) — see plan §2a for why.
- Migrations still follow `run_migrations()` in `main.py` (idempotent
  `ADD COLUMN IF NOT EXISTS`) — ran automatically against the local dev
  DB this phase, verified.

## Important files (new/changed this phase)
- `backend/app/services/patient_identity.py`, `file_hash.py`
- `backend/app/main.py` — dedup + identity blocks in `process_upload_job`,
  `/upload-jobs/{id}/confirm-identity`, `/documents/quarantined`,
  `/documents/{id}/identity-review`
- `backend/app/models.py` — `SourceEvidence`, new `Document`/`UploadJob`/
  `LabResult` columns, fixed `is_verified` type
- `frontend/components/upload-provider.tsx`,
  `frontend/app/my-records/upload/page.tsx` — inline identity confirm/
  reject UI

## Migrations
No manual step — same `run_migrations()` auto-apply as Phase 1. Verified
against the local dev DB (`mvp1_phase1`): all new columns + the
`source_evidence` table applied cleanly, 20 pre-existing documents
untouched.

## Environment variables
No new ones this phase. Still: `REDUCTO_ENABLED=false` everywhere until
Phase 3+ implements the real integration (see plan §3).

## Tests / status
- `cd backend && pytest -q` → **36 passed** (unit-only, no DB).
- Live functional test against the dev DB: SHA-256 duplicate
  short-circuit exercised end-to-end (`process_upload_job` on a real
  temp patient/document), asserted `status == "duplicate"` and correct
  `document_id`, then fully cleaned up (deleted temp rows + file,
  confirmed document count back to 20).
- `pyflakes app/main.py`: only the same 4 pre-existing warnings from
  before this phase.
- Frontend: `tsc --noEmit` and `eslint` clean.
- **Not done**: live OCR/AI end-to-end test (same reasoning as Phase 1 —
  would spend real API quota).

## Known issues
- Level-2 semantic duplicate detection deferred (see plan §2a) —
  nothing extracts accession/specimen IDs yet to key off.
- No dedicated quarantine review *page* yet (backend done; the common
  in-flow identity-confirmation case has UI, the rarer full-mismatch
  quarantine case doesn't yet).
- Double-OCR-on-classify shortcut from Phase 1 still stands.
- **Worth checking**: this session found `Document.is_verified` had
  drifted from the model (Integer) vs. the live DB (boolean) on the
  local dev DB. Fixed the model to match. If production has the same
  drift, this fix helps it; if production's column was already boolean
  (likely, if it was bootstrapped from an older model version), nothing
  changes for it either way — but worth a quick manual check.

## Manual configuration/authentication required
- None to keep everything working as-is.
- Reducto: still need your own account/API key + current API docs before
  Phase 3+ can implement the real provider (unchanged from Phase 1).
