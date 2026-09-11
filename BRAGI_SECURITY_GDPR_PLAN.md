# Bragi Security, GDPR & Production-Readiness Plan

Authoritative engineering checklist for the security/privacy/data-
governance hardening effort. This document is a living record — it is
updated as work proceeds, not written once and left stale. It governs
and is governed by the rules below; those rules apply to every future
edit of this document and every related commit.

## 0. How to read this document

**Status labels** (used consistently, nowhere else in this repo):

- `[PASS]` — implemented AND verified with real evidence (a named test,
  a real HTTP request/response, a real DB query result, a real browser
  session). Evidence is cited inline.
- `[FAIL]` — a real, currently-unmitigated gap.
- `[IMPLEMENTED — NOT DEPLOYED]` — code/design exists but is not active
  in production (feature-flagged off, requires an env var not yet set,
  etc).
- `[EXTERNAL ACTION]` — requires an action outside this codebase (a
  vendor console setting, a contract, a payment, credential rotation)
  that engineering cannot perform unilaterally.
- `[LEGAL REVIEW]` — requires legal/compliance interpretation before an
  engineering claim can be made.
- `[INDEPENDENT VALIDATION]` — requires a party other than the author
  of the code (pentest, external audit) to be credible.
- `[NOT APPLICABLE]` — the control's premise doesn't hold for this
  system's actual architecture (reasoning given, not asserted).
- `[UNKNOWN]` — not yet verified either way. Never used as a substitute
  for `[FAIL]` when the answer is knowable and unfavorable.

**Never** claim GDPR/HIPAA/MDR/EU-AI-Act/ISO-27001/SOC-2 certification
or compliance in this document. None of those has been established.
Everything here is an engineering self-assessment.

**Production-safety rule governing every change made under this plan**:
`main` auto-deploys to Render (backend) and Vercel (frontend). Every
commit pushed to `main` while executing this plan must be independently
production-safe — additive, backward-compatible, disabled-by-default
where risk exists, reversible. No item in this plan is pushed if it
depends on an unconfigured env var, an unapplied coordinated DB
migration, a DB role/RLS change that could break current runtime
access, a KMS config that doesn't exist, a vendor setting not yet
enabled, or a non-backward-compatible coordinated frontend/backend
deploy. Items that need such things are implemented (where safely
possible), tested in dev, documented, and left inactive —
`[IMPLEMENTED — NOT DEPLOYED]` or `[EXTERNAL ACTION]`, never force-
pushed live to prove a point.

## 1. System overview

See `docs/security/THREAT_MODEL.md` §1–2 for the full system/asset
summary. In short: FastAPI + Postgres (Neon) backend, Next.js frontend,
Reducto + OpenAI + Google Document AI as document-processing vendors,
Render (backend) + Vercel (frontend) as hosting, no AI chat feature
implemented yet.

## 2. Roles, actors, controller/processor assumptions

Roles in the system: `patient`, `doctor`, `admin`, `care_partner`,
`emergency_worker`. A `doctor` acting as a PCP is the same role with a
`is_pcp`/equivalent grant, not a separate account type (see
`docs/security/AUTHORIZATION_MATRIX.md` for the exact mechanism).

Controller/processor roles: **not settled by engineering** — this is a
legal determination (who is the data controller for patient health
data processed by this platform: the platform operator, the treating
clinic/hospital, or a joint-controller arrangement) that depends on
contracts this repository cannot see. See
`docs/privacy/CONTROLLER_PROCESSOR_MAP.md`. `[LEGAL REVIEW]`.

## 3. Work already completed and verified this round

