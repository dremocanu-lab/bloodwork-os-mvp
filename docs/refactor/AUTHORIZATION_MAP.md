# Authorization Map (pre-refactor)

Generated from the REAL, running application (`tests/contracts/
generate_route_inventory.py`, which introspects each route's actual
FastAPI dependant tree and, for `require_role(...)`, the real closure
cell holding `allowed_roles` — not re-derived from reading source and
guessing). Full machine-readable form:
`tests/contracts/route_inventory_pre_modularization.json`. This is the
ground truth Phase 4's authorization-centralization step (if attempted)
must reproduce exactly — see the Phase 4 program's own "do not decide a
role should have more/less access" rule.

Three custom role-gating closures exist beyond `require_role(*roles)`
(all defined in `app/main.py`, all wrap `get_current_user`):

- `require_pcp_or_admin()` — admin, OR a doctor with `doctor_type ==
  "pcp"`. Used by `/pcp/patients`, `/pcp/patients/{id}/summary`.
- `require_emergency_role()` — `emergency_worker` or `admin`. Used by
  every `/emergency/*` route.
- `require_ask_bragi_enabled` — not a role check; a feature-flag gate
  (`ASK_BRAGI_ENABLED`), combined with `require_role('patient','doctor')`
  on every Ask Bragi route.

## Route-level role requirements, by domain

(`(none)` = no `Depends(get_current_user)`/`require_role` at all — public
routes only: `/`, `/docs`, `/redoc`, `/openapi.json`.)

### auth
- `POST /auth/signup`, `POST /auth/login` — public (creates the session)
- `GET /auth/me` — any authenticated user (`get_current_user` only)

### assignments / access-requests
- `GET /assignments`, `POST /assignments` — admin
- `POST /access-requests` — doctor
- `GET /my/access-requests` — patient
- `POST /access-requests/{id}/respond` — patient
- `GET /users/doctors` — admin

### patients (core / PCP / search)
- `GET /patients`, `GET /patients/search`,
  `GET /patients/{id}/documents`, `GET /patients/{id}/medications*` —
  doctor or admin, PLUS in-body `doctor_has_patient_access`/
  `can_access_patient` check (route-level role alone is NOT sufficient —
  see "In-body / object-level checks" below)
- `GET /my-patients` — doctor (own assigned patients only, via
  `doctor_has_patient_access`)
- `GET /pcp/patients`, `GET /pcp/patients/{id}/summary` —
  `require_pcp_or_admin`
- `GET /patients/{id}/profile`, `GET /patients/by-public-id/{id}`,
  `GET /patients/{id}/bloodwork-trends` — any authenticated user
  (`get_current_user`), with `can_access_patient`/ownership enforced
  in-body — this is the exact IDOR-prevention boundary
  `test_idor_regression.py` targets.

### account (delete / export / profile)
- `DELETE /my/account` — patient, doctor, admin, OR care_partner (all
  four — deletion semantics differ per role in-body, see
  `_soft_delete_clinical_or_admin_account`/`_delete_care_partner_account`)
- `GET /my/profile`, `POST /my/export`,
  `DELETE /my/access/{doctor_user_id}` — patient
- `POST /my/link-patient`, `GET /my/dependants`, `GET /my/shared-pages` —
  care_partner

### documents / uploads
- `POST /upload`, `POST /upload/background`, `POST /upload/batch`,
  `GET /upload-jobs*`, `POST /upload-jobs/{id}/confirm-*` — any
  authenticated user (`get_current_user`); patient/doctor distinction and
  target-patient resolution enforced in-body (`resolve_upload_patient`)
- `GET /documents/{id}`, `PUT /documents/{id}`, `DELETE /documents/{id}`,
  `POST /documents/{id}/verify`, `POST /documents/{id}/identity-review`,
  `GET /documents/quarantined`, `GET /documents/by-public-id/{id}` — any
  authenticated user; ownership/access enforced in-body
- `GET /documents/{id}/file`, `GET /source-evidence/{id}/view`,
  `GET /lab-results/{id}/source` — any authenticated user; this is the
  provenance/"View in original" boundary — authorization here must match
  whatever the underlying document's access rules are (own patient, an
  authorized doctor, or an explicit care-partner share)
