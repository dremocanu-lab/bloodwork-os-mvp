"""Migration upgrade/downgrade round-trip tests (BRAGI_INTEROP_PLAN.md /
docs/database/MIGRATIONS.md). Real DB connectivity required — creates and
drops its OWN disposable scratch database(s) on the same Postgres server
DATABASE_URL points at (never touches the real dev/test database other
suites use), skipped gracefully if DATABASE_URL isn't set or the
connected role can't CREATE DATABASE (e.g. a restricted hosted Postgres).

Covers:
- A synthetic pre-interop ("legacy") schema, with real sample data,
  upgrades cleanly through 0001 -> head with no data loss (item 19).
- A database that already has the full Phase 1 schema (simulating one
  provisioned by the OLD run_migrations() before this Alembic conversion)
  is correctly recognized and stamped to head, with NO table recreation
  (item 20).
- A deliberately mutated/incomplete schema is correctly refused (item 21).
- The destructive-downgrade guard on revision 0001 fails closed without
  an explicit override, and succeeds with it, on a disposable database.
"""

from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not configured — this file needs real DB connectivity.", allow_module_level=True)


def _admin_url() -> str:
    raw = os.environ["DATABASE_URL"]
    if raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


def _can_create_database() -> bool:
    try:
        engine = create_engine(_admin_url())
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            test_db = f"bragi_migtest_probe_{uuid.uuid4().hex[:8]}"
            conn.execute(text(f"CREATE DATABASE {test_db}"))
            conn.execute(text(f"DROP DATABASE {test_db}"))
        return True
    except Exception:
        return False


if not _can_create_database():
    pytest.skip("Connected DB role cannot CREATE DATABASE — skipping migration round-trip tests.", allow_module_level=True)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

BACKEND_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent
ALEMBIC_INI = str(BACKEND_DIR / "alembic.ini")
LEGACY_REVISION = "77df8fa2b964"
# Read from the actual migration history rather than hardcoding — a
# hardcoded value here goes stale every time a new revision is added
# (reproduced for real: this constant silently pointed at the OLD head
# after 0003_phase3_hardening was added, and this test would have kept
# passing for the wrong reason — comparing against a stale expectation —
# until pytest caught the mismatch).
HEAD_REVISION = ScriptDirectory.from_config(Config(ALEMBIC_INI)).get_current_head()


def _db_url_for(name: str) -> str:
    from sqlalchemy.engine import make_url

    # str(url) hides the password by default in SQLAlchemy — needs
    # hide_password=False or the returned URL is unusable for a real
    # connection (would try to literally connect with password "***").
    return make_url(_admin_url()).set(database=name).render_as_string(hide_password=False)


@pytest.fixture
def scratch_db():
    name = f"bragi_migtest_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(_admin_url())
    with admin_engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text(f"CREATE DATABASE {name}"))
    url = _db_url_for(name)
    yield url
    with admin_engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


def _alembic_config(db_url: str) -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_fresh_database_upgrades_cleanly_to_head(scratch_db):
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")

    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert current == HEAD_REVISION
        # Spot-check both the legacy core and the Phase 1 additions exist.
        for table in ("users", "patients", "documents", "lab_results", "interop_connections", "interop_secrets"):
            exists = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"), {"t": table}
            ).scalar()
            assert exists, f"expected table {table!r} to exist after upgrade to head"


