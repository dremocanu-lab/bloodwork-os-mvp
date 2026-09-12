# Bragi Health Portal — Known Gaps

Honest, explicit list of what is missing or unfinished, for an
investor/production audience. This file exists specifically so these
gaps are never silently hidden — see `docs/CURRENT_STATE.md` for what
*is* implemented. Nothing here should be inferred as "probably fine";
each item is either genuinely unaddressed or addressed only partially,
as described.

## Security / compliance infrastructure gaps

- **No MFA** anywhere in the application (patient/doctor/admin/etc.
  login is password-only). Also unresolved at the infrastructure level:
  whether MFA is actually enforced on the Render/Vercel/Neon accounts
  that operate production is an operational fact outside this
  codebase's ability to verify (see `docs/security/
  PRODUCTION_ACCESS_POLICY.md`).
- **No server-side session/token revocation.** Logout is client-side
  only (the JWT is simply discarded by the browser) — there is no
  denylist or session store, so a stolen token remains valid until its
  natural expiry.
- **No production monitoring/alerting.** No error-tracking or analytics
  SDK (Sentry, PostHog, Segment, or equivalent) is wired into the
  backend or frontend. There is no security-event monitoring in
  production today.
- **No tested backup restoration.** Neon/Render's actual backup/PITR
  configuration is an account/console-level setting this codebase
  cannot verify or exercise. No restore drill has been performed.
- **No independent security pentest.** Every security review to date
  has been performed by the same author who wrote the code being
  reviewed — a fundamentally different guarantee than an independent
  third-party assessment.
- **No external legal/compliance review or certification.** No GDPR/
  HIPAA/MDR/EU-AI-Act/ISO-27001/SOC-2 compliance status is claimed or
  established. The controller-vs-processor role determination for
  Bragi's operator is explicitly unresolved (`[LEGAL REVIEW]` in
  `BRAGI_SECURITY_GDPR_PLAN.md`).
- **No real antivirus/malware-scanning engine connected.** Only a
  pipeline boundary (`app/services/security_scan.py`) plus a narrow
  heuristic screen for unambiguous malicious-PDF markers exists. Real
  ClamAV integration is wired to activate via `CLAMAV_HOST`/
  `CLAMAV_PORT` but neither is set in production. Non-PDF files receive
  no heuristic screening at all today.
- **No durable/versioned production object storage.** Uploaded files
  live on local disk on the Render backend instance (`UPLOAD_DIR`), not
  in a separately-backed-up object store (e.g. S3). This is a real,
  distinct disaster-recovery exposure, not merely a nice-to-have
  upgrade.
- **No encryption-at-rest for CNP** (Romanian national identifier) —
  a design document exists (`docs/security/
  IDENTIFIER_ENCRYPTION_PLAN.md`) but the migration to it has not been
  performed.
- **No Postgres Row-Level Security.** A design exists explaining why
  turning it on without further work would be unsafe given Neon's
  connection pooling and the app's background-job architecture; RLS is
  deliberately not enabled.

## Product/behavior gaps requiring a decision, not silently changed

- Doctor/admin account "deletion" is a soft-delete (login disabled,
  identifying fields replaced) rather than a full row delete, because a
  real delete would either violate other patients' clinical-record FK
  references or require silently anonymizing them — which patient
  record depth is correct here is explicitly a legal/product decision,
  not an engineering one (`BRAGI_SECURITY_GDPR_PLAN.md`, `[LEGAL
  REVIEW]`).
- `emergency_worker` accounts have no self-deletion path at all
  (a clean 403) — pending the same kind of product/legal decision.
- The `role` field at `/auth/signup` is client-supplied with no
  server-side gate on `doctor`/`admin` beyond the `care_partner` code
  check — flagged as a possible gap needing a product decision on how
  doctor/admin accounts should actually be provisioned; not changed
  unilaterally.
- `GET /admin/patients/search` has no department/hospital scoping,
  unlike `GET /admin/doctors` — same category of open decision.
- DSAR self-service export (`POST /my/export`) exists for the patient
  role only; doctor/admin/care_partner/emergency_worker accounts have
  no equivalent self-service export.
- No rectification/change-history mechanism: editing a structured
  field silently overwrites the prior value with no record of what it
  was corrected from.
- A known, reproduced `StaleDataError` race exists between account
  deletion and an in-flight upload job for the same account — low
  likelihood, not yet fixed.

## Product feature gaps (see docs/CURRENT_STATE.md's "Deferred" section for the full list)

Summarized pointer only — do not duplicate maintenance of this list in
two places: real mTLS transport for FHIR connectors; a background job
queue for FHIR sync; an admin FHIR connection wizard UI (backend-API-
only today); Playwright/browser-automation coverage (neither for
interop nor for the product generally); incremental `_lastUpdated`
FHIR re-sync; Bulk Data/IHE/HL7v2/CDA/DICOMweb; CNAS integration
(explicitly blocked on the product owner completing real CNAS
registration — do not implement CNAS/SIUI/SIPE/CEAS speculatively);
per-section source evidence for narrative (Reader) documents;
prescription/medication-list → `PatientMedication` linkage; Level-2
semantic duplicate-document matching; in-app document search, outline
navigation, and a conflicts/uncertainty UI; a full theme-consistency
pass on the analytics dashboard; document-organization UI restructuring
to the full 16-type taxonomy; automatic backfill of full-row PDF
highlighting for older documents; several Ask Bragi eval categories
(imaging, two-source medication conflicts) and a latency benchmark;
review of the `care-partner/upload` page; wiring the shared source
viewer into Chart/Reader/Timeline/Documents-list views.

## Phase 4 (backend modularization) — scope boundary, not a gap in the refactor itself

Everything in this section is a **deliberate, explicit** boundary of
the Phase 4 backend-modularization refactor (see `docs/ARCHITECTURE.md`
and the Phase 4 final report), not an accidental omission:

- Authorization was **relocated** (the three canonical checks now live
  in `app/policies/access.py`) but not further **centralized** —
  routers still call these functions individually rather than through
  a single consolidated dependency/middleware layer. Doing that safely
  requires the full authorization matrix already documented in
  `docs/refactor/AUTHORIZATION_MAP.md`, plus a dedicated regression
  pass, which this phase deliberately left as a follow-up rather than
  risk conflating "reorganize" with "redesign."
- Several cross-cutting helper functions (`serialize_user`,
  `add_audit_log`, the `ensure_patient_for_user` cluster,
  `document_has_abnormal_labs`/`doctor_reviewed_document`/
  `mark_doctor_reviewed_document`, `serialize_lab_result`,
  `serialize_document_card`, `get_document_payload`, and the ~700-line
  `process_upload_job` ingestion pipeline) remain physically defined in
  `app/main.py`, consumed by multiple routers via a deferred
  (function-body-scoped) `from app.main import ...`. This is a
  deliberate stopping point: each of these is used by 2+ already-
  extracted routers, and relocating them is a genuine service-
  extraction decision (which single module should "own" a helper used
  by 3-4 different domains) rather than a mechanical move — exactly the
  kind of decision Phase 4's own instructions reserve for a dedicated
  follow-up pass, not something to rush through while finishing route
  extraction.
- `app/models.py` was deliberately **not** split, per explicit
  instruction — acceptable to leave consolidated.
- No new interoperability standards, no mTLS, no FHIR admin wizard, no
  background job queue, and no CNAS work was added during this refactor
  — Phase 4 was reorganization only, not feature work.
- `demo.bragi.health` was explicitly out of scope and was not started.
