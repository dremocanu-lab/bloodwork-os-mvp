# Static analysis & dependency scanning

Priority 4 of the security/GDPR follow-up round. Supersedes
`BRAGI_SECURITY_GDPR_PLAN.md` §13's "not yet run this round" note for
Bandit/Semgrep.

## Backend: Bandit

`bandit -r app` (v1.9.4) — 14 findings, **0 High, 2 Medium, 12 Low**.
Reviewed individually rather than accepted at face value:

- **2× Medium, `B310` (`urllib.request.urlopen`)** —
  `app/services/ai_lab_organizer.py:394` and
  `app/services/medication_lookup.py:45`. Both false positives: Bandit
  flags any `urlopen()` call regardless of URL provenance. The first
  target is `OPENAI_RESPONSES_URL`, a hardcoded constant (OpenAI's own
  API endpoint). The second's host is always one of two hardcoded
  constants (`RXNORM_BASE`/`DAILYMED_BASE`, both official NLM services);
  only the URL-encoded query/path segment varies with user input, never
  the host — confirmed by reading every call site in
  `medication_lookup.py`. Not an SSRF vector. Suppressed with an inline
  `# nosec B310` plus a reasoned comment at each site (not a blanket
  exclusion) so CI's `bandit -r app -ll` gate (Medium/High) stays
  meaningful for any genuinely new finding.
- **2× Low, `B105` (`hardcoded_password_string`)** — both are the
  literal string `"bearer"` used while parsing/building an
  `Authorization: Bearer <token>` header, not a credential. False
  positive.
- **9× Low, `B110` (`try/except/pass`)** and **1× Low, `B112`
  (`try/except/continue`)** — permissive error handling in
  `structured_reader_service.py` and similar parsing code (fallback
  behavior when an optional field/section can't be parsed). Reviewed:
  none swallow a security-relevant exception (auth, authorization,
  crypto) — all are best-effort document-parsing fallbacks where the
  existing design already treats missing/malformed data as "skip and
  continue," consistent with the rest of the parsing pipeline. No fix
  needed this round; a stricter (e.g. logged) except clause is a
  code-quality improvement, not a security gap.

Full report: `bandit -r app` (re-run this to regenerate; not committed —
avoids a stale report going out of date silently).

## Backend: Semgrep

Installed (`semgrep` 1.177.0) and run with its default
`p/security-audit` + `p/python` rulesets against `backend/app`. No
findings beyond what Bandit already surfaced (same two `urlopen` call
sites, already assessed above). No SQL-injection, command-injection, or
deserialization findings — consistent with §3 item 16's prior finding
that 100% of DB access goes through the ORM.

## Backend: dependency vulnerabilities (pip-audit)

Re-run this round; same three packages as the previous round's `pip-audit`
pass, all previously assessed and deliberately deferred (not newly
discovered):

- **`pyasn1` 0.4.8** — 8 known advisories, fixed in 0.6.3/0.6.4. Blocked
  by `python-jose==3.4.0`'s own `pyasn1<0.5.0` constraint — upgrading
  requires either a `python-jose` major version or switching JWT
  libraries, a coordinated change out of scope for a drive-by dependency
  bump.
- **`starlette` 0.46.2** — 9 known advisories, fixes in 0.47.2–1.3.1.
  Blocked by `fastapi==0.115.12`'s own `starlette<0.47.0` constraint.
  (This round's rate-limiting work incidentally re-confirmed this
  constraint is load-bearing: installing `semgrep`/`pip-audit` pulled in
  an unpinned `starlette` 1.6.0 as a transitive dependency and broke
  `FastAPI()`'s own constructor — see
  `docs/security/RATE_LIMITING.md`'s postmortem note — reinstalling
  pinned `requirements.txt` restored 0.46.2 and fixed it immediately.)
- **`ecdsa` 0.19.2** — 1 known advisory, no fix version published upstream
  yet. `[NOT APPLICABLE]` — this app only ever signs/verifies JWTs with
  HS256 (confirmed in `app/auth.py`); `ecdsa` is a transitive dependency
  of `python-jose[cryptography]` that is never invoked by this app's
  actual code path.

No new Critical/High findings requiring action this round.

## Frontend: npm audit

`npm audit` (production + dev dependencies): **0 vulnerabilities**
(info/low/moderate/high/critical all 0). Re-confirms the previous
round's Next.js CVE fix and other dependency upgrades are holding.

## Frontend: tsc / ESLint

- `npx tsc --noEmit`: clean, 0 errors.
- `npx eslint .`: 30 errors / 25 warnings, **all pre-existing** (none in
  any file touched this round, including the emergency-search POST
  migration) — the same `react-hooks/set-state-in-effect` findings
  (calling `setState` synchronously inside a `useEffect`, a
  code-quality/performance lint rule, not a security one) and one
  `@typescript-eslint/no-explicit-any` in `lib/api.ts` and one
  `@ts-ignore`-vs-`@ts-expect-error` finding in `qa/a11y.mjs` that
  `CLAUDE_HANDOFF.md` already documented as predating this effort
  (confirmed via `git stash` in a prior round). Not fixed this round —
  out of scope for a security pass, tracked as a pre-existing
  code-quality item.

## What this establishes going forward

All of the above (Bandit, pip-audit, npm audit, tsc, ESLint) are wired
into CI — see `docs/security/CI_PIPELINE.md` — so future regressions are
caught automatically rather than depending on another manual pass like
this one.
