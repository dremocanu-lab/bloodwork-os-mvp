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
  specifically because it isn't reliable everywhere yet). **Partially
  closed in a later session** — see "Routing vs. classification" below.

## Routing vs. classification — two independent things, both now verified (pre-Phase-11 closure session)

This audit's original claim — "fresh Romanian discharge upload now opens
the Phase 8 reader" — was true but **incomplete**: every test built for
it (this audit's own `routing-and-integration-fixes.spec.ts`, and every
`seed_e2e_discharge_document.py`-based fixture) constructs a `Document`/
`UploadJob` with `document_type`/`section` **already hardcoded** to
`"discharge_summary"`. That proves ROUTING (does correct metadata reach
the right reader) but says nothing about CLASSIFICATION (does the real
classifier, given a real document's actual text, produce that correct
metadata in the first place). A later manual-QA report — a real/
synthetic Romanian document titled "BILET DE IEȘIRE DIN SPITAL /
SCRISOARE MEDICALĂ" not visibly reaching the reader — exposed exactly
this gap, and a dedicated session closed it. Full accounting:
`docs/handoffs/CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md`'s "Romanian
Discharge Classification / Reader Closure" section. Summary:

- **Real, reproduced classification bug found and fixed**: the legacy
  rule-based classifier (`document_classifier.py`) had a keyword entry
  for "bilet de externare" but NONE for "bilet de iesire (din spital)" —
  a different, equally common Romanian discharge-letter title with no
  shared substring. A realistic reproduction (the real title + a dense
  embedded hematology lab table, closely matching the reported document)
  scored discharge_summary=14.5 vs laboratory_results=14.0 — correctly
  the winner, but a margin of 0.5 (below `CONFIDENT_MARGIN_THRESHOLD=
  1.5`) forced an unnecessary `needs_confirmation` on an otherwise-clear
  discharge letter. Adding the missing keywords widened the margin to
  19.5 vs 14.0 (confidence 1.0, `classified`). Reducto's `CLASSIFICATION_
  SCHEMA` criteria for `discharge_summary` was also English-only (unlike
  sibling categories, which DO embed their own Romanian term in the
  criteria text — `hospital_admission_note` names "foaie de internare"
  directly) — updated to name the same Romanian titles explicitly and to
  instruct the model that embedded lab tables don't change a document's
  own dominant, document-level purpose. **Not independently live-tested
  against the real Reducto API this session** (no established, safe
  synthetic-PDF-generation fixture exists in this repo to do so without
  adding a new PDF-authoring dependency) — a real gap, honestly flagged,
  not silently assumed fixed.
- **Real, closed persistence gap**: `POST /upload/background` (the
  doctor/care-partner manual-section-picklist path) now sets
  `UploadJob.document_type` directly for the two `section` values that
  map onto exactly one `DocumentType` each — `discharge_summary` and
  `bloodwork` — via a new `UNAMBIGUOUS_SECTION_DOCUMENT_TYPE` map in
  `documents.py`. The other four section values (`medications`/`scans`/
  `hospitalizations`/`other`) are still deliberately left `NULL`: each
  covers more than one real `DocumentType`, and guessing one would be
  worse than leaving it unset.
- **New end-to-end test closing the real "never tested" boundary**:
  `backend/tests/test_romanian_discharge_classification_e2e.py` runs
  real Romanian source text through the REAL upload pipeline (`POST
  /upload/batch`, `REDUCTO_ENABLED` forced off for determinism, OCR
  stubbed to return the fixture text verbatim — nothing else mocked) —
  proving persisted `Document.document_type`/`section` and `GET
  /documents/{id}/clinical-reader` all the way through, not just
  `classify_document_text()` in isolation. A new Playwright suite,
  `frontend/e2e/romanian-discharge-classification.spec.ts`, seeds via a
  new script that calls the real classifier (never hardcodes
  `document_type`, and fails loudly if the classifier doesn't return
  `discharge_summary`) and proves the actual Phase 8 reader renders —
  Documents-list click-through, direct URL, hard refresh, and mobile.
