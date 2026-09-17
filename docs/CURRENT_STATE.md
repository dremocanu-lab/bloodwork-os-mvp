# Bragi Health Portal — Current State

Authoritative product/engineering state as of the Phase 4
backend-modularization merge (2026-09-12). Future sessions should read
**this file**, not `CLAUDE_HANDOFF.md`, as the source of truth for what
exists today — `CLAUDE_HANDOFF.md` may remain as historical, phase-by-
phase narrative, but it accumulated some stale/superseded statements
across rounds (noted below) that this file resolves.

Verified directly for this document: **310 tests passing** (`pytest -q`,
full suite, run repeatedly throughout Phase 4), Bandit clean, migration
drift clean, frontend TypeScript/lint-baseline/production build all
clean.

## IMPLEMENTED (live in production today, unflagged)

- **Core record portal**: patient/doctor/PCP/care_partner/admin/
  emergency_worker roles, server-side authorization on every route
  (`app/policies/access.py`), IDOR regression suite
  (`tests/test_idor_regression.py`).
- **Upload pipeline**: single/batch/mixed-PDF upload, automatic
  16-type document classification, low-confidence pause-for-
  confirmation, single-file splitting into linked child documents.
- **Reducto-based extraction** (classify/split/parse/extract) — live in
  production (`REDUCTO_ENABLED=true`); legacy rule-based classifier +
  Google Document AI/OpenAI-vision extraction remains the automatic
  fallback path.
- **Structured lab results ("Analize")** with canonical name/unit/
  range/flag normalization (`app/services/lab_resolver.py`,
  `app/services/lab_catalog.py`) — resolves common aliases (e.g. "WBC"
  ↔ "White Blood Cell Count"); genuinely unresolved values are shown as
  unresolved, never guessed.
- **Clinical Readers** for 7 narrative document types (discharge,
  imaging, operative, pathology, prescription, medication-list,
  consultation) — conservative, null-not-invent extraction.
- **Longitudinal Timeline** grouped by admission, labeled with the full
  16-type taxonomy.
- **Medications list** (patient-managed), with optional RxNorm/
  DailyMed background lookup.
- **Charts/trends**, with reference-band honesty (a band only renders
  when it truly applies to every point shown) and a chart-point → exact
  source-row deep link.
- **Source provenance / "View original"**: in-app PDF viewer, per-field
  bbox highlighting where geometry exists, page+quoted-text fallback
  otherwise, full-row highlight for documents processed after the
  relevant fix.
- **Security/GDPR baseline**: security response headers + CSP,
  dependency CVE fixes, login-timing-safe comparison
  (`verify_password_timing_safe`), 8-character password floor, upload
  validation (extension allowlist + magic-byte + size cap — see
  `app/api/routers/documents.py`), CNP minimization (never in URLs,
  masked in list/search responses — `app/core/utils.py::_mask_cnp`),
  CI security pipeline (gitleaks/Bandit/Semgrep/pip-audit/npm audit),
  self-service DSAR export for patients (`POST /my/export`), account
  deletion (patient/care_partner: real row delete with a documented,
  tested FK-cascade sequence — see `app/api/routers/patients.py`;
  doctor/admin: soft-delete, login disabled, PHI-identifying fields
  irreversibly replaced).
- **Rate limiting** — in-memory backend active in production today
  (fails open); Redis-backed distributed mode is built and tested but
  not configured in production (see Deferred).
- **Alembic migration framework** — schema is Alembic-managed
  (`backend/alembic/`, `docs/database/MIGRATIONS.md`); the old
  `create_all()`/hand-written `run_migrations()` startup path is
  retired (its body is kept, uncommented-out, purely as a historical
  reference in `app/main.py` — never invoked).
- **Ask Bragi** — `ASK_BRAGI_ENABLED=true` (backend, Render) and
  `NEXT_PUBLIC_ASK_BRAGI_ENABLED=true` (frontend, Vercel) are both
  configured and verified live in production against real traffic,
  per `CLAUDE_HANDOFF.md`'s Ask Bragi Phase 4/5 entries and
  `BRAGI_ASK_BRAGI_PLAN.md`'s own header. Treated here as **implemented
  and live**, not merely feature-flagged — see the note under
  Feature-Flagged below for why some of the plan doc's own language
  suggests otherwise, and reconfirm the Render/Vercel env vars directly
  before relying on this if a long time has passed since 2026-09.
  Includes: server-owned patient-context resolution (no route/request
  body ever accepts a caller-supplied patient id directly), real SSE
  streaming with cancellation, conversation ownership + a fresh access
  recheck on every load, source-evidence-validated citations, canonical
  lab-data grounding, medication-conflict awareness.
