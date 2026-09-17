"""Root and operational routes (BRAGI backend modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"root/ops" domain — classified as trivial risk: 2 routes, no shared
serialization helpers, no domain-specific business logic).
"""

from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter, Depends

from app.api.dependencies import require_role

router = APIRouter()


def _deployed_git_sha() -> str | None:
    """Best-effort commit identity of whatever code is actually running.

    Prefers the host platform's own env var (set automatically at deploy
    time, no dashboard configuration needed) over `git rev-parse`, since
    a deployed container frequently has no `.git` directory at all —
    `git rev-parse` is only a useful fallback for local dev.
    """
    for env_var in ("RENDER_GIT_COMMIT", "VERCEL_GIT_COMMIT_SHA", "GIT_SHA"):
        value = os.getenv(env_var)
        if value:
            return value

    try:
        # No explicit cwd override needed: `git rev-parse` walks UP from
        # wherever it's run looking for `.git` (the repo root is one
        # level above `backend/`, this file's own directory is well
        # inside that tree either way) — this is local-dev-only anyway,
        # since a deployed container may not ship `.git` at all, which is
        # exactly why the platform-injected env vars above are checked
        # first.
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=os.path.dirname(__file__),
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass

    return None


@router.get("/")
def root():
    return {"message": "API is running"}


@router.get("/health/version")
def health_version():
    """Answers "which exact backend code is this?" — deliberately tiny
    and unauthenticated (no PHI, no secrets, no filesystem paths beyond
    a commit hash) so it can be checked from anywhere, including a
    browser's own network tab, without a login. Exists specifically so
    "is my manual QA actually hitting this branch's code" is never again
    an unanswerable question — see docs/handoffs/
    CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md's "P0 AI Document
    Classification + Upload Reliability" section for why this was added.
    """
    return {
        "git_sha": _deployed_git_sha(),
        "environment": _deployed_environment(),
    }


def _deployed_environment() -> str:
    # Vercel's own env var already distinguishes production/preview/
    # development explicitly — trust it verbatim when present.
    vercel_env = os.getenv("VERCEL_ENV")
    if vercel_env:
        return vercel_env

    # Render sets IS_PULL_REQUEST=true only on its PR-preview environments
    # (a separate, real deploy from the main production service).
    if os.getenv("RENDER"):
        return "preview" if os.getenv("IS_PULL_REQUEST", "").lower() == "true" else "production"

    return "local"


@router.get("/admin/ops/rate-limit-status")
def rate_limit_status(current_user=Depends(require_role("admin"))):
    """Read-only diagnostic so ops can confirm which rate-limit backend is
    actually active in a given environment — never inferred from an env
    var alone, since a misconfigured/unreachable Redis silently falls
    back to the in-memory (per-instance-only) backend. See
    docs/security/RATE_LIMITING.md."""
    from app.rate_limit import RATE_LIMIT_DISABLED, RATE_LIMIT_REDIS_URL, is_distributed

    return {
        "distributed": is_distributed(),
        "redis_configured": bool(RATE_LIMIT_REDIS_URL),
        "disabled": RATE_LIMIT_DISABLED,
    }
