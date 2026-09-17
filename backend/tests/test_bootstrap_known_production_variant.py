"""Reproduces the REAL production schema variant discovered 2026-09-17 —
see docs/database/MIGRATIONS.md's "Known production legacy variant"
section and scripts/bootstrap_alembic.py's module docstring — against a
disposable scratch Postgres database, and proves
`_classify_known_production_variant()` / `_apply_known_variant()` handle
it exactly as required: recognize-but-refuse-to-mutate on a bare dry run,
repair ONLY the four specific missing indexes on an explicit
`--repair-known-legacy --apply`, preserve every named legacy extra, and
fail closed on anything that isn't an EXACT match for this one known
fingerprint.

Same real-DB-required skip conditions and scratch-database pattern as
tests/test_migrations.py (never touches the shared dev/test database).
"""

from __future__ import annotations

import importlib
import os
import sys
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
            test_db = f"bragi_bstest_probe_{uuid.uuid4().hex[:8]}"
            conn.execute(text(f"CREATE DATABASE {test_db}"))
            conn.execute(text(f"DROP DATABASE {test_db}"))
        return True
    except Exception:
        return False


if not _can_create_database():
    pytest.skip("Connected DB role cannot CREATE DATABASE — skipping bootstrap known-variant tests.", allow_module_level=True)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

BACKEND_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent
ALEMBIC_INI = str(BACKEND_DIR / "alembic.ini")
LEGACY_REVISION = "77df8fa2b964"
PHASE1_REVISION = "4cf06d926267"
HEAD_REVISION = ScriptDirectory.from_config(Config(ALEMBIC_INI)).get_current_head()

MISSING_BASELINE_INDEX_NAMES = {
    "ix_doctor_patient_access_is_active",
    "ix_emergency_access_sessions_public_id",
    "ix_lab_results_category",
    "ix_upload_jobs_file_sha256",
}

# The exact raw SQL commit b6d8ae9 ran (see git log -S) — reproduced here
# verbatim, not paraphrased, so the test schema really is bit-for-bit the
# same shape as real production.
LEGACY_INTEROP_DUPLICATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_epil_connection_id ON interop_patient_identity_links(connection_id)",
    "CREATE INDEX IF NOT EXISTS ix_epil_patient_id ON interop_patient_identity_links(patient_id)",
    "CREATE INDEX IF NOT EXISTS ix_epil_identifier_system ON interop_patient_identity_links(identifier_system)",
    "CREATE INDEX IF NOT EXISTS ix_epil_identifier_value ON interop_patient_identity_links(identifier_value)",
    "CREATE INDEX IF NOT EXISTS ix_iic_connection_id ON interop_identity_conflicts(connection_id)",
    "CREATE INDEX IF NOT EXISTS ix_iic_resolved ON interop_identity_conflicts(resolved)",
    "CREATE INDEX IF NOT EXISTS ix_itm_connection_id ON interop_terminology_mappings(connection_id)",
    "CREATE INDEX IF NOT EXISTS ix_itm_source_code ON interop_terminology_mappings(source_code)",
    "CREATE INDEX IF NOT EXISTS ix_itm_status ON interop_terminology_mappings(status)",
]


def _db_url_for(name: str) -> str:
    from sqlalchemy.engine import make_url

    return make_url(_admin_url()).set(database=name).render_as_string(hide_password=False)


@pytest.fixture
def scratch_db():
    name = f"bragi_bstest_{uuid.uuid4().hex[:10]}"
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


def _bootstrap_module():
    sys.path.insert(0, str(BACKEND_DIR))
    bootstrap = importlib.import_module("scripts.bootstrap_alembic")
    importlib.reload(bootstrap)
    return bootstrap


def _run_bootstrap(bootstrap, db_url: str, argv: list[str]) -> int:
    old_url_getter = bootstrap._database_url
    old_argv = sys.argv
    bootstrap._database_url = lambda: db_url
    try:
        sys.argv = argv
        return bootstrap.main()
    finally:
        bootstrap._database_url = old_url_getter
        sys.argv = old_argv


