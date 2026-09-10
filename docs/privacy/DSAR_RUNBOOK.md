# DSAR (Data Subject Access Request) Runbook

Status: draft runbook, mixing what the platform already supports
programmatically with manual fallback steps for what it doesn't.

## Right of access (Art.15) / data portability (Art.20)

**No dedicated self-service export feature was confirmed to exist**
in this codebase (checked this round: no `/export` or equivalent route
found in `backend/app/main.py`'s route surface for producing a
structured data export). A patient can view all of their own data
through the normal app UI (profile, documents, labs, medications,
timeline), which satisfies *access* in substance, but not in the
portable/machine-readable form Art.20 contemplates.

**Manual fallback today**: an engineer with legitimate authorization
can query the patient's own rows across the tables listed in
`docs/privacy/BRAGI_DATA_MAP.md` (keyed by `patient_id`) and produce an
export. This must follow the same rule as all other work under this
plan — never copy this into a ticket/fixture/log casually; treat it as
live PHI handling with the same care as any production access.

**Recommended fix (not implemented this round)**: a `GET
/my/data-export` route producing a structured JSON (or PDF) bundle of
the patient's own data, reusing the same `patient_id`-scoped queries
`can_access_patient()`-gated routes already use — a genuinely
achievable, safe, additive feature, not a large one. Flagged as a
near-term follow-up given its direct DSAR relevance.

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
| Access | `[PASS]` in substance (full UI visibility), `[FAIL]` for portable export |
| Erasure (patient) | `[PASS]` post this round's fixes |
| Erasure (other roles) | `[FAIL]` — no endpoint |
| Rectification | `[PASS]` in substance, `[FAIL]` for change-history |
| Restriction/objection | `[FAIL]`/`[UNKNOWN]` |
| Non-app-channel identity verification | `[UNKNOWN]` — no documented process |
