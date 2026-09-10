# DSAR (Data Subject Access Request) Runbook

Status: draft runbook, mixing what the platform already supports
programmatically with manual fallback steps for what it doesn't.

## Right of access (Art.15) / data portability (Art.20)

**Implemented this round**: `POST /my/export` (patient role only) —
`[PASS]`, evidence: `backend/tests/test_dsar_export.py` (8 tests,
real DB, real synthetic accounts) covering auth requirement, role
restriction (non-patients get 403), expected file presence, own-data
correctness, cross-patient isolation, and real original-file embedding.

Returns a zip containing: `profile.json`, `lab_results.json`,
`medications.json`, `events.json`, `access_relationships.json`
(doctor/care-partner access grants, requests, and links — a recipient's
identity is itself disclosable under Art.15(1)(c)), `emergency_contacts.
json`, `documents_manifest.json` (metadata for every uploaded document),
`documents/` (the original files themselves, up to a 500MB per-export
cap — see `DSAR_EXPORT_MAX_FILE_BYTES` in `backend/app/main.py`; beyond
the cap, a document is still fully described in the manifest with a note
that its raw file was omitted), `ai_conversations.json` (present but
empty — no AI chat feature exists yet), and `README.txt` explaining the
contents. Authorization reuses the existing pattern exactly (`require_
role("patient")` + `get_patient_for_user`, which only ever resolves to
the caller's own linked `Patient` row — there is no separate "which
patient" parameter for a caller to manipulate, unlike a lookup-by-id
route). Rate-limited (3/day per IP, see `docs/security/RATE_LIMITING.md`)
since it's a real disk/DB-cost operation. Every included document gets
its own `AuditLog` row (`action="dsar_export"`) — a durable, queryable
record of what was exported and when, in addition to a PHI-free summary
line in the server log.

**Deliberately excluded** (verified, not just assumed): any other
patient's data (every query is scoped to `patient.id`, confirmed via the
cross-patient isolation test); quarantined documents uploaded under this
identity but not yet confirmed as belonging to this patient's record
(`Document.patient_id` must match exactly; an `intended_patient_id`-only
row is unconfirmed, not exported); internal account security metadata
(password hash, JWT internals).

**Not implemented this round** (documented, not silently dropped):
export for non-patient roles (doctor/admin/care_partner/
emergency_worker) — their personal-data footprint is much smaller
(account fields, assignment history) and was judged lower-priority than
the patient export, which carries the bulk of this system's actual PHI;
a PDF rendering (JSON + original files was judged sufficient "machine-
readable" portability for Art.20 without adding a PDF-generation
dependency this round).

## Right to erasure (Art.17)

`DELETE /my/account` — `[PASS]` for patients (this round's FK-cascade
fixes directly improved this; see `BRAGI_SECURITY_GDPR_PLAN.md` §3
item 6 and §19). **Doctors, admins, care partners, and
emergency_worker accounts have no self-deletion endpoint at all** —
`[FAIL]`, a real gap. Manual fallback: an admin/engineer can delete
these rows directly, but there is no audited, self-service path today.
Flagged as a follow-up (a `DELETE /my/account` equivalent generalized
across roles, or role-specific deletion routes).

Note: erasure requests may still be subject to the same legal-minimum-
retention question as `docs/privacy/RETENTION_POLICY.md` raises —
right to erasure is not absolute where a legal retention obligation
applies (GDPR Art.17(3)(b)). `[LEGAL REVIEW]`.

## Right to rectification (Art.16)

Patients/doctors can edit most fields through the normal app UI
(document metadata, medications, etc.) — this satisfies rectification
in substance for user-editable fields. **No rectification-history/
audit trail was confirmed to exist for these edits** (distinct from
`documents.last_edited_at`, which is a single timestamp, not a change
history) — meaning a correction silently overwrites the prior value
with no record of what it was corrected from, or by whom, beyond that
single timestamp. This was flagged as a requirement in the original
task ("never silently overwrite provenance") and is a real,
unaddressed gap: not implemented this round given the scope (a proper
change-history table/mechanism is a real feature, not a safe drive-by
addition). `[FAIL]`.

## Right to restrict processing / object (Art.18/21)

No dedicated mechanism exists (e.g. a "pause AI processing on my
documents" toggle). `[FAIL]`/`[UNKNOWN]` whether this is actually
needed given the specific processing purposes involved —
`[LEGAL REVIEW]`.

## Identity verification for a DSAR

Any DSAR must first verify the requester is actually the data subject
(or their authorized representative) before acting — the existing
authentication system (a logged-in patient acting via their own
account) satisfies this for self-service requests. For a request
**not** made through the logged-in app (e.g. an email to a support
address), no verification procedure is documented here yet — flagged
as a process gap requiring a decision from whoever owns the security-
contact channel (`docs/security/PRODUCTION_ACCESS_POLICY.md`).

## Status summary

| Right | Status |
|---|---|
| Access | `[PASS]` — full UI visibility plus `POST /my/export` for portable export (patient role) |
| Erasure (patient) | `[PASS]` post this round's fixes |
| Erasure (other roles) | `[FAIL]` — no endpoint |
| Rectification | `[PASS]` in substance, `[FAIL]` for change-history |
| Restriction/objection | `[FAIL]`/`[UNKNOWN]` |
| Non-app-channel identity verification | `[UNKNOWN]` — no documented process |
