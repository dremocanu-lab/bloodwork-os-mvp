"""Per-connection sync concurrency guard (BRAGI_INTEROP_PLAN.md Phase 3
§3.7) — a Postgres advisory lock keyed by connection id, so two workers
(or two overlapping requests against the same connection) can never both
run a sync/preview against it at once. Session-level, not transaction-
level: released explicitly in a `finally`, and automatically by Postgres
if the connection drops (crash-safe, same reasoning as
scripts/run_migrations.py's migration lock).
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

# Distinct namespace from scripts/run_migrations.py's ADVISORY_LOCK_KEY
# (0x42524147/"BRAG") so the two lock domains can never collide.
_LOCK_NAMESPACE = 0x53594E43  # "SYNC" as an int32


class ConnectionSyncInProgress(RuntimeError):
    """Raised when another sync/preview is already running against this
    connection — the caller should report this to the admin rather than
    queue silently."""


@contextmanager
def connection_sync_lock(db: Session, connection_id: int):
    """Usage:

        with connection_sync_lock(db, connection.id):
            ... run discover/test/preview/sync ...

    Raises ConnectionSyncInProgress immediately (never blocks) if another
    sync is already holding the lock for this connection.
    """
    acquired = db.execute(
        text("SELECT pg_try_advisory_lock(:ns, :id)"), {"ns": _LOCK_NAMESPACE, "id": connection_id}
    ).scalar()
    if not acquired:
        raise ConnectionSyncInProgress(
            f"Another sync is already running for connection {connection_id} — refusing to run a second one concurrently."
        )
    try:
        yield
    finally:
        db.execute(text("SELECT pg_advisory_unlock(:ns, :id)"), {"ns": _LOCK_NAMESPACE, "id": connection_id})