- `GET /documents/{id}/shares`, `POST /documents/{id}/share`,
  `DELETE /documents/{id}/share/{care_partner_user_id}` — patient
    (sharing is patient-initiated only)

### labs / timeline / medications
- `GET /patients/{id}/bloodwork-trends` — see patients section above
- `POST /patient-events`, `POST /patient-events/{id}/discharge` — doctor
  or admin
- `GET /my/medications*`, `POST/PUT/DELETE /my/medications*` — patient
  (own medications only, scoped via `get_current_user` → own patient row)
- `GET /patients/{id}/medications*` — doctor or admin, plus
  `doctor_has_patient_access`

### care-partner + emergency-contact settings
- `GET/PUT /my/settings/emergency-access`,
  `GET/POST/PUT/DELETE /my/settings/emergency-contacts*`,
  `GET /my/care-partner-code`, `POST /my/care-partner-code/regenerate`,
  `GET /my/care-partners` — patient

### admin (doctor/patient management)
- `GET /admin/patients/search`, `GET /admin/doctors*`,
  `GET /admin/patients/{id}/assignments`, `POST /admin/assignments/*`,
  `GET /admin/analyte-gaps`, `GET /admin/ops/rate-limit-status` — admin

### emergency (break-glass)
- Every `/emergency/*` route — `require_emergency_role` (emergency_worker
  or admin). Every access is additionally written to
  `EmergencyAuditLog` in-body (not visible to the role-dependency layer
  itself — see the route bodies).

### Ask Bragi
- Every `/ask-bragi/conversations*` route — `require_role('patient',
  'doctor')` AND `require_ask_bragi_enabled` (feature flag). Server-owned
  patient/conversation context resolved in-body — no tool or route
  accepts a caller-supplied patient id (see `BRAGI_ASK_BRAGI_PLAN.md`).

### interoperability (FHIR)
- Every `/admin/interop/*` route (20 routes) — `require_role('admin')`,
  confirmed for all 20 both here and by the static count check performed
  during Phase 1 closure (21 call sites for `_require_interop_enabled()`:
  1 definition + 20 routes). Additionally gated by the
  `INTEROP_FHIR_ENABLED` flag (checked in-body via
  `_require_interop_enabled()`, not a FastAPI dependency — see
  `main.py`'s `_require_interop_enabled` helper).

## In-body / object-level checks (the IDOR-prevention layer)

Route-level role checks alone are NOT sufficient for most patient-scoped
routes — a doctor role-check doesn't by itself prevent doctor A from
reading patient B's record. The actual object-level authorization lives
in these shared helper functions, called explicitly inside route bodies:

- `can_access_patient(db, current_user, patient_id)` — the general-
  purpose "may this user see this patient" check (patient-self, an
  authorized doctor, or admin).
- `doctor_has_patient_access(db, doctor_user_id, patient_id)` — checks
  `DoctorPatientAccess.is_active` — this is what makes a REVOKED grant
  stop working immediately (see `test_idor_regression.py`'s revoked-
  access test).
- `care_partner_can_access_document(db, care_partner_user_id,
  document_id)` — explicit per-document share, not general patient
  access.
- Ask Bragi's own context-resolution functions
  (`app/services/ask_bragi/context.py`) — server-owned patient/
  conversation resolution, independently re-checked per tool call (not
  part of `main.py` at all, already its own module).

**Any centralization step in this phase (§9, if attempted) must call
these SAME functions from wherever routes end up — never re-implement
the check, and never loosen it "since it's being cleaned up anyway."**

## Regression coverage already protecting this map

`test_idor_regression.py`, `test_ask_bragi_security.py`,
`test_cnp_identifier_minimization.py`, `test_deletion_completeness.py`,
`test_dsar_export.py` — all real-DB, all currently passing (see
`BACKEND_MODULARIZATION_BASELINE.md`). These must stay green (or gain
new equivalents in the same spirit) after every extraction step.
