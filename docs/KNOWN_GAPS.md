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

## Clinical Document Intelligence V3 — Phases 9-21 (2026-09-16)

An implementation contract for rebuilding structured clinical-document
ingestion (discharge sections, dated clinical events, embedded lab/
medication extraction into canonical models, a new frontend document
reader) was received. Phase 0 (architecture inventory), Phase 1
(baseline), Phase 2 (a real Ask Bragi P0 fix — see ARCHITECTURE.md's
"Ask Bragi — tool-call round budget" section), Phase 3 (the structured
document schema), Phases 4-5 (source segmentation, canonical-section
consolidation, Clinical Course dated-event extraction with chronology
checks, and a full end-to-end orchestration), Phase 6 (embedded lab
extraction/grouping/canonical persistence into real `LabResult` rows,
feeding the existing shared analyte resolver, plus derived lab-artifact
backend semantics with real deletion and idempotency guarantees), Phase
7 (medication extraction/context classification/deterministic duration
parsing/end-date derivation into real `PatientMedication` rows, feeding
the existing status vocabulary, with an exact start-date priority that
never uses an upload/ingestion timestamp and explicit preservation of
same-drug conflicts), Phase 8 (the discharge/clinical-document
reader rebuilt around the canonical `StructuredClinicalDocument`
contract — a new reader API, a rewritten reader page, 7 new reusable
components including one `StructuredLabReport` for both embedded and
standalone use, honest PDF/non-PDF provenance, and derived-vs-explicit
medication date UX, proven with real Playwright coverage), Phase 9
(a derived "lab_report" `Document` is now a real, independently
openable Documents entry — a new standalone `/documents/{id}/
lab-report` route reusing `StructuredLabReport(mode="standalone")`
verbatim, restrained "Derived from: [parent]" Documents-card framing,
correct authorization/deletion/provenance semantics, and a completion
of a genuine Phase-6 gap where the derived artifact's own
`lab_result_ids` pointer was declared but never populated), and Phase 10
(canonical medication start/stop state changes now project onto the
patient's Timeline as real, idempotent `PatientEvent` rows via a new
`timeline_projection.py` service — never inventing a date, never
asserting a state change a conflicting row can't support, coexisting
with manually-created hospitalization events on the same table; a
clinical document/derived lab artifact deliberately is NOT separately
projected since it already appeared on the Timeline via a pre-existing
mechanism this phase fixed rather than duplicated) are all completed and
verified — see `docs/handoffs/CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md`
sections 9/9b/9c/9d/9e/9f/9g/9h/9i. None of Phases 3-10's EXTRACTION/
PERSISTENCE/PROJECTION code is wired into the live discharge upload
write path yet (deliberate sequencing, not an oversight — a brand-new
upload today still renders correctly through Phase 8's reader, just
without labs/medications attached until that write-side switch
happens). A subsequent post-Phase-10 integration-correction pass fixed
real bugs found by manual QA — 5 duplicated frontend document-routing
decisions consolidated into one shared resolver (a real classification-
taxonomy root cause found: `HOSPITAL_ADMISSION_NOTE`/`EMERGENCY_
DEPARTMENT_NOTE` map to the legacy `"hospitalizations"` section, not
`"discharge_summary"` — deliberately NOT changed, a product decision),
a real gap where both Timeline pages had no derived-artifact routing
check, a real Ask Bragi bug (the discharge reader sent a document id as
`patientId` for doctors), and two real UI bugs (upload-page width,
processing-indicator alignment) — see `docs/clinical_document_v3/
ROUTER_AUDIT.md`. An exact word-level source-highlighting engine (a
real coarse-highlight bug found by manual QA) was investigated and found
to require genuinely new provenance engineering for narrative text — see
below; the LAB-specific half of it (the reported NEUT#/PCT/NRBC# coarse-
highlight bug) was root-caused and fixed in a subsequent pre-Phase-11
exact-provenance session: `_union_row_bbox()`'s fixed-ratio padding
formula was bleeding into a neighboring row on a dense table, not a
Reducto data ceiling — fixed by persisting and rendering Reducto's own
real, unpadded per-field citation rects (new additive `SourceEvidence.
field_bboxes_json` column) instead of one padded union box. That same
session also shipped a real select-text-to-"Show in original"
interaction for lab/medication rows (same shared `openSourceEvidence`
engine). Arbitrary NARRATIVE-text (Clinical Course paragraphs, bullet
lists, key-value pairs) exact highlighting remains genuinely
unimplemented — confirmed, not merely suspected: Reducto's reader/
section extraction runs with `citations=False`, and `SourceSegment` is
not persisted with a page number at all, so there is no source geometry
of any precision for narrative text to render even coarsely beyond
"open the document." Ask-Bragi retrieval hardening for the new canonical
data (Phase 11), the exhaustive real-Postgres idempotency/deletion test
suites (Phases 6-10 each laid real groundwork but the full 1x/2x/10x/
exhaustive-cascade proofs remain open), the deterministic retrieval
benchmark, the full 7-viewport responsive screenshot matrix (Phase 8
manually verified 2 of 7), and an automated accessibility scan are all
**not implemented** — this remains a large, deliberate scope gap, not
an oversight. Full honest accounting
and a continuation plan: `docs/handoffs/CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md`.
