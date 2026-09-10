# Incident Response Plan

Status: draft plan. No incident-response tooling (alerting, on-call
rotation, a dedicated incident channel) is confirmed to exist —
`[UNKNOWN]` for organizational readiness; this document defines the
technical response procedure engineering would follow given what
exists in this codebase today.

## Detection (current capability)

`[FAIL]`/`[UNKNOWN]` — no security event monitoring or alerting exists
(`BRAGI_SECURITY_GDPR_PLAN.md` §17: no analytics/error-monitoring SDK
of any kind in the codebase). Detection today would rely on: a user
report, a vendor (Render/Vercel/Neon/Reducto/OpenAI/Google) alert or
anomaly notice, or a manual review of `audit_logs`/`admin_action_logs`/
`emergency_audit_logs`. There is no automated alert on, for example, a
spike in failed logins, an unusual volume of document access, or
repeated 403/401 responses. This is a real gap — see
`docs/security/PRODUCTION_ACCESS_POLICY.md`'s monitoring note.

## Classification (draft severities)

- **Sev 1 — Confirmed PHI exposure to an unauthorized party** (a real
  cross-patient data leak, a credential leak enabling data access, a
  successful account takeover with PHI viewed). Immediate response.
- **Sev 2 — Vulnerability found with no confirmed exploitation** (e.g.
  a newly-discovered IDOR, a dependency CVE with no evidence of
  exploitation).
- **Sev 3 — Availability incident with no data-confidentiality impact**
  (deploy failure, DB outage, vendor API outage).

## Response procedure

1. **Contain.** For a credential leak: rotate immediately
   (`docs/security/KEY_ROTATION_RUNBOOK.md`) — this is the one case
   where the "no automatic production credential rotation" rule that
   governs routine engineering work under this plan does not apply;
   incident response is exactly the scenario that rule's own exception
   carves out ("EXTERNAL ACTION" items still require a human to
   actually execute the rotation, but should do so without delay). For
   a code vulnerability: assess whether a hotfix can be deployed
   consistent with this plan's production-safety rules (additive,
   reversible) before the next scheduled work; do not rush a fix that
   itself risks breaking production availability without validating it
   first, even under incident pressure — a security fix that takes
   production down is not a net improvement.
2. **Assess scope.** Use `audit_logs`, `admin_action_logs`,
   `emergency_audit_logs`, and (if available) Render/Vercel/Neon access
   logs to determine what was actually accessed, by whom, and when.
   Never guess scope down to make the incident look smaller than the
   evidence supports.
3. **Notify.** GDPR Art.33/34 breach-notification timelines (72 hours
   to the supervisory authority for most personal-data breaches, and
   notification to affected data subjects for high-risk breaches) are a
   `[LEGAL REVIEW]` matter — engineering cannot make the notification
   determination or send the notification unilaterally, but must
   surface a confirmed incident to whoever holds that responsibility
   immediately, not after remediation is complete.
4. **Remediate.** Fix the root cause following the same production-
   safety and evidence-standard rules as any other change under this
   plan — a rushed, unverified "fix" during an incident is exactly the
   scenario most likely to introduce a second bug.
5. **Document.** Record what happened, what data was involved, how it
   was found, what was done, and what changes (code or process) prevent
   recurrence — this becomes an input to the next revision of
   `docs/security/THREAT_MODEL.md` and this plan's residual-risks list.

## What this plan does NOT establish

A monitored on-call rotation, a dedicated incident communication
channel/tool, or a tested runbook (no incident has been simulated or
drilled). `[UNKNOWN]`/`[EXTERNAL ACTION]` for all of these —
organizational readiness, not something this codebase can create.