def _build_known_production_variant_schema(db_url: str, with_sample_data: bool = False) -> tuple[int, int | None]:
    """Builds the EXACT real production legacy variant on a fresh scratch
    database: interop Phase 1 applied (via real Alembic, so every column/
    FK/type is byte-for-byte the canonical shape), then hand-mutated to
    match production exactly — 4 baseline indexes missing, 9 short-name
    interop duplicate indexes present, one harmless extra column, no
    alembic_version stamp. Returns (patient_id, session_id_with_public_id)
    when with_sample_data — used by the "no application data changes" and
    "duplicate public_id refuses" tests."""
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, PHASE1_REVISION)

    engine = create_engine(db_url)
    patient_id = None
    session_id = None
    with engine.connect() as conn:
        for name in MISSING_BASELINE_INDEX_NAMES:
            conn.execute(text(f"DROP INDEX {name}"))
        for stmt in LEGACY_INTEROP_DUPLICATE_INDEX_SQL:
            conn.execute(text(stmt))
        conn.execute(text("ALTER TABLE documents ADD COLUMN original_layout_json TEXT"))

        if with_sample_data:
            conn.execute(
                text(
                    "INSERT INTO users (email, full_name, password_hash, role) "
                    "VALUES ('bstest@example.com', 'BS Test', 'x', 'patient')"
                )
            )
            conn.execute(text("INSERT INTO patients (full_name, emergency_search_enabled) VALUES ('BS Test Patient', 0)"))
            patient_id = conn.execute(text("SELECT id FROM patients WHERE full_name = 'BS Test Patient'")).scalar()
            conn.execute(
                text(
                    "INSERT INTO emergency_access_sessions "
                    "(emergency_user_id, patient_id, reason, started_at, expires_at, created_at, public_id) "
                    "VALUES ((SELECT id FROM users WHERE email = 'bstest@example.com'), :pid, 'x', 'now', 'later', 'now', 'sess-1')"
                ),
                {"pid": patient_id},
            )
            session_id = conn.execute(text("SELECT id FROM emergency_access_sessions WHERE public_id = 'sess-1'")).scalar()

        conn.execute(text("DROP TABLE alembic_version"))
        conn.commit()

    return patient_id, session_id


def _existing_index_names(engine, table: str) -> set[str]:
    from sqlalchemy import inspect

    with engine.connect() as conn:
        return {ix["name"] for ix in inspect(conn).get_indexes(table)}


def test_dry_run_recognizes_known_variant_and_mutates_nothing(scratch_db):
    """Items 1-2: a bare (no-flag) run correctly identifies the exact
    known production variant and its repair plan, but changes nothing —
    no alembic_version, no new indexes."""
    _build_known_production_variant_schema(scratch_db)
    bootstrap = _bootstrap_module()

    exit_code = _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py"])
    assert exit_code == 0

    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        assert not engine.dialect.has_table(conn, "alembic_version")
    remaining_missing = MISSING_BASELINE_INDEX_NAMES - _existing_index_names(engine, "doctor_patient_access") - _existing_index_names(
        engine, "emergency_access_sessions"
    ) - _existing_index_names(engine, "lab_results") - _existing_index_names(engine, "upload_jobs")
    assert remaining_missing == MISSING_BASELINE_INDEX_NAMES  # still all missing — nothing created


def test_apply_without_repair_flag_does_not_touch_known_variant(scratch_db):
    """A bare --apply (no --repair-known-legacy) must NOT repair/stamp
    the known variant — only an ordinary exact chain match. This is the
    "clearest/safest interface" requirement: an operator who forgets the
    second flag gets a no-op, never a partial/unexpected mutation."""
    _build_known_production_variant_schema(scratch_db)
    bootstrap = _bootstrap_module()

    exit_code = _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py", "--apply"])
    assert exit_code == 0

    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        assert not engine.dialect.has_table(conn, "alembic_version")