All items below were implemented and verified live during this
hardening round (see git log `b4ad7dc`, `5ceec0c`, `7142646` on
`main`, all deployed and confirmed live — Render `dep-daheeitckfvc73bq8bug`
status `live`, Vercel production deployment `bloodwork-os-71o310xlq-...`
status `Ready`, both confirmed 2026-09-10).

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Security response headers (backend) | `[PASS]` | `security_headers_middleware` in `backend/app/main.py`; curl-verified against a running instance (X-Content-Type-Options, Referrer-Policy, Permissions-Policy, CSP, X-Frame-Options, HSTS outside dev) |
| 2 | Security response headers + CSP (frontend, browser-rendered surface) | `[PASS]` | `frontend/next.config.ts`; real Playwright/Chromium session across login, my-records, document detail, upload, and the PDF.js source viewer — zero CSP violations, zero console errors; headers re-confirmed via curl |
| 3 | Next.js critical CVE chain (16.2.4→16.3.4) | `[PASS]` | `npm audit`: 11 vulnerabilities (1 critical) → 0, verified before/after |
| 4 | Login timing side-channel (account enumeration via response time) | `[PASS]` | `verify_password_timing_safe()` in `backend/app/auth.py`; always pays real bcrypt cost against a dummy hash for nonexistent accounts |
| 5 | Missing password length floor | `[PASS]` | `SignupRequest.password: str = Field(min_length=8, max_length=256)` |
| 6 | Account-deletion FK-cascade gaps (`PatientMedication`, `EmergencyContact`, `EmergencyAccessSession`, `EmergencyAuditLog.emergency_user_id`/`session_id`) | `[PASS]` | Reproduced the exact 500 live end-to-end (real signup + medication + emergency session), applied fix, re-ran identical request → `{"deleted": true}` (200); re-verified via direct DB query that audit rows survive with correctly-nulled FKs |
| 7 | `is_active` staleness in `GET /patients` and `GET /my-patients` (revoked doctor still saw patient card) | `[PASS]` | Code fix + `test_idor_regression.py::test_revoked_doctor_access_is_denied_immediately` |
| 8 | File upload validation (no extension/content/size checks) | `[PASS]` | `_validate_upload_extension()`/`_read_and_validate_upload()` in `backend/app/main.py`; `backend/tests/test_upload_validation.py` (6 tests: real PDF/PNG accepted, `.exe` rejected, HTML-spoofed-as-PDF rejected by magic bytes, no-extension rejected, batch endpoint isolates one bad file) |
| 9 | PHI in logs (`ai_extract.py` printed patient name + raw model output) | `[PASS]` | Diff + review of all remaining `print()`/exception-handler call sites in `backend/app/*.py`; matches `reducto_client.py`'s pre-existing PHI-free `REDUCTO_TIMING` convention |
| 10 | Information disclosure (raw exception text in upload-save error responses) | `[PASS]` | Both handlers now return a generic client message; full detail logged server-side only |
| 11 | Cross-patient/cross-role IDOR regression coverage | `[PASS]` | `backend/tests/test_idor_regression.py`, 10 tests, all passing against the real dev DB |
| 12 | Security response header regression coverage | `[PASS]` | `backend/tests/test_security_headers.py`, 4 tests |
| 13 | Python dependency CVEs (python-jose, python-multipart, python-dotenv) | `[PASS]` | `pip-audit` before/after |
| 14 | npm dependency CVEs beyond Next.js itself (axios, brace-expansion, js-yaml, nanoid, browserslist, @babel/core, baseline-browser-mapping) | `[PASS]` | `npm audit fix`, verified 0 remaining |
| 15 | Undeclared `requests` dependency, unbounded `openai` dependency | `[PASS]` | Pinned in `backend/requirements.txt` |

## 3a. Round 2: technical controls implemented and verified (this round)

