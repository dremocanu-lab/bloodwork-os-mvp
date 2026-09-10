# Bragi Threat Model

Status: living document, engineering-owned. Last updated alongside the
security/GDPR hardening round documented in `BRAGI_SECURITY_GDPR_PLAN.md`.
This is not a substitute for independent penetration testing or a formal
DPIA sign-off (see `docs/privacy/DPIA_DRAFT.md`).

## 1. System summary

Bragi is a clinical-records web application: a FastAPI backend
(`backend/app/main.py`, one file, ~5900 lines) backed by Postgres (Neon),
and a Next.js frontend (`frontend/`). Patients upload medical documents;
Reducto and/or OpenAI/Google Document AI extract structured lab data from
them; doctors, PCPs, care partners, and emergency workers get scoped
access to patient records under different rules. No AI chat ("Ask
Bragi") feature is implemented yet — see `docs/ai/AI_GOVERNANCE.md` for
what governs it when it is.

## 2. Assets

| Asset | Where it lives | Sensitivity |
|---|---|---|
| Credentials (password hashes) | `users.password_hash` (bcrypt) | High |
| Session tokens (JWT, bearer) | Client `localStorage`, never server-persisted | High |
| CNP (Romanian national ID) | `patients.cnp`, `documents.cnp`, in most authenticated API responses | Very high (direct identifier + special-category-adjacent) |
| Patient identity (name, DOB, sex, MRN) | `patients.*`, duplicated per-document on `documents.*` | High |
| Uploaded medical documents (raw files) | Local disk (`UPLOAD_DIR`), served via `/documents/{id}/file` | Very high (raw PHI) |
| Extracted structured data (labs, meds, notes) | `lab_results`, `patient_medications`, `documents.extracted_text`/`parsed_content` | Very high |
| SourceEvidence (bbox + source text citations) | `source_evidence` | High (PHI excerpts) |
| Clinician access grants | `doctor_patient_access` | High (controls PHI access) |
| Emergency access sessions | `emergency_access_sessions`, `emergency_audit_logs` | High (audit trail of PHI access) |
| Audit records | `audit_logs`, `admin_action_logs`, `emergency_audit_logs` | High (integrity-sensitive) |
| Vendor API keys (Reducto, OpenAI, Google) | Render/Vercel env vars only, never in the repo | Very high |
| Database credentials | `DATABASE_URL` env var | Very high |
| JWT signing secret | `SECRET_KEY` env var | Very high (compromise = forge any session) |

## 3. Threat actors

- **Anonymous attacker** — no account, internet-reachable API/frontend.
- **Authenticated malicious patient** — a real account, tries to reach
  other patients' data.
- **Unauthorized clinician** — a doctor account with no assignment to a
  given patient.
- **Clinician with revoked access** — assignment `is_active` recently
  flipped to 0.
- **Malicious/compromised care partner** — a real care-partner account,
  tries to exceed its explicit per-document share scope.
- **Compromised admin** — admin credentials phished/leaked; admin has a
  near-blanket `can_access_patient` bypass (see
  `docs/security/AUTHORIZATION_MATRIX.md`).
- **Compromised vendor credential** — a leaked `REDUCTO_API_KEY` /
  `OPENAI_API_KEY` / `DATABASE_URL`.
- **Malicious uploaded document** — a file crafted to exploit a parser,
  spoof its type, or (once an AI chat feature exists) carry a prompt-
  injection payload.
- **Compromised frontend** — XSS in the Next.js app, or a compromised
  npm dependency in the build chain.
- **Emergency-access abuser** — an `emergency_worker` account used to
  browse patients without a genuine emergency reason.
- **Accidental internal disclosure** — a developer with dev-DB access
  who mixes dev/prod, or pastes PHI into a log/ticket/chat.

## 4. Threat scenarios

Each row: asset, entry point, likelihood (Low/Med/High, engineering
estimate — not a formal risk-scoring exercise), impact, existing
controls, planned/residual controls, evidence.

### 4.1 IDOR / broken access control (cross-patient)

- Entry point: any route taking `document_id`/`patient_id`/
  `lab_result_id`/`source_evidence_id`.
- Likelihood: Med (this is the single most consequential class of bug
  for this product). Impact: Critical (PHI of a real, different patient).
- Existing controls: `can_access_patient()` gates the overwhelming
  majority of these routes (verified route-by-route — see
  `docs/security/AUTHORIZATION_MATRIX.md`); `/source-evidence/{id}/view`,
  `/lab-results/{id}/source`, `/documents/{id}/file` all resolve up to
  the owning `Document.patient_id` before authorizing, and never return
  a bare/public file URL.
- Found and fixed this round: `GET /patients` and `GET /my-patients`
  did not filter `DoctorPatientAccess.is_active == 1`, so a revoked
  doctor still saw the patient's card in those two list views (not the
  detail/document routes, which were already correctly filtered).
  Fixed.
