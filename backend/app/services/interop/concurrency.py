"""Per-connection sync concurrency guard (BRAGI_INTEROP_PLAN.md Phase 3
§3.7) — a Postgres advisory lock keyed by connection id, so two workers
(or two overlapping requests against the same connection) can never both
run a sync/preview against it at once. Session-level, not transaction-
level: released explicitly in a `finally`, and automatically by Postgres
if the connection drops (crash-safe, same reasoning as
scripts/run_migrations.py's migration lock).

IMPORTANT — why this does NOT use the caller's `db: Session`: a Postgres
session-level advisory lock (`pg_advisory_lock`/`pg_try_advisory_lock`) is
held by the specific physical DBAPI connection that acquired it, and can
only be released by `pg_advisory_unlock` on that SAME connection. The
routes that hold this lock call `db.commit()` several times internally
(via `_record_sync_run`/`_finish_sync_run` and the route bodies) — each
commit ends the current transaction, and SQLAlchemy's connection pool is
free to hand the Session a DIFFERENT physical connection for whatever
statement runs next. If the lock was acquired on connection A and the
later unlock call happens to run on pooled connection B, the unlock is a
no-op (B never held it) and the lock stays held on A forever once A goes
back to the pool — every subsequent request against that connection_id
then sees "locked" permanently. This was reproduced for real in CI
(discovered against a fresh ephemeral Postgres, not this session's own
long-lived dev database) before being fixed here: the lock is now
acquired and released on one dedicated connection checked out directly
from the engine and held for the exact lifetime of the `with` block,
completely independent of whatever the caller's ORM Session does with
its own transactions in between.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import engine

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
    sync is already holding the lock for this connection. `db` is accepted
    for API symmetry/future use but deliberately NOT used to run the lock/
    unlock statements — see the module docstring for exactly why.
    """
    with engine.connect() as lock_connection:
        acquired = lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:ns, :id)"), {"ns": _LOCK_NAMESPACE, "id": connection_id}
        ).scalar()
        if not acquired:
            raise ConnectionSyncInProgress(
                f"Another sync is already running for connection {connection_id} — refusing to run a second one concurrently."
            )
        try:
            yield
        finally:
            lock_connection.execute(text("SELECT pg_advisory_unlock(:ns, :id)"), {"ns": _LOCK_NAMESPACE, "id": connection_id})
