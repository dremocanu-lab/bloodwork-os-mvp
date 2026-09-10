# CI / CD security pipeline

Priority 5 of the security/GDPR follow-up round. Closes
`BRAGI_SECURITY_GDPR_PLAN.md` §18's "no CI exists at all" gap.

## What exists now

Two workflows, `.github/workflows/ci.yml` and
`.github/workflows/nightly-security.yml`.

### `ci.yml` — every push/PR to `main`

- **`backend` job**: spins up an ephemeral, CI-only Postgres 16 service
  container (not the real Neon dev/prod database, no production secret
  involved anywhere in this job), installs
  `backend/requirements-dev.txt`, runs `bandit -r app -ll` (fails the job
  only on Medium/High findings — this round's Low-severity findings are
  all reviewed false positives/accepted risk, see
  `docs/security/STATIC_ANALYSIS.md`, and gating on them would just be
  noise), then runs the full `pytest` suite against the fresh Postgres
  instance. Running the real app (which calls `run_migrations()` at
  import time) against a brand-new, empty schema on every run doubles as
  migration-sanity checking — a migration that isn't actually idempotent
  or that fails against a clean schema will fail this job.
- **`frontend` job**: `npm ci`, `tsc --noEmit`, `eslint` (non-blocking —
  see below), `npm run build` (a real production Next.js build, not just
  typecheck).
- **`secret-scan` job**: gitleaks against full git history (`fetch-depth:
  0`) on every push — this round's full-history scan (see
  `docs/security/SECRET_SCAN_HISTORY.md`) took ~4 seconds locally, cheap
  enough to run on every push rather than only nightly.

ESLint is currently non-blocking (`|| true`) because this round found
30 pre-existing errors/25 warnings that predate this security effort
(confirmed via `git stash` in an earlier round — see
`CLAUDE_HANDOFF.md`) — all `react-hooks/set-state-in-effect` /
`no-explicit-any` code-quality findings, not security issues. Making
ESLint blocking immediately would fail CI on unrelated pre-existing code,
not on anything this round introduced. Tracked as a follow-up: either
fix the pre-existing findings or add an ESLint baseline/ignore list, then
flip this to blocking.

### `nightly-security.yml` — daily (03:17 UTC) + manual trigger

Deeper scanning that needs a live network fetch against vulnerability
databases (which can be slow or occasionally flaky) or a broader,
slower ruleset — kept off the per-push critical path:

- `pip-audit` (Python dependency CVEs) — non-blocking (`|| true`); this
  repo has 3 known, already-triaged findings (pyasn1/starlette/ecdsa, see
  `docs/security/STATIC_ANALYSIS.md`) that would otherwise fail every
  run. A human reads the job log for anything NEW, rather than the job
  going red on findings already assessed.
- `npm audit` — same non-blocking rationale (currently 0 findings, but a
  future finding should be triaged by a human before deciding whether to
  gate on it).
- Semgrep with a broader ruleset (`p/security-audit`, `p/python`,
  `p/owasp-top-ten`) than what's practical to justify running on every
  push.

## Design decisions

- **No production secrets in Actions.** The backend job's `DATABASE_URL`
  points at an ephemeral container-local Postgres created fresh for that
  job run and destroyed after — never the real Neon dev/prod database.
  `SECRET_KEY` is a fixed, clearly-labeled CI-only dummy value. No
  `OPENAI_API_KEY`/`REDUCTO_API_KEY`/real credential of any kind is set
  anywhere in either workflow — confirmed by reading every test file
  that touches those integrations
  (`test_extraction_provider.py`/`test_structured_reader_service.py`):
  they `monkeypatch` a fake key and never make a real network call.
- **Third-party actions are pinned to a full commit SHA**, not a floating
  version tag (`actions/checkout@fbc6f39...` with a `# v5` comment for
  readability, not `actions/checkout@v5` itself) — a compromised or
  re-tagged release of a marketplace action can't silently execute
  different code on the next run. Every action in both workflows follows
  this.
- **Fast vs. nightly split**, per this round's explicit instruction: unit
  tests, security regression tests, typecheck, lint, a real production
  build, secret scanning, and migration sanity all stay on the fast path
  (every push) since they're cheap enough to justify that (the full
  measured local runtimes this round: pytest ~70s, bandit/semgrep
  seconds, gitleaks full-history ~4s, npm audit/tsc seconds). Dependency
  vulnerability-database lookups and the broader Semgrep ruleset move to
  a nightly schedule, since they depend on a live external advisory feed
  that can be slow and whose findings need human triage against this
  repo's existing deliberately-deferred list, not a blocking gate on
  unrelated work.
- **`concurrency` + `cancel-in-progress`** on `ci.yml` so a rapid series
  of pushes to the same branch doesn't queue redundant runs.

## What was actually verified this round

Every check in `ci.yml` was run manually against the real repository
before being wired into the workflow (not just written and assumed to
work) — see `docs/security/STATIC_ANALYSIS.md` and
`docs/security/SECRET_SCAN_HISTORY.md` for the actual tool output this
round: `pytest` (105 passed), `bandit -r app` (0 High, 2 Medium — both
reviewed false positives, see STATIC_ANALYSIS.md), `npx tsc --noEmit`
(clean), `npx eslint .` (pre-existing findings only), `npm audit` (0
vulnerabilities), `npm run build` (succeeds per `CLAUDE_HANDOFF.md`'s
prior-round record — not re-run as part of *this* file's checkpoint to
avoid an unnecessary long local build; will run for real on the first
GitHub Actions execution of this workflow), and `gitleaks detect --source
. --log-opts="--all"` (245 commits, 1 reviewed false positive).

**Confirmed with a real GitHub Actions run** (not just local dry-runs):
the first push (`fce4652`) correctly FAILED the `backend` job — `bandit
-r app -ll` caught the same 2 Medium findings this document already
identifies as reviewed false positives, which had been documented but
not yet suppressed in code. Fixed by adding a reasoned inline `# nosec
B310` at each of the two call sites (commit `326908d`) rather than
lowering the severity gate. The next run
(https://github.com/dremocanu-lab/bloodwork-os-mvp/actions/runs/34527610904)
passed all three jobs: `Frontend` (1m6s), `Secret scan` (7s), `Backend`
(57s, including the full pytest suite against the real ephemeral
Postgres service container). This is real evidence the workflow YAML
itself works end-to-end on GitHub's infrastructure, not just that the
equivalent commands work locally — and it's a real example of this
round's own CI catching a genuine (if low-severity, already-triaged)
issue before it could regress silently.

`nightly-security.yml` has not yet run (it fires on a schedule/manual
dispatch, not on push) — it can be triggered manually via `gh workflow
run nightly-security.yml` or the Actions UI to verify before relying on
its first scheduled firing.
