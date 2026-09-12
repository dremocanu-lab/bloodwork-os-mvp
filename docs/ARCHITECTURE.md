# Bragi Backend Architecture

Authoritative as of the Phase 4 backend-modularization merge. See
`docs/refactor/BACKEND_DECOMPOSITION_PLAN.md` and
`docs/refactor/AUTHORIZATION_MAP.md` for the reasoning behind this
structure, and `docs/refactor/OPENAPI_EQUIVALENCE_REPORT.md` for proof
this refactor changed no external behavior.

## Directory layout

```
backend/app/
  main.py                    FastAPI app construction, CORS + security-
                              headers middleware, router registration,
                              and a set of cross-cutting helpers shared
                              by multiple routers (see "What's still in
                              main.py" below) — NOT primarily route
                              handlers anymore; every HTTP route lives
                              in app/api/routers/.
  models.py                  SQLAlchemy ORM models (all of them — see
                              "models.py" below for why this isn't split).
  db.py                       Engine/SessionLocal setup.
  auth.py                     JWT + password hashing primitives.
  rate_limit.py                Rate limiter (Redis-backed when
                              configured, in-memory fallback otherwise).

  api/
    dependencies.py           get_db, get_current_user, require_role —
                              the auth dependency chain every route in
                              the app uses. Extracted first (Phase 4's
                              first commit) precisely so every other
                              router could import it without depending
                              on app.main.
    routers/                 One module per product domain — see below.

  core/
    utils.py                  Trivial, dependency-free shared primitives:
                              now_iso(), generate_public_id(), _mask_cnp().

  policies/
    access.py                  Canonical patient-access/IDOR-prevention
                              checks: get_patient_for_user,
                              doctor_has_patient_access, can_access_patient,
                              care_partner_can_access_document. Any new
                              authorization check on patient/document
                              access MUST call these, never re-implement
                              them — see AUTHORIZATION_MAP.md.

  schemas/
    serializers.py             Shared response-shaping helpers used by
                              more than one router: serialize_patient_event.

  services/                   Business logic and external integrations,
                              unchanged by Phase 4: document_pipeline,
                              discharge_summary_pipeline, document_taxonomy,
                              extraction_provider, reducto_client,
                              reducto_extraction, ocr_service, file_hash,
                              security_scan, patient_identity,
                              structured_reader_service, lab_catalog,
                              lab_resolver, medication_lookup,
                              ask_bragi/ (context.py, service.py),
                              interop/ (Phase 1/3 FHIR connector stack).
```

## Router modules (`app/api/routers/`)

| Module | Domain | Routes | Notable local state |
|---|---|---|---|
| `root.py` | Health/ops | `GET /`, `GET /admin/ops/rate-limit-status` | — |
| `auth.py` | Signup/login/me | 3 | `_normalize_doctor_type`, PCP department sniffing |
| `assignments.py` | Doctor-patient assignments, access requests | 6 | — |
| `patients.py` | Patient listing/search/PCP workspace, account delete/export/profile | 10 | `build_patient_profile_response`, the account-deletion FK-cascade sequence, DSAR export |
| `labs.py` | Bloodwork trends | 1 | canonical-lab trend grouping (resolution itself lives in `services/lab_resolver.py`) |
| `patient_events.py` | Hospitalization timeline mutations | 2 | — |
| `medications.py` | Patient medications | 9 | RxNorm/DailyMed background lookup |
| `care_partner_settings.py` | Care-partner code, emergency-discoverability toggle, emergency contacts, document sharing | 13 | — |
| `admin.py` | Admin doctor/patient management | 9 | department/hospital scoping |
| `source_evidence.py` | Citation/"View original" resolution | 2 | — |
| `documents.py` | Document CRUD, upload pipeline entry points, quarantine/identity-review | 18 | the ~700-line `process_upload_job` ingestion pipeline, upload validation config |
| `emergency.py` | Break-glass emergency access | 10 | `_add_emergency_audit` (also used by `care_partner_settings.py`) |
| `ask_bragi.py` | Ask Bragi conversations (incl. streaming) | 6 | server-owned patient-context resolution, SSE streaming |
| `interop.py` | FHIR/HL7 interoperability admin | 21 | Phase 1/3 connector lifecycle, drift detection, sync |

