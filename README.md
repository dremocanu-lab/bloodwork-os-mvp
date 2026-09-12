# Bragi Health Portal

Bragi is a longitudinal medical-record platform. Patients upload their
medical documents — lab reports, discharge summaries, imaging reports,
prescriptions, and more — and Bragi organizes them into structured,
searchable patient data while keeping every original document and every
extracted fact traceable back to its source.

Doctors, primary-care physicians, care partners, administrators, and
emergency responders each get a role-appropriate, authorization-scoped
view of that record. The original uploaded document always remains the
authoritative source; structured data is a derived, verifiable layer on
top of it, not a replacement for it.

**Ask Bragi — a source-grounded AI conversation over a patient's own
record, with real streaming responses — is implemented and live.** See
[Ask Bragi](#ask-bragi) below for how it works and what it reuses from
the rest of Bragi rather than duplicating.

---

## The product loop

```
UPLOAD → CLASSIFY → STRUCTURE → ORGANIZE → READ → CONNECT → VISUALIZE → VERIFY SOURCE
```

A document is uploaded once. Bragi classifies what it is, extracts its
structure, organizes it into the patient's longitudinal record, presents
it through a purpose-built reader, connects related facts (a trend, a
timeline, a medication), visualizes it where useful (charts), and — at
any point — lets you jump back to the exact original document, page, and
region a fact came from. Structured data always stays traceable to
source evidence when that provenance exists; see
[Source verification](#source-verification-view-in-original) for what
"when it exists" means in practice.

---

## What Bragi currently does

- **Upload** — single or multi-file upload, both direct (patient/doctor
  choosing a category) and automatic (drop everything in, Bragi figures
  out what each file is).
- **Automatic document classification** — each upload is classified into
  one of 16 document types (lab results, discharge summary, imaging
  report, operative report, pathology report, prescription, medication
  list, specialist consultation, ED note, admission note, procedure
  report, referral, vaccination record, medical certificate,
  insurance/administrative, other). Low-confidence classifications pause
  for human confirmation rather than guessing.
- **Mixed-PDF splitting** — a single uploaded file containing multiple
  logical documents (e.g. a lab table followed by an imaging report) is
  detected and split into separate documents, each linked back to the
  original file and its real page range.
- **Structured lab results ("Analize")** — bloodwork and other lab
  panels are parsed into canonical, chartable rows (raw provider term +
  resolved canonical name + value/unit/reference range/flag), not just
  stored as text.
- **Longitudinal Timeline** — documents and clinical events are grouped
  by admission/episode and labeled by their actual document type, not
  just a coarse category.
- **Clinical Readers** — discharge summaries, imaging, operative,
  pathology, prescription, medication-list, and consultation documents
  each get a structured, source-grounded reader view (conservative
  extraction — nulls rather than invents when a field isn't present).
- **Medications** — a patient-managed medication list with optional
  official drug-information lookup (RxNorm/DailyMed).
- **Charts and trends** — lab values over time, with reference bands
  that only render when they're honestly applicable to every point shown
  (see [Reducto's role](#reducto), no single stale reference range
  painted across a chart that spans different assays/dates).
- **Source provenance and "View in original"** — every structured lab
  value can be traced back to the exact page and region of the original
  document it came from (see
  [Source verification](#source-verification-view-in-original)).
- **Romanian and international documents** — built and tested against
  real Romanian medical-document formats (decimal-comma values, RO/EN
  bilingual labels) alongside general/private lab formats.
- **Ask Bragi** — a source-grounded AI conversation over a patient's
  own record, for both patients and their authorized clinicians, with
  real streaming responses, persistent conversation history, and every
  answer traceable back to a real source — see [Ask Bragi](#ask-bragi).
- **Role-based access** — patient, doctor (including a dedicated
  PCP/family-doctor workspace), care partner, admin, and emergency
  (break-glass) roles, each authorized and audited server-side (see
  [Roles](#roles)).
- **Reducto-based ingestion** with a legacy fallback path (see
  [Reducto's role](#reducto)).

---

## Architecture

```
┌──────────────────────┐      ┌──────────────────────┐      ┌────────────────────┐
│  Frontend             │      │  Backend              │      │  Database           │
│  Next.js (App Router) │◄────►│  FastAPI + SQLAlchemy │◄────►│  PostgreSQL (Neon)  │
│  React                │      │                       │      └────────────────────┘
│  ECharts (trends)     │      │  Document processing: │
│  PDF.js (source       │      │   - Reducto (primary) │      ┌────────────────────┐
│  viewer)              │      │   - legacy fallback   │◄────►│  Reducto            │
└──────────────────────┘      │   - Google Document AI│      │  (classify/split/   │
                                │     (OCR support)     │      │   parse/extract)    │
                                │   - OpenAI (vision     │      └────────────────────┘
                                │     extraction where   │
                                │     used, see below)   │      ┌────────────────────┐
                                └──────────────────────┘      │  OpenAI / Google     │
                                                                │  Document AI         │
                                                                └────────────────────┘
```

- **Frontend**: Next.js (App Router), React, ECharts for trend charts,
  PDF.js for the in-app source viewer. A persistent navigation sidebar
  (desktop/tablet) frames an independently-scrolling main workspace; a
  contextual right-hand workspace hosts the source viewer and/or Ask
  Bragi side by side with the structured page, never as an overlay.
- **Backend**: FastAPI, SQLAlchemy, JWT bearer-token auth.
- **Database**: PostgreSQL, hosted on Neon.
- **Document processing**: Reducto for classification/splitting/parsing/
  extraction (see [Reducto's role](#reducto)); a legacy rule-based
  classifier + Google Document AI/OpenAI vision extraction as a fallback
  path when Reducto is disabled or a call fails.
- **Deployment**: Vercel (frontend), Render (backend), Neon (database).
  `main` auto-deploys to both — see [Deployment](#deployment).

No secrets, service IDs, or private infrastructure details are included
here or anywhere in this repository's tracked history (see
[Security & privacy](#security--privacy)).

---

## Data flow

```
Upload
  │
  ▼
Upload validation / security-scan boundary
  (extension + magic-byte + size check, then a
   security_scan step — see docs/security/MALWARE_SCANNING_PLAN.md)
  │
  ▼
Document classification (Reducto, or legacy fallback)
  │
  ▼
Split, if the file contains multiple logical documents
  │
  ▼
Parse / Extract (structured content + source geometry)
  │
  ▼
Patient identity matching (does this document belong to this patient?)
  │
  ▼
Duplicate handling (exact-file and exact-observation dedup)
  │
  ▼
Bragi normalization (canonical lab names, units, structured sections)
  │
  ▼
Document / LabResult / SourceEvidence (+ PatientEvent, PatientMedication)
  │
  ▼
Timeline / Analize / Clinical Readers / charts
  │
  ▼
"View in original" — jump back to the exact source page/region
```

A document that fails identity matching is quarantined (never silently
attached to the wrong patient, never silently discarded) and held for
review. A document flagged by the security-scan boundary as explicitly
malicious never reaches classification/extraction at all.

---

## Reducto

[Reducto](https://reducto.ai) is Bragi's document-reading provider. It
performs:

- **Classify** — what kind of document is this (one of the 16 types)?
- **Split** — does this one upload actually contain multiple logical
  documents?
- **Parse** — page/region-tagged structured blocks (tables, headers, key
  values) from the document.
- **Extract** — structured fields (lab rows, narrative report sections,
  identity fields) with per-field source geometry and confidence.

**Reducto is not Bragi's clinical reasoning layer.** It reads documents;
Bragi decides what that reading means for a patient's record. Bragi
retains, independently of Reducto:

- canonical lab-name/value normalization (raw provider term → resolved
  clinical concept, OCR-confusion-aware, conservative — see
  [Lab normalization](#lab-normalization));
- patient identity matching and duplicate detection;
- authorization (who can see this document/fact);
- provenance linkage (`SourceEvidence` — which structured fact came from
  which page/region of which document);
- the entire user experience (Timeline, Readers, charts, source viewer).

A legacy rule-based classifier and a Google Document AI/OpenAI
vision-extraction path exist as a fallback: if Reducto is disabled, or a
Reducto call fails for any document, that document falls back to the
legacy path rather than failing the upload. OpenAI is also used directly
for discharge-summary extraction in its own dedicated pipeline. See
`BRAGI_REDUCTO_PLAN.md` for the full integration history and exactly
what has and hasn't been verified against the live Reducto API.

---

## Source verification (`View in original`)

Provenance is a first-class feature, not an afterthought:

```
Structured fact (e.g. a lab value)
  │
  ▼
SourceEvidence row
  (which document, which page, which region — when known)
  │
  ▼
Original document (the actual uploaded file, unmodified)
  │
  ▼
In-app source viewer (PDF.js)
  (page navigation, region highlighting, split-view alongside the
   structured reading)
```

`View in original` opens the actual source file authorization-checked
the same way every other document access is — a care partner or an
unrelated patient can't reach a document through this path any more than
through any other. Where per-field page/region coordinates exist, the
viewer highlights the exact region a value came from; where they don't
(older documents, or a document type without per-field geometry yet),
the viewer still opens the right page with the extracted text quoted, a
verifiable but coarser fallback.

**Honest limitation**: not every historical document has row-level
bounding-box geometry — that capability was added after some documents
were already processed, and there is no automatic backfill (re-running
an old document through extraction again would cost real API spend per
document). Newer uploads get full per-field/per-row geometry; older ones
fall back to page + quoted source text.

Precision is reported honestly at whichever level actually exists —
`exact_bbox` (page + highlighted region) down through `page_only` and
`document_only` — and a coarser level is never presented as if it were
exact. Ask Bragi's own citations and chart points open through this
exact same viewer rather than a second one: a citation resolves to a
real `SourceEvidence` row, and a lab-trend chart point carries the same
row identity a table's own "View in original" action uses, so both land
on the same page/region (or the same honest fallback) a person clicking
the underlying data directly would see.

---

## Lab normalization

```
Raw provider term (as written on the source document)
  │
  ▼
Bragi resolver (exact/alias match, then a conservative
  OCR-confusion-aware fuzzy match as a last resort)
  │
  ▼
Canonical clinical concept (name, category, unit)
```

The raw term as it appeared on the source document is always preserved
alongside the resolved canonical name — normalization never overwrites
what the document actually said. Aliases and RO/EN language variants are
resolved first; a narrow, calibrated fuzzy-matching step handles
single-glyph OCR misreads (e.g. a visually similar character
substitution) only when nothing else matches, and only above a
confidence floor. When nothing resolves confidently, the term is left
**unresolved** rather than guessed — a wrong clinical guess is worse than
an honestly-unresolved term. See `BRAGI_REDUCTO_PLAN.md` §11/§12 for the
detailed engineering history of this design if you need it; that level
of detail deliberately doesn't belong here.

---

## Roles

| Role | What they can do |
|---|---|
| **Patient** | Upload documents, view their own record (Timeline, Analize, Readers, charts), manage medications, control who else can see their record, opt in/out of emergency discoverability, export their own data, delete their own account |
| **Doctor** | View records for patients who've granted them access (or who they're assigned), request access, add clinical notes/events |
| **PCP / family doctor** | Same as doctor, plus a dedicated multi-patient PCP workspace |
| **Care partner** | View structured lab pages a patient has explicitly shared with them — no general record access |
| **Admin** | User/assignment management, document identity-review, patient/doctor search |
| **Emergency (break-glass)** | Time-limited, reason-logged access to patients who've opted into emergency discoverability, in a dedicated emergency workspace — every search and every access is audited |

Every role's access is enforced server-side (not just hidden in the UI)
and is covered by an authorization regression suite — see
[Testing](#testing).

---

## Local development

### Prerequisites

- Python (this project runs on 3.13 in CI and development; check
  `backend/requirements.txt` for exact pinned dependency versions)
- Node.js (this project runs on Node 22 in CI; see `frontend/package.json`
  for exact dependency versions, including Next.js 16 and React 19)
- A PostgreSQL database (local, or a Neon branch)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # includes requirements.txt + pytest
cp .env.example .env          # fill in real values, never commit this file
alembic upgrade head          # provisions the schema — see docs/database/MIGRATIONS.md
uvicorn app.main:app --reload
```

Schema is managed by Alembic (`backend/alembic/`), not created
automatically at startup — see `docs/database/MIGRATIONS.md` for a brand-
new database, bootstrapping an existing one, writing a new migration, and
the rollback policy.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local    # fill in real values
npm run dev
```

---

## Environment variables

Variable **names** only — see `backend/.env.example`/`frontend/.env.example`
for the current template files, and never commit real values. Production
credentials must always differ from development ones. Backend secrets
must never be prefixed `NEXT_PUBLIC_*` (that prefix ships the value to
the browser).

**Core**
- `DATABASE_URL`, `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
  `ENVIRONMENT` (`development` relaxes the `SECRET_KEY` strength check —
  never set this in production), `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_MB`,
  `FRONTEND_ORIGINS` (extra allowed CORS origins beyond the built-in
  production ones)
- Frontend: `NEXT_PUBLIC_API_URL`

**Reducto**
- `REDUCTO_API_KEY` (backend-only, never exposed to the frontend),
  `REDUCTO_ENABLED`, `DOCUMENT_EXTRACTION_PROVIDER`,
  `DOCUMENT_EXTRACTION_FALLBACK`

**OpenAI / Google Document AI**
- `OPENAI_API_KEY`, plus a set of model/tuning overrides for the
  discharge-summary and structured-reader extraction paths (see
  `app/main.py` and `app/services/*.py` for the full list — not
  reproduced here since most deployments never need to touch them)
- `GOOGLE_APPLICATION_CREDENTIALS` (or `_JSON`), `GOOGLE_CLOUD_PROJECT_ID`,
  `GOOGLE_DOCUMENT_AI_LOCATION`, `GOOGLE_DOCUMENT_AI_PROCESSOR_ID`

**Rate limiting** (see `docs/security/RATE_LIMITING.md`)
- `RATE_LIMIT_REDIS_URL` (or `REDIS_URL`) — activates the distributed
  backend; unset means a per-instance in-memory fallback
- `RATE_LIMIT_DISABLED` — kill switch

**Malware-scan pipeline** (see `docs/security/MALWARE_SCANNING_PLAN.md`)
- `CLAMAV_HOST`, `CLAMAV_PORT` — activates real ClamAV scanning; unset
  means a narrow heuristic structural screen only, never described as
  full malware scanning

**Interoperability** (see `BRAGI_INTEROP_PLAN.md`; not enabled in
production)
- `INTEROP_FHIR_ENABLED` — whole-feature kill switch for the FHIR
  connector and all `/admin/interop/*` routes, default false
- `INTEROP_SECRET_ENCRYPTION_KEY` — required before any connector secret
  (bearer token, OAuth client secret, SMART private key) can be stored;
  fails closed rather than storing plaintext if unset

---

## Deployment

- **Frontend** → Vercel
- **Backend** → Render
- **Database** → Neon (PostgreSQL)

`main` auto-deploys to both Render and Vercel on push. Because of this,
every commit to `main` is expected to be independently production-safe —
additive, backward-compatible, and not dependent on a manual coordinated
step unless explicitly documented. Database schema changes are Alembic
migrations (`backend/alembic/`, see `docs/database/MIGRATIONS.md`),
applied via `python scripts/run_migrations.py` — ideally as a Render
pre-deploy step (**[EXTERNAL ACTION]** — this requires a one-time Render
dashboard configuration change this repository cannot make on its own;
see that doc's "Production deployment" section) so schema is ready
before the new code that expects it starts serving traffic.

---

## Testing

**Backend** (`cd backend && pytest`): unit tests plus a real-DB security
and correctness regression suite — cross-patient/cross-role
authorization (IDOR), CNP/identifier minimization, upload validation,
malware-scan quarantine, DSAR export, account-deletion completeness,
rate limiting, and AI-provider data-minimization. Ask Bragi has its own
dedicated suites: conversation/tool authorization and cross-patient
isolation, prompt-injection resistance, citation validation, and the
streaming endpoint (mocked-model tests against the real route/DB/auth,
including that a stopped generation is never persisted). DB-dependent
tests skip gracefully (not silently pass) when `DATABASE_URL` isn't
set.

**Frontend**: `npx tsc --noEmit` (typecheck), `npx eslint .` (lint),
`npm run build` (a real production build, not just a typecheck). A
Playwright-based visual/interaction QA suite exists under `frontend/qa/`
but is a manual/ad-hoc tool today, not part of the automated CI
pipeline.

**Security-specific**: full git-history secret scanning (gitleaks),
Python/JS static analysis (Bandit, Semgrep) and dependency scanning
(`pip-audit`, `npm audit`).

---

## CI

`.github/workflows/`:

- **`ci.yml`** — every push/PR to `main`: backend tests against a real
  ephemeral Postgres service container provisioned via `alembic upgrade
  head` (proving a brand-new database builds from migration history
  alone — see `docs/database/MIGRATIONS.md`) plus a migration drift check,
  Bandit, frontend typecheck/lint (a real regression gate against a
  frozen pre-existing-error baseline, see `frontend/.eslint-baseline.json`)/
  production build, and a full git-history secret scan.
- **`nightly-security.yml`** — daily + manual dispatch: dependency
  vulnerability scanning (`pip-audit`, `npm audit`) and a broader
  Semgrep ruleset — kept off the fast per-push path since they depend on
  live external advisory-database lookups.

No production secrets are used in either workflow; every third-party
GitHub Action is pinned to a full commit SHA.

---

## Security & privacy

Bragi includes privacy- and security-by-design controls and maintains
dedicated security/GDPR engineering documentation, kept current as an
evidence-based (not aspirational) status record. Implemented and
verified controls include:

- Server-side, role-aware authorization on every route, with a
  dedicated cross-patient/cross-role regression suite.
- Direct-identifier (CNP) minimization — removed from URLs, masked in
  list/search responses, full value only where a workflow genuinely
  needs it.
- Private, authorization-checked source-document/evidence retrieval.
- Ask Bragi: server-owned patient context on every conversation/tool
  call (never a client-suppliable patient/document id), AI-provider
  data minimization before anything reaches OpenAI, server-validated
  citations and chart data (never trusted from the model as-is), and a
  live-verified prompt-injection test (a document instructing the model
  to ignore its role was retrieved and ignored).
- Upload validation (extension/magic-byte/size) plus a security-scan
  pipeline boundary — a file explicitly identified as malicious cannot
  reach clinical processing.
- Rate limiting on abuse-sensitive endpoints (login, signup, uploads,
  source retrieval, emergency access, exports), with a real distributed
  backend available behind configuration.
- Full git-history secret scanning, static analysis, and dependency
  scanning, wired into CI.
- Audit logging for document access, emergency-worker searches/sessions,
  and DSAR data exports.
- A self-service data export (DSAR/GDPR Art. 15/20) and account
  deletion, with deliberately different deletion semantics per role
  (see `docs/privacy/DSAR_RUNBOOK.md`).
- Separation between development and production credentials/environments.

**Bragi is not certified or claimed compliant with GDPR, HIPAA, MDR, the
EU AI Act, ISO 27001, or SOC 2.** Formal legal, vendor-contractual, and
independent (third-party) validation are tracked separately from
technical implementation and remain open — see:

- `BRAGI_SECURITY_GDPR_PLAN.md` — the full engineering status record
- `docs/PRODUCTION_READINESS_CHECKLIST.md` — the compact, evidence-cited
  checklist form of the above
- `docs/EXTERNAL_COMPLIANCE_ACTIONS.md` — everything that requires a
  vendor, a legal determination, or a product decision outside
  engineering (a real antivirus engine, a distributed rate-limit backend
  in production, vendor DPA/retention terms, and more)
- `docs/security/`, `docs/privacy/` — the detailed supporting documents
  each of the above links into

---

## Project structure

```
backend/
  app/
    main.py              — routes, authorization
    models.py             — SQLAlchemy models
    services/             — Reducto client/extraction, document pipeline,
                             lab resolver, security scan, rate limiting,
                             AI-provider minimization, medication lookup,
                             interop/ (FHIR connector — see BRAGI_INTEROP_PLAN.md)
  alembic/                 — schema migrations (see docs/database/MIGRATIONS.md)
  scripts/                 — run_migrations.py (deploy), bootstrap_alembic.py
                             (one-time existing-DB stamping), check_migration_drift.py (CI)
  tests/                   — unit + real-DB regression suite

frontend/
  app/                     — Next.js App Router routes (per role/feature)
  components/              — shared UI (timeline, upload, source viewer, ...)
  lib/                      — API client, i18n, chart theme, taxonomy labels
  qa/                       — manual/ad-hoc Playwright QA scripts

docs/
  database/                — migration framework (docs/database/MIGRATIONS.md)
  security/                — threat model, auth matrix, rate limiting,
                              malware scanning, CI pipeline, static analysis,
                              secret-scan history, and more
  privacy/                  — data map, DSAR runbook, retention policy,
                              vendor/transfer registers, DPIA/ROPA drafts
  vendors/                  — Reducto/OpenAI production-requirements docs
  ai/                       — AI governance for Ask Bragi
  regulatory/               — MDR/EU AI Act boundary statement
```

---

## Engineering documentation index

| Document | What it's for |
|---|---|
| `CLAUDE_HANDOFF.md` | Rolling status log across every development round — read this for "what happened and when," not the README |
| `BRAGI_REDUCTO_PLAN.md` | The architecture/phase reference for document ingestion, classification, extraction, and source verification |
| `BRAGI_INTEROP_PLAN.md` | Standards-based interoperability (FHIR/HL7/CDA/DICOMweb/IHE partner connectivity) — scope, phasing, and Phase 1 (FHIR connector) status. Feature-flagged off (`INTEROP_FHIR_ENABLED`) |
| `BRAGI_SECURITY_GDPR_PLAN.md` | The authoritative, evidence-cited security/privacy engineering status record |
| `docs/PRODUCTION_READINESS_CHECKLIST.md` | The compact checklist form of the security/GDPR plan |
| `docs/EXTERNAL_COMPLIANCE_ACTIONS.md` | Everything outside engineering's control — vendor, legal, product decisions |
| `docs/security/*`, `docs/privacy/*`, `docs/vendors/*` | Detailed supporting documents for each security/privacy topic |

---

## Current status

**Implemented**: the core record portal; role-based auth and
authorization; multi-file/mixed-PDF upload pipeline; Reducto-based
classification/split/parse/extract with a legacy fallback; structured
lab results and normalization; Clinical Readers for 7 document types;
longitudinal Timeline; medications; trend charts; source
provenance/`View in original`; the security/GDPR hardening round
(rate limiting, malware-scan boundary, CNP minimization, DSAR export,
deletion completeness, CI security pipeline, secret/dependency
scanning — see [Security & privacy](#security--privacy)); Ask Bragi
(see below) — **live in production**, with real streaming responses,
Stop/cancellation, and persistent conversation history for both
patients and clinicians, verified directly against production.

**Next**: the imaging/medication-conflict eval categories and a
proper large-sample latency benchmark for Ask Bragi (the reverse-
language case is done); remaining UX/QA polish (a full Playwright QA
pass, per-section source evidence for Reader sections, prescription→
medication linkage, and other items tracked in `BRAGI_REDUCTO_PLAN.md`'s
per-phase "deferred" notes); production/vendor/legal closure and
independent security validation (see
`docs/EXTERNAL_COMPLIANCE_ACTIONS.md`).

---

## Ask Bragi

Ask Bragi is a source-grounded AI conversation over a patient's own
longitudinal record — for the patient themselves, and separately for
their authorized clinicians about one patient at a time. **Live in
production**, not a design document: `ASK_BRAGI_ENABLED` and a real
`OPENAI_API_KEY` are configured on the Render backend, and
`NEXT_PUBLIC_ASK_BRAGI_ENABLED=true` in Vercel — confirmed by a real
synthetic-account round trip and real streaming/stop/conversation-
history/reverse-language verification directly against production, not
assumed from configuration alone.

It reuses Bragi's existing controls end to end rather than introducing
a parallel system:

```
authenticated user (patient, or a clinician authorized for one patient)
  │
  ▼
server-owned patient context — resolved from the session server-side;
  no tool accepts a caller-supplied patient or document id
  │
  ▼
restricted, authorized Bragi tools (labs, medications, timeline,
  documents — each call independently re-checks authorization)
  │
  ▼
OpenAI Responses API — real function/tool calling; the model requests
  data and requests a chart's intent, never raw database access
  │
  ▼
the same canonical patient record every other Bragi screen reads
  (Analize, Timeline, Readers) — not a separate copy
  │
  ▼
SourceEvidence — citations are validated against what the tools
  actually returned this conversation; chart datapoints are always
  server-resolved from real observations, never model-generated
  │
  ▼
a validated response (answer + citations + chart) — nothing reaches
  the browser until the server has checked it
  │
  ▼
the existing in-app source viewer (openSourceEvidence) — the same
  viewer every "View in original" action already uses, not a second one
```

**Streaming.** Responses stream progressively (a real OpenAI Responses
API stream, not a delayed single reply), with a distinct visual status
while a tool call is in progress — never the model's raw reasoning or
tool output, only the answer itself as it's written. The composer
stays editable the entire time — a user can keep typing while Bragi is
thinking or writing, and a draft survives the response completing. A
Stop control cancels generation for real: the backend detects the
client disconnecting and closes the provider stream from its side
rather than continuing to generate unread, and a stopped answer is
never persisted.

**Conversation history.** Patients see their own past conversations,
can continue any of them, or start a new one. Clinicians see history
scoped to the one patient they're currently viewing — never mixed
across patients — alongside a compact, always-visible "Asking about
[patient]" indicator, and switching to a different patient safely
resets to that patient's own history.

**Scope.** A conversation opened from a specific document defaults to
that document; Analize/Timeline/Overview default to the whole record.
Scope is server-authoritative, not a client-side setting the model can
override: a document-scoped conversation can widen for one turn via an
explicit control or server-side detection of phrases implying a
longitudinal question ("over time," "has this happened before"), never
the model's own unconstrained judgment — and any such broadening is
always shown in the conversation, never silent. This is what makes
longitudinal questions ("has my hemoglobin always been in range?")
work safely from inside a single-document conversation without quietly
exposing the rest of the record.

**Charts.** The model can request a chart's *intent* (which analyte,
what date range) — it never supplies the numbers. Bragi's backend
resolves the actual datapoints from real stored observations and
renders them with the same expanded trend view Analize/Overview
already use for a single analyte: real date/value axes, a reference
band shown only when it honestly applies to every point plotted,
a hover/tap/keyboard readout per point (value, unit, date, reference
range, abnormal flag — never colour alone), and a click-through to that
point's real source. Incompatible units are never silently combined
onto one axis.

**Security posture**, all reused rather than reinvented for this
feature: every tool call is independently re-authorized against the
same server-owned patient context (see [Roles](#roles)); the AI-
provider data-minimization boundary in `app/services/ai_minimization.py`
governs what leaves the server; conversations and messages are
authorization-checked the same way any other patient record data is,
included in the existing DSAR export and account-deletion paths; a
real adversarial prompt-injection attempt (a document instructing the
model to ignore its role) was retrieved and its instructions were
completely ignored, verified live rather than assumed from design; and
Ask Bragi is covered by the same rate limiting, audit logging, and CI
security scanning as the rest of the platform. See
`docs/ai/AI_GOVERNANCE.md` for the governance document and
`BRAGI_ASK_BRAGI_PLAN.md` for full architecture, test evidence, and
current limitations — notably two eval categories (imaging, a
two-source medication conflict) and a proper large-sample latency
benchmark remain open; the reverse-language case has been verified
against real production output, in both Romanian and English. A
`docs/ai/AI_GOVERNANCE.md`-governed rollout to real patients is a
business decision, not one this repository makes on its own.

---

## Medical disclaimer

Bragi Health Portal is a **records management tool**, not a diagnostic
or clinical decision system. It does not diagnose conditions, recommend
treatments, or prescribe medications. All information displayed is
patient-entered or extracted from uploaded source documents and must be
reviewed by a qualified healthcare professional.