def test_legacy_data_survives_upgrade_to_head(scratch_db):
    """Item 19 — real sample data (users/patients/documents/lab_results/
    source_evidence) inserted at the legacy revision must still be there,
    unchanged, after upgrading to head."""
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, LEGACY_REVISION)

    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, full_name, password_hash, role) "
                "VALUES ('migtest@example.com', 'Mig Test', 'x', 'patient')"
            )
        )
        conn.execute(text("INSERT INTO patients (full_name, emergency_search_enabled) VALUES ('Mig Test Patient', 0)"))
        patient_id = conn.execute(text("SELECT id FROM patients WHERE full_name = 'Mig Test Patient'")).scalar()
        conn.execute(
            text(
                "INSERT INTO documents (patient_id, section, filename, created_at, is_verified) "
                "VALUES (:pid, 'bloodwork', 'test.pdf', 'now', false)"
            ),
            {"pid": patient_id},
        )
        document_id = conn.execute(text("SELECT id FROM documents WHERE filename = 'test.pdf'")).scalar()
        conn.execute(
            text("INSERT INTO lab_results (document_id, raw_test_name, value) VALUES (:did, 'Hemoglobin', '13.8')"),
            {"did": document_id},
        )
        conn.commit()

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT full_name FROM users WHERE email = 'migtest@example.com'")).scalar() == "Mig Test"
        assert conn.execute(text("SELECT full_name FROM patients WHERE id = :pid"), {"pid": patient_id}).scalar() == "Mig Test Patient"
        assert conn.execute(text("SELECT filename FROM documents WHERE id = :did"), {"did": document_id}).scalar() == "test.pdf"
        assert conn.execute(text("SELECT raw_test_name FROM lab_results WHERE document_id = :did"), {"did": document_id}).scalar() == "Hemoglobin"
        # And the new Phase 1 columns exist on that same, pre-existing row —
        # nullable, unset, not a destructive rewrite.
        assert conn.execute(text("SELECT source_connection_id FROM lab_results WHERE document_id = :did"), {"did": document_id}).scalar() is None


def test_bootstrap_recognizes_already_applied_phase1_schema_no_recreation(scratch_db):
    """Item 20 — simulates a database the OLD run_migrations() already
    built out to the full Phase 1 schema (no alembic_version table at
    all). bootstrap_alembic.py must recognize it and stamp head WITHOUT
    dropping/recreating anything."""
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")
    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.commit()

    import importlib
    import sys

    sys.path.insert(0, str(BACKEND_DIR))
    bootstrap = importlib.import_module("scripts.bootstrap_alembic")
    importlib.reload(bootstrap)

    old_url_getter = bootstrap._database_url
    old_argv = sys.argv
    bootstrap._database_url = lambda: scratch_db
    try:
        sys.argv = ["bootstrap_alembic.py"]  # argparse reads real sys.argv, not pytest's own
        assert bootstrap.main() == 0  # dry-run report only
        with engine.connect() as conn:
            assert not engine.dialect.has_table(conn, "alembic_version")  # dry-run: nothing written yet

        sys.argv = ["bootstrap_alembic.py", "--apply"]
        assert bootstrap.main() == 0
        with engine.connect() as conn:
            stamped = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert stamped == HEAD_REVISION
    finally:
        bootstrap._database_url = old_url_getter
        sys.argv = old_argv


def test_bootstrap_refuses_unknown_drifted_schema(scratch_db):
    """Item 21 — a deliberately incomplete/wrong schema must be refused,
    never stamped."""
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")
    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(text("ALTER TABLE interop_connections DROP COLUMN status"))
        conn.commit()

    import importlib
    import sys

    sys.path.insert(0, str(BACKEND_DIR))
    bootstrap = importlib.import_module("scripts.bootstrap_alembic")
    importlib.reload(bootstrap)

    old_url_getter = bootstrap._database_url
    old_argv = sys.argv
    bootstrap._database_url = lambda: scratch_db
    try:
        sys.argv = ["bootstrap_alembic.py", "--apply"]
        assert bootstrap.main() == 1
        with engine.connect() as conn:
            assert not engine.dialect.has_table(conn, "alembic_version")  # refused — never stamped
    finally:
        bootstrap._database_url = old_url_getter
        sys.argv = old_argv


def test_downgrade_past_legacy_baseline_is_refused_without_override(scratch_db, monkeypatch):
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")

    monkeypatch.delenv("ALEMBIC_ALLOW_DESTRUCTIVE_DOWNGRADE", raising=False)
    with pytest.raises(Exception, match="Refusing to downgrade"):
        command.downgrade(cfg, "base")


def test_downgrade_past_legacy_baseline_succeeds_with_explicit_override(scratch_db, monkeypatch):
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")

    monkeypatch.setenv("ALEMBIC_ALLOW_DESTRUCTIVE_DOWNGRADE", "yes-i-am-sure")
    command.downgrade(cfg, "base")

    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')")
        ).scalar()
        assert not exists


def test_downgrade_interop_phase1_only_is_safe_and_reversible(scratch_db):
    """Downgrading JUST 0002 (not past the legacy baseline) needs no
    override and must not touch legacy tables."""
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, LEGACY_REVISION)

    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')")
        ).scalar()
        assert not conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'interop_connections')")
        ).scalar()

    # And re-upgrading from there works too (round-trip).
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'interop_connections')")
        ).scalar()
