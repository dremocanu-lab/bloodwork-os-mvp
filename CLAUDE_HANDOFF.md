# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale and §2f/§8 for the
final verification detail. This file is status only.

## CURRENT PHASE
None — all 7 phases from the original spec, a real Reducto integration
(§8), a full DB-backed production-readiness round (§9), a real
production-failure fix + classification-latency round (§10), a
normalization/source-viewer/popup-rework round (§11), a correction
round (§12: fixed a fabricated PSW clinical claim from §11, completed
the popup audit), a visual/interaction correction pass (§13: upload
compaction, an Overview display bug, source-viewer route lifecycle,
full-lab-row PDF framing, PDF render quality, a blank-viewer layout
bug), a source-highlighting correctness pass (§14: page-association
bleed, a structured-pane scroll-jump bug — code-level fix only, NOT yet
proven in a real browser at that point), and a real-browser-verified
fix for what §14 missed (§15: the structured pane still jumped in
practice because content reflow at the new, narrower width moves a row
independent of scroll offset — fixed with a real visual anchor, proven
with an actual local Playwright/Chromium session against a real
Reducto-processed document, not just code inspection) are implemented
and merged to `main`. See plan §2f, §8, §9, §10, §11, §12, §13, §14,
§15 for exactly what "done" means here and what's honestly still
deferred. `REDUCTO_ENABLED` is `true` in production (confirmed via live
traffic) — see §10 for the real production bug that was blocking every
upload there and is now fixed.

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
14. Fixed three more bugs found by manually retesting the deployed §13
    viewer: the highlight could bleed onto the wrong PDF page (including
    landing in empty space) because nothing checked that the evidence's
    own page matched the page actually on screen — now gated, plus a
    monotonic request-id guard against async render races and a bbox
    sanity check as defense in depth; still-field-sized highlighting on
    some documents turned out to be pre-existing SourceEvidence rows
    created before §13e shipped (no per-field geometry was ever retained
    for those to backfill from — verified the row-union math itself is
    correct against a real Reducto extraction, see plan §14a); opening
    "View in original" was unmounting and remounting the entire
    structured page (a Fragment-vs-div branch in the split-view
    composition), destroying its scroll position — fixed by keeping a
    stable DOM wrapper (`display: contents` when inactive) plus
    explicitly carrying the scroll offset across the transition in both
    directions. See plan §14.
15. §14's scroll-jump fix turned out to be real but incomplete — a live
    retest (screenshot) proved the pane still jumped. Root cause: the
    numeric scrollTop transfer was correct, but the left pane also gets
    NARROWER when the split opens, so its content reflows (longer names
    wrap onto more lines, etc.) — a row can end up several hundred
    pixels from where it was even with a numerically "correct" scroll
    offset, since reflow changes how much content sits above it,
    independent of scrollTop. Fixed with a real visual anchor
    (`captureVisualAnchor()` — captures the clicked element + its
    on-screen position, re-measures it after the layout swap, nudges
    scroll by the exact difference) instead of just a number. A second,
    subtler bug was found and fixed in the same pass: the anchor was
    initially captured too late (after an async gap during which the
    clicked button had already been disabled and therefore blurred),
    landing on `document.body` instead of the real row — fixed by
    capturing the anchor as the very first thing the click handler does.
    This round was verified in an ACTUAL local browser (Playwright +
    Chromium, a real synthetic patient account, a real document
    processed through live Reducto) — not just code inspection: open
    preserves position to within 0.45px, close to within 0.2px, page-2
    navigation shows zero highlight bleed, and a real page-2 analyte
    highlights correctly there. See plan §15.

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
- **Any lab document uploaded before §13e shipped will never show a
  full-row PDF highlight** — it'll keep falling back to the old
  field-only bbox forever, because the four individual field citations
  needed to compute a row union were never retained for pre-existing
  SourceEvidence rows (only one final bbox was ever stored per row
  historically). This is why the field-only highlighting in this
  round's report kept appearing even after §13e shipped — see plan
  §14b. There's no backfill path short of re-processing the original
  document through Reducto again; not attempted this round (out of
  scope, and would cost real API quota per affected document).
- §14's page-association gating was real and held up under real-browser
  retesting (§15). §14's scroll-preservation claim did NOT hold up —
  it was verified only by code/CSS inspection at the time, and a live
  retest proved it wrong (content reflow at the narrower split width
  moves rows independent of scroll offset). This is a standing lesson,
  not just a fixed bug: for anything that depends on actual browser
  layout/reflow behavior, code-level reasoning is not sufficient
  evidence of "fixed" — see plan §15 for how it was actually verified
  this time (a real local Playwright/Chromium session, a real synthetic
  account, a real Reducto-processed document, pixel-level before/after
  measurements).
