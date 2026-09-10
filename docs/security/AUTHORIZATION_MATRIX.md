# Authorization Matrix

Source: `backend/app/main.py`'s authorization primitives, read directly
(not inferred): `require_role()` (line 644), `can_access_patient()`
(line 742), `doctor_has_patient_access()` (line 729),
`care_partner_can_access_document()` (line 758), `require_pcp_or_admin()`
(line 2703), `require_emergency_role()` (line 5539). There is no
separate policy engine — authorization is these six functions, applied
consistently at each route. This matrix is the result of reviewing the
route surface against them this round, not a specification written in
advance of the code.

## Roles

- **PATIENT** — `users.role == "patient"`, has exactly one linked
  `patients` row (`patients.linked_user_id`).
- **DOCTOR** — `users.role == "doctor"`. Gains per-patient access only
  via an active `doctor_patient_access` row.
- **PCP / FAMILY DOCTOR** — NOT a separate role. Same `users.role ==
  "doctor"` row, with `doctor_type == "pcp"`. Gates access to `/pcp/*`
  routes via `require_pcp_or_admin()`; patient-level access is the same
  `doctor_patient_access` mechanism as any other doctor.
- **CARE PARTNER** — `users.role == "care_partner"`. Has NO general
  patient-record access (`can_access_patient()` returns `False`
  unconditionally for this role) — access is exclusively per-document,
  via `SharedStructuredPage` rows created when a patient explicitly
  shares a specific document.
- **ADMIN** — `users.role == "admin"`. `can_access_patient()` returns
  `True` unconditionally for admin — a deliberate, broad grant, not a
  bug; see the residual-risk note below.
- **EMERGENCY** — `users.role == "emergency_worker"`. Does not use
  `can_access_patient()` at all; gated entirely through
  `require_emergency_role()` + an active `EmergencyAccessSession`
  (see §"Emergency access" below).

## Resource × action matrix

Legend: ✅ allowed via the named mechanism, ❌ never allowed, 🔶
conditional (see note).

| Resource | PATIENT | DOCTOR (assigned) | DOCTOR (unassigned) | CARE PARTNER | ADMIN | EMERGENCY |
|---|---|---|---|---|---|---|
| Own/patient profile (READ) | ✅ own only | ✅ via `doctor_has_patient_access` | ❌ | ❌ (no profile route) | ✅ (blanket) | 🔶 active session only |
| Patient identity fields (READ) | ✅ own | ✅ | ❌ | ❌ | ✅ | 🔶 masked CNP in search, full in an active session |
| Documents (READ) | ✅ own | ✅ | ❌ (404, not 403 — no ID-existence leak, see `test_idor_regression.py`) | 🔶 shared documents only, via `SharedStructuredPage` | ✅ | 🔶 active session only |
| Document raw file (READ) | ✅ own | ✅ | ❌ | 🔶 shared documents only — `care_partner_can_access_document()` explicitly checked before `/documents/{id}/file` serves bytes | ✅ | 🔶 |
| Documents (CREATE/upload) | ✅ own | ✅ (on behalf of assigned patient) | ❌ | ❌ | ✅ | ❌ |
| Documents (DELETE) | ✅ own | 🔶 — needs confirming per-route (not exhaustively re-verified this round beyond the deletion-path audit in `BRAGI_SECURITY_GDPR_PLAN.md` §19) | ❌ | ❌ | ✅ | ❌ |
| Labs / LabResult (READ) | ✅ own | ✅ | ❌ | 🔶 via parent document share | ✅ | 🔶 |
| SourceEvidence (READ) | ✅ own | ✅ | ❌ | 🔶 via parent document share | ✅ | 🔶 |
| Timeline / PatientEvent | ✅ own | ✅ | ❌ | ❌ | ✅ | 🔶 |
| Medications (READ/CREATE/UPDATE) | ✅ own | ✅ | ❌ | ❌ | ✅ | 🔶 |
| Sharing (grant/revoke care-partner access) | ✅ (own patient only, via care-partner code flow) | ❌ | ❌ | ❌ (recipient, not grantor) | ✅ | ❌ |
| Access grants (doctor↔patient) | 🔶 request/approve own | ✅ request own | ❌ | ❌ | ✅ full control | ❌ |
| AI extraction trigger (upload pipeline) | ✅ own uploads | ✅ assigned-patient uploads | ❌ | ❌ | ✅ | ❌ |
| Exports | 🔶 own data — see `BRAGI_SECURITY_GDPR_PLAN.md`/DSAR runbook for current state (not confirmed to exist as a dedicated feature) | — | — | — | — | — |
| Account deletion (self) | ✅ (`DELETE /my/account`) | ❌ no endpoint exists | — | ❌ no endpoint exists | ❌ no endpoint exists | ❌ no endpoint exists |
| Admin actions (role/access management) | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Audit log (READ) | ❌ no user-facing route found | ❌ | ❌ | ❌ | ✅ (`admin_action_logs`, implicitly via admin routes) | ❌ |
| Emergency access session (create/use) | ❌ (opt-in only, via `emergency_search_enabled`) | ❌ | ❌ | ❌ | ❌ | ✅ own sessions, 30-min expiry, audited |

## Emergency access — how it actually works

Emergency access is layered on the **same** login/JWT system, not a
parallel auth stack: an `emergency_worker` logs in through the normal
`/auth/login`, then calls `POST /emergency/access-sessions` (gated by
`require_emergency_role()`) to open a time-boxed session against one
opted-in patient. Every read route that serves patient data checks for
an active, non-expired session for that specific patient/worker pair —
verified by direct code read this round, not assumed. Key controls
(see `docs/security/THREAT_MODEL.md` §4.19 for the full write-up):
patient opt-in (`emergency_search_enabled`) required, 30-minute
server-enforced expiry, max 8 concurrent sessions per worker, full
audit trail (`emergency_audit_logs`) including IP/user-agent/reason
text, CNP masked in search results. `[PASS]`.

## Known residual items (not silently fixed — see `BRAGI_SECURITY_GDPR_PLAN.md`)

1. **Admin is a blanket-access role** (`can_access_patient()` returns
   `True` unconditionally for `role == "admin"`, and `/admin/patients/
   search` has no department/hospital scoping unlike `/admin/doctors`).
   This may be intentional for the product's current stage. Flagged as
   a product decision, not changed unilaterally (§5/§6 of the plan doc).
2. **`role` at signup is self-selected** with no server-side gate for
   `doctor`/`admin` beyond a code for `care_partner` — see plan doc §6.
3. **Document DELETE authorization** was not re-verified route-by-route
   with the same rigor as READ routes this round (READ routes were the
   focus of the IDOR regression suite); flagged as a follow-up.
4. Fixed this round (previously a real gap): `GET /patients` and
   `GET /my-patients` did not filter `is_active == 1` on
   `DoctorPatientAccess` — a revoked doctor still saw the patient card
   in these two list views even though every detail/document route
   already correctly used `doctor_has_patient_access()` (which does
   filter). See `test_idor_regression.py::test_revoked_doctor_access_is_denied_immediately`.

## Evidence

`backend/tests/test_idor_regression.py` (10 tests, real DB): cross-
patient document/profile/trends access denied, unassigned-doctor
denied, revoked-doctor-access-denied-immediately, care-partner scope
enforced (cannot access an unshared document, including a real
document row inserted directly to bypass the pipeline for that specific
test), unauthenticated/malformed-token rejected uniformly with no
existence-leaking status-code difference. All passing against the real
dev DB as of this round's work.
