/**
 * Deployment-parity mechanism (production deployment closure session) —
 * the frontend's own answer to "which exact code is this?", mirroring
 * the backend's `GET /health/version`. Deliberately tiny and
 * unauthenticated (no PHI, no secrets, no filesystem paths beyond a
 * commit hash) so it can be queried directly — `curl https://
 * app.bragi.health/api/version` — without a login, from anywhere,
 * including automated deployment-verification tooling.
 *
 * Runs server-side (a Route Handler, not a client component), so it can
 * read the platform's own raw commit env var directly — no NEXT_PUBLIC_
 * prefix/build-time-inlining detour needed, unlike next.config.ts's
 * NEXT_PUBLIC_GIT_SHA (which exists separately for the in-app account-
 * menu display, a different consumer with a different constraint: that
 * one has to be visible to CLIENT code after the bundle is already
 * built, this one can just read the live server process's own env at
 * request time).
 */

export const dynamic = "force-dynamic";

function deployedGitSha(): string | null {
  return (
    process.env.VERCEL_GIT_COMMIT_SHA ||
    process.env.RENDER_GIT_COMMIT ||
    process.env.NEXT_PUBLIC_GIT_SHA ||
    null
  );
}

function deployedEnvironment(): string {
  // Vercel's own env var already distinguishes production/preview/
  // development explicitly — trust it verbatim when present.
  return process.env.VERCEL_ENV || "local";
}

export async function GET() {
  return Response.json({
    git_sha: deployedGitSha(),
    environment: deployedEnvironment(),
  });
}