def test_apply_repairs_only_four_expected_indexes_and_preserves_everything(scratch_db):
    """Items 3-9: --repair-known-legacy --apply creates ONLY the four
    known missing indexes, preserves original_layout_json and every
    legacy duplicate index, changes no application data, stamps exactly
    4cf06d926267, and the resulting database then upgrades cleanly to
    head and passes migration drift."""
    patient_id, _ = _build_known_production_variant_schema(scratch_db, with_sample_data=True)
    bootstrap = _bootstrap_module()

    exit_code = _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py", "--repair-known-legacy", "--apply"])
    assert exit_code == 0

    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        stamped = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert stamped == PHASE1_REVISION  # item 7

        # item 3 — exactly the 4 expected indexes now exist.
        for name in MISSING_BASELINE_INDEX_NAMES:
            exists = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :n)"), {"n": name}
            ).scalar()
            assert exists, f"expected index {name} to have been created"

        # item 4 — original_layout_json preserved (column still exists).
        assert conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'documents' AND column_name = 'original_layout_json')"
            )
        ).scalar()

        # item 5 — old short-name duplicate indexes preserved.
        for stmt in LEGACY_INTEROP_DUPLICATE_INDEX_SQL:
            index_name = stmt.split("EXISTS ")[1].split(" ON")[0]
            exists = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :n)"), {"n": index_name}
            ).scalar()
            assert exists, f"expected legacy duplicate index {index_name} to be preserved"

        # item 6 — application data unchanged.
        assert conn.execute(
            text("SELECT full_name FROM patients WHERE id = :pid"), {"pid": patient_id}
        ).scalar() == "BS Test Patient"

    # item 8 — run_migrations.py's own job (alembic upgrade head) now
    # applies cleanly on top of the repaired+stamped database.
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD_REVISION

    # item 9 — resulting schema passes migration drift (only the
    # documented, tolerated legacy duplicate indexes remain as diff).
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app import models
    from scripts._alembic_baseline_fingerprint import flatten_diff
    from scripts.check_migration_drift import _is_tolerated

    with engine.connect() as conn:
        migration_context = MigrationContext.configure(conn)
        diff = flatten_diff(compare_metadata(migration_context, models.Base.metadata))
    real_drift = [d for d in diff if not _is_tolerated(d)]
    assert real_drift == [], f"unexpected migration drift after repair+upgrade: {real_drift}"


def test_bootstrap_rerun_after_repair_is_a_safe_noop(scratch_db):
    """Item 10 — running bootstrap again after a successful repair+stamp
    is a safe no-op (already-stamped guard), never a second repair
    attempt or an error."""
    _build_known_production_variant_schema(scratch_db)
    bootstrap = _bootstrap_module()
    assert _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py", "--repair-known-legacy", "--apply"]) == 0

    exit_code = _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py", "--repair-known-legacy", "--apply"])
    assert exit_code == 0  # "already stamped — nothing to do", not an error

    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == PHASE1_REVISION


def test_duplicate_emergency_public_id_refuses(scratch_db):
    """Item 11 — a duplicate public_id must block creating the UNIQUE
    index; bootstrap refuses rather than attempting (and either failing
    loudly or, worse, somehow succeeding on) a duplicate-violating create.

    Real production has never had two rows with the same public_id (the
    legacy partial-unique `ix_eas_public_id` — see
    KNOWN_LEGACY_DUPLICATE_INDEXES — already enforces this on any
    database that went through the OLD run_migrations() bootstrap, which
    is why it must also be dropped here to make the scenario this test
    exercises possible at all). The explicit duplicate check this test
    proves exists as defense-in-depth regardless — it must never be the
    ONLY thing standing between a repair and a broken UNIQUE index."""
    _build_known_production_variant_schema(scratch_db, with_sample_data=True)
    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        conn.execute(text("DROP INDEX ix_eas_public_id"))
        conn.execute(
            text(
                "INSERT INTO users (email, full_name, password_hash, role) "
                "VALUES ('bstest2@example.com', 'BS Test 2', 'x', 'patient')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO emergency_access_sessions "
                "(emergency_user_id, reason, started_at, expires_at, created_at, public_id) "
                "VALUES ((SELECT id FROM users WHERE email = 'bstest2@example.com'), 'x', 'now', 'later', 'now', 'sess-1')"
            )
        )  # same public_id 'sess-1' as the first fixture row — a real duplicate
        conn.commit()

    bootstrap = _bootstrap_module()
    exit_code = _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py", "--repair-known-legacy", "--apply"])
    assert exit_code == 1

    with engine.connect() as conn:
        assert not engine.dialect.has_table(conn, "alembic_version")  # refused — never stamped
        assert not conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_emergency_access_sessions_public_id')")
        ).scalar()  # and never created


