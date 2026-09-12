"""Trivial shared utilities used across nearly every domain (BRAGI backend
modularization, Phase 4). Moved verbatim from app/main.py, alongside
app/api/dependencies.py, as part of the same narrow prerequisite: any
router module needs these without importing app.main itself (which would
be circular, since app.main imports and registers the routers)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def generate_public_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _mask_cnp(cnp: str | None) -> str | None:
    """Mask all but the first/last two characters of a Romanian CNP
    (national identifier) for display — used anywhere a patient's raw CNP
    must not be shown in full (documents, patient listings, admin
    search, emergency search results). Moved verbatim from app/main.py
    (same name kept, including the leading underscore, to avoid touching
    every call site's name across domains not yet extracted)."""
    if not cnp:
        return None
    n = len(cnp)
    if n <= 4:
        return "*" * n
    return cnp[:2] + "*" * (n - 4) + cnp[-2:]
