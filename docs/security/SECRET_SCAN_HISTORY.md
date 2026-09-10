# Full git-history secret scan

Priority 3 of the security/GDPR follow-up round. Supersedes
`BRAGI_SECURITY_GDPR_PLAN.md` §11's "not exhaustively scanned this
round" note — this round ran the full-history scan.

## Tool and scope

- **Primary tool**: [gitleaks](https://github.com/gitleaks/gitleaks)
  v8.30.1 (downloaded fresh from the official GitHub release for this
  scan — not previously installed in this environment), a
  purpose-built git-history secret scanner with curated detection rules
  for cloud-provider keys (AWS, GCP, Azure), API keys for dozens of named
  services, JWTs, private keys, and generic high-entropy/credential-shaped
  strings.
- **Command**: `gitleaks detect --source . --log-opts="--all"` — scans
  every commit reachable from every ref (`--all`), not just the current
  `main` HEAD or a shallow history window.
- **Coverage**: 245 commits, ~5.09 MB of historical blob content scanned.
- **Supplementary manual pass**: targeted `git log --all -p -S"<pattern>"`
  pickaxe searches (finds the commit that introduced OR removed a line
  matching the pattern, across all history) for patterns gitleaks'
  generic rules could plausibly under-weight: `postgres://`,
  `postgresql://`, `sk-` (OpenAI-style keys), `re_` (Reducto-style keys),
  `AKIA` (AWS access key ID prefix), literal `OPENAI_API_KEY=sk`,
  `REDUCTO_API_KEY=`, `DATABASE_URL=postgres`, `SECRET_KEY=`, PEM
  `-----BEGIN` headers, `RENDER_API_KEY`, `VERCEL_TOKEN`, `SMTP_PASSWORD`/
  `SMTP_PASS`, `GOOGLE_APPLICATION_CREDENTIALS`, `private_key`,
  `client_secret`, `AIza` (Google API key prefix), `ghp_` (GitHub token
  prefix), `xox` (Slack token prefix).

## Findings

| # | Category | Path (commit) | Likely real | Current/historical | Remediation |
|---|---|---|---|---|---|
| 1 | Generic high-entropy string, flagged by gitleaks' `generic-api-key` rule | `BRAGI_REDUCTO_PLAN.md` (commit `51a90cf`) | **No** — the flagged string is the literal env var assignment `REDUCTO_ENABLED=true` inside prose describing a boolean feature flag, not a credential. High entropy score is a false positive on a short mixed-case/digit token. | N/A (not a secret) | None. |

Every manual pickaxe pattern above resolved to one of:
- A placeholder value in `backend/.env.example` (e.g.
  `DATABASE_URL=postgresql://user:password@localhost:5432/bragi`,
  `SECRET_KEY=replace-with-a-strong-random-secret-at-least-32-chars`,
  `REDUCTO_API_KEY=` with no value) — never a real credential.
- A code identifier or prose substring coincidentally matching the
  pattern (e.g. `disk-persistence`, `queue-microtask` matching `sk-`;
  `GOOGLE_APPLICATION_CREDENTIALS` referring only to a local file path,
  `./google-docai-key.json`, never an embedded key/JSON blob).
- Zero matches at all (`AKIA`, `AIza`, `ghp_`, `xox`, `RENDER_API_KEY`,
  `VERCEL_TOKEN`, `SMTP_PASSWORD`/`SMTP_PASS`, `-----BEGIN`,
  `private_key`, `client_secret`).

**No entries require `ROTATION REQUIRED`.** No real, currently-valid or
previously-committed-then-removed credential was found anywhere in the
245-commit history for OpenAI, Reducto, Neon/Postgres, Render, Vercel,
JWT/`SECRET_KEY`, email, storage, or any other provider.

## What this does NOT cover

- Secrets that were only ever set directly in Render/Vercel's environment
  variable UI and never committed (the correct pattern this repo already
  follows) are outside git's history by construction and were not (and
  could not be) scanned here.
- A rotation event that already occurred outside this repo (e.g. a key
  rotated in the Reducto/OpenAI console after local `.env` use) is not
  detectable from git history alone.
- This is a self-run scan, not an independent audit — see
  `BRAGI_SECURITY_GDPR_PLAN.md`'s evidence-standard rules on
  `[INDEPENDENT VALIDATION]`.
