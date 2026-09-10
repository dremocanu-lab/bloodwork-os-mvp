# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale. This file is
status only.

## CURRENT PHASE
Phase 1 — Reducto foundation + multi-file classification: **done, committed.**

## COMPLETED PHASES
- **Phase 1**: `DocumentExtractionProvider` abstraction (legacy/Reducto),
  16-type document taxonomy, rule-based RO/EN classifier, `needs_confirmation`
  flow, `POST /upload/batch`, `POST /upload-jobs/{id}/confirm-type`,
  `GET /document-types`, rewritten patient upload page (no manual type
  picker), 23 passing unit tests.

## NEXT PHASE
Phase 2 — Identity / duplicates / canonical data / provenance:
- SHA-256 exact-duplicate detection on upload.
- Patient identity mismatch detection + quarantine (today: none — a
  document's extracted identity only fills *blank* patient fields, never
  flags a mismatch).
- `ClinicalObservation` (raw + canonical) evolving `LabResult` (which
  already has raw/canonical fields — a head start).
- `SourceEvidence` model (document/page/bbox/text) — no provenance model
  exists yet at all.
- First DB-backed tests (need fixtures — none exist yet).

## Architecture decisions
- New `document_type` rides *alongside* the existing `section` column
  (not a replacement) — every current route/page/filter on `section`
  keeps working. See `backend/app/services/document_taxonomy.py` for the
  mapping.
- Migrations follow the repo's existing convention: idempotent
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements appended to
  `run_migrations()` in `backend/app/main.py` (no Alembic). They ran
  automatically against the local dev DB during this phase (verified —
  see Tests/status) and will run automatically on the next backend start
  in any other environment, including production, on deploy.
- Reducto is fully abstracted but **not implemented** — no Reducto MCP
  or API key was available this phase. `ReductoExtractionProvider`
  always raises until it's actually wired up (see plan §3).

## Important files
- `backend/app/services/document_taxonomy.py` — taxonomy + legacy-section mapping
- `backend/app/services/document_classifier.py` — "legacy_rules" keyword classifier
- `backend/app/services/extraction_provider.py` — provider abstraction/factory
- `backend/app/main.py` — `run_migrations()`, `process_upload_job()` classification
  block, `/upload/batch`, `/upload-jobs/{id}/confirm-type`, `/document-types`
- `backend/app/models.py` — new columns on `Document` and `UploadJob`
- `frontend/components/upload-provider.tsx` — `enqueueAutoClassifyUploads`,
  `confirmDocumentType` (additive; `enqueueUploads` unchanged for other pages)
- `frontend/app/my-records/upload/page.tsx` — rewritten patient upload page

## Migrations
No manual step needed — `run_migrations()` runs on every backend start
and only adds nullable columns (`document_type`, `classification_status`,
`classification_confidence`, `classification_source` on `documents` and
`upload_jobs`). Verified against the local dev DB this phase (20 existing
`documents` rows, 0 `upload_jobs` — untouched, columns added cleanly).

## Environment variables (manual configuration needed for Phase 3+, NOT now)
Added to `backend/.env.example`, all safe defaults already in place —
**no action needed to keep the app working as before**:
```
DOCUMENT_EXTRACTION_PROVIDER=legacy   # only "legacy" actually works right now
DOCUMENT_EXTRACTION_FALLBACK=legacy
REDUCTO_API_KEY=                      # backend-only; never NEXT_PUBLIC_*
REDUCTO_ENABLED=false                 # do not set true until §3 of the plan is done
```
When you're ready to start real Reducto integration (Phase 3+), you'll
need to get a Reducto account/API key yourself — I have no way to
provision one. Nothing else needs manual setup for what's shipped so far.

## Tests / status
- `cd backend && pip install -r requirements-dev.txt && pytest -q` →
  **23 passed** (taxonomy, classifier, provider abstraction — all
  unit-only, no DB).
- `python -m py_compile` / `ast.parse` clean on all edited/new backend
  files; `pyflakes app/main.py` shows only 4 **pre-existing** warnings,
  none touching this phase's code.
- Full `app.main` import succeeded against the local dev DB
  (`mvp1_phase1` on `localhost:5432`) with a throwaway `SECRET_KEY`/
  `OPENAI_API_KEY` — confirms `run_migrations()` applied the new columns
  without error and without touching existing rows.
- Frontend: `npx tsc --noEmit` clean, `npx eslint` clean on both changed
  files.
- **Not done this phase**: a real end-to-end upload through live Google
  Document AI / OpenAI (would spend real API quota — run this locally
  yourself when convenient by uploading a real or synthetic file through
  "Add medical records" and watching the classification label appear).

## Known issues
See `BRAGI_REDUCTO_PLAN.md` §6 — the main one worth knowing about:
auto-classified uploads currently run OCR twice (once to classify, once
inside the existing bloodwork/discharge pipeline). Deliberate, documented
shortcut; fix lands naturally with Phase 3's "parse once, persist"
requirement.

## Manual configuration/authentication required
- None to keep everything working as-is today.
- For Phase 3+ real Reducto integration: you'll need to create/provide a
  Reducto account and `REDUCTO_API_KEY` yourself, and confirm current
  Reducto Classify/Split/Parse/Extract API behavior (no Reducto MCP was
  connected this session to verify it directly).
