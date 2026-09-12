"""Shared FastAPI dependencies (BRAGI backend modularization, Phase 4 —
see docs/refactor/BACKEND_DECOMPOSITION_PLAN.md). Moved verbatim from
app/main.py as the first, narrow prerequisite for extracting any router
into its own module — every domain router needs `get_db`/
`get_current_user`/`require_role`, and this is the one place they now
live to avoid a circular import between `app.main` and the routers it
registers.

This is a pure relocation, not a redesign: byte-for-byte the same
authorization semantics as before (see docs/refactor/AUTHORIZATION_MAP.md,
captured from the app BEFORE this move — re-run
tests/contracts/generate_route_inventory.py after this change and diff
to confirm nothing shifted).
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.auth import decode_access_token
from app.db import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    try:
        user_id_int = int(user_id)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(models.User).filter(models.User.id == user_id_int).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.deleted_at:
        # Soft-deleted (doctor/admin self-deletion — see
        # BRAGI_SECURITY_GDPR_PLAN.md §19/Priority 8): the row still
        # exists (clinical/audit records reference it) but the account
        # itself must behave as gone for every authorization purpose —
        # including a JWT issued before the deletion that hasn't expired
        # yet, which is exactly what this check catches.
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_role(*allowed_roles):
    def dependency(current_user=Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return dependency
