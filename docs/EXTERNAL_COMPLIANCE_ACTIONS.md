# External / Vendor / Legal Action Items

A consolidated list of everything in this engineering effort that
requires action OUTSIDE this codebase — a vendor account/contract, a
legal/compliance determination, an independent audit, or a product
decision this engineering round could not make unilaterally. Nothing in
this document is resolved by writing more code; each item below is
either genuinely external, or requires a decision-maker other than the
person authoring the engineering work. See `BRAGI_SECURITY_GDPR_PLAN.md`
for the full engineering narrative each item is drawn from.

**This document does not claim GDPR/HIPAA/MDR/EU-AI-Act/ISO-27001/SOC-2
compliance.** None of that is established by anything in this list —
several items below are prerequisites to even beginning that
determination, not the determination itself.

## `[EXTERNAL ACTION]` — requires a vendor/account/contract decision

| # | Item | Detail | Reference |
|---|---|---|---|
| 1 | Real antivirus/malware-scanning engine | No ClamAV or equivalent is connected in any environment. The pipeline boundary (`upload -> security_scan -> accepted/quarantined -> processing`) is real and enforced, and a ClamAV integration is ready to activate behind `CLAMAV_HOST`, but nothing has been provisioned. | `docs/security/MALWARE_SCANNING_PLAN.md` |
| 2 | Distributed rate-limiting backend (Redis) | `RATE_LIMIT_REDIS_URL`/`REDIS_URL` is not set in Render's environment. The app runs correctly on a per-instance in-memory fallback today (correct for a single instance), but this must be provisioned before/at the same time as any horizontal scaling. | `docs/security/RATE_LIMITING.md` |
| 3 | OpenAI DPA / Zero Data Retention terms | Whether OpenAI's actual contract terms with this organization support the processing done here (raw document images/PDFs sent for extraction) is not knowable from this codebase. | `docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md` |
| 4 | Reducto DPA / data-handling terms | Same category as above — Reducto receives full document content for classify/split/parse/extract. | `docs/vendors/REDUCTO_PRODUCTION_REQUIREMENTS.md` |
| 5 | Google Document AI DPA / data-handling terms | Same category — OCR/discharge-summary support sends document content. | `docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md`, `docs/privacy/VENDOR_REGISTER.md` |
| 6 | Neon (Postgres) backup/PITR configuration | Actual backup/point-in-time-recovery settings are an account/console-level configuration this codebase cannot verify or change. No restore test has been performed. | `docs/security/BACKUP_DR_PLAN.md` |
| 7 | Render backup/disk-persistence guarantees for uploaded files | Whether uploaded files on Render's disk survive a redeploy/instance migration/disk failure is a platform guarantee, not something this codebase controls. | `docs/security/BACKUP_DR_PLAN.md` |
| 8 | International data-transfer register completeness | Where each vendor actually processes/stores data (which region, which sub-processors) requires vendor-provided documentation this codebase doesn't have. | `docs/privacy/TRANSFER_REGISTER.md` |
| 9 | Production access policy enforcement (current state) | The policy is documented; whether it's actually enforced today (who has prod DB/Render/Vercel access, MFA, offboarding) is an operational fact outside this codebase. | `docs/security/PRODUCTION_ACCESS_POLICY.md` |
| 10 | Security monitoring / incident detection tooling | No analytics/error-monitoring SDK exists in the codebase — there is no automated detection of a real security incident today; the incident-response *procedure* is documented, but nothing triggers it automatically. | `docs/security/INCIDENT_RESPONSE.md` |

## `[LEGAL REVIEW]` — requires a legal/compliance determination

