#!/usr/bin/env python
"""Deployment migration runner: acquires a Postgres advisory lock, runs
`alembic upgrade head`, releases the lock. Use this (not a bare `alembic
upgrade head`) wherever schema migration runs as part of a real deploy —
see docs/database/MIGRATIONS.md's "Production deployment" section.

Why a lock: Render (or any platform) may run more than one instance/
release step concurrently, or a deploy may retry. Two migration runs
racing against the same database is exactly the kind of thing that turns
a routine deploy into an incident. A Postgres session-level advisory lock
(pg_advisory_lock) is cheap, requires no extra table, and is
automatically released if the connection drops (crash-safe) — a second
concurrent runner blocks until the first finishes rather than racing it.

Exit codes: 0 success, 1 migration failed, 2 could not acquire the lock
within the timeout (another migration is already running).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# Arbitrary, fixed, namespaced advisory lock key for "Bragi schema
# migration" — any two 32-bit ints work as long as they're consistent
# across every deploy; picked once and never changed.
ADVISORY_LOCK_KEY = (0x42524147, 0x494D4947)  # "BRAG"/"IMIG" as int32 pairs

LOCK_WAIT_TIMEOUT_SECONDS = 120
LOCK_POLL_INTERVAL_SECONDS = 2


def _database_url() -> str:
    import os

    raw = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:dreams@localhost:5432/mvp1_phase1")
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


def main() -> int:
    engine = create_engine(_database_url())
    conn = engine.connect()

    deadline = time.monotonic() + LOCK_WAIT_TIMEOUT_SECONDS
    acquired = False
    while time.monotonic() < deadline:
        result = conn.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), {"a": ADVISORY_LOCK_KEY[0], "b": ADVISORY_LOCK_KEY[1]})
        acquired = result.scalar()
        if acquired:
            break
        print("Another migration run holds the lock — waiting...")
        time.sleep(LOCK_POLL_INTERVAL_SECONDS)

    if not acquired:
        print(f"Could not acquire the migration advisory lock within {LOCK_WAIT_TIMEOUT_SECONDS}s. Refusing to proceed.")
        conn.close()
        return 2

    try:
        print("Migration lock acquired. Running `alembic upgrade head`...")
        alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
        cfg = Config(str(alembic_ini))
        command.upgrade(cfg, "head")
        print("Migration complete.")
        return 0
    except Exception as exc:  # noqa: BLE001 — surfaced with full detail, this is an ops script
        print(f"MIGRATION FAILED: {exc}")
        return 1
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(:a, :b)"), {"a": ADVISORY_LOCK_KEY[0], "b": ADVISORY_LOCK_KEY[1]})
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
