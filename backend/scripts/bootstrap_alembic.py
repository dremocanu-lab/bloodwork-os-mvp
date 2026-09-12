#!/usr/bin/env python
"""One-time operator tool: stamp an EXISTING database (one that got its
schema from the OLD hand-written run_migrations()/create_all() startup
code, or from an earlier Alembic revision than the current head) to the
correct Alembic revision — WITHOUT re-running any CREATE TABLE/ALTER
TABLE.

This is never run automatically by the application. It is an explicit,
one-time, human-invoked action per docs/database/MIGRATIONS.md.

    cd backend
    python scripts/bootstrap_alembic.py            # inspect + report only
    python scripts/bootstrap_alembic.py --apply     # actually stamp

Classifies the target database against the REAL migration chain (read
from alembic/versions/ at run time — never a hardcoded revision id, which
would go stale the moment a new migration is added; this exact staleness
was reproduced for real once already — see REVISION_ADDITIONS' own
comment) into exactly one of:

  - Matches an EARLIER revision in the chain exactly (e.g. the pre-
    interop legacy baseline, or Phase 1 applied but not yet Phase 3) →
    stamped to that revision. `alembic upgrade head` then carries it
    forward normally.
  - Matches HEAD exactly → stamped to head directly.
  - Anything else (missing tables/columns, unexpected extra objects, a
    type mismatch, a partially-applied migration, ...) → UNKNOWN.
    REFUSES to stamp and prints the exact diff so a human can decide
    what to do — never "if tables exist then stamp head."

Uses the same alembic.autogenerate.compare_metadata engine `alembic
check`/`revision --autogenerate` use — real column/index/FK comparison,
not just a table-name existence check.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _mask_credentials(url: str) -> str:
    """Never print a real DB password — even in a local/dev-only operator
    tool, this output can end up in a terminal scrollback, a CI log, or a
    pasted bug report."""
    return re.sub(r"://[^:@/]+:[^@]+@", "://***:***@", url)


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from dotenv import load_dotenv
from sqlalchemy import create_engine

from scripts._alembic_baseline_fingerprint import KNOWN_LEGACY_DUPLICATE_INDEXES, entry_label, flatten_diff

load_dotenv()

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

# What each migration BOUNDARY adds, in chain order (index i = what moving
# from chain[i] to chain[i+1] introduces). This is the one place that must
# be updated when a new migration ships — the revision IDs themselves are
# always resolved dynamically from the chain (see _revision_chain), never
# hardcoded, so THAT part can't go stale. This list going out of sync with
# reality just means an old-schema database gets classified as UNKNOWN
# (fails closed, refuses to stamp) rather than silently misclassified —
# never a silent wrong stamp.
REVISION_ADDITIONS = [
    {  # 0001_legacy_baseline -> 0002_interop_phase1
        "tables": {
            "interop_secrets",
            "interop_connections",
            "interop_patient_identity_links",
            "interop_sync_runs",
            "interop_terminology_mappings",
            "interop_identity_conflicts",
        },
        "columns": {
            ("documents", "source_connection_id"),
            ("lab_results", "source_connection_id"),
            ("lab_results", "external_observation_id"),
        },
        "fk_tables": {"documents", "lab_results"},
    },
    {  # 0002_interop_phase1 -> 0003_phase3_hardening
        "tables": set(),
        "columns": {
            ("interop_connections", "capability_fingerprint"),
            ("interop_connections", "consecutive_failures"),
            ("interop_connections", "last_failure_at"),
            ("interop_connections", "last_failure_reason"),
            ("interop_connections", "sync_cursor_json"),
            ("interop_connections", "disabled_at"),
        },
        "fk_tables": set(),
    },
]


def _revision_chain(cfg: Config) -> list[str]:
    """Revision IDs from the first (legacy baseline) to head, in order —
    always read from alembic/versions/ at run time."""
    script = ScriptDirectory.from_config(cfg)
    revisions = list(script.walk_revisions(base="base", head="head"))
    revisions.reverse()  # walk_revisions yields head-to-base
    return [r.revision for r in revisions]


def _database_url() -> str:
    import os

    raw = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:dreams@localhost:5432/mvp1_phase1")
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


def _split_diff(diff: list, expected_tables: set[str], expected_columns: set[tuple[str, str]], expected_fk_tables: set[str]) -> tuple[list, list]:
    """Splits a flattened diff into (expected, unexplained) against one
    candidate revision boundary's addition set."""
    expected: list = []
    unexplained: list = []

    for entry in flatten_diff(diff):
        kind = entry[0]

        if kind == "remove_index":
            index_name = getattr(entry[1], "name", None)
            (expected if index_name in KNOWN_LEGACY_DUPLICATE_INDEXES else unexplained).append(entry)
            continue

        if kind == "add_table":
            (expected if entry[1].name in expected_tables else unexplained).append(entry)
            continue

        if kind == "add_column":
            table_name, column = entry[2], entry[3]
            (expected if (table_name, column.name) in expected_columns else unexplained).append(entry)
            continue

        if kind == "add_index":
            index = entry[1]
            table_name = index.table.name if index.table is not None else None
            index_columns = list(index.columns.keys())
            on_new_table = table_name in expected_tables
            on_new_column = table_name in expected_fk_tables and any((table_name, c) in expected_columns for c in index_columns)
            (expected if (on_new_table or on_new_column) else unexplained).append(entry)
            continue

        if kind == "add_fk":
            fk = entry[1]
            table_name = fk.table.name if fk.table is not None else None
            (expected if table_name in expected_fk_tables else unexplained).append(entry)
            continue

        # remove_table, remove_column, modify_type, modify_nullable, an
        # unexplained remove_fk, etc. — never expected, always unknown/drift.
        unexplained.append(entry)

    return expected, unexplained