| # | Item | Detail | Reference |
|---|---|---|---|
| 11 | Controller/processor determination | Who is the data controller for patient health data processed by this platform (the platform operator, the treating clinic/hospital, or a joint-controller arrangement) depends on contracts this repository cannot see. | `docs/privacy/CONTROLLER_PROCESSOR_MAP.md` |
| 12 | Processing purposes / legal basis (final) | Working assumptions are documented; the final legal basis for each processing purpose needs sign-off. | `docs/privacy/PROCESSING_PURPOSES.md` |
| 13 | Clinical-data retention periods | Whether/how long health records must legally be retained (a floor, not just a privacy-driven ceiling) varies by jurisdiction and record type. This governs both the (deliberately unimplemented) auto-deletion question and the erasure-vs-retention tension below. | `docs/privacy/RETENTION_POLICY.md` |
| 14 | Doctor/admin account soft-delete as an erasure policy | This round implemented doctor/admin self-deletion as a soft-delete (login disabled, PII on the account itself anonymized, but the row and every OTHER patient's clinical records that reference it survive) rather than a full erasure, specifically because those records are part of a DIFFERENT patient's own care history. Whether this is the legally correct final shape (vs. a longer grace period, deeper anonymization, or a different retention argument entirely) needs review. | `docs/privacy/DSAR_RUNBOOK.md` §"Right to erasure" |
| 15 | Right to restrict processing / object (Art. 18/21) | No dedicated mechanism exists (e.g. "pause AI processing on my documents"). Whether this is actually required given the specific processing purposes involved needs a legal read, not an engineering guess. | `docs/privacy/DSAR_RUNBOOK.md` |
| 16 | Privacy notice, DPIA, ROPA | All drafted; none published/approved. | `docs/privacy/PRIVACY_NOTICE_DRAFT.md`, `docs/privacy/DPIA_DRAFT.md`, `docs/privacy/ROPA_DRAFT.md` |
| 17 | MDR / EU AI Act boundary statement | Conservative language throughout; does not claim to be definitively outside either regime's scope. | `docs/regulatory/INTENDED_PURPOSE_DRAFT.md` |
| 18 | Non-app-channel DSAR identity verification | A DSAR submitted through the logged-in app is verified by the existing auth system. A request submitted another way (e.g. an email to a support address) has no documented verification procedure — needs a decision from whoever owns that channel. | `docs/privacy/DSAR_RUNBOOK.md` |

## `[PRODUCT DECISION REQUIRED]` — requires a product-owner decision (not silently guessed at by engineering)

| # | Item | Detail | Reference |
|---|---|---|---|
| 19 | `emergency_worker` self-deletion | Deliberately not implemented this round — emergency-access accounts are commonly tied to institutional/break-glass provisioning this codebase has no visibility into. A clean 403 is returned today, not a broken/missing feature. | `docs/privacy/DSAR_RUNBOOK.md` |
| 20 | `role` self-selection at signup | `POST /auth/signup`'s `role` field accepts `admin`/`doctor` with no server-side gate beyond a code for `care_partner`. Could be intentional open self-service onboarding, or a real gap — cannot be told apart from the code alone, and changing it risks breaking the actual current onboarding process. | `BRAGI_SECURITY_GDPR_PLAN.md` §6 |
| 21 | `/admin/patients/search` scoping | Has no department/hospital scoping, unlike `/admin/doctors`. Admin is already treated as a broad/trusted role elsewhere; narrowing it unilaterally could break an intended workflow. | `BRAGI_SECURITY_GDPR_PLAN.md` §5 |

## `[INDEPENDENT VALIDATION]` — requires a party other than the author of the code

| # | Item | Detail |
|---|---|---|
| 22 | Everything in this document and `BRAGI_SECURITY_GDPR_PLAN.md` | This is a self-run engineering effort. A real security posture claim (penetration test, external audit, or a certification body's assessment) requires a party other than the author of the code being reviewed. Nothing here substitutes for that. |

## Status labels used above

Same convention as `BRAGI_SECURITY_GDPR_PLAN.md` §0 — see that document
for the full definitions. This document only ever uses
`[EXTERNAL ACTION]`, `[LEGAL REVIEW]`, `[PRODUCT DECISION REQUIRED]`, and
`[INDEPENDENT VALIDATION]` — anything markable `[PASS]`/`[FAIL]` belongs
in the main plan document, not here.
