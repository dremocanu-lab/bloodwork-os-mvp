# Rate limiting

Implements Priority 2 of the security/GDPR follow-up round. See
`backend/app/rate_limit.py` for the implementation and
`backend/tests/test_rate_limit.py` for the regression suite.

## Architecture

Two backends, selected automatically at process start:

1. **Redis-backed (distributed, real protection across multiple Render
   instances)** — active when `RATE_LIMIT_REDIS_URL` (or `REDIS_URL`) is
   set to a reachable Redis instance. Uses `INCR`+`EXPIRE` fixed-window
   counters, keyed `bragi:ratelimit:<endpoint>:<client-ip>`.
2. **In-memory (per-process only)** — the default when no Redis URL is
   configured. Real protection for a **single** running instance; each
   additional instance gets its OWN independent quota, which silently
   weakens the effective limit (e.g. a 15/5min login limit becomes
   15/5min PER INSTANCE, not 15/5min total) the moment the backend is
   horizontally scaled. **Before enabling more than one Render instance,
   configure Redis** — do not rely on the in-memory fallback across
   multiple instances and call it distributed protection; it isn't.

`GET /admin/ops/rate-limit-status` (admin-only) reports which backend is
actually active (`distributed: true/false`) — use it to verify the real
runtime state in any environment rather than inferring it from whether an
env var is merely set (a misconfigured/unreachable Redis URL fails open
to the in-memory backend automatically, see below).

## Fail-safe behavior

Every check is wrapped: if the configured backend (Redis) throws for any
reason — connection refused, DNS failure, timeout — the request is
**allowed through** and the failure is logged server-side. A rate-limiter
outage must never become an application outage for a clinical-records
system. `RATE_LIMIT_DISABLED=true` is a global kill-switch for the same
reason (an incident where the limiter itself misbehaves).

## Endpoints covered (this round)

| Endpoint | Limit | Key |
|---|---|---|
| `POST /auth/signup` | 10 / hour | client IP |
| `POST /auth/login` | 15 / 5 min | client IP |
| `POST /upload`, `/upload/background`, `/upload/batch` | 30 / hour | client IP |
| `GET /documents/{id}/file`, `GET /source-evidence/{id}/view`, `GET /lab-results/{id}/source` | 120 / 5 min | client IP |
| `POST /my/medications/{id}/refresh-official-info` (external RxNorm lookup) | 20 / hour | client IP |
| `GET`/`POST /emergency/search` | 60 / 5 min | client IP |
| `POST /emergency/access-sessions` | 30 / hour | client IP |

Password reset, email verification, and any OpenAI/"Ask Bragi" chat
endpoints do not exist in this codebase yet (confirmed by route-table
review) — nothing to rate-limit there today; add a limit when any such
endpoint is built. The DSAR export endpoint added this round
(`POST /my/export`) also carries its own limit — see
`docs/privacy/DSAR_RUNBOOK.md`.

Keying is by client IP only (from `X-Forwarded-For`'s first hop, which
Render sets on its proxy). A per-account limiter (e.g. failed-login count
per email) was deliberately not added this round — it would need to read
the request body inside the dependency before the route handler parses
it, which is a bigger, riskier change to get right across every affected
route; IP-based limiting is the safe, well-understood default and covers
the primary abuse cases (scripted brute force, scraping, cost-driving
upload floods) from a single source. Tracked as a possible future
enhancement, not a gap that blocks this round.

## Activation requirements for the distributed backend

1. Provision a Redis instance (Render's own Key Value add-on, or any
   externally reachable Redis — e.g. Upstash).
2. Set `RATE_LIMIT_REDIS_URL` (or reuse `REDIS_URL` if one already exists
   for another purpose) in Render's environment variables for the
   backend service.
3. Redeploy (or let the next deploy pick it up — no code change needed;
   `redis` is already an unconditional dependency in
   `backend/requirements.txt`).
4. Confirm via `GET /admin/ops/rate-limit-status` that `distributed` is
   `true`.

Until step 2 is done, the app runs correctly and safely on the
in-memory backend — this is not a blocking requirement, only a
correctness upgrade for when/if Render is scaled beyond one instance.

## What was tested

- `backend/tests/test_rate_limit.py` (14 tests, no DB required): in-memory
  fixed-window behavior (allows up to limit, blocks over limit, resets
  after the window, independent keys), the FastAPI dependency's 429 +
  `Retry-After` behavior, per-IP isolation, `X-Forwarded-For` handling,
  fail-open on a simulated backend exception, the `RATE_LIMIT_DISABLED`
  kill-switch, and `is_distributed()` correctness.
- Real, live verification (not just `TestClient`): a real local `uvicorn`
  process, 12 real HTTP `POST /auth/signup` requests — the first 10
  returned `200`, the 11th and 12th returned `429` with a real
  `Retry-After` header (`3571`, i.e. ~1 hour, matching the configured
  window) — followed by real login + `DELETE /my/account` cleanup of all
  10 synthetic accounts created during the test.
- Full backend pytest suite (105 tests) re-run green after adding rate
  limiting to 12 routes — `backend/tests/conftest.py` disables rate
  limiting for the test session by default (the existing regression
  suite creates many synthetic accounts via `TestClient`, which always
  reports the same fake client IP, so it would otherwise share one global
  quota across the whole test run and fail from test volume, not abuse);
  `test_rate_limit.py` explicitly re-enables it per-test since it exists
  specifically to exercise real enforcement.

## A bug this round's own testing caught before it shipped

The first implementation used a class instance (`RateLimiter(...)`) as
the `Depends()` callable directly. That broke every route it was added
to: FastAPI stopped recognizing the `request: Request` parameter as the
special injectable type and instead required it as a mandatory query
parameter, turning every rate-limited route into a guaranteed `422`. This
was caught by running the full test suite before committing (not by
reading the code), fixed by switching to a plain closure-returning
factory function (the unambiguous, well-established FastAPI dependency
shape), and is exactly the kind of thing this round's evidence standard
exists to catch.
