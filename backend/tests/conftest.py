import os
from pathlib import Path

from dotenv import load_dotenv

# Same convention app/main.py uses — loads backend/.env for local
# development. Needed here (not just in app.main) because conftest.py now
# needs to know DATABASE_URL BEFORE any test module (including the one
# that first imports app.main, which would otherwise be the first to load
# .env) — see the migration-provisioning block below. No-op if the file
# doesn't exist.
load_dotenv()

# The rate limiter (app/rate_limit.py) keys by client IP by default.
# Starlette's TestClient reports the same fake IP for every request, so
# every test file in a pytest session would otherwise share ONE global
# counter across the whole run — an account-creation-heavy regression
# suite (test_idor_regression.py, test_upload_validation.py, and this
# round's deletion/DSAR/malware tests) would trip production rate limits
# from test volume alone, not abuse. Disable rate limiting for the test
# session by default; app/rate_limit.py's own unit tests
# (test_rate_limit.py) explicitly re-enable it via monkeypatch per-test
# since they need to exercise real enforcement.
#
# This must be set before `app.rate_limit` (imported by `app.main`) is
# first imported, since RATE_LIMIT_DISABLED is read once at module load —
# conftest.py is collected before any test module, so this always runs
# first.
os.environ.setdefault("RATE_LIMIT_DISABLED", "true")

# Schema provisioning via Alembic (see docs/database/MIGRATIONS.md).
# app/main.py no longer creates/migrates schema as an import-time side
# effect (see BRAGI_INTEROP_PLAN.md's migration-framework section) — a
# fresh test database needs `alembic upgrade head` run explicitly before
# any test that touches the DB. Only attempted when DATABASE_URL is
# actually configured, matching every DB-dependent test file's own
# skip-gracefully convention (test_idor_regression.py and friends) —
# a pure-unit-test run with no Postgres available must keep working
# exactly as before.
if os.environ.get("DATABASE_URL"):
    from alembic import command
    from alembic.config import Config

    _alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    _cfg = Config(str(_alembic_ini))
    command.upgrade(_cfg, "head")