- **FHIR interop capability-drift detection** — despite an unresolved
  "next phase" list in `BRAGI_INTEROP_PLAN.md` still naming this as
  pending, Phase 3's own shipped code (`app/services/interop/drift.py`)
  does mark an ACTIVE connection DEGRADED when its capability
  fingerprint changes on rediscovery. Real and shipped, gated by the
  same `INTEROP_FHIR_ENABLED` flag as the rest of interop (see below).

## FEATURE-FLAGGED (built, code-complete, off by default in production)

| Feature | Flag | Default |
|---|---|---|
| FHIR interop connector (Phase 1 inbound connector + Phase 3 hardening: lifecycle state machine, drift detection, incremental sync groundwork, retry/circuit-breaker, per-connection concurrency locking) | `INTEROP_FHIR_ENABLED` | **false** — confirmed off, not activated in production |
| Interop secret-at-rest encryption | `INTEROP_SECRET_ENCRYPTION_KEY` | required before any connector secret can be stored; fails closed if unset |
| Distributed rate limiting | `RATE_LIMIT_REDIS_URL` (or `REDIS_URL`) | unset in production today; in-memory fallback active instead |
| Real ClamAV malware scanning | `CLAMAV_HOST`, `CLAMAV_PORT` | unset — only the pipeline boundary + a narrow heuristic screen run today (see Known Gaps) |
| Ask Bragi cost/latency tuning | `ASK_BRAGI_MODEL`, `ASK_BRAGI_MAX_TOOL_ROUNDS`, `ASK_BRAGI_MAX_OUTPUT_TOKENS`, `ASK_BRAGI_TIMEOUT_SECONDS`, `ASK_BRAGI_HISTORY_TURNS` | `gpt-4.1` / 4 / 1200 / 45 / 6 — knobs, not an on/off gate |

## DEFERRED (deliberately scoped out or partially built, with a stated later plan)

- Real mTLS transport for FHIR connectors (certificate-reference
  architecture exists; no client-cert TLS wired).
- Background job queue for FHIR sync (currently synchronous inside the
  admin request — fine at current bounded sync sizes).
- Admin → Integrations frontend page / connection wizard for interop
  (backend API only today, 21 routes in `app/api/routers/interop.py`).
- Playwright / browser-automation coverage, both for interop
  specifically and for the product generally (`qa/flows.mjs` exists but
  is not run in CI; historically blocked on a full `BRAGI_TOKENS` file
  covering every role).
- Incremental `_lastUpdated`-based FHIR re-sync (capability-detected,
  not yet used to narrow a query).
- Bulk Data, IHE MHD/PIXm/PDQm, HL7v2, CDA, DICOMweb — all explicitly
  out of scope for the phases shipped so far.
- **CNAS integration** — explicitly not implemented; shown in any admin
  UI as "Awaiting registration." Do not implement CNAS/SIUI/SIPE/CEAS
  until the product owner has completed real CNAS registration (see
  `BRAGI_INTEROP_PLAN.md`, "Why this exists").
- Per-section `SourceEvidence` for narrative (Reader) documents — only
  a document-level fallback citation exists for these today.
- Prescription/medication_list extraction → `PatientMedication` linkage
  (currently display text only, not parsed into the medication
  system).
- Level-2 semantic duplicate-document matching (institution+date+
  accession fingerprint) — no reliable accession/specimen-ID extraction
  yet.
- Outline/section navigation, in-app document search, a "30-second
  read" summary view, and a conflicts/uncertainty surfacing UI — named
  in the original product spec, not built.
- Full theme-consistency pass on the analytics dashboard (~2,400-line
  page has some hardcoded non-theme colors; reviewed, not fixed).
- Document-organization UI restructuring to the full 16-type taxonomy
  (only the labels were updated; grouping/nav still uses the legacy
  6-bucket `section`).
