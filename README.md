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

**Ask Bragi (AI chat over a patient's record) is implemented and
feature-flagged.** See [Ask Bragi](#ask-bragi) below for what's built,
and what's still required before it's live for real users.

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
  PDF.js for the in-app source viewer.
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
uvicorn app.main:app --reload
```

Database tables/columns are created and kept up to date automatically:
`run_migrations()` runs idempotent `CREATE TABLE IF NOT EXISTS`/
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements on every backend
start (no separate migration-tool step to run).

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

---

## Deployment

- **Frontend** → Vercel
- **Backend** → Render
- **Database** → Neon (PostgreSQL)

`main` auto-deploys to both Render and Vercel on push. Because of this,
every commit to `main` is expected to be independently production-safe —
additive, backward-compatible, and not dependent on a manual coordinated
step unless explicitly documented. Database schema changes apply
automatically on the next backend start (see `run_migrations()` above),
not via a separate deploy step.

---

## Testing

**Backend** (`cd backend && pytest`): unit tests plus a real-DB security
and correctness regression suite — cross-patient/cross-role
authorization (IDOR), CNP/identifier minimization, upload validation,
malware-scan quarantine, DSAR export, account-deletion completeness,
rate limiting, and AI-provider data-minimization. DB-dependent tests
skip gracefully (not silently pass) when `DATABASE_URL` isn't set.

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
  ephemeral Postgres service container (which doubles as migration
  sanity checking), Bandit, frontend typecheck/lint/production build,
  and a full git-history secret scan.
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
    main.py              — routes, authorization, migrations
    models.py             — SQLAlchemy models
    services/             — Reducto client/extraction, document pipeline,
                             lab resolver, security scan, rate limiting,
                             AI-provider minimization, medication lookup, ...
  tests/                   — unit + real-DB regression suite

frontend/
  app/                     — Next.js App Router routes (per role/feature)
  components/              — shared UI (timeline, upload, source viewer, ...)
  lib/                      — API client, i18n, chart theme, taxonomy labels
  qa/                       — manual/ad-hoc Playwright QA scripts

docs/
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
(see below) — code-complete, tested, feature-flagged, and activated in
Vercel production, but **not yet live for real users** pending a
Render-side configuration step (below) that requires dashboard access
this environment doesn't have.

**Next**: setting `ASK_BRAGI_ENABLED=true` + a real `OPENAI_API_KEY` on
the Render backend (the one remaining step before Ask Bragi actually
answers in production); the imaging/medication-conflict/reverse-language
eval categories and a latency benchmark for Ask Bragi (both need that
same OpenAI credential); remaining UX/QA polish (a full Playwright QA
pass, per-section source evidence for Reader sections, prescription→
medication linkage, and other items tracked in `BRAGI_REDUCTO_PLAN.md`'s
per-phase "deferred" notes); production/vendor/legal closure and
independent security validation (see
`docs/EXTERNAL_COMPLIANCE_ACTIONS.md`).

---

## Ask Bragi

Ask Bragi — a conversational AI interface over a patient's own record —
is **implemented, tested, and feature-flagged** (`ASK_BRAGI_ENABLED` /
`NEXT_PUBLIC_ASK_BRAGI_ENABLED`, both required for it to appear/respond).
It reuses Bragi's existing controls rather than introducing parallel
ones:

```
user
  │
  ▼
existing server-side authorization (the same checks every other route uses)
  │
  ▼
minimum-necessary retrieval (only what the query actually needs)
  │
  ▼
identity stripping / data minimization (app/services/ai_minimization.py)
  │
  ▼
the model — answering with citations back to real SourceEvidence,
  via the existing openSourceEvidence resolution path
```

It reuses, rather than duplicates: existing authorization (every tool
call is resolved against a server-owned patient context — no tool
accepts a caller-suppliable patient/document id), the AI-provider
data-minimization boundary in `app/services/ai_minimization.py`,
`SourceEvidence`/`openSourceEvidence` for verifiable citations, audit
logging, rate limiting, and the rest of this repository's security/GDPR
controls. Scope (a single document vs. the whole record) is
server-authoritative — a document-scoped conversation can widen for one
turn via an explicit UI toggle or server-side keyword detection over the
user's own message, never the model's own unconstrained judgment, and
any broadening is always shown in the UI, never silent. Every response
is grounded in real, validated citations; an unvalidated/hallucinated
citation is dropped before the response ever reaches the user. See
`docs/ai/AI_GOVERNANCE.md` for the governance document and
`BRAGI_ASK_BRAGI_PLAN.md` for full architecture, test evidence, and
current limitations (notably: real per-turn latency and three eval
categories — imaging, a two-source medication conflict, reverse
language — are not yet exercised against a real OpenAI key from this
environment; a `docs/ai/AI_GOVERNANCE.md`-governed rollout to real
patients is a business decision, not one this repository makes on its
own).

**Status**: `ASK_BRAGI_ENABLED` and `OPENAI_API_KEY` still need to be
set on the Render backend before this is live for real users — the
Vercel-side flag alone only reveals the nav entry/UI; without the
backend flag+key, users see the nav item and a safe, worded
"unavailable" error rather than a working answer.

---

## Medical disclaimer

Bragi Health Portal is a **records management tool**, not a diagnostic
or clinical decision system. It does not diagnose conditions, recommend
treatments, or prescribe medications. All information displayed is
patient-entered or extracted from uploaded source documents and must be
reviewed by a qualified healthcare professional.
