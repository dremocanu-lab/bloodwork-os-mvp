# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale. This file is
status only.

## CURRENT PHASE
Phase 5 — Longitudinal / Timeline / document organization: starting.

## COMPLETED PHASES
- **Phase 1**: extraction-provider abstraction, taxonomy, classifier,
  `/upload/batch`, classification confirmation.
- **Phase 2**: SHA-256 dedup, patient identity check + quarantine,
  `SourceEvidence`, Level-3 duplicate-observation linking, canonical
  columns on `LabResult`. Fixed `is_verified` type-drift bug.
- **Phase 3**: row-level "View original" for lab rows (source-text
  quote, no bbox yet).
- **Phase 4**: conservative structured extraction
  (`structured_reader_service.py`, OpenAI vision, same convention as
  the existing discharge pipeline) for the 6 document types with no
  prior pipeline; rendered as labeled section cards in the document
  detail page. Fixed a second pre-existing bug (eager OpenAI client
  construction at import time in `openai_discharge_service.py`).

## NEXT PHASE
Phase 5 — Longitudinal / Timeline / document organization: feed
Phase 4's extracted sections (diagnoses, procedures, admissions,
consultations) into `PatientEvent`/Timeline where reliable, and
automatic document organization by medical meaning (not just the 6
legacy `section` buckets).

## Architecture decisions
- (Phases 1-3 unchanged.) Phase 4's reader lives as one new branch in
  the existing `documents/[id]/page.tsx` ternary, not 6 new page routes
  or a separate generic Reader route — see plan §2c for why.
- `structured_reader_service.py` mirrors `openai_discharge_service.py`'s
  conventions exactly (vision API, temp 0, explicit no-fabrication
  instruction) rather than inventing a new extraction style.

## Important files (new/changed this phase)
- `backend/app/services/structured_reader_service.py` (new)
- `backend/app/services/openai_discharge_service.py` — lazy client fix
- `backend/app/main.py` — extraction call in `process_upload_job`,
  `document_type`/`structured_sections` in `get_document_payload`
- `backend/app/models.py` — `Document.structured_sections`
- `frontend/lib/reader-sections.ts` (new) — section labels
- `frontend/app/documents/[id]/page.tsx` — new reader branch

## Migrations
`documents.structured_sections TEXT` — applied automatically via
`run_migrations()`, verified against the local dev DB.

## Environment variables
Unchanged. Structured reader extraction reuses the existing
`OPENAI_API_KEY` (no new env var) — it's simply not run for a document
if that key isn't set (graceful, not an error).

## Tests / status
- `cd backend && pytest -q` → **42 passed** (was 36; +6 for
  `structured_reader_service`).
- Full `app.main` import + migration succeeded against the local dev DB.
- `pyflakes`: same 4 pre-existing warnings, nothing new.
- Frontend: `tsc --noEmit` clean; `eslint` shows the same one
  pre-existing warning as Phase 3 (`getFlagStyle` unused) plus a
  pre-existing (unrelated, far from my edits) `i18n.ts` hook-rules
  finding — neither introduced by this phase.
- **Not done**: a real OpenAI vision call against an actual document
  (would spend real API quota — same reasoning as every phase so far).
  Worth trying locally on a real imaging/pathology/prescription upload
  once you're ready to spend a bit of quota on it.

## Known issues
- No outline/search/30-second-read/what-changed/conflicts UI yet — see
  plan §2c "deferred" list. This phase built the extraction + display
  foundation, not the full Reader experience described in the original
  spec (that's realistically its own phase-sized effort).
- No section-level source verification (only document-level "Original").
- Prescription/medication_list sections aren't linked into
  `PatientMedication` yet (Phase 5 concern).

## Manual configuration/authentication required
- None to keep everything working as-is.
- Reducto: unchanged — still need your own account/API key + current
  docs before any Reducto phase work can start for real.
