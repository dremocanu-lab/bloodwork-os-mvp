# Processing Purposes

Maps each category of personal-data processing (from
`docs/privacy/BRAGI_DATA_MAP.md`) to its purpose and likely GDPR legal
basis. Legal-basis conclusions are engineering's working assumption for
planning purposes only — final determination is `[LEGAL REVIEW]`.

| Processing activity | Purpose | Likely legal basis (working assumption) |
|---|---|---|
| Account creation (`users`, `patients`) | Provide the patient/clinician with the service | Contract (Art.6(1)(b)) — necessary to provide the account the user signed up for |
| Document upload + OCR/extraction (Reducto/OpenAI/Google) | Turn an uploaded medical document into structured, searchable, chartable data for the patient | Explicit consent (Art.9(2)(a)) for special-category health data — the patient affirmatively uploads their own document, but explicit, informed consent language for AI-vendor processing has not been confirmed to exist in the current signup/upload flow; see `docs/privacy/PRIVACY_NOTICE_DRAFT.md` |
| Doctor/PCP access to patient records | Enable clinical review by a clinician the patient (or admin) has granted access to | Consent (patient grants access) or, for a treating clinician, potentially Art.9(2)(h) (health/social care) — needs legal confirmation given Bragi is a records portal, not itself a care-delivery system |
| Care-partner access | Let a patient share records with a family member/caregiver of their choosing | Consent — explicit, patient-initiated via a share code |
| Emergency/break-glass access | Give an authorized emergency worker time-limited access to a patient's records when the patient has opted in | Vital interests (Art.9(2)(c)) for the access itself, combined with prior patient consent to be discoverable (`emergency_search_enabled`) — a reasonable double basis, not yet legally confirmed |
| Audit logging (`audit_logs`, `admin_action_logs`, `emergency_audit_logs`) | Security, accountability, and (for emergency access) abuse deterrence | Legal obligation / legitimate interest (Art.6(1)(c)/(f)) — accountability is itself a GDPR Art.5(2) requirement |
| Emergency contacts | Let a patient record who to contact in an emergency | Consent (patient-entered, about a third party) — see `docs/privacy/BRAGI_DATA_MAP.md`'s note on emergency contacts having no account/rights interface of their own |

## Purposes NOT currently served by any processing

- Marketing/advertising: none found — no analytics, no marketing SDK,
  no email-campaign integration in the codebase.
- Automated decision-making with legal/similarly-significant effect on
  a data subject: none found — no feature makes an automated clinical
  decision; all AI-extracted data is presented as extracted evidence
  with a source citation, not as a diagnosis or recommendation, and no
  route acts on extracted data without a human view step (consistent
  with the "conservative clinical readers" design established in
  `BRAGI_REDUCTO_PLAN.md`'s Phase 4).

## Gaps for legal review

- No confirmed, explicit consent-capture step exists in the signup/
  upload flow specifically covering "your document will be sent to
  Reducto/OpenAI/Google for processing" — this needs to exist and be
  logged (with a version, mirroring the pattern already used for
  `emergency_search_consent_text_version`) before "explicit consent"
  can be claimed as the Art.9 basis for AI-vendor processing.
- The legal basis for doctor/PCP access needs confirmation given the
  ambiguity in `docs/privacy/CONTROLLER_PROCESSOR_MAP.md`.
