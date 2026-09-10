# Production Access Policy

Status: policy document. Most of what this document should state
(who actually holds credentials today, whether MFA is enforced on
Render/Vercel/Neon/GitHub/Reducto/OpenAI/Google accounts) is
**account-level fact this codebase cannot verify** — `[UNKNOWN]` for
current state throughout, with the policy this repo commits to going
forward stated explicitly.

## What engineering can confirm from the repository

- No hardcoded credentials, API keys, or personal contact information
  exist in the working tree (`detect-secrets` scan, this round,
  0 findings — `BRAGI_SECURITY_GDPR_PLAN.md` §11).
- All production secrets (`DATABASE_URL`, `SECRET_KEY`,
  `REDUCTO_API_KEY`, `OPENAI_API_KEY`, Google service-account
  credentials) are environment-variable-scoped via Render/Vercel, never
  committed.
- There is no in-app admin console for managing infrastructure access
  (Render/Vercel/Neon/vendor consoles are all managed outside this
  application) — production access governance is entirely an
  account-management concern, not an application feature.
- There is no in-app audit trail of *infrastructure* access (who
  logged into Render/Neon/Vercel and when) — only *application-level*
  access is audited (`audit_logs`, `admin_action_logs`,
  `emergency_audit_logs`). This is a real, separate gap from
  application-layer auditing.

## Policy (going forward — not yet verified as currently enforced)

1. Production credentials (Render, Vercel, Neon console access,
   `DATABASE_URL`, vendor API keys) should be held by the minimum
   necessary set of people, each with their own individually-
   attributable account — never a shared login. `[UNKNOWN]` whether
   this currently holds; `[EXTERNAL ACTION]` to verify/enforce via each
   vendor's own console.
2. MFA should be enabled on every account with production access
   (Render, Vercel, Neon, GitHub, and each AI vendor console).
   `[UNKNOWN]`/`[EXTERNAL ACTION]`.
3. Direct production database access (e.g. `psql` against the
   production `DATABASE_URL`) should be logged/justified per use, not
   routine — this repository's own testing convention (dev DB + real
   `/auth/signup`-created synthetic accounts, established throughout
   this project's history) exists specifically so routine engineering
   work never needs production DB access at all.
4. No engineer or automated process should copy production PHI into a
   local fixture, test file, or ticket — synthetic data only, per this
   round's explicit governing rule (§20 of `BRAGI_SECURITY_GDPR_PLAN.md`).
5. Any person granted production access should be removed promptly when
   their need for it ends (offboarding) — `[EXTERNAL ACTION]`, no
   technical control in this codebase can enforce this.

## Security contact

A dedicated security-contact channel (e.g. `security@` alias) is
recommended for the privacy notice and vulnerability-disclosure
purposes (`docs/privacy/PRIVACY_NOTICE_DRAFT.md`). No such alias is
established in this document — a placeholder only, deliberately no
hardcoded personal email/phone number of any individual. `[EXTERNAL
ACTION]` to actually provision the alias and monitoring for it.
