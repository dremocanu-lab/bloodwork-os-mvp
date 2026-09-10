# Record of Processing Activities (ROPA) — DRAFT

`[LEGAL REVIEW]` required for final form and completeness (Art.30
requires specific fields this draft approximates but does not
guarantee are exhaustive). Structured from the code-verified facts in
`docs/privacy/BRAGI_DATA_MAP.md` and `docs/privacy/PROCESSING_PURPOSES.md`.

| Processing activity | Categories of data subjects | Categories of personal data | Purpose | Recipients | Retention | Transfers |
|---|---|---|---|---|---|---|
| Patient account management | Patients | Name, email, password hash | Provide the service | None external | Until account deletion | N/A |
| Document upload & AI extraction | Patients | Full document content incl. identity fields (name, DOB, sex, CNP), clinical data | Convert uploaded documents into structured, chartable records | Reducto, OpenAI, Google Document AI (see `docs/privacy/VENDOR_REGISTER.md`) | Until document/account deletion | `[UNKNOWN]` — see `docs/privacy/TRANSFER_REGISTER.md` |
| Clinician access grants | Patients, doctors | Access-grant metadata (who, when, active/revoked) | Enable authorized clinical review | None external | Until account deletion (audit trail may persist detached, see retention policy) | N/A |
| Care-partner sharing | Patients, care partners | Document-share grants | Let patients share specific records with a chosen person | None external | Until revoked/account deletion | N/A |
| Emergency/break-glass access | Patients, emergency workers | Access-session metadata, reason text, IP/user-agent | Enable time-limited emergency record access | None external | Persists (detached from deleted patient) for accountability | N/A |
| Security/audit logging | All roles | Actor, action, timestamp, free-text details | Security, accountability | None external | Persists (detached from deleted subject where applicable) | N/A |
| Emergency contact records | Patients (about a third party) | Third party's name, phone, relationship | Patient-configured emergency contact info | None external | Until patient removes/account deletion | N/A |

## Known incompleteness

- Retention periods are stated as "until deletion" rather than a fixed
  period because no fixed retention policy has been legally established
  — see `docs/privacy/RETENTION_POLICY.md`.
- Transfer mechanisms are `[UNKNOWN]` pending
  `docs/privacy/TRANSFER_REGISTER.md`'s account-configuration
  confirmations.
- Legal basis per activity is a working assumption, not a legal
  conclusion — see `docs/privacy/PROCESSING_PURPOSES.md`.
- Controller identity is not settled — see
  `docs/privacy/CONTROLLER_PROCESSOR_MAP.md`. A ROPA is normally
  maintained BY the controller; this draft assumes Bragi's operating
  entity is the controller for drafting purposes only.

## Status

Draft, code-verified for the "what data/what purpose/what recipients"
columns; `[LEGAL REVIEW]` for retention and transfer columns and for
overall Art.30 completeness.