- §15's fix was verified locally (see plan §15d for the exact method)
  but not against the repo's own `qa/flows.mjs`/`qa/a11y.mjs` suite,
  and not beyond a 2-page synthetic document or the desktop split
  layout (mobile/tablet's full-screen sheet variant wasn't retested
  this round). `BRAGI_TOKENS` itself is still not available as a
  pre-existing file, but this round found a working alternative: create
  a synthetic account through the real `/auth/signup` endpoint, use its
  real JWT — that path is now proven to work locally and could be
  extended to run the full `qa/` suite too, if a future round needs it.

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
  → **67 passed** (42 original + 15 `test_lab_resolver.py` cases after
  §12a's rewrite + 5 `test_reducto_row_bbox.py` cases from §13 + 5 new
  `test_reducto_page_convention.py` cases this round), unit-only (no DB
  fixtures convention exists yet).
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
- §13: confirmed by direct inspection of the actual production build
  output that the PDF.js worker is correctly emitted and referenced at
  its real static-asset path (ruling it out as a contributor to the
  blank-PDF bug before attributing that bug to a CSS layout-collapse
  root cause instead — see plan §13f). The row-bbox union/padding
  geometry is covered by 5 unit tests. Not run: a live browser pass
  confirming the fixed layout, the new hover/selected-row treatment, or
  the row-bbox highlight against a real rendered PDF — same
  `BRAGI_TOKENS` blocker as always; see plan §13i for exactly what that
  leaves unverified.
- §14: a real synthetic 2-page PDF was generated (PyMuPDF) and run
  through the actual live Reducto API and the actual
  `extract_lab_results()` function — not a mocked response or a
  handcrafted rectangle — confirming the row-bbox union math itself
  produces correct, page-scoped geometry for every row across both
  pages (see plan §14a for the full transcript of what was verified).
  The page-association fix and the scroll-preservation architecture
  were verified by direct code/CSS/reconciliation-behavior inspection
  ONLY, not a live browser pass — and that turned out to matter: see §15.
- §15: this round actually ran a real browser (Playwright + Chromium —
  already an existing devDependency, `@playwright/test`, not a new
  tool) against a local Next.js dev server + local FastAPI backend
  pointed at the shared Neon dev DB. `BRAGI_TOKENS` as a pre-existing
  file is still unavailable, but this round found and used a legitimate
  alternative: a synthetic patient account created through the real
  `/auth/signup` endpoint (normal registration, normal JWT — not an
  auth bypass), seeded into `localStorage` the same way the existing
  `qa/flows.mjs` harness seeds its own tokens. A real 20-row, 2-page
  synthetic CBC + Basic Metabolic Panel PDF was uploaded through the
  real `/upload/batch` endpoint and confirmed (via its own audit trail)
  to have gone through live Reducto classify+extract, not the legacy
  OCR path. Four scenarios were measured directly in the browser (DOM
  `getBoundingClientRect()`, not assumptions) with screenshots as
  supporting evidence: open-preserves-position (Δ0.45px), switch-to-a-
  visible-row-doesn't-move (Δ1px), page-isolation (zero highlight
  elements on an unrelated page; a real page-2 analyte highlights
  correctly there), close-preserves-position (Δ0.2px). The synthetic
  account and document were deleted after testing. Not run: the repo's
  own broader `qa/flows.mjs`/`qa/a11y.mjs` suite, multi-page documents
  beyond 2 pages, or the mobile/tablet full-screen-sheet variant.

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
- **Playwright QA**: nobody's generated a real `BRAGI_TOKENS` file
  covering every role (see `qa/flows.mjs` for the expected shape) —
  but §15 found and used a working way to get at least one real,
  legitimate token when needed: sign up a synthetic account through the
  actual `/auth/signup` endpoint (normal registration, real JWT
  returned), then seed it into `localStorage` the same way `qa/flows.mjs`'s
  own `seed()` does. That covers one role at a time (whichever the
  synthetic account was created as) — building a full `BRAGI_TOKENS`
  covering every role the same way (patient/doctor/pcp/admin/care_partner/
  emergency_worker) is mechanical from here, just not done this round.

## BRAGI SECURITY / GDPR

A full security/GDPR/privacy/data-governance hardening round. Master
document: `BRAGI_SECURITY_GDPR_PLAN.md` (repo root) — read that first;
this section is a pointer/summary, not a duplicate. Supporting
documents: `docs/security/*`, `docs/privacy/*`, `docs/vendors/*`,
`docs/ai/AI_GOVERNANCE.md`, `docs/regulatory/INTENDED_PURPOSE_DRAFT.md`,
`docs/PRODUCTION_READINESS_CHECKLIST.md` (the compact, evidence-cited
launch checklist).

