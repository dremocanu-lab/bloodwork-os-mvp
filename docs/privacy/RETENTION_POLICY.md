# Data Retention Policy

Status: draft. **No automatic retention/expiry/cleanup of clinical
data exists today, and none was added this round** — per the explicit
governing rule for this task: no speculative auto-deletion of clinical
data without legal approval, since retention periods for health
records are frequently legally-mandated *minimums*, not privacy-driven
maximums. Deleting a patient's lab result "for privacy" before any
legally-required retention period has elapsed could itself be a
compliance violation, not a compliance improvement — this is why no
`expires_at`-style mechanism was added speculatively.

## Current state by data category

| Category | Retention today | Notes |
|---|---|---|
| Patient account + all clinical data | Until the patient deletes their own account (`DELETE /my/account`) or an admin action removes it | No automatic expiry |
| Documents, lab results, medications, source evidence | Cascade-deleted with the owning patient/document (verified this round — see the FK-cascade fixes in `BRAGI_SECURITY_GDPR_PLAN.md` §3 item 6) | No independent retention clock |
| `upload_jobs` | Persists indefinitely, even after reaching a terminal status | Real gap — see `docs/privacy/BRAGI_DATA_MAP.md` |
| `audit_logs`, `admin_action_logs` | Persists indefinitely, detached (not deleted) from a deleted patient via `ON DELETE SET NULL` | Deliberate — audit/accountability records outliving the subject's account is standard practice, not a bug |
| `emergency_access_sessions`, `emergency_audit_logs` | Same — persists, detached from a deleted patient | Deliberate, same reasoning; also directly relevant to defending against emergency-access abuse claims, which requires the record to survive |
| Uploaded raw files on disk | Persists until the owning document is deleted (file removal on document deletion was not re-verified exhaustively this round — flagged as a follow-up: confirm every document-deletion path actually removes the on-disk file, not just the DB row) |
| `ask_bragi_conversations`, `ask_bragi_messages` | Cascade-deleted with the owning patient (verified this round — see the FK-cascade fix added alongside this feature: `delete_my_account()` now explicitly deletes a patient's Ask Bragi messages/conversations before the patient row, the same pattern already used for other child tables) | No independent retention clock, no automatic expiry. Asymmetric by existing, deliberate design (not a new gap): deleting the PATIENT's account removes every conversation about them, including a doctor's own questions inside those conversations. Deleting a DOCTOR's account does NOT remove conversations they asked about a still-active patient — doctor/admin accounts are soft-deleted (`_soft_delete_clinical_or_admin_account`), not hard-deleted, specifically because a real `DELETE FROM users` would either violate NOT NULL FKs like `ask_bragi_conversations.owner_user_id` across OTHER patients' records or require silently anonymizing content that legitimately documents another patient's care (see that function's own docstring and `[LEGAL REVIEW]` flag, which already covers this table — no new flag needed for Ask Bragi specifically) |
| OpenAI (per Ask Bragi turn, when `ASK_BRAGI_ENABLED=true`) | Not Bragi's to retain or delete — `store=False` means OpenAI does not keep the conversation server-side beyond its own standard API abuse-monitoring window (a fixed, vendor-set period, not one Bragi controls) | Deleting a patient's account removes Bragi's own copy of every Ask Bragi message but cannot reach into OpenAI's abuse-monitoring retention — this is a real limit on what "deletion" can mean for this specific data flow, not a Bragi implementation gap; see `docs/ai/AI_GOVERNANCE.md` for the full vendor posture |

## What a real retention policy needs before it can be implemented

1. **Legal minimum retention periods** for medical records under
   applicable law (Romanian health-data regulations, and any other
   jurisdiction this platform's patient base falls under) —
   `[LEGAL REVIEW]`. This determines the *floor*, below which data
   cannot be deleted even at the patient's own request in some
   jurisdictions for certain record types (though a patient records
   *portal* storing copies, rather than being the system of record for
   a treating institution, may have a different legal posture than the
   originating clinical system — this distinction itself needs legal
   confirmation).
2. Once a floor is confirmed, a *ceiling* (maximum retention, i.e. "we
   commit to actually deleting/anonymizing data after N years of
   inactivity") can be defined as a genuine privacy-by-design
   improvement — but only after the floor is known, so the ceiling
   never contradicts a legal minimum.
3. Operational cleanup for genuinely non-clinical, time-boxed data
   (e.g. `upload_jobs` rows after a job is terminal and its resulting
   `documents` row exists) IS safe to implement without legal review,
   since it duplicates data that remains available via the `documents`
   table — flagged as a safe, low-risk follow-up distinct from clinical
   record retention.

## Status

`[LEGAL REVIEW]` for clinical-data retention limits — not yet defined.
`[FAIL]`/opportunity for `upload_jobs` cleanup specifically — safe to
implement, not done this round due to scope, tracked as a follow-up.