- Automatic backfill of full-row PDF highlighting for documents
  processed before the relevant fix (would require re-running Reducto
  at real per-document API cost; those documents permanently keep the
  older field-only bbox behavior).
- Ask Bragi: imaging-document and two-source medication-conflict eval
  categories, and an N-sample latency benchmark — not attempted (needs
  more synthetic-document setup / OpenAI credential time than was
  available).
- `care-partner/upload/page.tsx` — the third upload-page
  implementation, not reviewed during the most recent upload-UI pass.
- Wiring the shared source viewer (`openSourceEvidence`) into Chart/
  Reader/Timeline/Documents-list views — only "Analize" uses it today;
  `AnalyticsDrilldownDrawer` needs a `lab_result_id`/`source_evidence_id`
  threaded through the analytics pipeline first.

## UNIMPLEMENTED / KNOWN GAPS

See `docs/KNOWN_GAPS.md` for the full list with detail — summarized
here: no MFA anywhere in the application; no server-side session/token
revocation (a stolen JWT is valid until natural expiry); no production
error/security monitoring (no Sentry/PostHog/equivalent); no tested
backup restoration (Neon/Render's actual backup/PITR posture is
unverified from this codebase); no independent security pentest; no
external legal/compliance review or certification (GDPR/HIPAA/MDR/
ISO-27001/SOC-2 controller-vs-processor role is explicitly
`[LEGAL REVIEW]`, unsettled); no real antivirus engine connected
(`CLAMAV_HOST`/`PORT` ready but unset); uploaded files live on local
disk on the Render instance, not in a durable/versioned object store;
no encryption-at-rest for CNP (design doc only); no Postgres
Row-Level Security (design doc only, deliberately not enabled given
Neon's pooling/background-job architecture); no DSAR export for
non-patient roles; several explicit `[LEGAL REVIEW]`/`[PRODUCT
DECISION]` items never silently resolved (doctor/admin erasure depth,
`emergency_worker` self-deletion, client-supplied `role` at signup,
`/admin/patients/search` scoping).

## A note on doc staleness found while compiling this file

Two statements elsewhere in the repo are superseded and should not be
trusted over this file:

1. `BRAGI_ASK_BRAGI_PLAN.md`'s "Remaining limitations" section still
   says "No real SSE streaming (V1 is synchronous)" — this is stale;
   the same document's own later Phase 5 section, and
   `CLAUDE_HANDOFF.md`, both confirm real SSE streaming was built and
   verified live. Ask Bragi streaming is implemented.
2. `CLAUDE_HANDOFF.md`'s "Manual configuration/authentication
   required" section (written mid-way through the Reducto rounds)
   predates the later, separately-documented fact that
   `ASK_BRAGI_ENABLED`/`OPENAI_API_KEY`/
   `NEXT_PUBLIC_ASK_BRAGI_ENABLED` were subsequently configured in
   Render/Vercel (Ask Bragi Phase 5) — that action item is done, the
   section was just never rewritten.

## Clinical Document Intelligence V3 — PARTIAL (Phases 0-10 of 21)

Branch `fix/clinical-document-intelligence-v3`. A real, verified fix for
the Ask Bragi P0 bug ("Ask Bragi could not process this message") is
done: `ASK_BRAGI_MAX_TOOL_ROUNDS` (4) was too tight for broad multi-
analyte questions like "what changed in my latest bloodwork" — fixed via
prompt guidance + raising the budget to 8, both proven with tests that
fail under the old default and pass under the new one. A RightWorkspace
geometry Playwright regression was also added (Phase 2). Phases 3-5
built a real, tested structured-document pipeline: a typed, versioned
`StructuredClinicalDocument` schema; deterministic source segmentation
and canonical-section consolidation; deterministic Clinical Course
dated-event extraction with chronology/plausibility checks; and a full
end-to-end orchestration (`discharge_parser.py`), all proven against the
contract's own required suspicious-data fixtures. Phase 6 added embedded
lab extraction from a discharge's laboratory_results section into REAL,
canonical `LabResult` rows — feeding the existing
`lab_resolver.resolve_analyte()`, never a private alias dictionary or a
second lab datastore — plus one derived "lab_report" `Document` artifact
per coherent source report, with real deletion-cascade and idempotency
guarantees, DB-proven with 44 new tests. Phase 7 added medication
extraction/context classification from a discharge's medication-bearing
sections into REAL, canonical `PatientMedication` rows — feeding the
existing status vocabulary, never a second medication table — with
deterministic Romanian/English duration parsing, real calendar-month
end-date derivation, an exact 4-tier start-date priority that never uses
an upload/ingestion timestamp, and explicit preservation of same-drug
conflicts and explicit-vs-derived date disagreements, DB-proven with 81
new tests. **Phase 8 (NEW) rebuilt the discharge/clinical-document
reader** around the canonical `StructuredClinicalDocument` contract: a
new `GET /documents/{id}/clinical-reader` API, a rewritten reader page,
and 7 new reusable frontend components (a canonical section outline,
ONE `StructuredLabReport` component for both embedded and standalone
use, a Clinical Course chronological event timeline that never
"corrects" a suspicious source date, honest PDF/non-PDF provenance
reusing the existing source-viewer system, and derived-vs-explicit
medication end-date UX with honest conflict presentation) — proven with
17 new backend tests and 6 new real-browser Playwright tests against a
synthetic discharge fixture, and confirmed to render BOTH an old legacy
discharge document and a real forward-parsed one through the exact same
contract. **None of Phases 3-8's EXTRACTION/PERSISTENCE code is wired
into the live discharge upload write path yet — deliberate, not an
oversight (a brand-new upload today still renders correctly through
Phase 8's reader, just without labs/medications attached yet, since
nothing has extracted them for it; see the handoff's sequencing note
and Phase 8's own detailed reasoning for keeping this deferred).
**Phase 9 (NEW) made a derived "lab_report" `Document` a real,
independently openable Documents entry**: a new standalone
`/documents/{id}/lab-report` route renders `StructuredLabReport(mode=
"standalone")` — reused verbatim from Phase 8, never duplicated —
against the SAME canonical `LabResult` rows Phase 6 created, never a
copy; Documents/patient-profile cards show a restrained "Derived from:
[parent]" line (no badge, no alarming styling); direct deletion of a
derived artifact is now rejected (still removable only via its
parent's cascade); a genuine Phase-6 gap (the derived artifact's own
`lab_result_ids` pointer was declared but never populated) was
completed to make all of this possible — proven with 15 new backend
tests and 8 new real-browser Playwright tests. **Phase 10 (NEW) made
canonical medication state changes appear on the patient's Timeline** as
real, idempotent `PatientEvent` projections: a new `timeline_
projection.py` service reads already-canonical `PatientMedication` rows
and projects "medication started"/"medication completed" events (never
inventing a date, never asserting a state change a conflicting row can't
support, never duplicating on reprocessing), coexisting with manually-
created hospitalization events on the SAME table — no second Timeline
system. A deliberate architecture decision: a clinical document/derived
lab artifact is NOT separately projected, since it already appeared on
the Timeline via the pre-existing client-side document/event fusion —
Phase 10 fixed that mechanism's derived-artifact title instead of
building a redundant path, and along the way found and fixed a real bug
that would have made a projected medication event corrupt the existing
admission-grouping logic across four frontend files — proven with 15 new
backend tests and 7 new real-browser Playwright tests. **A post-Phase-10
integration-correction pass (NEW)** fixed real bugs real manual QA
found: 5 duplicated frontend document-routing decisions consolidated
into one shared resolver (`lib/document-routing.ts`) — checking
`document_type` alongside the legacy `section`/`report_type` signals,
never replacing them — plus a real gap where both Timeline pages had no
derived-artifact check at all; a real Ask Bragi bug where the discharge
reader passed a document id as `patientId` for doctors; and two real UI
bugs (an upload-page width cap, a misaligned processing-indicator dot).
Deliberately NOT attempted: an exact word-level source-highlighting
engine (found to require genuinely new provenance engineering, not a
small fix) and Phase 11 in its entirety. **A subsequent pre-Phase-11
exact-provenance session (NEW) fixed the real coarse-highlight root
cause**: `_union_row_bbox()`'s fixed-ratio padding was bleeding a lab
row's highlight into a neighboring row on a dense table (e.g. NEUT#
covering PCT/NRBC#) — Reducto's own per-field citations were already
precise, so the fix persists and renders those real, unpadded per-field
rects (new additive `SourceEvidence.field_bboxes_json` column) instead
of tuning the padding formula, proven with a dedicated adjacent-row
fixture. A real select-text-to-"Show in original" interaction now also
exists for lab/medication rows (same shared `openSourceEvidence`
engine, a new small contextual menu on text selection), proven with 13
new backend tests and 7 new Playwright tests. Arbitrary narrative-text
(Clinical Course paragraphs etc.) exact highlighting remains
unimplemented — confirmed to require enabling citations on Reducto's
reader-section extraction (currently `citations=False`) plus new
segment-level page/offset persistence, a genuinely larger upstream gap,
not attempted. **A subsequent Romanian discharge classification closure
session (NEW) fixed a real, reproduced classification bug**: a genuine
inpatient discharge letter titled "BILET DE IEȘIRE DIN SPITAL /
SCRISOARE MEDICALĂ" — a title the legacy classifier had zero keyword
coverage for (only "bilet de externare" existed) — combined with a
realistic dense embedded lab table, scored a near-tie between
discharge_summary and laboratory_results, forcing an unnecessary
confirmation prompt on an otherwise-clear discharge letter. Fixed by
adding the missing keywords (verified: discharge margin went from 0.5
to 5.5) and by naming the same Romanian titles explicitly in Reducto's
own classification criteria (not independently live-verified against
the real API this session — no safe synthetic-PDF fixture process
exists yet). Also closed a real, previously-deferred gap where a
doctor/care-partner manual "Discharge Summary" section pick never set
`document_type` at all. A new, genuinely end-to-end test suite (real
Romanian text → real classifier → real persisted Document → real Phase
8 reader in the browser) closes the exact "routing was tested,
classification never was" boundary the prior routing-consolidation pass
left open. **A subsequent P0 AI document classification + upload
reliability session (NEW) first audited deployment parity**: found real
manual QA cannot be proven to have exercised this branch at all — `main`
is 61 commits/5 days stale, is the only branch this repo documents as
auto-deploying, and a leftover local worktree with no env config would
silently hit the real production backend with 3-month-stale frontend
code. Added a permanent fix: `GET /health/version` (git_sha +
environment) plus a frontend build-SHA display, so this is never again
unanswerable. Then replaced brittle keyword-only auto-classification
with a real AI semantic classifier (`ai_document_classifier.py` +
`document_classification_service.py`) constrained to the existing
`DocumentType` taxonomy, using the same OpenAI structured-output pattern
already proven in Ask Bragi — AI is the primary auto-classifier when it
succeeds confidently; Reducto/legacy remain real pre-signals and the
fallback on any AI failure, never a failed upload. Also found and fixed
the real, confirmed cause of "upload remained processing": the
backend's security-scan quarantine status (`security_quarantined`) had
no frontend mapping at all and fell through to "queued" (active)
forever — proven both ways (fails without the fix, passes with it). The
processing-dot geometry was investigated with real pixel measurement
(not inspection alone): the current code already centers the dot within
a fraction of a pixel of the text's visual center — the reported "still
too high" symptom most likely reflects the same stale-deployment risk
found above, not a remaining rendering bug; a real, defensible CSS
improvement (a testable DOM dot, corrected line-height) was made anyway.
Phases 11-21 of the originating contract (Ask-Bragi
retrieval hardening and everything downstream) are entirely
unimplemented** — see
`docs/handoffs/CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md` for the
full, section-by-section honest accounting and how to continue.

## Phase 4 (backend modularization) — this document's own origin

`app/main.py` went from an 8,141-line MVP-era monolith to a 2,017-line
file containing app construction, middleware, router registration, and
a deliberately-retained set of cross-cutting helper functions (see
`docs/ARCHITECTURE.md`). All 117 routes now live in 14 domain router
modules under `app/api/routers/`. This was a strict, verified
behavior-preserving refactor — see `docs/refactor/
OPENAPI_EQUIVALENCE_REPORT.md` for the zero-unexplained-differences
proof. No product behavior, database schema, or authorization semantics
changed as part of this work.