**Status labeling convention introduced this round** (used consistently
across all of the above, and recommended for any future security/
compliance work in this repo): `[PASS]` (implemented AND verified with
real evidence — never code-appearance alone), `[FAIL]`,
`[IMPLEMENTED — NOT DEPLOYED]`, `[EXTERNAL ACTION]`, `[LEGAL REVIEW]`,
`[INDEPENDENT VALIDATION]`, `[NOT APPLICABLE]`, `[UNKNOWN]` (never
turned into a false `[PASS]` for uncertainty). No GDPR/HIPAA/MDR/EU-AI-
Act/ISO-27001/SOC-2 compliance or certification is claimed anywhere —
none has been externally established.

### Shipped to production this round (3 commits, all deployed and confirmed live)

- `b4ad7dc` — Python dependency CVE fixes (jose, multipart, dotenv);
  `starlette`/`pyasn1` CVEs correctly left un-upgraded (blocked by
  direct-dependency version constraints — see plan §3/§12, not forced).
- `5ceec0c` — backend hardening: security response headers, login-
  timing side-channel fix, password-length floor, 4 real account-
  deletion FK-cascade bugs found via live reproduction and fixed
  (500→200, DB-verified audit-trail preservation), `is_active`
  staleness fix in 2 doctor-facing endpoints, file-upload validation
  (extension/magic-byte/size), PHI removed from `ai_extract.py` logs,
  2 info-disclosure fixes, 20 new regression tests (IDOR, headers,
  upload validation) — all against the real dev DB, all passing.
- `7142646` — frontend CSP + security headers (`next.config.ts`,
  verified live in a real Playwright/Chromium session including the
  PDF.js source viewer — zero violations), Next.js critical CVE fix
  (16.2.4→16.3.4, `npm audit` 11→0).

Render (`dep-daheeitckfvc73bq8bug`, commit `7142646`): `live`. Vercel
(same push): `Ready`. Both confirmed 2026-09-10.

### Real, unmitigated gaps found this round (not fixed — documented, prioritized in the plan doc)

No rate limiting anywhere in the backend; no malware/AV scanning of
uploads; CNP (Romanian national ID) not comprehensively minimized
(full value in most responses, including `/patients/search` and
`/admin/patients/search`; appears in a URL query string on
`GET /emergency/search?type=cnp&q=...` specifically); no
encryption-at-rest for CNP (design-only, deliberately not migrated —
`docs/security/IDENTIFIER_ENCRYPTION_PLAN.md`); no RLS (design-only,
deliberately not enabled — `docs/security/RLS_PLAN.md` explains exactly
why blind activation would be unsafe with this app's Neon pooling/
background-job architecture); no CI at all (`.github/workflows`
doesn't exist); no data-minimization before sending document content
to OpenAI (full page image + up to 12,000 chars of OCR text) or
Reducto; no token-revocation mechanism; no self-deletion endpoint for
doctor/admin/care_partner/emergency_worker accounts (patient
self-deletion is fixed and working); a real (found via testing, not
fixed) `StaleDataError` race between account deletion and an in-flight
background upload job. Full prioritized list:
`BRAGI_SECURITY_GDPR_PLAN.md` §24 and
`docs/PRODUCTION_READINESS_CHECKLIST.md`'s "highest-priority next
steps."

### Things requiring a product decision (not silently changed)

`role` is entirely client-supplied at `/auth/signup` with no
server-side gate for `doctor`/`admin` beyond a code for `care_partner`
— could be intentional self-service onboarding or a real gap;
`/admin/patients/search` has no department/hospital scoping unlike
`/admin/doctors`. Neither was changed unilaterally — changing either
without confirming intent risks breaking the actual current onboarding/
admin workflow, which this round's own production-safety rules
prohibit doing without confirmation. See plan §5/§6.

### Testing convention this round reused/extended

Real dev DB (Neon, via `backend/.env`, gitignored), synthetic accounts
created through the real `/auth/signup` endpoint (never mocked), FastAPI
`TestClient`-based pytest tests gated with
`pytest.skip(..., allow_module_level=True)` when `DATABASE_URL` is
unset — a deliberate departure from this repo's prior unit-only
convention, added specifically for IDOR/security regression coverage
that needs real authorization checks against real rows. See
`backend/tests/test_idor_regression.py`,
`backend/tests/test_security_headers.py`,
`backend/tests/test_upload_validation.py`.

### If you continue this work

Read `BRAGI_SECURITY_GDPR_PLAN.md` in full first — it is the
authoritative, up-to-date status. Do not mark anything `[PASS]` without
the same evidence standard (a named test, a real request/response, a
real DB query) used throughout. Do not enable RLS, migrate CNP
encryption, or add rate limiting/CI without reading the corresponding
design doc first — each documents a specific reason the naive version
of that change would be unsafe for this app's actual architecture.
