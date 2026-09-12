"""Root and operational routes (BRAGI backend modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"root/ops" domain — classified as trivial risk: 2 routes, no shared
serialization helpers, no domain-specific business logic).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import require_role

router = APIRouter()


@router.get("/")
def root():
    return {"message": "API is running"}


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
