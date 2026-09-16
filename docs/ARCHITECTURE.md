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

## Ask Bragi — tool-call round budget (2026-09-14)

`ASK_BRAGI_MAX_TOOL_ROUNDS` (in `app/services/ask_bragi/service.py`)
governs how many `client.responses.create()` round trips a single turn
may use before Ask Bragi gives up and returns a generic error. Raised
from 4 to 8 after a real, reproduced failure: a broad multi-analyte
question ("what changed in my latest bloodwork") can legitimately need
several tool rounds (context calls + one comparison per analyte in a
panel), and 4 was not enough headroom. See
`docs/handoffs/CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md` section 15
for the full diagnosis and `prompts.py`'s "TOOL EFFICIENCY" guidance,
which reduces how many rounds this class of question actually needs in
the first place.

## `SourceEvidence` generalizing beyond lab rows (2026-09-15)

`SourceEvidence.lab_result_id` was always nullable specifically so this
model could "generalize to other clinical entities... not just lab
rows" (its own long-standing docstring). Clinical Document Intelligence
V3 Phase 7 is the first real use of that intent: a new, symmetric
`SourceEvidence.medication_id` (nullable FK → `patient_medications.id`,
`ondelete="SET NULL"`) provides the same provenance mechanism for a
document-derived `PatientMedication` row that `lab_result_id` already
provides for a `LabResult` row. `PatientMedication` itself gained three
additive provenance columns (`source_document_id`, `source_segment_id`,
`stop_date_basis`) — see `docs/handoffs/
CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md` section 9f for the full
design reasoning, including why `source_document_id` deliberately uses
`ondelete="SET NULL"` rather than the hard-delete-with-parent pattern
Phase 6 used for its derived lab artifact (a medication fact stays
independently meaningful once its source document is gone; a
pointer-only derived artifact does not).

## One deliberate reader payload, not N internal endpoints (2026-09-16)

Clinical Document Intelligence V3 Phase 8 added `GET /documents/{id}/
clinical-reader` — the first genuinely new route since the Phase 4
backend-modularization baseline (117 → 118 routes). It exists
specifically so the frontend discharge/clinical-document reader fetches
ONE deliberate, purpose-built payload (`{document, structured_document,
labs, medications}`, each fact already carrying its own
`source_evidence_id`) instead of composing several existing internal
endpoints client-side — see `docs/handoffs/
CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md` section 9g for the full
design. This is the pattern to follow for any future reader-shaped
surface in this app (Phase 10's Timeline integration): a dedicated read
endpoint assembling canonical facts server-side, not a frontend-side
join across multiple generic endpoints. Also extracted `app/services/
source_evidence.py` (`ensure_document_level_evidence`,
`first_source_evidence_id`) from logic that used to live only inside
`ask_bragi/tools.py` — both that module and the new reader endpoint now
share it, proven equivalent by the existing Ask Bragi test suite
staying green unchanged.

## Derived-artifact card context: one batched resolver, not N+1 (2026-09-16)

Clinical Document Intelligence V3 Phase 9 gave a derived lab artifact
(Phase 6's `Document.derived_artifact_kind`) a real presence in every
document-card listing — but a card's caller already has the FULL
document list for that patient in memory before calling `serialize_
document_card` per row, so resolving a derived artifact's parent
metadata and its own abnormal-flag status (which needs its `note_body`
pointer's `lab_result_ids`, never `document_has_abnormal_labs(db,
document.id)` — that always returns `False` for a derived artifact,
since every `LabResult` row lives on the PARENT's id per Phase 6's
ownership rule) must never cost one query per derived artifact.
`app/main.py::resolve_derived_artifact_contexts(db, documents)` takes
that already-fetched list, indexes it in memory for parent lookups, and
issues exactly ONE batched `LabResult.id.in_(...)` query across every
derived artifact's referenced ids — used identically by both
`patients.py::build_patient_profile_response` and `documents.py::
get_patient_documents`, so this behavior is defined once, not
reimplemented per route. `serialize_document_card` itself stays a pure
per-row serializer — it accepts the pre-resolved `parent_document`/
`has_abnormal_override` as optional keyword params rather than querying
inside the loop.

## `PatientEvent` as a projection target, not a second source of truth (2026-09-16)

Clinical Document Intelligence V3 Phase 10 needed canonical medication
state changes (`PatientMedication`, Phase 7) to appear on the patient's
Timeline, which is persisted exclusively via the pre-existing
`PatientEvent` table (previously written only by the doctor-driven
`POST /patient-events` route). Rather than adding a second Timeline
table or copying medication data into `PatientEvent`'s free-text fields,
`app/services/clinical_document/timeline_projection.py::project_
clinical_document_to_timeline(db, document)` treats `PatientEvent` as a
PROJECTION target: it reads a document's own already-canonical
`PatientMedication` rows and idempotently creates/updates/retracts
`PatientEvent` rows that reference them via two new additive, nullable
FK columns — `source_document_id` (`ondelete="SET NULL"`, mirroring
`PatientMedication.source_document_id`'s own Phase 7 choice: the fact
survives its source document's deletion) and `source_medication_id`
(`ondelete="CASCADE"` — the projection is deleted once the fact it
represents is). A manually-created event has both columns `null`; that
alone distinguishes "manual" from "projected," no separate boolean flag.
This is the pattern to follow for any future canonical-fact-to-Timeline
projection: add a nullable FK from `PatientEvent` to the canonical
table, key idempotency off that FK (never `created_at`), and give the
`ondelete` rule the SAME independent-meaningfulness semantics the
canonical fact's own provenance FK already has — never invent a new one.

A deliberate, explicitly-recorded non-decision worth knowing before
extending this further: a `Document` (including a Phase 6 derived lab
artifact) is NOT projected this way, because it already appears on the
Timeline via a separate, pre-existing mechanism — `frontend/app/
my-records/timeline/page.tsx`/`patients/[id]/timeline/page.tsx` fuse
`GET /my/profile`'s document list directly into the rendered Timeline
client-side. Projecting a `PatientEvent` for the same document would
duplicate it. See `timeline_projection.py`'s own module docstring for
the full reasoning.
