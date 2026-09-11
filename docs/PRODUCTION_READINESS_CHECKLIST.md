# Production Readiness Checklist

The authoritative, evidence-cited status document for the Bragi
security/GDPR/privacy hardening effort. Every `[PASS]` below is backed
by a specific test name, request/response, or diff — not by code
appearance or documentation existence alone, per this task's own
evidence standard. See `BRAGI_SECURITY_GDPR_PLAN.md` for the full
narrative; this document is the compact checklist form of it, "the
launch checklist."

## Security — implemented & verified

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Security response headers (backend, defense-in-depth) | `[PASS]` | `security_headers_middleware`, `backend/app/main.py`; curl-verified |
| 2 | CSP + security headers (frontend, browser-rendered surface) | `[PASS]` | `frontend/next.config.ts`; real Playwright/Chromium session, zero CSP violations across login/records/document/upload/PDF-viewer pages; curl-verified |
| 3 | Next.js critical CVE fix (16.2.4→16.3.4) | `[PASS]` | `npm audit` 11→0 |
| 4 | Login timing side-channel fixed | `[PASS]` | `verify_password_timing_safe()`, `backend/app/auth.py` |
| 5 | Password minimum length (8 chars) | `[PASS]` | `SignupRequest.password` field constraint |
| 6 | Account-deletion FK-cascade gaps fixed (4 tables) | `[PASS]` | Live reproduction: 500→200; DB-verified audit-trail preservation |
| 7 | `is_active` doctor-access staleness fixed (2 endpoints) | `[PASS]` | `test_idor_regression.py::test_revoked_doctor_access_is_denied_immediately` |
| 8 | File upload validation (extension/magic-byte/size) | `[PASS]` | `test_upload_validation.py`, 6 tests |
| 9 | PHI removed from `ai_extract.py` logs | `[PASS]` | Diff + full-file review |
| 10 | Info-disclosure fix (raw exception text in responses) | `[PASS]` | Diff, 2 handlers |
| 11 | Cross-patient/cross-role IDOR regression suite | `[PASS]` | `test_idor_regression.py`, 10 tests, real dev DB |
| 12 | Security-header regression suite | `[PASS]` | `test_security_headers.py`, 4 tests |
| 13 | Python dependency CVEs (jose, multipart, dotenv) | `[PASS]` | `pip-audit` before/after |
| 14 | npm dependency CVEs (8 non-Next.js) | `[PASS]` | `npm audit` 0 remaining |
| 15 | Undeclared/unbounded dependency gaps fixed | `[PASS]` | `backend/requirements.txt` pinned |
| 16 | SQL injection surface | `[PASS]` | 100% ORM query construction, no raw string-built SQL in application code (code review of every `db.query()` site) |
| 17 | `dangerouslySetInnerHTML` usage | `[PASS]` (zero found) | Repo-wide grep |
| 18 | Unsafe iframes | `[PASS]` | CSP `frame-src 'none'` |
| 19 | CSRF applicability | `[NOT APPLICABLE]` | Zero cookie usage anywhere (grep-confirmed); bearer-token-only auth |
| 20 | SSRF surface | `[NOT APPLICABLE]` | No user-supplied-URL-fetch feature exists |
| 21 | Secrets in working tree | `[PASS]` | `detect-secrets` scan, 0 findings |
| 22 | Emergency/break-glass access design | `[PASS]` | Direct code read: opt-in, 30-min server-enforced expiry, full audit trail, CNP masked in search |
| 23 | Analytics/monitoring PHI leakage | `[NOT APPLICABLE]` | No analytics/monitoring SDK exists in the codebase |
| 24 | Secrets in git history | `[PASS]` | gitleaks v8.30.1, full 245-commit history; 1 finding, reviewed false positive; no ROTATION REQUIRED — `docs/security/SECRET_SCAN_HISTORY.md` |
| 25 | Static analysis (Bandit/Semgrep) | `[PASS]` | 0 High from either tool; 2 Medium reviewed as false positives (fixed-constant URLs, not SSRF) and suppressed with reasoned `# nosec` — `docs/security/STATIC_ANALYSIS.md`; now gated in CI |
| 26 | Rate limiting | `[PASS]` mechanism + in-memory backend; `[IMPLEMENTED — NOT DEPLOYED]` distributed Redis backend | `backend/app/rate_limit.py`, 14 tests + real live 429/Retry-After verification — `docs/security/RATE_LIMITING.md` |
| 27 | Malware/AV scanning of uploads | `[PASS]` pipeline boundary + heuristic screen; `[FAIL]`/`[EXTERNAL ACTION]` real AV engine | `backend/app/services/security_scan.py`, 9 tests incl. real end-to-end quarantine of an actual malicious PDF — `docs/security/MALWARE_SCANNING_PLAN.md` |
| 28 | CNP minimization in responses/URLs | `[PASS]` | CNP removed from URLs entirely (POST-only for CNP search); masked in every list/search response; full value only to the patient's own profile view — `backend/tests/test_cnp_identifier_minimization.py`, 10 tests; `BRAGI_SECURITY_GDPR_PLAN.md` §8 |
| 29 | CNP/identifier encryption at rest | `[FAIL]` | Plaintext columns; design only, deliberately not migrated (`docs/security/IDENTIFIER_ENCRYPTION_PLAN.md`) |
| 30 | Row-Level Security (RLS) | `[FAIL]` for "enabled"; design exists | Not implemented — `docs/security/RLS_PLAN.md`; absence assessed as defense-in-depth gap, not a currently-exploitable hole, since app-layer authorization is independently verified working |
| 31 | Token revocation / session denylist | `[FAIL]` | No mechanism exists; logout is client-side only |
| 32 | Full production-error-handling audit (beyond the 2 fixed leaks) | `[UNKNOWN]` | Not exhaustively re-reviewed this round |
| 33 | Open-redirect audit (frontend) | `[UNKNOWN]` | Not performed this round |
| 34 | Document-DELETE authorization re-verification | `[UNKNOWN]` | READ routes were this round's IDOR-suite focus; DELETE not equivalently covered |
| 35 | CI security gates | `[PASS]` | `.github/workflows/ci.yml` + `nightly-security.yml`, confirmed with real GitHub Actions runs (including one real caught-and-fixed failure) — `docs/security/CI_PIPELINE.md` |