The previous round completed documentation and a first hardening pass
but explicitly deferred several items as `[FAIL]`/near-term follow-ups
(§24 below, and `docs/PRODUCTION_READINESS_CHECKLIST.md`'s "highest-
priority next steps"). This round implemented and verified those
technical controls. Commits on `main` (all deployed, all independently
production-safe per this plan's own rule): `807f2fd` (CNP-in-URL fix +
response minimization + AI-minimization boundary), `c1d06a3` (rate
limiting), `fce4652`/`326908d`/`8e61f24`/`9f5618f` (secret history scan +
static analysis + CI pipeline, including a real caught-and-fixed CI
failure), `7292b0d` (DSAR export), `9f6f55b` (deletion completeness),
`77c8f48` (malware-scanning pipeline boundary), `9f4f0df` (CNP
regression suite). See each linked doc for full detail; this section is
the pointer, not a duplicate.

| # | Item | Status | Evidence |
|---|---|---|---|
| 16 | CNP removed from URLs (`GET /emergency/search?type=cnp`) | `[PASS]` | New `POST /emergency/search` (JSON body) used by every frontend caller for every search type; the legacy `GET` form now rejects `type=cnp` with 400 unconditionally. `backend/tests/test_cnp_identifier_minimization.py` — 10 tests, real dev DB, including a real POST-based CNP search that still finds the right patient |
| 17 | CNP minimized in API responses | `[PASS]` | Masked in `/patients`, `/my-patients`, `/patients/search`, `/admin/patients/search`, `/patients/{id}/documents`; full value only to the patient viewing their own `/my/profile` (masked for a doctor/admin viewing `/patients/{id}/profile`); masked for care_partner viewers of `/documents/{id}`. Evidence: same 10-test suite above |
| 18 | Reusable AI-provider data-minimization boundary | `[PASS]` (boundary + audit); `[NOT APPLICABLE — no current call needs it]` for retrofitting existing calls | `backend/app/services/ai_minimization.py` + 9 tests (`test_ai_minimization.py`). Audited all 3 existing OpenAI call sites: none inject a separate patient-context object (no email/phone/address — `Patient` model doesn't even have those columns); the identity fields these calls return are the intended extraction output, not incidental exposure. See §21 |
| 19 | Rate limiting | `[PASS]` for the mechanism + in-memory (single-instance) backend; `[IMPLEMENTED — NOT DEPLOYED]` for the distributed (Redis) backend, since no `RATE_LIMIT_REDIS_URL` is configured in production yet | `backend/app/rate_limit.py`, 14 unit tests + a real live verification (real `uvicorn`, 12 real HTTP requests, 10×200 then 2×429 with a real `Retry-After` header). See §9, `docs/security/RATE_LIMITING.md` |
| 20 | Full git-history secret scan | `[PASS]` | gitleaks v8.30.1, 245 commits, full history (`--log-opts="--all"`). One finding, reviewed as a false positive. No `ROTATION REQUIRED` entries. See §11, `docs/security/SECRET_SCAN_HISTORY.md` |
| 21 | Static analysis (Bandit/Semgrep) | `[PASS]` | 0 High findings from either tool; 2 Medium (Bandit)/2 (Semgrep, same 2) reviewed as false positives and suppressed with reasoned `# nosec` annotations, caught by CI's own first real run (see §18 below). See §13, `docs/security/STATIC_ANALYSIS.md` |
| 22 | CI security pipeline | `[PASS]` | `.github/workflows/ci.yml` (every push — backend tests against a real ephemeral Postgres service container, Bandit, frontend typecheck/lint/build, full-history secret scan) + `nightly-security.yml` (daily — pip-audit, npm audit, broader Semgrep). Both confirmed via real GitHub Actions runs, not just local dry-runs — see §18, `docs/security/CI_PIPELINE.md` |
| 23 | DSAR export | `[PASS]` (patient role) | `POST /my/export` — 8 tests including real cross-patient isolation and a real original-file embedding round-trip. Non-patient-role export not implemented this round (documented). See §19a, `docs/privacy/DSAR_RUNBOOK.md` |
| 24 | Non-patient-role account deletion | `[PASS]` for care_partner (real delete) and doctor/admin (soft-delete/deactivation — `[LEGAL REVIEW]`ed design decision, not a full erasure); `[FAIL]`/`[PRODUCT DECISION REQUIRED]` for emergency_worker (deliberately not offered) | 6 tests (`test_deletion_completeness.py`), real DB, including a real active-access-grant-ends-with-no-500 check. See §19a |
| 25 | Malware-scanning pipeline boundary | `[PASS]` for the boundary + a narrow heuristic screen; `[FAIL]`/`[EXTERNAL ACTION]` for a real connected antivirus engine (not softened) | `backend/app/services/security_scan.py`, wired into `process_upload_job()`. 9 tests including a real end-to-end HTTP upload of a PDF with an actual `/Launch` action, confirmed quarantined before reaching clinical processing. See §10, `docs/security/MALWARE_SCANNING_PLAN.md` |

Deferred/declined upgrades (documented, not forced — see §12):
`starlette` CVEs (blocked by `fastapi==0.115.12`'s own `starlette<0.47.0`
constraint — needs a coordinated FastAPI major bump); `pyasn1` CVEs
(blocked by `python-jose==3.4.0`'s `pyasn1<0.5.0` constraint — needs a
python-jose major bump or a library switch); `ecdsa`'s known CVE
(`[NOT APPLICABLE]` — this app only uses HS256, never ECDSA-based JWT
algorithms).

## 4. Threat model

See `docs/security/THREAT_MODEL.md` — 19 threat scenarios assessed,
each with likelihood/impact/controls/evidence. Summary of the highest-
priority items from the first round, updated with this round's status:

- Rate limiting: **implemented** — §9. A distributed (Redis) backend
  isn't configured in production yet, but the mechanism and in-memory
  fallback are real and verified.
- Malware/antivirus scanning: **pipeline boundary implemented**, no real
  AV engine connected yet — §10, `docs/security/MALWARE_SCANNING_PLAN.md`.
- CNP (Romanian national ID) exposure: **fixed** — masked in API
  responses/frontend list views, removed from URLs entirely — §8 below.
- AI vendor data-minimization: **boundary implemented**; existing calls
  audited and found to need no retrofit (they never sent more than the
  document's own content) — §21 below.
- Client-supplied `role` at signup has no server-side gate beyond a
  code for `care_partner` — a product decision is needed, not a silent
  fix (§6). Unchanged.
- No RLS at the database layer (`docs/security/RLS_PLAN.md` assesses
  actual risk given that application-layer authorization is functioning
  — absence of RLS is not automatically scored as Critical). Unchanged.

## 5. Authorization

See `docs/security/AUTHORIZATION_MATRIX.md` for the full role ×
resource × action matrix. Core mechanism: `can_access_patient()`,
`doctor_has_patient_access()`, `care_partner_can_access_document()`,
`require_role()`, `require_emergency_role()`, `require_pcp_or_admin()`
in `backend/app/main.py` — not a separate policy engine, but
consistently applied (verified route-by-route this round; the two
staleness bugs found were the only gaps identified across the full
route surface).

Open item: `GET /admin/patients/search` has no department/hospital
scoping, unlike `/admin/doctors`. `[UNKNOWN — PRODUCT DECISION
REQUIRED]`: flagged for the product owner, not silently changed, since
admin is already treated as a broad/trusted role elsewhere in this
system and narrowing it unilaterally could itself break an intended
workflow.

## 6. Self-service role escalation at signup

`POST /auth/signup`'s `role` field accepts `admin`/`doctor` with no
server-side gate other than `care_partner_code` for the `care_partner`
role. This is either an intentional open self-service onboarding flow
for the product's current stage, or a real gap — engineering cannot
tell which from the code alone. `[UNKNOWN — PRODUCT DECISION
REQUIRED]`. Not changed this round: changing it without confirming
intent risks breaking the actual current onboarding process for
doctors/admins, which would itself be a production-availability
regression — exactly what this plan's own safety rules prohibit acting
on without confirmation.

## 7. Row-Level Security (RLS)

See `docs/security/RLS_PLAN.md`. Not enabled. Explicitly NOT enabled
blindly this round per the user's own instruction: Neon's pooled
runtime connection, `SET LOCAL`/transaction-scoped context needs, and
background-job (non-request-scoped) DB connections all need a proven
strategy before RLS activation is safe, or RLS would silently break
runtime DB access. `[IMPLEMENTED — NOT DEPLOYED]` for the plan/design
only; no RLS policy has been written or applied to any table.

## 8. Identifier exposure (CNP)

**Fixed and verified this round** (§3a items 16-17;
`backend/tests/test_cnp_identifier_minimization.py`, 10 tests, real dev
DB):

- `GET /emergency/search?type=cnp&q=<CNP>` no longer accepts `cnp` — it
  returns 400 unconditionally. A new `POST /emergency/search` (JSON
  body) handles every search type, including CNP, and is what both
  frontend callers (`emergency/search`, `emergency/workspace`) now use.
  The CNP-search functional path is preserved and tested end-to-end (a
  real POST search by CNP still finds the right patient); no other route
  accepts or echoes CNP as a query parameter (confirmed by the original
  audit, unchanged this round).
- CNP is now masked (`_mask_cnp()`) in every list/search response that
  doesn't need the real value: `GET /patients`, `/my-patients`,
  `/patients/search`, `/admin/patients/search`,
  `/patients/{id}/documents`. `GET /patients/{id}/profile` (and
  `/my/profile`, sharing `build_patient_profile_response`) returns the
  full value only to the patient viewing their own record — a
  doctor/admin viewing someone else's profile gets the masked value.
  `GET /documents/{id}` masks CNP specifically for `care_partner`
  viewers (no identity-matching workflow needs it there); patient/
  doctor/admin keep the full value for the identity-review/correction
  workflow it exists for.
- Verified no identity-matching logic depends on any of these response
  bodies — `services/patient_identity.py`'s comparison runs entirely
  server-side against the uploaded document's own extracted CNP.

`[PASS]` for both response-body minimization and URL exposure. See
`docs/security/THREAT_MODEL.md` §4.11 for the original audit this fix
responds to. See `docs/security/IDENTIFIER_ENCRYPTION_PLAN.md` for the
separate, larger question of encrypting CNP at rest — explicitly NOT
undertaken impulsively this round per the user's instruction never to
migrate production encryption without a proven, reversible strategy.

## 9. Rate limiting

**Implemented and verified this round** — `[PASS]` for the mechanism
and the in-memory (single-instance) backend; `[IMPLEMENTED — NOT
DEPLOYED]` for the distributed (Redis) backend specifically, since no
`RATE_LIMIT_REDIS_URL` is configured in the actual Render environment
yet (an env-var-only activation step, no code change needed — see
`docs/security/RATE_LIMITING.md`). `backend/app/rate_limit.py`: a
FastAPI dependency factory selecting Redis (real, shared, correctly
distributed across however many instances are running) when
`RATE_LIMIT_REDIS_URL`/`REDIS_URL` is set, or an explicitly-documented
per-instance-only in-memory fallback otherwise — never described as
distributed when it isn't. Fails open on any backend error (a
rate-limiter outage must never take the app down with it).

Applied to `/auth/signup` (10/hour), `/auth/login` (15/5min),
`/upload`+`/upload/background`+`/upload/batch` (30/hour),
`/documents/{id}/file`+`/source-evidence/{id}/view`+
`/lab-results/{id}/source` (120/5min), `/my/medications/{id}/
refresh-official-info` (20/hour, external RxNorm lookup), `GET`+
`POST /emergency/search` (60/5min), `/emergency/access-sessions`
(30/hour), and `POST /my/export` (3/day, added with the DSAR feature —
see §19a). Password reset/verification/Ask-Bragi endpoints don't exist
in this codebase — nothing to limit there yet.

14 unit tests (`test_rate_limit.py`) plus a real live verification: a
real local `uvicorn` process, 12 real HTTP `POST /auth/signup` requests
(10×200, then 2×429 with a real `Retry-After: 3571` header), followed by
real login+delete cleanup of all 10 synthetic accounts. A real bug (a
class-instance `Depends()` callable breaking FastAPI's `Request`
parameter recognition, which would have 422'd every rate-limited route
in production) was caught by this round's own test suite before it
shipped — see `docs/security/RATE_LIMITING.md`'s postmortem note.

## 10. File upload & malware scanning

Extension/content/size validation: `[PASS]` (§3 item 8).

**Malware-scanning pipeline boundary implemented and verified this
round**: `[PASS]` for the boundary itself and a narrow, honestly-labeled
heuristic screen; `[FAIL]`/`[EXTERNAL ACTION]` for a real connected
antivirus engine (no ClamAV or equivalent is connected in any
environment today — not softened into a false pass).
`backend/app/services/security_scan.py`, wired into
`process_upload_job()` (the single canonical processing entry point
every upload route funnels through) right after the file is confirmed
saved and BEFORE SHA-256/duplicate detection, Reducto, OpenAI, or any
other clinical-processing step. Two backends: ClamAV (real AV, active
when `CLAMAV_HOST` is set — ready to activate, not connected) and a
heuristic structural screen (fallback, always available — PyMuPDF-based
detection of a PDF `/Launch` action or an embedded file with an
executable-shaped extension; deliberately never flags `/JavaScript`
alone, to avoid false-positiving on legitimate PDF forms). Only an
`infected` verdict blocks processing — a new, distinct
`UploadJob.status = "security_quarantined"` (never conflated with the
pre-existing `"quarantined"` value, which means an identity mismatch).
Never labeled "malware scanning" in code/logs/API responses when only
the heuristic screen ran.

9 tests: `test_security_scan.py` (7 unit tests — a real PDF built with
an actual `/Launch` action and a real embedded `.exe`, both correctly
flagged; ClamAV-configured-but-unreachable falls back rather than
false-claiming clean) and `test_malware_quarantine.py` (2 end-to-end
tests, real DB, real HTTP — a real malicious PDF uploaded through the
real `/upload/background` endpoint is confirmed quarantined with no
Document ever created, i.e. it never reached clinical processing; a
real clean PDF is confirmed not blocked). See
`docs/security/MALWARE_SCANNING_PLAN.md`.

## 11. Secrets

Working-tree secrets scan: `[PASS]` — unchanged from the prior round.
**Full git-history scan completed this round**: `[PASS]` — gitleaks
v8.30.1 against the full history (`--log-opts="--all"`, 245 commits,
~5.09MB), plus targeted pickaxe cross-checks for Postgres/OpenAI/
Reducto/AWS/GCP/GitHub/Slack credential shapes. One finding, reviewed
and dismissed as a false positive (a boolean env-var assignment in
prose). **No entries require `ROTATION REQUIRED`.** See
`docs/security/SECRET_SCAN_HISTORY.md`. `.env`/`backend/.env` confirmed
`.gitignore`d (unchanged).

## 12. Dependency / supply-chain security

Python: `pip-audit` re-run this round — same 3 findings as before
(pyasn1/starlette/ecdsa), all still correctly deferred/not-applicable
for the same reasons (see §3, §13). npm: `npm audit` re-run — 0
vulnerabilities. GitHub Actions: **no longer `[NOT APPLICABLE]`** — CI
now exists (§18); every third-party action in both workflows is pinned
to a full commit SHA, not a floating version tag.

## 13. Static & dynamic analysis

**Bandit and Semgrep run this round** — `[PASS]`. Bandit (`bandit -r
app`): 0 High, 2 Medium (both `urllib.request.urlopen` calls whose
target host is always a hardcoded constant, never user input — reviewed
as false positives, not an SSRF vector, suppressed with reasoned
`# nosec B310` annotations so CI's severity gate stays meaningful), 12
Low (permissive `try/except/pass` error handling and a `"bearer"`
string false-positived as a hardcoded password — reviewed, no action
needed). Semgrep (`p/security-audit` + `p/python`): identical 2 findings,
no new ones. Full detail: `docs/security/STATIC_ANALYSIS.md`. Now wired
into CI (§18) so this doesn't require another manual pass to stay
current.

Dynamic/API tests run this round beyond the 20 regression tests: SQL
injection (`[PASS]` — 100% ORM query construction, no raw string-built
SQL in application code, confirmed by review of every `db.query()` call
site), file-type spoofing (`[PASS]`, §3 item 8), oversized-file
behavior (`[PASS]`, streaming cap tested). Not yet run: XSS payload
injection against form fields that get echoed back, path traversal
against filename handling beyond the extension check. `[UNKNOWN]` for
those two, scheduled as follow-up — all such testing must stay within
this plan's safe-testing rules (§20) and only ever target the local/dev
environment.

## 14. Frontend security

`dangerouslySetInnerHTML`: `[PASS]` — zero uses found (grep across
`frontend/app`, `frontend/components`). Unsanitized markdown rendering:
`[NOT APPLICABLE]` — no markdown-rendering feature exists in the
current frontend. Open redirects: `[UNKNOWN]` — not yet audited this
round. Token storage: `localStorage` (not `HttpOnly` cookie) — a
deliberate architecture choice given the bearer-token-only backend; the
resulting risk (XSS → token theft) is mitigated primarily by the new
CSP (§3 item 2) and the absence of any known injection point, not by
cookie-based storage. CNP in URLs: `[FAIL]`, see §8. Unsafe iframes:
`[PASS]` — CSP sets `frame-src 'none'`.

## 15. Session / cookie security

`[NOT APPLICABLE]` for CSRF (see `docs/security/THREAT_MODEL.md` §4.7
— zero cookie usage anywhere in the app, confirmed by grep). No
server-side session store or token revocation/denylist exists —
logout is client-side only, and account deletion only incidentally
invalidates tokens because `get_current_user` re-queries the `User` row
every request. This is a real architectural limitation (a stolen JWT
remains valid until its expiry, with no way to revoke it server-side)
worth documenting even though it isn't a "bug" — flagged for a future
phase, not fixed this round given a token-revocation mechanism is a
meaningfully-sized feature, not a safe drive-by change.

## 16. Production error handling

Two raw-exception-in-response leaks found and fixed this round (§3
item 10). Broader review of remaining error handlers across
`backend/app/main.py`: not yet exhaustively completed beyond the
upload-save paths that were the specific, reproduced finding.
`[UNKNOWN]` for full coverage — scheduled as a follow-up grep-and-
review pass (search every `HTTPException(...detail=f"...{e}"...)` /
`detail=str(...)` pattern repo-wide).

## 17. Analytics / monitoring PHI leakage

`[NOT APPLICABLE]` — no analytics or error-monitoring SDK (Sentry,
PostHog, Segment, etc.) found anywhere in the codebase (confirmed via
dependency lists and code search in an earlier subagent pass this
round). Nothing currently exists that could leak PHI through such a
channel because no such channel exists. This also means there is
**no security event monitoring in production today** — a gap in its
own right, see `docs/security/PRODUCTION_ACCESS_POLICY.md`.

## 18. CI / CD security gates

**Implemented and verified this round** — `[PASS]`.
`.github/workflows/ci.yml` (every push/PR to `main`): backend tests
against a real ephemeral Postgres 16 service container (which doubles as
migration-sanity checking), Bandit (fails on Medium/High), frontend
`tsc`/ESLint/production build, and a full-history gitleaks secret scan.
`.github/workflows/nightly-security.yml` (daily + manual dispatch):
`pip-audit`, `npm audit`, a broader Semgrep ruleset. No production
secrets in either workflow (the backend job's `DATABASE_URL` points at a
container-local ephemeral Postgres; no vendor API key is ever set).
Every third-party action is pinned to a full commit SHA.

Both workflows were confirmed with real GitHub Actions runs, not just
local dry-runs — including a genuine catch: the first real `ci.yml` run
correctly failed on 2 Bandit findings that had been reviewed as false
positives (§13) but not yet suppressed in code; fixed with a reasoned
`# nosec` annotation, re-run confirmed green. See
`docs/security/CI_PIPELINE.md` for the exact run links and design
rationale (the fast-vs-nightly split, why ESLint is non-blocking this
round).

## 19. Data retention & deletion

See `docs/privacy/RETENTION_POLICY.md` and `docs/privacy/DSAR_RUNBOOK.md`.
No `expires_at`-style automatic retention/cleanup exists for clinical
data today (deliberately — the user's instruction is explicit that no
speculative auto-deletion of clinical data may be added without legal
approval, since retention periods for health records are frequently
legally mandated minimums, not just privacy-driven maximums).

### 19a. Deletion completeness and DSAR export (this round)

`DELETE /my/account` now covers every role except `emergency_worker`,
with deliberately different semantics per role rather than one forced
shape — see `docs/privacy/DSAR_RUNBOOK.md` for full rationale:

- **patient**: unchanged, real row delete (`[PASS]`, prior round).
- **care_partner**: real row delete (`[PASS]`) — their only rows
  (`CarePartnerPatientLink`, `SharedStructuredPage`) have no independent
  clinical/audit value to anyone else.
- **doctor/admin**: a soft-delete (`[PASS]` for what it does; `[LEGAL
  REVIEW]` for whether this is the correct final policy) — the row
  persists (`users.deleted_at` set) because ~8 tables hold NOT-NULL
  clinical/audit references to a clinician/admin's user id that are part
  of OTHER patients' own records (who treated them, who uploaded a
  document) and must not disappear or go anonymous. What does happen:
  every active `DoctorPatientAccess` grant ends immediately; the
  account's own login-identifying data (email, password) is
  irreversibly replaced; `get_current_user()`/`login()` both reject the
  account outright, so an already-issued JWT stops working immediately.
- **emergency_worker**: deliberately not offered (`[FAIL]`/`[PRODUCT
  DECISION REQUIRED]`) — a clean 403, not a 500 or silent no-op;
  emergency-access accounts are commonly tied to institutional
  provisioning this codebase has no visibility into.

6 tests (`test_deletion_completeness.py`), real dev DB, including a real
active-access-grant-ends-with-no-500 check and double-deletion
idempotency.

**DSAR export implemented**: `POST /my/export` (patient role) — `[PASS]`,
returns a zip (profile/labs/medications/events/access-relationships/
emergency-contacts/documents-manifest/original-files/README, capped at
500MB). Reuses existing authorization exactly (no separate "which
patient" parameter to get wrong). Rate-limited (3/day). 8 tests
including real cross-patient isolation and a real original-file
embedding round-trip. Non-patient-role export not implemented this round
(documented, lower priority — smaller personal-data footprint).

## 20. Safe security testing rules (governs all testing under this plan)

Applies to every test written or run as part of this effort, permanently:
local/dev-environment and the shared Neon dev DB only, using synthetic
accounts created through the real signup endpoint, never production.
Never, against production or otherwise: brute-force/credential-stuffing
runs, automated SQL-injection scanners, load/DoS tests, rate-limit
flooding, malware-upload flooding, destructive deletion testing against
real user accounts, mass enumeration of `SourceEvidence`/document IDs,
intentional spend attacks against OpenAI/Reducto/Google, or destructive
database tests. The 20 regression tests from the first round and every
test added in this round (rate limiting, CNP minimization, DSAR export,
deletion completeness, malware-scan quarantine — 138 backend tests
total as of this round) comply: they run against the dev DB, use
synthetic `@example.com` accounts created via `/auth/signup`, and delete
(or, for doctor/admin, soft-delete) their own fixtures on teardown.

## 21. AI / vendor data handling

See `docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md`,
`docs/vendors/REDUCTO_PRODUCTION_REQUIREMENTS.md`, and
`docs/ai/AI_GOVERNANCE.md`. Three vendors process document content
today: Reducto (`platform.reducto.ai` — classify/split/parse/extract on
the full uploaded file), OpenAI (fallback page extraction + discharge-
summary extraction, both send substantial raw content), and Google
Document AI (`app/services/document_ai_layout.py`,
`app/services/google_document_ai_service.py` — OCR and discharge-
summary support, confirmed as live imports in `main.py`, not dead
code).

**This round**: audited exactly what each of the 3 OpenAI call sites
sends (`ai_extract.py`, `services/openai_discharge_service.py`,
`services/discharge_summary_pipeline.py`) — each sends only the raw
uploaded document (page image/native PDF bytes) plus a fixed
extraction-schema prompt; none separately constructs or attaches a
patient-context object (no email/phone/address — the `Patient` model
doesn't even have those columns). The identity fields these calls
return (name/CNP/DOB) are the intended extraction output (matching a
document to the right patient), not incidental exposure. Built
`app/services/ai_minimization.py` — reusable
`redact_direct_identifiers()`/`minimize_patient_context()` helpers plus
a documented boundary (user → server authz → minimum-necessary
retrieval → identity stripping → provider call) for any FUTURE call that
DOES need to assemble a patient-context object, most obviously a future
Ask Bragi retrieval step. 9 tests
(`backend/tests/test_ai_minimization.py`). `[PASS]` for the boundary +
this-round's audit of existing calls; `[NOT APPLICABLE]` for retrofitting
existing calls with input-stripping, since none currently sends anything
beyond the document's own inherent content. Reducto assessed the same
way, same conclusion (file handed directly, no separate patient-context
injection) — consistent with this document's own acknowledgment that
document extraction inherently requires document contents.

Vendor DPA/ZDR terms remain not knowable from this codebase alone —
`[EXTERNAL ACTION]`/`[LEGAL REVIEW]` for the actual contract terms with
OpenAI/Reducto/Google, unchanged this round.

Ask Bragi (AI chat): **implemented this round, `[IMPLEMENTED — NOT
DEPLOYED]`** — see `BRAGI_ASK_BRAGI_PLAN.md` for the full architecture
and evidence. `ASK_BRAGI_ENABLED`/`NEXT_PUBLIC_ASK_BRAGI_ENABLED` both
default false; nothing changes for any real user until explicitly
activated. Every §2.1–2.7 forward-looking requirement in
`docs/ai/AI_GOVERNANCE.md` Part 2 is now a concrete, tested control
rather than a design note — patient-context injection is server-side
only (no tool accepts a `patient_id` parameter, verified directly
against the tool schemas), every tool call independently re-
authorizes, a real adversarial prompt-injection document was retrieved
and its instructions ignored (live-verified, not just designed for),
missing/conflicting-data handling is real and tested, chart data is
always server-resolved never model-generated, and conversation storage
is integrated into DSAR export and account deletion (the latter closing
a real FK-cascade bug this feature's own tests found before merging).
`docs/ai/AI_GOVERNANCE.md` itself has not yet been rewritten to drop its
now-stale "does not exist" framing — flagged as a follow-up doc update,
not a technical gap.

## 22. Backups & disaster recovery

See `docs/security/BACKUP_DR_PLAN.md`. `[UNKNOWN]` — Neon and Render's
actual backup/PITR configuration is an account/console-level setting
this codebase cannot verify. No restore test has been performed.

## 23. Regulatory posture (MDR / EU AI Act)

See `docs/regulatory/INTENDED_PURPOSE_DRAFT.md`. `[LEGAL REVIEW]` —
this document uses conservative language throughout and does NOT state
that Bragi is definitively outside MDR/EU-AI-Act scope, nor that it is
certified under either.

## 24. Residual risks

Resolved this round (moved out of the open list; kept here for
traceability): rate limiting (§9), CNP exposure in URLs/unmasked
responses (§8), the AI-vendor data-minimization boundary (§21, for
existing calls — see below for what's still open), no CI (§18), no
non-patient-role self-deletion endpoint (§19/§19a, except
`emergency_worker` — see #6 below), no malware-scanning pipeline
boundary (§10, though no real AV engine is connected — see #2 below).

**Still open / carried forward:**

1. Real `StaleDataError` race condition between account deletion and an
   in-flight background upload job (found via testing in the prior
   round, not fixed — see §3 item 8's evidence and
   `backend/tests/test_upload_validation.py`'s fixture comment). Low
   likelihood (narrow timing window), but real.
2. No real antivirus engine connected (§10) — the pipeline boundary and
   a narrow heuristic screen exist and are enforced, but this is not a
   substitute for a real scanner. `[EXTERNAL ACTION]` for vendor
   selection.
3. No distributed (Redis) rate-limit backend configured in the actual
   Render environment yet (§9) — the in-memory fallback is correct for
   today's single instance but must be paired with `RATE_LIMIT_REDIS_URL`
   before/at the same time as any horizontal scaling change.
4. Doctor/admin account deletion is a soft-delete, not a full erasure
   (§19a) — `[LEGAL REVIEW]` on whether that's the correct final policy.
5. No token revocation mechanism (§15) — unchanged.
6. `emergency_worker` accounts have no self-deletion path at all (§19a)
   — `[PRODUCT/LEGAL DECISION REQUIRED]`.
7. `role` self-selection at signup with no server-side gate (§6) — needs
   a product decision. Unchanged.
8. `GET /admin/patients/search` has no scoping (§5) — needs a product
   decision. Unchanged.
9. DSAR export doesn't cover doctor/admin/care_partner/emergency_worker
   roles (§19a) — documented, lower priority than the patient export.
10. Non-`.pdf` files (images, etc.) get no heuristic security screening
    at all (§10) — `scan_unavailable`, not blocking, but also not
    checked; only relevant once/if a real AV engine is connected, which
    would cover every file type regardless.

## 25. Document index

| Document | Status |
|---|---|
| `docs/security/THREAT_MODEL.md` | Done |
| `docs/privacy/BRAGI_DATA_MAP.md` | Done |
| `docs/privacy/CONTROLLER_PROCESSOR_MAP.md` | Done |
| `docs/privacy/PROCESSING_PURPOSES.md` | Done |
| `docs/security/AUTHORIZATION_MATRIX.md` | Done |
| `docs/security/RLS_PLAN.md` | Done |
| `docs/security/IDENTIFIER_ENCRYPTION_PLAN.md` | Done |
| `docs/security/MALWARE_SCANNING_PLAN.md` | Done — updated this round with the real implementation |
| `docs/security/RATE_LIMITING.md` | Done (new this round) |
| `docs/security/SECRET_SCAN_HISTORY.md` | Done (new this round) |
| `docs/security/STATIC_ANALYSIS.md` | Done (new this round) |
| `docs/security/CI_PIPELINE.md` | Done (new this round) |
| `docs/EXTERNAL_COMPLIANCE_ACTIONS.md` | Done (new this round) |
| `docs/security/PRODUCTION_ACCESS_POLICY.md` | Done |
| `docs/security/KEY_ROTATION_RUNBOOK.md` | Done |
| `docs/security/INCIDENT_RESPONSE.md` | Done |
| `docs/security/BACKUP_DR_PLAN.md` | Done |
| `docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md` | Done |
| `docs/vendors/REDUCTO_PRODUCTION_REQUIREMENTS.md` | Done |
| `docs/privacy/VENDOR_REGISTER.md` | Done |
| `docs/privacy/TRANSFER_REGISTER.md` | Done |
| `docs/privacy/RETENTION_POLICY.md` | Done |
| `docs/privacy/DSAR_RUNBOOK.md` | Done |
| `docs/privacy/PRIVACY_NOTICE_DRAFT.md` | Done |
| `docs/privacy/DPIA_DRAFT.md` | Done |
| `docs/privacy/ROPA_DRAFT.md` | Done |
| `docs/ai/AI_GOVERNANCE.md` | Done |
| `docs/regulatory/INTENDED_PURPOSE_DRAFT.md` | Done |
| `docs/PRODUCTION_READINESS_CHECKLIST.md` | Done |

(This table is updated as each document is written during this round;
see each document's own header for its last-updated context.)

## 26. Governing rules carried forward

Every rule in the original task specification governs all future work
under this plan, permanently, until the user says otherwise: work only
on `main`, no force-push, every commit independently production-safe,
never expose secrets, never weaken auth, never bulk-delete production
data, never use real patient data when synthetic will do, never claim
compliance without external validation, always cite real evidence for
`[PASS]`, always use `[UNKNOWN]` rather than inventing certainty.
