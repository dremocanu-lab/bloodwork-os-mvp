# Key Rotation Runbook

Status: runbook draft. No rotation has been performed as part of this
round — this task's own rules explicitly prohibit automatic production
credential rotation; this document describes the manual procedure for
when a human operator decides to rotate.

## Secrets inventory (what would ever need rotating)

| Secret | Where used | Rotation impact |
|---|---|---|
| `SECRET_KEY` (JWT signing, HS256) | `backend/app/auth.py` | Rotating invalidates **every** currently-issued JWT immediately — every logged-in user is logged out at once. No refresh-token/dual-key mechanism exists to make this graceful today (a real gap — see below). |
| `DATABASE_URL` (Neon connection string, includes DB password) | `backend/app/db.py` via env var | Rotating requires coordinated update of the Render env var and a restart; no connection-pooling downtime-avoidance mechanism beyond Render's own deploy behavior has been verified. |
| `REDUCTO_API_KEY` | `app/services/reducto_client.py` | Rotating breaks new uploads until the new key is deployed; in-flight requests using the old key would fail (`ReductoAuthError`, confirmed to be handled as non-retryable in `reducto_client.py`). |
| `OPENAI_API_KEY` | `app/ai_extract.py` (`OpenAI()` reads it from env implicitly) | Similar — breaks the OpenAI-fallback extraction path until rotated in the deploy env. |
| Google Document AI service-account credentials | `app/services/document_ai_layout.py`, `app/services/google_document_ai_service.py` | Rotating requires updating the service-account key file/env reference; Google-side key revocation timing needs to be coordinated with the Render env update to avoid a gap. |

## When to rotate

- Suspected or confirmed leak (found in a log, a ticket, a screen
  share, a public repo, etc).
- Personnel offboarding for anyone who had direct access to the value.
- Routine rotation cadence — not yet defined as a policy; recommended
  as an annual minimum for `SECRET_KEY` and `DATABASE_URL`, and
  per-vendor-recommendation for API keys, once a monitoring/reminder
  mechanism exists to actually track this (none does today).

## Procedure (manual, `[EXTERNAL ACTION]` for every step — engineering
cannot automate credential rotation per this task's own rules)

1. Generate the new secret value in the vendor's own console (Neon,
   Reducto, OpenAI, Google Cloud) or via a cryptographically secure
   random generator for `SECRET_KEY` (never hand-typed).
2. Update the corresponding Render/Vercel environment variable.
3. Trigger a redeploy (or confirm Render/Vercel picks up the env change
   without a code push, per each platform's own behavior — verify this
   rather than assume it for the specific variable being rotated).
4. Revoke/delete the old value in the vendor console only **after**
   confirming the new value is live and working (avoid a
   window with no valid credential).
5. For `SECRET_KEY` specifically: expect and warn users in advance if
   possible — every session ends at once. There is no way to rotate it
   without this effect in the current architecture (no dual-key
   verification window exists). Adding one (accept tokens signed by
   either the old or new key for a transition period) is a real,
   reasonably small follow-up worth doing before the first real
   rotation is needed in production, so that a security-driven rotation
   doesn't also become a scheduled-outage event.

## Status

`[IMPLEMENTED — NOT DEPLOYED]` does not apply — this is a manual
runbook, not code. No rotation has occurred this round. `[EXTERNAL
ACTION]` for every actual rotation step.