## Privacy / GDPR — documentation & design

| # | Item | Status |
|---|---|---|
| 36 | Threat model | `[PASS]` (documented; `[INDEPENDENT VALIDATION]` recommended for real assurance) — `docs/security/THREAT_MODEL.md` |
| 37 | Data map | `[PASS]` (documented, code-verified against all 20 DB tables) — `docs/privacy/BRAGI_DATA_MAP.md` |
| 38 | Controller/processor determination | `[LEGAL REVIEW]` — `docs/privacy/CONTROLLER_PROCESSOR_MAP.md` |
| 39 | Processing purposes / legal basis | `[LEGAL REVIEW]` for final basis; documented working assumptions — `docs/privacy/PROCESSING_PURPOSES.md` |
| 40 | Authorization matrix | `[PASS]` (documented + tested) — `docs/security/AUTHORIZATION_MATRIX.md` |
| 41 | Vendor register | `[PASS]` (documented); DPA status `[UNKNOWN]` per vendor — `docs/privacy/VENDOR_REGISTER.md` |
| 42 | International transfer register | `[UNKNOWN]` throughout — `docs/privacy/TRANSFER_REGISTER.md` |
| 43 | Retention policy | `[LEGAL REVIEW]` for clinical-data limits; no auto-deletion implemented (deliberately) — `docs/privacy/RETENTION_POLICY.md` |
| 44 | DSAR runbook | `[PASS]` (documented); export feature `[PASS]` (`POST /my/export`, patient role, 8 tests); non-patient-role erasure `[PASS]` for care_partner (real delete) and doctor/admin (soft-delete, `[LEGAL REVIEW]`ed), `[FAIL]`/`[PRODUCT DECISION REQUIRED]` for emergency_worker — `docs/privacy/DSAR_RUNBOOK.md` |
| 45 | Privacy notice | `[LEGAL REVIEW]`, not published — `docs/privacy/PRIVACY_NOTICE_DRAFT.md` |
| 46 | DPIA | `[LEGAL REVIEW]`, draft only — `docs/privacy/DPIA_DRAFT.md` |
| 47 | ROPA | `[LEGAL REVIEW]`, draft only — `docs/privacy/ROPA_DRAFT.md` |
| 48 | Backup/DR plan | `[UNKNOWN]` — no restore test performed; uploaded-file durability flagged as a bigger concern than DB backups — `docs/security/BACKUP_DR_PLAN.md` |
| 49 | Incident response plan | `[PASS]` (documented procedure); detection tooling `[FAIL]` (none exists) — `docs/security/INCIDENT_RESPONSE.md` |
| 50 | Production access policy | `[UNKNOWN]` for current enforcement; policy documented — `docs/security/PRODUCTION_ACCESS_POLICY.md` |
| 51 | Key rotation runbook | `[PASS]` (documented procedure); `SECRET_KEY` rotation has no graceful dual-key window (real gap, noted) — `docs/security/KEY_ROTATION_RUNBOOK.md` |
| 52 | AI governance / Ask Bragi | `[IMPLEMENTED — NOT DEPLOYED]` — Ask Bragi built this round (feature-flagged off); every forward-looking §2 item in `docs/ai/AI_GOVERNANCE.md` is now a tested control — `BRAGI_ASK_BRAGI_PLAN.md` |
| 53 | AI vendor data-minimization (existing pipeline) | `[PASS]` for the reusable boundary + this round's audit (every existing call sends only the document itself, no separate patient-context object — nothing to strip); `[EXTERNAL ACTION]`/`[LEGAL REVIEW]` for vendor DPA/ZDR terms, unchanged — `app/services/ai_minimization.py`, `docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md` |
| 54 | MDR/EU AI Act boundary statement | `[LEGAL REVIEW]`, conservative language, no certification claimed — `docs/regulatory/INTENDED_PURPOSE_DRAFT.md` |

