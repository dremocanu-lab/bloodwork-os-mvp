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
priority open items (all `[FAIL]` or partial):

- No rate limiting anywhere in the backend (login, signup, uploads, AI,
  exports, emergency access all unlimited) — §9 below.
- No malware/antivirus scanning of uploaded files — `docs/security/MALWARE_SCANNING_PLAN.md`.
- CNP (Romanian national ID) not comprehensively minimized in API
  responses or masked in all frontend views; appears in 2 URL query
  strings — §8 below.
- No data-minimization layer before sending documents to Reducto/OpenAI/
  Google Document AI — `docs/vendors/`.
- Client-supplied `role` at signup has no server-side gate beyond a
  code for `care_partner` — a product decision is needed, not a silent
  fix (§6).
- No RLS at the database layer (`docs/security/RLS_PLAN.md` assesses
  actual risk given that application-layer authorization is functioning
  — absence of RLS is not automatically scored as Critical).

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

Found, not fixed this round (see `docs/security/THREAT_MODEL.md` §4.11
for full detail): CNP appears in full in most authenticated JSON
responses — including `GET /patients/search` and `GET /admin/patients/
search`, both of which return the unmasked `cnp` field, though neither
accepts CNP as a search term (both search by name/identifier/code
only, confirmed by reading both route bodies) — and is masked in only
3 of the frontend's list views. Separately, `GET /emergency/search?
type=cnp&q=<CNP>` puts the full CNP value in a URL query string (this
IS a real search-by-CNP endpoint) — confirmed the only route that does
so; no other route accepts or echoes CNP as a query parameter.
`[FAIL]` for response-body minimization; `[FAIL]`, narrower in scope
than earlier assumed, for URL exposure specifically (one route, not
two).

Planned fix (not yet implemented — needs its own careful pass, not a
rushed one, given CNP is used as a real search/lookup key in emergency
workflows where breaking search would itself be a patient-safety
regression): convert `/emergency/search`'s CNP lookup to POST-with-body
(removing it from URLs/logs), and apply the existing `_mask_cnp()`
helper consistently to every response that doesn't require CNP for form-
prefill (edit forms genuinely need the real value; list/search views do
not). See `docs/security/IDENTIFIER_ENCRYPTION_PLAN.md` for the
separate, larger question of encrypting CNP at rest — explicitly NOT
undertaken impulsively this round per the user's instruction never to
migrate production encryption without a proven, reversible strategy.

## 9. Rate limiting

`[FAIL]` — no rate-limiting library or middleware exists anywhere in
the backend (confirmed by dependency list and code search). This is a
real, unmitigated gap for `/auth/login`, `/auth/signup`, uploads,
AI-triggering endpoints, exports, and `/emergency/access-sessions`.

Not implemented this round: Render's current deployment is a single
instance (verified via `render services` — no horizontal scaling
configured), so an in-process limiter (e.g. `slowapi`) would be
technically correct today but would silently stop working exactly when
the app is scaled to multiple instances, without any noisy failure
mode — a foot-gun this plan declines to introduce without also
documenting the scaling caveat prominently. Recommended approach:
`slowapi` (Starlette-native) for immediate protection, with an explicit
TODO to migrate to a shared store (Redis, or Postgres-backed) before or
at the same time as any horizontal scaling change. `[IMPLEMENTED — NOT
DEPLOYED]` is not accurate here since nothing has been written yet —
correctly `[FAIL]`, scheduled as a near-term follow-up rather than
blocking the rest of this plan's documentation deliverables.

## 10. File upload & malware scanning

Extension/content/size validation: `[PASS]` (§3 item 8). Malware/AV
scanning: `[FAIL]` — no scanner integrated. See
`docs/security/MALWARE_SCANNING_PLAN.md` for a design that can be
added without breaking the current upload flow (async post-upload
scan + quarantine state, reusing the existing `UploadJob.status`
state machine which already has a `quarantined` value defined but
currently only reachable via other logic — confirm and wire up).

## 11. Secrets

Working-tree secrets scan: `[PASS]` — `detect-secrets scan` run
against all real source directories (`backend/app`, `backend/tests`,
`frontend/app`, `frontend/components`, `frontend/lib`, root docs); zero
findings requiring `ROTATION REQUIRED`. Git history: not exhaustively
scanned this round (a full-history `detect-secrets` pass across every
commit was not run due to time; recommended as a near-term follow-up,
`[UNKNOWN]` for history, `[PASS]` for current working tree).
`.env`/`backend/.env` confirmed `.gitignore`d.

## 12. Dependency / supply-chain security

Python: `pip-audit` run before and after this round's fixes — see §3.
Deferred (documented, not forced): `starlette`, `pyasn1` (both blocked
by direct-dependency version constraints, need coordinated major-
version work — see §3). npm: `npm audit` — see §3, 11→0. GitHub
Actions: `[NOT APPLICABLE]` — no `.github/workflows` exists in this
repo (confirmed), so there is no Actions supply chain to audit yet;
becomes relevant once CI is added (§18).

## 13. Static & dynamic analysis

Not yet run this round: Bandit (Python SAST), Semgrep. `[UNKNOWN]` —
scheduled as a near-term follow-up; both can run safely against the
codebase with no production impact and should be added to CI (§18)
rather than run as a one-off.

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

`[FAIL]` — no CI exists at all (`.github/workflows` confirmed absent).
This is a genuine, sizable gap: none of this round's new regression
tests run automatically on any commit today; they only ran because
they were run manually. Designing and adding a real CI pipeline (fast
checks on every push — lint/typecheck/unit tests/secret-scan; heavier
checks — full pytest with DB, `pip-audit`/`npm audit`, Bandit/Semgrep —
on a scheduled/nightly job, per the user's explicit instruction not to
make every commit unusably slow) is in scope for this plan and tracked
as a near-term follow-up alongside rate limiting and the CNP fix.

## 19. Data retention & deletion

See `docs/privacy/RETENTION_POLICY.md` and `docs/privacy/DSAR_RUNBOOK.md`.
No `expires_at`-style automatic retention/cleanup exists for clinical
data today (deliberately — the user's instruction is explicit that no
speculative auto-deletion of clinical data may be added without legal
approval, since retention periods for health records are frequently
legally mandated minimums, not just privacy-driven maximums).

Deletion path re-audit: `DELETE /my/account` (patient self-deletion) —
`[PASS]` post-fix, §3 item 6. **Doctor, admin, care_partner, and
emergency_worker accounts have no self-deletion endpoint at all** —
`[FAIL]`, a real gap for DSAR/right-to-erasure requests from non-
patient users, tracked in the DSAR runbook as a manual-process fallback
until a proper endpoint exists.

## 20. Safe security testing rules (governs all testing under this plan)

Applies to every test written or run as part of this effort, permanently:
local/dev-environment and the shared Neon dev DB only, using synthetic
accounts created through the real signup endpoint, never production.
Never, against production or otherwise: brute-force/credential-stuffing
runs, automated SQL-injection scanners, load/DoS tests, rate-limit
flooding, malware-upload flooding, destructive deletion testing against
real user accounts, mass enumeration of `SourceEvidence`/document IDs,
intentional spend attacks against OpenAI/Reducto/Google, or destructive
database tests. All 20 regression tests added this round comply: they
run against the dev DB, use synthetic `@example.com` accounts created
via `/auth/signup`, and delete their own fixtures on teardown.

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
code). No data-minimization layer exists before any of the three
calls. `[FAIL]` for minimization; see the vendor docs for what each
vendor's own data-handling terms would need to say before this can be
called acceptable, which is not knowable from this codebase alone —
`[EXTERNAL ACTION]`/`[LEGAL REVIEW]` for the actual DPA/ZDR terms.

Ask Bragi (AI chat): does not exist in this codebase (confirmed via
exhaustive grep for conversation/chat/ask_bragi identifiers across
`backend/app`). All AI-chat-related items in this plan are forward-
looking design work, marked `[NOT APPLICABLE — FORWARD-LOOKING
REQUIREMENT DOCUMENTED]`, not `[FAIL]` (there's nothing to fail yet).

## 22. Backups & disaster recovery

See `docs/security/BACKUP_DR_PLAN.md`. `[UNKNOWN]` — Neon and Render's
actual backup/PITR configuration is an account/console-level setting
this codebase cannot verify. No restore test has been performed.

## 23. Regulatory posture (MDR / EU AI Act)

See `docs/regulatory/INTENDED_PURPOSE_DRAFT.md`. `[LEGAL REVIEW]` —
this document uses conservative language throughout and does NOT state
that Bragi is definitively outside MDR/EU-AI-Act scope, nor that it is
certified under either.

## 24. Residual risks (carried forward, not resolved this round)

1. Real `StaleDataError` race condition between account deletion and an
   in-flight background upload job (found via testing this round, not
   fixed — see §3 item 8's evidence and `backend/tests/test_upload_validation.py`'s
   fixture comment). Low likelihood (narrow timing window), but real.
2. No rate limiting (§9).
3. No malware scanning (§10).
4. CNP exposure in URLs/unmasked responses (§8).
5. No AI vendor data minimization (§21).
6. No token revocation mechanism (§15).
7. No CI (§18).
8. No non-patient-role self-deletion endpoint (§19).
9. `role` self-selection at signup with no server-side gate (§6) — needs a
   product decision.
10. `GET /admin/patients/search` has no scoping (§5) — needs a product
    decision.

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
| `docs/security/MALWARE_SCANNING_PLAN.md` | Done |
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
