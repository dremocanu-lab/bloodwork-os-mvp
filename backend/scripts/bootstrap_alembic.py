#!/usr/bin/env python
"""One-time operator tool: stamp an EXISTING database (one that got its
schema from the OLD hand-written run_migrations()/create_all() startup
code, before this Alembic conversion) to the correct Alembic revision —
WITHOUT re-running any CREATE TABLE/ALTER TABLE.

This is never run automatically by the application. It is an explicit,
one-time, human-invoked action per docs/database/MIGRATIONS.md.

    cd backend
    python scripts/bootstrap_alembic.py            # inspect + report only
    python scripts/bootstrap_alembic.py --apply     # actually stamp

Classifies the target database into exactly one of:

  A. LEGACY   — matches the pre-interop schema (0001) exactly. Stamped to
                revision 0001.
  B. PHASE1   — matches the full current schema (0001+0002) exactly.
                Stamped to head (0002).
  C. UNKNOWN  — anything else (missing legacy tables/columns, unexpected
                extra objects, partially-applied interop tables, a type
                mismatch, etc.). REFUSES to stamp and prints the exact
                diff so a human can decide what to do — never
                "if tables exist then stamp head."

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
from dotenv import load_dotenv
from sqlalchemy import create_engine

from scripts._alembic_baseline_fingerprint import KNOWN_LEGACY_DUPLICATE_INDEXES, entry_label, flatten_diff

load_dotenv()

LEGACY_REVISION = "77df8fa2b964"  # 0001_legacy_baseline
HEAD_REVISION = "4cf06d926267"  # 0002_interop_phase1

# The exact Phase 1 addition — every `add_*` diff entry that's OK to see
# on a database that hasn't had 0002 applied yet (i.e., is otherwise a
# faithful legacy-baseline match).
PHASE1_NEW_TABLES = {
    "interop_secrets",
    "interop_connections",
    "interop_patient_identity_links",
    "interop_sync_runs",
    "interop_terminology_mappings",
    "interop_identity_conflicts",
}
PHASE1_NEW_COLUMNS = {
    ("documents", "source_connection_id"),
    ("lab_results", "source_connection_id"),
    ("lab_results", "external_observation_id"),
}
PHASE1_FK_TABLES = {"documents", "lab_results"}


def _database_url() -> str:
    import os

    raw = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:dreams@localhost:5432/mvp1_phase1")
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


def _classify_diff(diff: list) -> tuple[str, list[tuple]]:
    """Returns (classification, unexplained_entries). classification is
    one of 'head' (empty/only-tolerated diff), 'legacy' (diff is exactly
    the expected Phase 1 addition), or 'unknown'. A "modify_*" entry (see
    flatten_diff's docstring) always ends up unexplained here — it's never
    part of the expected Phase 1 addition, so any real column-level drift
    correctly refuses to stamp rather than being silently miscategorized."""
    unexplained = []
    phase1_shaped = []

    for entry in flatten_diff(diff):
        kind = entry[0]

        if kind == "remove_index":
            index_name = getattr(entry[1], "name", None)
            if index_name in KNOWN_LEGACY_DUPLICATE_INDEXES:
                continue  # tolerated, always — not phase1-related
            unexplained.append(entry)
            continue

        if kind == "add_table":
            table = entry[1]
            if table.name in PHASE1_NEW_TABLES:
                phase1_shaped.append(entry)
            else:
                unexplained.append(entry)
            continue

        if kind == "add_column":
            table_name, column = entry[2], entry[3]
            if (table_name, column.name) in PHASE1_NEW_COLUMNS:
                phase1_shaped.append(entry)
            else:
                unexplained.append(entry)
            continue

        if kind == "add_index":
            index = entry[1]
            table_name = index.table.name if index.table is not None else None
            index_columns = list(index.columns.keys())
            on_new_table = table_name in PHASE1_NEW_TABLES
            on_new_column = table_name in PHASE1_FK_TABLES and any((table_name, c) in PHASE1_NEW_COLUMNS for c in index_columns)
            if on_new_table or on_new_column:
                phase1_shaped.append(entry)
            else:
                unexplained.append(entry)
            continue

        if kind == "add_fk":
            fk = entry[1]
            table_name = fk.table.name if fk.table is not None else None
            if table_name in PHASE1_FK_TABLES:
                phase1_shaped.append(entry)
            else:
                unexplained.append(entry)
            continue

        # Any other kind (remove_table, remove_column, modify_type,
        # modify_nullable, remove_fk not otherwise explained, etc.) is
        # never expected — always unknown/drift.
        unexplained.append(entry)

    if unexplained:
        return "unknown", unexplained
    if phase1_shaped:
        return "legacy", []
    return "head", []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually stamp the database. Without this, only reports the classification.")
    args = parser.parse_args()

    from app import models  # deferred: needs sys.path set up above

    url = _database_url()
    engine = create_engine(url)

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

    classification, unexplained = _classify_diff(diff)

    if classification == "unknown":
        print("UNKNOWN/DRIFTED SCHEMA — refusing to stamp.")
        print(f"Target: {_mask_credentials(url)}")
        print(f"\n{len(unexplained)} unexplained difference(s) between the live database and app/models.py:")
        for entry in unexplained:
            print(f"  - {entry_label(entry)}")
        print(
            "\nThis database does not match either the known legacy baseline (0001) or the "
            "known Phase 1 schema (head) exactly. Do not stamp blindly — investigate the "
            "difference(s) above, fix the database or the models, and re-run this tool."
        )
        return 1

    target_revision = LEGACY_REVISION if classification == "legacy" else HEAD_REVISION
    label = "legacy baseline (0001)" if classification == "legacy" else "Phase 1 / head (0002)"
    print(f"Database matches {label} exactly.")

    if not args.apply:
        print(f"Would stamp: alembic stamp {target_revision}")
        print("Re-run with --apply to actually stamp.")
        return 0

    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(alembic_ini))
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