## Never claimed (explicitly, per this task's own rules)

This effort does **not** claim GDPR compliance, HIPAA compliance, MDR
certification, EU AI Act compliance, ISO 27001 certification, or SOC 2
attestation. None of these has been externally established. Every
`[LEGAL REVIEW]`/`[EXTERNAL ACTION]`/`[INDEPENDENT VALIDATION]` item
above remains open until a party outside this engineering effort
completes it.

## What actually shipped to production this round

### Round 1 — three commits, all deployed and confirmed live
- `b4ad7dc` — dependency upgrades (Python CVEs)
- `5ceec0c` — backend security hardening (headers, auth timing, FK
  fixes, upload validation, PHI-in-logs, authorization staleness, 20
  new regression tests)
- `7142646` — frontend CSP/security headers + Next.js critical CVE fix

Render deploy `dep-daheeitckfvc73bq8bug` for commit `7142646`: status
`live`. Vercel production deployment (same push): status `Ready`. Both
confirmed 2026-09-10.

### Round 2 — eight commits, all pushed and CI-confirmed green

`807f2fd` (CNP URL fix + response minimization + AI-minimization
boundary), `c1d06a3` (rate limiting), `fce4652`/`326908d`/`8e61f24`/
`9f5618f` (secret history scan + static analysis + CI pipeline —
including a real CI-caught-and-fixed Bandit finding), `7292b0d` (DSAR
export), `9f6f55b` (deletion completeness), `77c8f48` (malware-scanning
pipeline boundary), `9f4f0df` (CNP regression suite). Every commit
independently production-safe (additive, backward-compatible) per this
plan's own rule. Full backend suite: 138 tests passing, confirmed both
locally and in a real GitHub Actions run against a fresh ephemeral
Postgres instance.

## Highest-priority next steps (updated after round 2)

Round 1's list (rate limiting, CNP minimization, CI, malware scanning,
git-history secret scan, static analysis, AI vendor data minimization,
DSAR export, non-patient-role self-deletion) is now `[PASS]` — see the
table above and `BRAGI_SECURITY_GDPR_PLAN.md` §3a for the consolidated
evidence. Carried forward:

1. Rectification/change-history mechanism (`docs/privacy/DSAR_RUNBOOK.md`)
   — still not implemented; edits still silently overwrite prior values
   with no change history.
2. A real antivirus engine (`[EXTERNAL ACTION]` — vendor selection) —
   the pipeline boundary exists but nothing is connected.
3. Distributed (Redis) rate-limit backend in the actual Render
   environment (`[EXTERNAL ACTION]`/config-only) — the mechanism exists,
   `RATE_LIMIT_REDIS_URL` isn't set yet.
4. DSAR export for non-patient roles (doctor/admin/care_partner/
   emergency_worker) — smaller personal-data footprint, lower priority.
5. `emergency_worker` self-deletion — `[PRODUCT/LEGAL DECISION
   REQUIRED]`, see `docs/EXTERNAL_COMPLIANCE_ACTIONS.md`.
6. Whether doctor/admin soft-delete is the correct final erasure policy
   — `[LEGAL REVIEW]`, see `docs/EXTERNAL_COMPLIANCE_ACTIONS.md`.
7. Token revocation mechanism (§15 of the plan) — unchanged, still open.
8. `role` self-selection at signup, `/admin/patients/search` scoping —
   both still `[PRODUCT DECISION REQUIRED]`, unchanged.

See `docs/EXTERNAL_COMPLIANCE_ACTIONS.md` for the full consolidated list
of everything that needs a vendor, a legal determination, or a product
decision outside this engineering effort.

This checklist is a living document — update status labels and evidence
citations as each item above is actually completed and verified, never
in advance of the evidence.
