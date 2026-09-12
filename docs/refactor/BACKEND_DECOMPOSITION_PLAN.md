# Backend Decomposition Plan

Written BEFORE any code moved (per Phase 4's process) from a direct read
of `app/main.py` at the baseline commit — see
`BACKEND_MODULARIZATION_BASELINE.md`.

## Shared application setup / true main.py content

These stay in `main.py` (or move to `core/`/`db/` — see Target
Architecture) — they are infrastructure, not one domain's business logic:

- `app = FastAPI()`, CORS middleware, security-headers middleware
- `get_db()`, `get_current_user()`, `require_role()` — the auth
  dependency chain every route uses
- `now_iso()`, `generate_public_id()` — trivial shared utilities
- `serialize_user()` — shared response shaping
- `add_audit_log()` — shared audit-log helper
- The startup migration-retirement comment block (historical
  `run_migrations()`, already dead code per the Alembic PR)

## Shared authorization/business helpers (candidates for `policies/`)

Read directly from the file, not guessed — these are called from
multiple domains and are exactly the kind of logic
`docs/refactor/AUTHORIZATION_MAP.md` maps in full before anything is
centralized:

- `get_patient_for_user`, `ensure_patient_for_user`
- `doctor_has_patient_access`, `can_access_patient`
- `care_partner_can_access_document`
- `_generate_unique_care_partner_code`, `_ensure_patient_code`
- `lab_flag_is_abnormal`, `document_has_abnormal_labs`
- `doctor_reviewed_document`, `mark_doctor_reviewed_document`
- `_is_pcp_doctor`, `require_pcp_or_admin`
- `resolve_upload_patient`

## Shared serialization helpers (candidates for `schemas/` support code)

- `serialize_lab_result`, `serialize_document_card`,
  `serialize_patient_event`, `serialize_doctor_access`,
  `build_patient_profile_response`, `get_document_payload`,
  `serialize_upload_job`, `get_best_document_date`,
  `lab_value_to_float`, `_contact_dict`

## Domain boundaries (route groups, by path prefix — line numbers refer to
the baseline commit `30080fb`)

| Domain | Representative routes | Approx. line range | Risk to extract |
|---|---|---|---|
| **root/ops** | `GET /`, `GET /admin/ops/rate-limit-status` | 2505-2525 | Trivial |
| **auth** | `/auth/signup`, `/auth/login`, `/auth/me` | 2526-2640 | Medium (touches `SECRET_KEY`/JWT, every other domain depends on `get_current_user`) |
| **assignments/access-requests** | `/users/doctors`, `/assignments`, `/access-requests*` | 2640-2877 | Low-medium |
| **patients (core/PCP/search)** | `/patients`, `/my-patients`, `/pcp/patients*`, `/patients/search`, `/patients/{id}/profile` | 2877-3470 | Medium (large, central) |
| **account (delete/export/profile)** | `/my/account`, `/my/access/{id}`, `/my/profile`, `/my/export` | 3470-4024 | High (the FK-cascade-bug-prone deletion path — see Phase 1/Alembic history; test exhaustively) |
| **documents/uploads** | `/patients/{id}/documents`, `/upload*`, `/upload-jobs*`, `/documents/*` | 4024-4966 | High (largest domain, most routes, upload pipeline) |
| **source evidence** | `/source-evidence/{id}/view`, `/lab-results/{id}/source` | 4684-4810 | Medium (provenance/authorization-sensitive) |
| **labs/bloodwork trends** | `/patients/{id}/bloodwork-trends` | 4966-5102 | Low |
| **patient events/timeline** | `/patient-events*` | 5102-5163 | Low |
| **care-partner + emergency-contact settings** | `/my/care-partner-code*`, `/my/settings/emergency-*`, `/my/care-partners`, `/my/dependants`, `/my/shared-pages`, `/documents/{id}/share*` | 5163-5639 | Medium |
| **admin (doctor/patient mgmt)** | `/admin/patients/*`, `/admin/doctors*`, `/admin/assignments/*`, `/my/link-patient`, `/admin/analyte-gaps` | 5639-6109 | Medium |
| **medications** | `/my/medications*`, `/patients/{id}/medications*` | 6109-6538 | Low-medium |
| **emergency (break-glass)** | `/emergency/*` | 6538-7106 | High (security-critical, heavily audited) |
| **Ask Bragi** | `/ask-bragi/conversations*` | 7106-7530 | High (streaming route, server-owned-context invariants) |
| **interoperability (FHIR)** | `/admin/interop/*` | 7530-8141 (end of file) | **Lowest** — contiguous, self-contained, newest code, most recently and thoroughly tested (Phase 1/3) |

## Recommended extraction order

Chosen for actual dependency risk, not the illustrative order in the
Phase 4 prompt (interop is safer to move FIRST here, not last, precisely
because it's contiguous/self-contained/freshest — see also §7's own
"inspect dependencies first and change the order if safer"):

1. **interop** — contiguous block at the end of the file, its own
   `app/services/interop/` package already fully separate, comprehensive
   existing test suite (51+ tests across 8 files). Zero shared
   serialization helpers with any other domain. Ideal first slice.
2. **root/ops** — trivial, 2 routes.
3. **labs/bloodwork trends** — small, one route family, read-only.
4. **patient events/timeline** — small, low fan-out.
5. **medications** — moderate size, clear boundary, own serializers.
6. **assignments/access-requests** — moderate, some shared helpers with
   patients domain (`doctor_has_patient_access`) — extract policies
   helper alongside or just import it from wherever it lands.
7. **care-partner + emergency-contact settings** — moderate, mostly
   self-contained.
8. **admin (doctor/patient mgmt)** — moderate, admin-only throughout.
9. **source evidence** — small but authorization-sensitive; do after the
   documents domain it depends on conceptually is understood, not
   necessarily after it's physically moved.
10. **documents/uploads** — large, high fan-out (upload pipeline,
    identity/quarantine, sharing). Extract only after 1-9 have proven the
    pattern is safe.
11. **patients (core/PCP/search) + account (delete/export)** — largest,
    most central, most FK-cascade-history-laden. Last non-emergency
    domain.
12. **emergency (break-glass)** — extract with extra care; every route
    here is independently audited (`EmergencyAuditLog`).
13. **Ask Bragi** — extract last among "normal" domains; the streaming
    route (`.../messages/stream`) and server-owned-context invariants
    make this the most behaviorally delicate to move.
14. **auth** — genuinely last, since `get_current_user`/`require_role`
    (defined alongside it) are imported by literally every other router;
    moving it first would force every other extraction to deal with the
    import simultaneously instead of one domain at a time.

This plan itself may be revised between slices if a dependency turns out
riskier in practice than anticipated here — per Phase 4's own instruction
to inspect real dependencies before committing to an order, not follow a
theoretical one blindly.

## Target architecture note

See Phase 4 prompt §4 for the full desired tree. This plan does not
create empty `services/`/`policies/` subfolders per domain speculatively
— each domain's extraction step decides, from its OWN actual code,
whether a `services/<domain>/` split is warranted (real orchestration
logic worth a boundary) or whether the router file alone is sufficient
for that domain's actual size or complexity.
