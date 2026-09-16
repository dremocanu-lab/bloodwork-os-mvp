# Clinical Document Intelligence V3 — Document Routing Audit

Written during the post-Phase-10 integration-correction pass, triggered
by real manual QA finding a fresh Romanian discharge upload still opened
the legacy generic reader instead of the Phase 8 canonical discharge
reader. This document records every place a document's "which reader
should open" decision is made, the real root cause found, and the fix.

## The real root cause

`frontend/app/documents/[id]/page.tsx`'s redirect logic (and 4 other
independent copies of the same decision — see "Routing decision points"
below) checked only the legacy `section`/`report_type` fields, never
`document_type`. That alone would only matter if `document_type` were
ever MORE reliable than `section`/`report_type` — investigation found a
real case where it is: `LEGACY_SECTION_BY_DOCUMENT_TYPE`
(`backend/app/services/document_taxonomy.py`) maps `DocumentType.
HOSPITAL_ADMISSION_NOTE` and `DocumentType.EMERGENCY_DEPARTMENT_NOTE` to
the legacy section `"hospitalizations"`, not `"discharge_summary"` — a
real discharge-shaped document the classifier tags as one of those two
types never matches `section === "discharge_summary"`, no matter how
the frontend routing is written.

**This document does NOT change that taxonomy mapping** — whether an
admission note or an ED note should open the SAME Phase 8 discharge
reader as a document explicitly classified `discharge_summary` is a
genuine product decision (they are different real-world documents),
not a routing bug, and is left for a future session to decide
deliberately. What WAS fixed: `document_type === "discharge_summary"`
is now checked ALONGSIDE the legacy signals everywhere a routing
decision is made — never replacing them, since `document_type` is not
reliably populated on every upload path today (see below).

## Why `document_type` cannot be the SOLE routing authority