117 routes total, matching the pre-Phase-4 baseline exactly (see
OPENAPI_EQUIVALENCE_REPORT.md).

## What's still in `app/main.py`

`main.py` is 2,017 lines (down from the 8,141-line pre-Phase-4
baseline — a 75% reduction) and contains:

- FastAPI app construction, CORS middleware, the security-headers
  middleware.
- Router registration (the `from app.api.routers.X import router as
  X_router` + `app.include_router(X_router)` block at the very end).
- A historical, **uncalled**, dead `run_migrations()` function kept
  verbatim as a reference for exactly what the old pre-Alembic startup
  path used to do (see its own docstring/comment block) — not part of
  any request path.
- A set of genuinely cross-cutting helper functions still consumed by
  multiple routers via a deferred (`from app.main import X`, inside the
  function body) import: `serialize_user`, `add_audit_log`,
  `ensure_patient_for_user`/`_ensure_patient_code`/
  `_generate_unique_care_partner_code`, `lab_flag_is_abnormal`,
  `document_has_abnormal_labs`, `doctor_reviewed_document`/
  `mark_doctor_reviewed_document`, `serialize_lab_result`,
  `serialize_document_card`, `get_document_payload`, and the upload
  pipeline (`_finish_mixed_reducto_upload`, `process_upload_job`).

That last group is a deliberate, explicit scope boundary, not an
oversight — see `docs/KNOWN_GAPS.md` ("Deferred service extraction").
Every route itself has left `main.py`; what remains is shared
non-route logic several domains call into.

### The deferred-import pattern

Every router that still needs one of those `app.main` helpers imports
it **inside the function body** that uses it, not at module load time:

```python
def some_route(...):
    from app.main import ensure_patient_for_user
    patient = ensure_patient_for_user(db, current_user)
    ...
```

This is safe specifically because `app.main` registers every router at
the very end of its own module body — by the time any HTTP request is
actually served, `app.main` has always finished executing, so the name
being imported always exists. A top-level import in the router module
would work too (Python would just finish loading `app.main` first,
which already happens once at process startup), but the deferred form
makes the "this still belongs to app.main, not this router" relationship
explicit in the code, and was kept for consistency across every router
that needed it.

**Known regression class from this pattern** (found once, during the
interop extraction, and proactively checked for on every subsequent
extraction): a test that does `monkeypatch.setattr(app_main, "X", ...)`
patches the module-level name on `app.main`. If `X` is later moved out
of `app.main` (or a router does `from app.main import X` and reads its
own independent binding instead of the live attribute), that monkeypatch
silently stops having any effect. Both real occurrences of this bug
(interop's `INTEROP_FHIR_ENABLED`/`IS_PRODUCTION`, Ask Bragi's
`ASK_BRAGI_ENABLED`) were found and fixed during this phase by updating
the test to patch the module where the value is actually read — see the
corresponding commit messages on `refactor/backend-modularization` for
each.

## `models.py`

Left fully consolidated (891 lines, unchanged from baseline) per Phase
4's explicit instruction not to aggressively split it — it is acceptable
to leave it as one module. It is not split by this refactor.

## Authorization

The three canonical IDOR-prevention/access checks
(`get_patient_for_user`, `doctor_has_patient_access`,
`can_access_patient`, `care_partner_can_access_document`) live in
`app/policies/access.py` and are called, never re-implemented, by every
router that needs them. `docs/refactor/AUTHORIZATION_MAP.md` documents
every route's real role requirement and the three custom authorization
closures (`require_pcp_or_admin`, `require_emergency_role`,
`require_ask_bragi_enabled`) as they existed before this refactor —
still accurate, since no route's authorization semantics changed.
Authorization logic was **not** further centralized/consolidated beyond
this relocation — that is explicitly a follow-up decision (see
KNOWN_GAPS.md), to be done only with the full authorization matrix in
hand and with no route's actual permitted-caller set changing.

## Database / migrations

Alembic remains authoritative (`backend/alembic/`,
`docs/database/MIGRATIONS.md`). Phase 4 made **zero** schema changes —
confirmed by `scripts/check_migration_drift.py` passing after every
single commit in this phase, and no new Alembic revision was created.
