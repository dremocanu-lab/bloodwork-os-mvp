/**
 * The single source of truth for how this app resolves the backend API
 * base URL (production deployment closure session).
 *
 * Real gap this closes: every real deployment (Vercel production AND
 * preview) has `NEXT_PUBLIC_API_URL` explicitly configured — but four
 * separate files (`lib/api.ts`, `lib/ask-bragi-api.ts`,
 * `lib/emergency-api.ts`, `next.config.ts`) each independently
 * hand-rolled `process.env.NEXT_PUBLIC_API_URL || "https://bloodwork-os-
 * api.onrender.com"` — the REAL production backend. A stale/misconfigured
 * local checkout with no `.env.local` (confirmed to exist in this repo:
 * a leftover agent worktree with zero env files) would silently read
 * AND WRITE real production patient data the moment anyone ran it,
 * with no error, no warning, nothing distinguishing it from a genuine
 * local dev session.
 *
 * Policy: `NEXT_PUBLIC_API_URL` unset in a real build (`NODE_ENV=
 * "production"` — true for `next build`/`vercel build` regardless of
 * whether the target environment is Vercel production or preview) is
 * now a hard, loud failure, never a silent fallback to the real
 * production API. Only genuine local development (`next dev`,
 * `NODE_ENV="development"`) falls back, and only to a LOCAL backend —
 * never the real one.
 */

const LOCAL_DEV_API_FALLBACK = "http://localhost:8000";

export function getApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL;
  if (configured) return configured;

  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not configured for this build. Refusing to " +
        "silently fall back to the real production API — set NEXT_PUBLIC_API_URL " +
        "explicitly for this environment (Vercel project settings)."
    );
  }

  return LOCAL_DEV_API_FALLBACK;
}