Confirmed by reading the real upload pipeline
(`backend/app/main.py::process_upload_job`): `job.document_type` is only
ever assigned inside the `if job.section == AUTO_CLASSIFY_SECTION:`
block — i.e. only for the patient's own self-upload path (`POST
/upload/batch`, always auto-classify). A doctor or care-partner upload
(`POST /upload/background`) that picks a concrete section from a
picklist — including an explicit "Discharge Summary" option in both
`frontend/app/patients/[id]/upload/page.tsx` and `frontend/app/
care-partner/upload/page.tsx` — never enters that block, so
`document_type` stays `NULL` on the resulting `Document` row even though
`section`/`report_type` are already correct. Using `document_type` alone
would have broken doctor-uploaded discharge documents, which are common,
not fixed a rare case.

## Shared resolver

`frontend/lib/document-routing.ts` (new) — `resolveDocumentRoute(doc,
documentId)`, `isDischargeShapedDocument(doc)`,
`isDerivedLabReportDocument(doc)`. Every routing decision point below
now calls this instead of its own inline copy.

## Routing decision points (frontend)

| File | Function | Before | After |
|---|---|---|---|
| `documents/[id]/page.tsx` | redirect in `fetchData()` | `section`/`parsed_data.report_type` only | + `document_type`, via shared resolver |
| `my-records/page.tsx` | `getStructuredDocumentPath`/`isDischargeDocument` | `section`/`report_type` only | + `document_type`, via shared resolver |
| `patients/[id]/page.tsx` | `getStructuredDocumentPath`/`isDischargeDocument` | `section`/`report_type` only | + `document_type`, via shared resolver |
| `my-records/timeline/page.tsx` | `openTimelineDocument` | **no `derived_artifact_kind` check at all** — a derived lab artifact opened from this Timeline landed on the generic reader | now routes through the shared resolver (fixes the missing derived-artifact check too) |
| `patients/[id]/timeline/page.tsx` | `openTimelineDocument` | same gap as above | same fix |
| `components/analytics/analytics-drilldown-drawer.tsx` | `openSource` | already checked `document_type` only (the one outlier) — no `section`/`report_type` fallback | now via shared resolver (adds the fallback for consistency; `derived_artifact_kind` intentionally not checked here — see file's own comment: `LabResult.document_id` always points at the parent, never a derived artifact) |
| `documents/[id]/lab-report/page.tsx` | `parentDocumentPath` | already correct (`document_type` only, its one available signal) | now via shared resolver, for consistency |
| `documents/[id]/discharge/page.tsx` | none (gap) | **no redirect-away guard at all** — asymmetric with the lab-report reader's own guard | added: redirects to `/documents/{id}/lab-report` if the id resolves to a derived artifact |

## Backend routes / endpoints (unchanged by this audit — confirmed correct)

| Endpoint | Authorization | Notes |
|---|---|---|
| `GET /documents/{id}` | `can_access_patient`/`care_partner_can_access_document` | Generic payload; already returns `document_type`/`derived_artifact_kind`/`patient_id` |
| `GET /documents/{id}/clinical-reader` | same two-branch check | **Extended this session**: `document.patient_id` added to the `document` object (see "Ask Bragi target audit" below) |
| `GET /my/profile` / `GET /patients/{id}/profile` | existing patient/doctor checks | Document cards already carry `document_type`/`derived_artifact_kind` (Phase 9) |
| `GET /patients/{patient_id}/documents` | `doctor_has_patient_access` | Same card shape as above |

No backend route needed a NEW endpoint — this was entirely a frontend
consolidation plus one additive field on an existing response.

## Entry-point agreement (A3)

Verified: Documents list, Overview-tab preview, Timeline (both dedicated
pages), and direct URL all now resolve a canonical discharge document to
`/documents/{id}/discharge` via the SAME `resolveDocumentRoute` function
— previously five independent, drifting copies of this decision existed,
two of which (both Timeline pages) had a real, distinct gap (no
derived-artifact check at all, not just a `document_type` omission).

Ask Bragi citation navigation and derived-artifact parent navigation
were separately audited (see `structured-lab-report.tsx`/
`reader-source-action.tsx`, unchanged — they navigate via
`openSourceEvidence`, a different mechanism from document-reader
routing, not affected by this audit) and confirmed to already resolve
correctly.

## Ask Bragi target audit (A4)

`AskBragiSideTab` has exactly two call sites in the whole frontend:

1. `frontend/app/documents/[id]/page.tsx:1058` — **already correct**:
   `patientId: documentData.patient_id` (the generic reader's own
   `DocumentResponse` already carries a real `patient_id` field).
2. `frontend/app/documents/[id]/discharge/page.tsx:305` — **a real bug,
   confirmed and fixed**: `patientId: document.id` for a doctor/admin
   viewer — the DOCUMENT's own id, not the patient's. This was not a
   copy-paste mistake picking the wrong variable name; the data was not
   even available — `ReaderDocumentMeta` (the discharge reader's own
   document type) had no `patient_id` field at all.

**Fix**: `document.patient_id` added to `GET /documents/{id}/
clinical-reader`'s `document` object (mirrors the generic reader's own
field exactly) and to the `ReaderDocumentMeta` TS type; the discharge
page's Ask Bragi target now reads it. Regression test:
`test_reader_payload_document_includes_real_patient_id`
(`test_clinical_document_reader_api.py`).

**Why this was a functional bug, not a demonstrated cross-patient data
leak**: the backend's `resolve_patient_id_for_new_conversation` +
`recheck_access` (`app/services/ask_bragi/context.py`) validates the
`patient_id` a doctor sends against a real `DoctorPatientAccess` grant,
and `resolve_document_scope` separately confirms the requested document
actually belongs to the resolved patient. A document id sent in
`patient_id`'s place would, in the overwhelming majority of cases,
simply fail that grant check (403) — Ask Bragi not working for doctors
from the discharge reader, not silently serving the wrong patient. Both
independent server-side checks operate on already-trusted data, never
the raw client value alone. Confirmed by reading the actual
authorization code, not assumed.

Other Ask Bragi surfaces (`patients/[id]/ask-bragi/page.tsx`, `/ask-bragi`)
render `AskBragiChat` directly with a `patientId` derived from the URL
route or server-resolved from `current_user` — never a document field —
and were confirmed already correct.

## Deliberately not changed in this pass

- The `HOSPITAL_ADMISSION_NOTE`/`EMERGENCY_DEPARTMENT_NOTE` →
  `"hospitalizations"` taxonomy mapping (see "real root cause" above) —
  a product decision, not a routing bug.
- `document_type` is still not set on every upload path (doctor/
  care-partner manual-section uploads). Making it reliably set
  everywhere is a real, separate improvement a future session could make
  to `process_upload_job`, out of scope for this routing-consolidation
  pass (which deliberately treats `document_type` as an ADDITIVE signal
  specifically because it isn't reliable everywhere yet).
