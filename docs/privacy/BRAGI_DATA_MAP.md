# Bragi Data Map

Source of truth: `backend/app/models.py` (20 tables, read in full for
this document — table list below is exhaustive, not sampled). This
document maps what personal/health data exists, where, and its
sensitivity — the input to `docs/privacy/PROCESSING_PURPOSES.md`,
`docs/privacy/ROPA_DRAFT.md`, and `docs/privacy/DPIA_DRAFT.md`.

Sensitivity key: **Direct ID** (identifies a person on its own),
**Special category** (GDPR Art.9 health data), **Indirect ID**
(identifying in combination), **Audit/meta** (operational, not health
data itself but privacy-relevant as an access record).

## Tables

| Table | Key personal-data columns | Sensitivity | Notes |
|---|---|---|---|
| `users` | `email`, `full_name`, `password_hash`, `department`, `hospital_name` | Direct ID (all roles — patients, doctors, admins, care partners, emergency workers all have a `users` row) | `password_hash` is bcrypt, never plaintext |
| `patients` | `full_name`, `date_of_birth`, `age`, `sex`, `cnp`, `patient_identifier` | Direct ID + special-category-adjacent (`cnp` is Romania's national ID — treat as a direct identifier of high sensitivity) | `emergency_search_enabled`/`_updated_at`/`_consent_text_version` are consent-state fields, not health data |
| `documents` | `patient_name`, `date_of_birth`, `age`, `sex`, `cnp`, `patient_identifier`, `extracted_text`, `structured_sections`, `parsed_content`, `note_body`, plus clinical metadata (`lab_name`, `referring_doctor`, `report_name`, `test_date`, etc.) | Special category (the raw/extracted content of a real medical document) + Direct ID (identity fields duplicated per-document, independent of `patients`) | The single largest concentration of PHI in the schema; `saved_to` points to the raw file on disk (also PHI) |
| `lab_results` | `raw_test_name`, `canonical_name`, `value`, `flag`, `reference_range`, `unit`, `institution`, `accession_id` | Special category | Structured extraction of `documents.extracted_text`; no direct identifiers of its own (reached via `document_id`) |
| `source_evidence` | `source_text` (verbatim excerpt from the source document) | Special category | Exists specifically to let the UI show provenance — `source_text` can contain any PHI that appeared near a lab value |
| `patient_medications` | `name`, `dose_strength`, `frequency`, `reason`, `prescriber`, `extra_info` | Special category | Patient- or clinician-entered, not just extracted |
| `emergency_contacts` | `name`, `contact_relationship`, `phone`, `notes` | Indirect ID + special-category-adjacent (identifies a third party, the patient's contact, who is not themselves a system user) |
| `patient_events` | `title`, `description`, `hospital_name`, `department` | Special category (admission/discharge episodes) |
| `doctor_patient_access`, `doctor_patient_access_requests` | doctor/patient ID pairs, timestamps | Indirect ID | Access-grant records — privacy-relevant as "who could see this patient," not health data itself |
| `note_document_links` | none beyond FKs | — | Structural only |
| `upload_jobs` | duplicates a subset of `documents` fields during processing (`filename`, `saved_to`, classification fields) | Special category | Transient processing state; not fully cleared after a job completes (see §"Data not yet minimized" below) |
| `audit_logs` | `actor`, `details` (free text) | Audit/meta, but `details` is not schema-constrained — could carry PHI if a caller ever put PHI into it (not observed in current call sites, not proven absent either) |
| `admin_action_logs` | `details` (free text), links to `patient_id`/`doctor_user_id` | Audit/meta |
| `doctor_document_reviews` | doctor/document ID pairs | Audit/meta |
| `patient_care_partner_codes`, `care_partner_patient_links` | invite codes, linkage | Indirect ID |
| `shared_structured_pages` | document/care-partner share grants | Indirect ID |
| `emergency_access_sessions` | `reason`, `reason_note` (free text), `ip_address`, `user_agent` | Audit/meta + special-category-adjacent (`reason_note` could describe the patient's condition) |
| `emergency_audit_logs` | `details` (free text), `ip_address`, `user_agent` | Audit/meta |

## Data flows (where personal data leaves the database)

1. **Upload → vendor processing → back into the DB.** A patient/doctor
   uploads a file (`POST /upload`, `/upload/background`, `/upload/batch`)
   → the raw file is sent to Reducto (`platform.reducto.ai`) and/or
   OpenAI (`api.openai.com`, via the `openai` SDK) and/or Google
   Document AI (`app/services/document_ai_layout.py`,
   `app/services/google_document_ai_service.py`) for OCR/classification/
   extraction → results are written back into `documents`, `lab_results`,
   `source_evidence`. See `docs/vendors/` for per-vendor detail. This is
   the only outbound flow of raw document content in the system.
2. **Frontend ↔ backend.** Every authenticated API response can carry
   PHI to the browser; the JWT (no PHI inside it — carries only user id/
   role, confirmed by reading `create_access_token`) authorizes each
   request. No PHI is ever embedded in a URL path (path params are
   integer IDs), but CNP is embedded in **query strings** on
   `/emergency/search` and `/patients/search` — see
   `BRAGI_SECURITY_GDPR_PLAN.md` §8.
3. **File storage.** Uploaded files are written to local disk
   (`UPLOAD_DIR`) under randomized filenames, served back only through
   authenticated, per-request-authorized routes (`/documents/{id}/file`,
   never a static/public path).
4. **No outbound flow to analytics/monitoring** — confirmed no such SDK
   exists in the codebase (`BRAGI_SECURITY_GDPR_PLAN.md` §17).
5. **No AI chat feature** — so no outbound "ask a question about my
   records" flow exists yet; see `docs/ai/AI_GOVERNANCE.md` for what
   will need to be true before one is built.

## Data NOT yet minimized (real gaps, not paperwork)

- `documents` duplicates `patients`' identity fields per-row rather
  than only referencing `patient_id` — a deliberate product design
  (documents can arrive before identity is confirmed, see
  `identity_status`), but it means identity data exists in two places
  that must both be corrected/deleted together. Confirmed this round:
  account deletion correctly removes both (patient row + all its
  documents cascade).
- `upload_jobs` rows are not cleaned up after a job reaches a terminal
  state — they persist indefinitely, duplicating filename/classification
  data that also lives on the resulting `documents` row. Not a security
  bug, but a retention-policy gap — see `docs/privacy/RETENTION_POLICY.md`.
- No field-level encryption exists for `cnp` or any other column — all
  special-category data is protected by access control and (in transit)
  TLS only, not by encryption-at-rest beyond whatever Neon provides at
  the storage-volume level by default. See
  `docs/security/IDENTIFIER_ENCRYPTION_PLAN.md`.

## Data subjects

- **Patients** — the primary data subjects; most tables key off
  `patient_id`.
- **Emergency contacts** — third parties whose name/phone/relationship
  is stored by the patient's own choice, but who are not themselves
  system users and have no account, consent flow, or access to see/
  correct/delete what's stored about them. Flagged for
  `docs/privacy/PRIVACY_NOTICE_DRAFT.md` and `docs/privacy/DSAR_RUNBOOK.md`
  — a DSAR against an emergency contact's data would have to be
  actioned via the patient's account, since the contact has no login.
- **Doctors/admins/care partners/emergency workers** — data subjects
  for their own `users` row (email, name) and for their own activity
  records (`audit_logs.actor`, `emergency_access_sessions`,
  `admin_action_logs`), but not for the patient data they merely access.
