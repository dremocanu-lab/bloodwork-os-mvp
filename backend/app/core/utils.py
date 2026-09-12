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
