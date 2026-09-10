# Row-Level Security (RLS) Plan

Status: assessment + design only. **Not enabled on any table.** This
document exists to think through RLS carefully before touching
production, per the explicit instruction governing this round: do not
enable RLS blindly, and do not classify its current absence as a
Critical vulnerability if application-layer authorization is actually
functioning — assess real risk, not theoretical risk.

## Why this needs care before activation, specifically for this stack

1. **Neon connection pooling.** This app connects to Neon, which is
   commonly used through PgBouncer-style transaction pooling. RLS
   policies that rely on a session-level `SET` (e.g. `SET
   app.current_patient_id = ...`) do not reliably survive across pooled
   connections unless `SET LOCAL` inside an explicit transaction is
   used consistently, and every DB access in the app would need to
   guarantee that. `backend/app/db.py`'s actual pooling configuration
   has not been re-verified against Neon's current pooler mode as part
   of this round — doing so is a prerequisite, not an assumption to
   make.
2. **The app has no per-request "current patient" concept at the DB
   session level today.** Authorization happens in Python
   (`can_access_patient()` and friends), not via a Postgres role/session
   variable the DB itself enforces. Introducing RLS means introducing an
   entirely new mechanism (setting a session variable per request) that
   does not exist anywhere in this codebase yet — this is a real
   architecture change, not a config flip.
3. **Background jobs are not request-scoped.** `process_upload_job`
   (background-task processing) and any other non-HTTP-request DB
   access (migrations, ad-hoc scripts) would need their own RLS-bypass
   path (e.g. a superuser/BYPASSRLS role) or they would silently break —
   this has real potential to turn into a production outage
   (`process_upload_job` failing silently, uploads stuck `processing`
   forever) if not planned for explicitly.
4. **Admin's blanket access** (`can_access_patient()` returns `True`
   unconditionally for `role == "admin"`, see
   `docs/security/AUTHORIZATION_MATRIX.md`) would need an equivalent
   RLS bypass policy, not just per-patient scoping — a naive
   patient-scoped RLS policy would break every admin route.
5. **Care-partner and emergency-worker access patterns are not
   simple per-patient ownership** — they're per-document
   (`SharedStructuredPage`) and per-active-session
   (`EmergencyAccessSession`) respectively. An RLS policy expressive
   enough to encode both correctly is materially more complex than the
   textbook "`WHERE patient_id = current_setting('app.patient_id')`"
   pattern.

## Actual current risk assessment

Application-layer authorization (`can_access_patient()` and friends) is
consistently applied across the route surface — verified this round via
route-by-route review and a 10-test IDOR regression suite, all passing.
The two real gaps found (`is_active` staleness in two list endpoints)
were both fixed and are unrelated to RLS — they were bugs in the
Python-layer checks, which RLS would not have automatically prevented
either (RLS enforces row visibility, not business rules like "is this
grant still active"). **Conclusion: the absence of RLS is a defense-
in-depth gap, not evidence that unauthorized cross-patient access is
currently possible.** RLS would protect against a *future* bug that
bypasses the Python-layer check (e.g. a new raw-SQL query that forgets
to filter by patient), which is a real value proposition — but it is
additive protection, not a fix for a currently-exploitable hole.

## Path to a safe RLS rollout (not started)

1. Confirm Neon's actual pooling mode for this project and how
   `backend/app/db.py`'s engine is configured (pool class, pooling
   library) — currently `[UNKNOWN]`.
2. Design a session-variable-setting pattern (`SET LOCAL` inside each
   request's transaction) and verify empirically, in the dev DB only,
   that it survives real usage under the app's actual connection
   pooling before writing a single policy.
3. Create a dedicated low-privilege Postgres role for the app's normal
   runtime connection, and a separate BYPASSRLS role reserved for
   migrations/background jobs/admin routes — do not attempt RLS with
   the app's current runtime role if it has superuser or table-owner
   privileges (RLS is bypassed by both).
4. Write policies for `patients`, `documents`, `lab_results`,
   `source_evidence`, `patient_medications`, `emergency_contacts`,
   `patient_events` mirroring `can_access_patient()`'s actual logic,
   including the admin bypass and the care-partner/emergency exceptions.
5. Run the full existing test suite (87+ tests) and the IDOR regression
   suite specifically against a dev DB with RLS enabled, before ever
   considering a production rollout.
6. Roll out with RLS policies present but not yet `FORCE`d, monitoring
   for query failures, before making it mandatory.

None of steps 1–6 has been executed. `[IMPLEMENTED — NOT DEPLOYED]`
applies only to this planning document itself; no code or policy exists
yet.