- Residual: `GET /admin/patients/search` has no department/hospital
  scoping (contrast with `/admin/doctors`, which does) — any admin can
  search/see any patient system-wide. This may be intentional (admin is
  already a near-blanket role in this app) but is worth an explicit
  product decision — see `docs/security/AUTHORIZATION_MATRIX.md`.
- Evidence: `backend/tests/test_idor_regression.py` — 10 automated,
  DB-backed regression tests (cross-patient profile/document/trends
  access, unassigned-doctor denial, revoked-doctor-denied-immediately,
  care-partner scope limits, unauthenticated/malformed-token rejection).
  `[PASS]` for the routes covered by those tests.

### 4.2 Credential stuffing / brute force

- Entry point: `POST /auth/login`.
- Likelihood: Med. Impact: High (a successfully-guessed patient
  password exposes that patient's full record).
- Existing controls: bcrypt hashing (slow by design), account-
  enumeration-safe error message.
- Gaps: **no rate limiting or lockout exists on `/auth/login` or
  `/auth/signup`** — confirmed by code search, no rate-limiting library
  is even installed. `[FAIL]` — no automated brute-force protection
  today. See `BRAGI_SECURITY_GDPR_PLAN.md` for the rate-limiting phase
  (not implemented this round — needs a decision on in-process vs.
  shared-store limiting given Render's current single-instance
  deployment, see item 22 there).

### 4.3 Account enumeration

- Entry point: `/auth/login`, `/auth/signup`.
- Likelihood: High (trivial to script). Impact: Low-Med (confirms an
  email has an account; doesn't itself expose PHI).
- Existing controls: `/auth/login`'s error message is enumeration-safe.
- Found and fixed this round: `/auth/login`'s response **timing** was
  not enumeration-safe (a nonexistent-email request skipped bcrypt
  entirely) — fixed with `verify_password_timing_safe()`, which always
  pays real bcrypt cost. `/auth/signup` still returns a distinct "Email
  already exists" error — a deliberate product trade-off (users need to
  know an email is taken to recover access) rather than a bug; flagged
  for a product decision in the plan doc rather than silently changed.

### 4.4 Privilege escalation via self-selected role

- Entry point: `POST /auth/signup`'s `role` field.
- Likelihood: Med. Impact: Critical if unmitigated.
- Finding: `role` is entirely client-supplied at signup, restricted to
  `{patient, doctor, admin, care_partner, emergency_worker}`, with **no
  server-side gate other than `care_partner_code`** for the
  `care_partner` role. A client can `POST /auth/signup` with
  `role: "admin"` and get an admin account outright.
- Impact assessment: this needs a real product decision, not a silent
  engineering fix (admin/doctor account provisioning may be an
  intentionally open self-service flow for this product's current
  stage, or it may be a real gap) — flagged as `[UNKNOWN — PRODUCT
  DECISION REQUIRED]` in `BRAGI_SECURITY_GDPR_PLAN.md`. Not changed
  this round to avoid breaking whatever the current onboarding flow for
  doctors/admins actually is without confirming intent first.

### 4.5 SQL injection

- Entry point: every query parameter.
- Likelihood: Low. Impact: Critical if present.
- Controls: 100% SQLAlchemy ORM query construction observed across
  `main.py` (no raw string-interpolated SQL found in application query
  code — the only raw `text()` SQL is in `run_migrations()`, which
  takes no user input). `[PASS]` — evidence: code review of every
  `db.query(...)` call site during this round's audit; no dynamic SQL
  string building found.

### 4.6 XSS

- Entry point: any user-controlled string rendered in the frontend
  (document names, patient names, note bodies, AI output once it
  exists).
- Likelihood: Low-Med. Impact: High (token theft, since the JWT lives
  in `localStorage`, not an `HttpOnly` cookie).
- Controls: React's default JSX escaping protects most rendering paths.
  Repo-wide search for `dangerouslySetInnerHTML` found **zero uses** in
  `frontend/app` or `frontend/components` — confirmed via grep, not
  assumed. New this round: a real CSP (`frontend/next.config.ts`) with
  `script-src 'self' 'unsafe-inline'` (no `'unsafe-eval'`), `object-src
  'none'`, restrictive `default-src` — real defense-in-depth even
  though no injection point was found. `[PASS]` — evidence: grep + the
  CSP itself, live-verified against a real browser session (zero
  console violations across every page tested, including the PDF
  viewer).

### 4.7 CSRF

- Not applicable in the traditional sense: auth is 100% bearer-token
  (`Authorization` header from `localStorage`), zero cookie usage
  anywhere in the app (confirmed via grep for `set_cookie`/
  `document.cookie`/`withCredentials` — no matches). A CSRF attack
  relies on the browser automatically attaching credentials (cookies);
  there is nothing here for it to attach. `[NOT APPLICABLE]`.

### 4.8 SSRF

- Entry point: none found. The app never fetches a URL supplied by a
  request body/param (Reducto/OpenAI calls always target the vendor's
  own fixed API host; no "fetch this URL and process it" feature
  exists). `[NOT APPLICABLE]` today — revisit if a future feature (e.g.
  fetching a document from a URL) is added.

### 4.9 Malicious upload / file-type spoofing

- Entry point: `/upload`, `/upload/background`, `/upload/batch`.
- Likelihood: Med. Impact: Med (served back with the client's own
  claimed Content-Type; no code path executes an uploaded file).
- Found and fixed this round: no extension allowlist, no content
  verification, no size limit existed before this round — any
  extension (`.exe`, `.php`, ...) was accepted verbatim, and a
  malicious payload could be saved with a spoofed extension (e.g. HTML
  content saved as `.pdf`). Fixed: extension allowlist matching the
  product's actual supported formats, real magic-byte verification for
  PDF/PNG/JPEG/WEBP/TIFF, a 50MB streaming size cap. Verified live (see
  `backend/tests/test_upload_validation.py`).
- Residual: **no malware/antivirus scanning exists** — file-type
  validation is not malware scanning. See
  `docs/security/MALWARE_SCANNING_PLAN.md`. `[IMPLEMENTED — NOT
  DEPLOYED]` for the scanning boundary design; no scanner is wired up.
- Residual: uploaded files are stored on **local disk**, not encrypted
  object storage — see `docs/security/IDENTIFIER_ENCRYPTION_PLAN.md`/
  the data-map for storage-at-rest notes.

### 4.10 Storage / source enumeration

- Entry point: guessing a `document_id` or `source_evidence_id`.
- Likelihood: Med (sequential integer IDs are guessable). Impact: High
  if unauthorized.
- Controls: every route resolving these IDs re-checks
  `can_access_patient` before returning anything — knowing an ID is not
  sufficient, confirmed by `test_idor_regression.py`'s
  `test_nonexistent_document_is_404_not_500_or_leak` and the cross-
  patient tests. Files are stored under randomized UUID filenames on
  disk (never the original filename) and are never served from a
  public/unauthenticated path. `[PASS]`.

### 4.11 CNP leakage

- Entry points: API responses (most return full CNP), `GET /emergency/
  search?type=cnp&q=<CNP>` (full CNP in a URL query string), logs.
- Likelihood: Med. Impact: High (CNP is a direct, high-sensitivity
  national identifier).
- Found, not fixed this round (flagged for a dedicated pass — see
  `BRAGI_SECURITY_GDPR_PLAN.md` item 9): CNP appears in full in most
  authenticated JSON responses; masking exists in only 3 frontend list
  views (`admin/doctors/[id]`, `assignments`, `patients/search`), not
  in detail/edit views or in the emergency-search backend serializer's
  raw field (a separate `_mask_cnp()` helper exists and IS applied to
  the emergency-search list endpoint specifically). The
  `/emergency/search` GET-query-string exposure is real but behind
  `require_emergency_role()` auth; query strings can still land in
  access/proxy logs. `[FAIL]` for comprehensive minimization; `[PASS]`
  for "never unauthenticated."
- Confirmed clean: no CNP found in application logs (`print()`/
  `logging` call sites reviewed) or in `REDUCTO_TIMING` log lines
  (explicitly documented PHI-free in `reducto_client.py`).

### 4.12 Log leakage (PHI in logs)

- Found and fixed this round: `ai_extract.py`'s OpenAI-fallback
  extraction path printed the real `patient_name` on every successful
  extraction and up to 1200 chars of raw (potentially PHI-bearing)
  model output on parse failure. Fixed to log only safe metadata. See
  `BRAGI_SECURITY_GDPR_PLAN.md`. `[PASS]` post-fix, evidence: diff +
  code review of every remaining `print()`/exception-handler call site
  in `backend/app/*.py`.

### 4.13 Prompt injection / cross-patient AI retrieval

- Not applicable today — no AI chat feature is implemented (confirmed:
  zero `conversation`/`chat_message`/`ask_bragi` matches anywhere in
  the backend). Documented as a forward-looking requirement in
  `docs/ai/AI_GOVERNANCE.md` for whenever Ask Bragi is built: patient
  context must be injected server-side, never taken as a model-
  controllable argument, and every tool call must independently
  re-authorize. `[NOT APPLICABLE — FORWARD-LOOKING REQUIREMENT
  DOCUMENTED]`.

### 4.14 Vendor data overexposure (Reducto / OpenAI)

- Entry point: every document upload.
- Likelihood: High (happens on every upload by design). Impact:
  depends entirely on each vendor's own data-handling terms — see
  `docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md` and
  `docs/vendors/REDUCTO_PRODUCTION_REQUIREMENTS.md`.
- Facts (confirmed by code review, not vendor-console review): the
  **full original uploaded file** goes to Reducto (classify/parse/
  extract/split all operate on the whole file); OpenAI's fallback
  extraction path sends a **full rendered page image** plus up to
  12,000 chars of raw OCR text, and the discharge-summary path sends
  the **entire uploaded file** as a base64 data URL. Neither path
  redacts identity fields before sending — both explicitly ask the
  model to extract CNP/name/DOB as part of the structured output. No
  data-minimization layer exists before either vendor call today.
  `[FAIL]` for data minimization to AI vendors — a real, substantial
  gap, not a paperwork one. See the plan doc's phase list.

### 4.15 Accidental dev/prod mixing

- Entry point: environment configuration.
- Likelihood: Low-Med (already happened once — see `dfd0cf7` /
  `documents.is_verified` schema-drift history). Impact: Critical if a
  dev process ever wrote to the production DB, or vice versa.
- Controls: `ENVIRONMENT` env var gates `SECRET_KEY` strength
  enforcement; `DATABASE_URL`/`REDUCTO_API_KEY`/`OPENAI_API_KEY` are
  all environment-scoped via Render/Vercel env vars, never hardcoded.
  No automated "fail closed if DATABASE_URL looks like production but
  ENVIRONMENT says development" guard exists yet — flagged in the plan
  doc as a cheap, safe addition worth doing.

### 4.16 Destructive deletion / data loss

- Entry point: `DELETE /my/account`, `DELETE /documents/{id}`.
- Likelihood: Low (requires the account owner's own token). Impact:
  High if buggy (orphaned PHI, or an unrelated user's data caught by a
  bad filter).
- Found and fixed this round: four more FK-cascade gaps in `DELETE
  /my/account` beyond the two already fixed in an earlier round (see
  `BRAGI_SECURITY_GDPR_PLAN.md`) — reproduced live, fixed, re-verified
  live. `[PASS]` post-fix for every table now covered; see the
  authorization/deletion sections of the plan doc for the exhaustive
  table-by-table check.
- Residual: a real race condition was found (not fixed) between
  account deletion and an in-flight background upload job for the same
  account — see the plan doc's residual risks.

### 4.17 Backup failure / ransomware / data loss at the infra layer

- Not verifiable from this codebase — depends on Neon's own backup/PITR
  configuration, which is account/console-level, not code-level. See
  `docs/security/BACKUP_DR_PLAN.md`. `[UNKNOWN]` until verified against
  the actual Neon project settings.

### 4.18 Insider access / production access governance

- Not verifiable from this codebase — depends on who actually holds
  Render/Vercel/Neon/Reducto/OpenAI/GitHub credentials and whether
  MFA/least-privilege is enforced on those accounts. See
  `docs/security/PRODUCTION_ACCESS_POLICY.md`. `[UNKNOWN]`.

### 4.19 Emergency-access abuse

- Entry point: `POST /emergency/access-sessions`.
- Likelihood: Low-Med (requires a real `emergency_worker` account).
  Impact: High (grants real PHI access).
- Controls: patient opt-in required (`emergency_search_enabled`),
  30-minute fixed session expiry enforced server-side at read time (no
  reliance on frontend state), max 8 concurrent sessions per worker,
  every step audit-logged (`emergency_audit_logs`) with reason text,
  IP, and user agent, CNP masked in search results, sessions
  automatically revoked when a patient disables discoverability.
  `[PASS]` — this is a genuinely well-built break-glass mechanism;
  verified by direct code read of every step in this round's audit
  (see `BRAGI_SECURITY_GDPR_PLAN.md`'s emergency-access section).
- Gap: nothing currently *reviews* emergency-access audit logs for
  abuse patterns (e.g. a worker opening many sessions with vague
  reasons) — a process/monitoring gap, not a code gap. See
  `docs/security/PRODUCTION_ACCESS_POLICY.md` and item 67 of the plan
  doc.

## 5. Out of scope for this document

Formal penetration testing, fuzzing, and independent security review —
see `docs/PRODUCTION_READINESS_CHECKLIST.md`'s `[INDEPENDENT
VALIDATION]` items. This threat model is an engineering self-assessment,
not a substitute for one.