def classify(diff: list, chain: list[str]) -> tuple[str, str | None, list]:
    """Returns (classification, target_revision, unexplained_entries).
    classification is 'match' (target_revision is where to stamp) or
    'unknown' (target_revision is None)."""
    # Try each possible "already at revision chain[i]" hypothesis, from
    # head (i.e. no further additions expected) backwards to the very
    # first revision. The first one whose expected-addition-set exactly
    # accounts for every entry in the diff (nothing left unexplained) wins.
    for i in range(len(chain) - 1, -1, -1):
        expected_tables: set[str] = set()
        expected_columns: set[tuple[str, str]] = set()
        expected_fk_tables: set[str] = set()
        for addition in REVISION_ADDITIONS[i:]:
            expected_tables |= addition["tables"]
            expected_columns |= addition["columns"]
            expected_fk_tables |= addition["fk_tables"]

        _expected, unexplained = _split_diff(diff, expected_tables, expected_columns, expected_fk_tables)
        if not unexplained:
            return "match", chain[i], []

    # Nothing matched — report against the HEAD hypothesis (i == len-1,
    # the strictest/most informative diff — expects nothing beyond
    # tolerated legacy indexes) so the admin sees the full picture.
    _, unexplained = _split_diff(diff, set(), set(), set())
    return "unknown", None, unexplained


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually stamp the database. Without this, only reports the classification.")
    args = parser.parse_args()

    from app import models  # deferred: needs sys.path set up above

    url = _database_url()
    engine = create_engine(url)
    cfg = Config(str(ALEMBIC_INI))
    chain = _revision_chain(cfg)
    head_revision = chain[-1]

    with engine.connect() as conn:
        # Already stamped? Don't re-classify/re-stamp blindly.
        existing_version = None
        if engine.dialect.has_table(conn, "alembic_version"):
            result = conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchone()
            existing_version = result[0] if result else None

        if existing_version:
            print(f"Database is already stamped at revision {existing_version!r} — nothing to do.")
            print("If this looks wrong, resolve it manually (this tool never overwrites an existing stamp).")
            return 0

        migration_context = MigrationContext.configure(conn)
        diff = compare_metadata(migration_context, models.Base.metadata)

    classification, target_revision, unexplained = classify(diff, chain)

    if classification == "unknown":
        print("UNKNOWN/DRIFTED SCHEMA — refusing to stamp.")
        print(f"Target: {_mask_credentials(url)}")
        print(f"\n{len(unexplained)} unexplained difference(s) between the live database and app/models.py:")
        for entry in unexplained:
            print(f"  - {entry_label(entry)}")
        print(
            "\nThis database does not match any known revision in the migration chain "
            f"({', '.join(chain)}) exactly. Do not stamp blindly — investigate the "
            "difference(s) above, fix the database or the models, and re-run this tool."
        )
        return 1

    label = "head" if target_revision == head_revision else f"revision {target_revision} (not yet head — `alembic upgrade head` will carry it forward)"
    print(f"Database matches {label} exactly.")

    if not args.apply:
        print(f"Would stamp: alembic stamp {target_revision}")
        print("Re-run with --apply to actually stamp.")
        return 0

    # Explicit — a bare Config(alembic_ini) has no sqlalchemy.url set, and
    # env.py's own _database_url() (a DIFFERENT function, reading the real
    # DATABASE_URL env var — monkeypatching THIS module's _database_url,
    # as tests/test_migrations.py does, has no effect on it) would silently
    # stamp the real default database instead of `url` above. Reproduced
    # for real (a test's scratch database was correctly classified but the
    # real dev database got stamped instead) and fixed before this shipped.
    cfg.set_main_option("sqlalchemy.url", url)
    command.stamp(cfg, target_revision)
    print(f"Stamped database at revision {target_revision} ({label}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