@pytest.mark.parametrize(
    "mutate_sql,description",
    [
        ("ALTER TABLE documents ADD COLUMN some_unexplained_column TEXT", "unexpected extra column"),
        ("ALTER TABLE interop_connections DROP COLUMN status", "unexpected missing column"),
        (
            "CREATE INDEX ix_lab_results_category ON lab_results (document_id)",
            "wrong index definition (same name, wrong column)",
        ),
        ("CREATE INDEX ix_totally_unrelated_extra ON patients (full_name)", "extra unknown index"),
        (
            "ALTER TABLE interop_connections ADD COLUMN capability_fingerprint VARCHAR",
            "partially-applied phase3 (1 of 6 columns)",
        ),
    ],
)
def test_unexplained_drift_refuses_known_variant_recognition(scratch_db, mutate_sql, description):
    """Items 12-16 — anything beyond the EXACT known fingerprint must
    refuse, never be silently tolerated or misclassified as a clean
    match."""
    _build_known_production_variant_schema(scratch_db)
    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        conn.execute(text(mutate_sql))
        conn.commit()

    bootstrap = _bootstrap_module()
    exit_code = _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py", "--repair-known-legacy", "--apply"])
    assert exit_code == 1, f"expected refusal for: {description}"

    with engine.connect() as conn:
        assert not engine.dialect.has_table(conn, "alembic_version"), f"must not have stamped for: {description}"


def test_fresh_database_still_recognized_by_ordinary_path(scratch_db):
    """Item 17 — the known-variant path must never interfere with the
    ordinary "ready-made head, never touched by hand" case: a database
    Alembic itself built from scratch is a plain exact match, not a
    "known legacy variant"."""
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")
    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.commit()

    bootstrap = _bootstrap_module()
    with engine.connect() as conn:
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext

        from app import models

        migration_context = MigrationContext.configure(conn)
        diff = compare_metadata(migration_context, models.Base.metadata)
    chain = bootstrap._revision_chain(cfg)
    classification, target_revision, _ = bootstrap.classify(diff, chain)
    assert classification == "match"
    assert target_revision == HEAD_REVISION


def test_exact_legacy_baseline_still_recognized(scratch_db):
    """Item 18 — a database that matches 0001 exactly (nothing from Phase
    1 onward) is still recognized and stamped by the ordinary path, using
    a bare --apply (never the known-variant repair flags)."""
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, LEGACY_REVISION)
    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.commit()

    bootstrap = _bootstrap_module()
    exit_code = _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py", "--apply"])
    assert exit_code == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == LEGACY_REVISION


def test_exact_phase1_still_recognized(scratch_db):
    """Item 19 — a database that matches Phase 1 (4cf06d926267) EXACTLY
    (no missing baseline indexes, no legacy duplicate indexes, no
    original_layout_json) is a plain ordinary match, not the known
    variant — recognized and stamped via a bare --apply."""
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, PHASE1_REVISION)
    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.commit()

    bootstrap = _bootstrap_module()
    exit_code = _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py", "--apply"])
    assert exit_code == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == PHASE1_REVISION


def test_current_head_database_still_recognized(scratch_db):
    """Item 20 — a database already at the CURRENT real head (every CDI
    migration included, not just Phase 1) is still a clean ordinary
    match — proves the chain-length growth since this tool was first
    written didn't break the head case either."""
    cfg = _alembic_config(scratch_db)
    command.upgrade(cfg, "head")
    engine = create_engine(scratch_db)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.commit()

    bootstrap = _bootstrap_module()
    exit_code = _run_bootstrap(bootstrap, scratch_db, ["bootstrap_alembic.py", "--apply"])
    assert exit_code == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD_REVISION
