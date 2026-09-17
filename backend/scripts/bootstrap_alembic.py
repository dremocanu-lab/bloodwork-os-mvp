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
would go stale the moment a new migration is added) into exactly one of:

  - Matches an EARLIER revision in the chain exactly (e.g. the pre-
    interop legacy baseline, or Phase 1 applied but not yet Phase 3) →
    stamped to that revision. `alembic upgrade head` then carries it
    forward normally.
  - Matches HEAD exactly → stamped to head directly.
  - Matches the one specific KNOWN PRODUCTION LEGACY VARIANT described
    below → recognized, but requires a SEPARATE, more explicit repair
    step (see "Production legacy variant reconciliation").
  - Anything else (missing tables/columns, unexpected extra objects, a
    type mismatch, a partially-applied migration, ...) → UNKNOWN.
    REFUSES to stamp and prints the exact diff so a human can decide
    what to do — never "if tables exist then stamp head."

Uses the same alembic.autogenerate.compare_metadata engine `alembic
check`/`revision --autogenerate` use — real column/index/FK comparison,
not just a table-name existence check.

## Production legacy variant reconciliation

Real production (discovered 2026-09-17 — see
docs/database/MIGRATIONS.md's "Known production legacy variant" section)
predates Alembic bookkeeping AND predates 0003_phase3_hardening, but is
not a clean match for any single chain revision either:

  - it has the full interop Phase 1 schema (built by the OLD
    interoperability-era run_migrations() raw SQL, before Alembic
    existed) but NOT yet the Phase 3 hardening columns;
  - it carries 9 short-name duplicate interop indexes that same OLD raw
    SQL created (see KNOWN_PRODUCTION_LEGACY_EXTRA_INDEXES in
    scripts/_alembic_baseline_fingerprint.py) — harmless, preserved;
  - it carries one harmless extra column, documents.original_layout_json
    (see KNOWN_PRODUCTION_LEGACY_EXTRA_COLUMNS in the same module) —
    harmless, preserved;
  - it is MISSING 4 indexes the legacy baseline (0001) itself declares —
    SQLAlchemy's `create_all()` only creates missing TABLES on an
    existing database, never retroactively adds an index that got added
    to a column already sitting on an existing table, which is exactly
    what happened here.

This exact, narrow combination is recognized by
`_classify_known_production_variant()` below and requires an explicit,
SEPARATE two-flag apply (`--repair-known-legacy --apply`, not a bare
`--apply`) that does ONLY four things: verify the live schema still
matches this exact known variant right before mutating, create the 4
missing indexes (nothing else), verify no duplicate
emergency_access_sessions.public_id exists first (that index is UNIQUE),
and stamp `4cf06d926267` (interop Phase 1 — the logical revision this
repaired schema now matches exactly). It never chains into
`alembic upgrade head` itself — `scripts/run_migrations.py` remains
solely responsible for that, run separately afterward.
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
from sqlalchemy import Index, MetaData, Table, create_engine, inspect, text

from scripts._alembic_baseline_fingerprint import (
    KNOWN_LEGACY_DUPLICATE_INDEXES,
    KNOWN_PRODUCTION_LEGACY_EXTRA_COLUMNS,
    KNOWN_PRODUCTION_LEGACY_EXTRA_INDEXES,
    entry_label,
    flatten_diff,
)

load_dotenv()

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

# What each migration BOUNDARY adds, keyed by the REVISION IT MOVES *FROM*
# (i.e. REVISION_ADDITIONS["77df8fa2b964"] is what moving from
# 77df8fa2b964 to the NEXT revision in the chain introduces). Keyed by
# revision id — never by position — so an appended revision can never
# silently shift what an existing entry means. This is the one place that
# must gain a new entry when a new migration ships; `_validate_coverage()`
# below FAILS CLOSED (raises) if any non-head revision in the real chain
# has no entry here, rather than letting classification silently treat an
# unlisted boundary as "nothing to add" (the exact staleness bug this
# module used to have: REVISION_ADDITIONS was a positional list with only
# 2 entries after 4 more migrations had shipped, so any database at
# 2398fbce8a2c or later was silently misclassified as already matching
# head). See tests/test_bootstrap_revision_metadata.py.
REVISION_ADDITIONS: dict[str, dict] = {
    "77df8fa2b964": {  # 0001_legacy_baseline -> 0002_interop_phase1
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
    "4cf06d926267": {  # 0002_interop_phase1 -> 0003_phase3_hardening
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
    "2398fbce8a2c": {  # 0003_phase3_hardening -> phase6 derived artifact kind
        "tables": set(),
        "columns": {("documents", "derived_artifact_kind")},
        "fk_tables": set(),
    },
    "b52c5c35f707": {  # phase6 derived artifact kind -> phase7 medication provenance
        "tables": set(),
        "columns": {
            ("patient_medications", "source_document_id"),
            ("patient_medications", "source_segment_id"),
            ("patient_medications", "stop_date_basis"),
            ("source_evidence", "medication_id"),
        },
        "fk_tables": {"patient_medications", "source_evidence"},
    },
    "ff84f15530a9": {  # phase7 medication provenance -> phase10 timeline projection
        "tables": set(),
        "columns": {
            ("patient_events", "source_document_id"),
            ("patient_events", "source_medication_id"),
        },
        "fk_tables": {"patient_events"},
    },
    "a1c9d4e7f203": {  # phase10 timeline projection -> source evidence field bboxes (head)
        "tables": set(),
        "columns": {("source_evidence", "field_bboxes_json")},
        "fk_tables": set(),
    },
}

# The one specific production legacy variant this module knows how to
# reconcile — see the module docstring's "Production legacy variant
# reconciliation" section. Both are exact, named facts, never inferred.
KNOWN_PRODUCTION_VARIANT_LOGICAL_REVISION = "4cf06d926267"

# Indexes the legacy baseline (0001) itself declares that `create_all()`
# never retroactively added to the already-existing production tables —
# see 0001_legacy_baseline.py's own create_index calls for these exact
# names/tables/columns/uniqueness, which this list must always match
# exactly (never inferred from the name alone).
MISSING_BASELINE_INDEXES: list[dict] = [
    {"name": "ix_doctor_patient_access_is_active", "table": "doctor_patient_access", "columns": ("is_active",), "unique": False},
    {"name": "ix_emergency_access_sessions_public_id", "table": "emergency_access_sessions", "columns": ("public_id",), "unique": True},
    {"name": "ix_lab_results_category", "table": "lab_results", "columns": ("category",), "unique": False},
    {"name": "ix_upload_jobs_file_sha256", "table": "upload_jobs", "columns": ("file_sha256",), "unique": False},
]


def _revision_chain(cfg: Config) -> list[str]:
    """Revision IDs from the first (legacy baseline) to head, in order —
    always read from alembic/versions/ at run time."""
    script = ScriptDirectory.from_config(cfg)
    revisions = list(script.walk_revisions(base="base", head="head"))
    revisions.reverse()  # walk_revisions yields head-to-base
    return [r.revision for r in revisions]


def _validate_coverage(chain: list[str]) -> None:
    """FAIL CLOSED if REVISION_ADDITIONS doesn't have an entry for every
    non-head revision in the real chain — see REVISION_ADDITIONS' own
    comment for exactly why this matters. Raises rather than silently
    treating a missing boundary as "nothing added there"."""
    required = set(chain[:-1])  # every revision except head has a "what's next" boundary
    known = set(REVISION_ADDITIONS.keys())
    missing = required - known
    if missing:
        raise RuntimeError(
            "bootstrap_alembic.py's REVISION_ADDITIONS is missing an entry for "
            f"{sorted(missing)} — a migration was added to the chain without updating "
            "REVISION_ADDITIONS. Refusing to classify any database until this is fixed: "
            "an incomplete REVISION_ADDITIONS would silently misclassify a database that "
            "stopped at one of the missing boundaries. Add the missing entry(ies) — see "
            "REVISION_ADDITIONS' own comment for the format."
        )
    extra = known - set(chain)
    if extra:
        raise RuntimeError(
            f"bootstrap_alembic.py's REVISION_ADDITIONS references revision(s) {sorted(extra)} "
            "that no longer exist in alembic/versions/ — a migration file was removed/renamed "
            "without updating REVISION_ADDITIONS. Fix REVISION_ADDITIONS before continuing."
        )


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


def _expected_additions_from(chain: list[str], i: int) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    """Union of every boundary's additions from chain[i] onward — what a
    database "already at chain[i]" is still missing relative to head."""
    expected_tables: set[str] = set()
    expected_columns: set[tuple[str, str]] = set()
    expected_fk_tables: set[str] = set()
    for boundary_revision in chain[i : len(chain) - 1]:
        addition = REVISION_ADDITIONS[boundary_revision]
        expected_tables |= addition["tables"]
        expected_columns |= addition["columns"]
        expected_fk_tables |= addition["fk_tables"]
    return expected_tables, expected_columns, expected_fk_tables


def _diff_present(entries: list) -> tuple[set[str], set[tuple[str, str]]]:
    """Which tables/columns from `entries` (already-flattened diff
    entries) show up as add_table/add_column — i.e. genuinely missing
    from the live database relative to head."""
    present_tables: set[str] = set()
    present_columns: set[tuple[str, str]] = set()
    for entry in entries:
        kind = entry[0]
        if kind == "add_table":
            present_tables.add(entry[1].name)
        elif kind == "add_column":
            present_columns.add((entry[2], entry[3].name))
    return present_tables, present_columns


def _has_partially_applied_boundary(chain: list[str], i: int, diff_entries: list) -> str | None:
    """A migration boundary is atomic: a real database either has NOT
    reached it (every one of its additions is missing) or HAS reached it
    (every one of its additions is already present, so none show up in
    the diff). Anything in between — e.g. 3 of Phase 3's 6 hardening
    columns present — is not a clean match for ANY hypothesis and must be
    refused (item 16), even though every diff entry that IS present would
    otherwise be individually "expected". Returns the first partially-
    applied boundary's revision id, or None if every boundary from
    chain[i] onward is cleanly all-missing or all-present."""
    present_tables, present_columns = _diff_present(diff_entries)
    for boundary_revision in chain[i : len(chain) - 1]:
        addition = REVISION_ADDITIONS[boundary_revision]
        total = len(addition["tables"]) + len(addition["columns"])
        if total == 0:
            continue
        present = len(addition["tables"] & present_tables) + len(addition["columns"] & present_columns)
        if 0 < present < total:
            return boundary_revision
    return None


def classify(diff: list, chain: list[str]) -> tuple[str, str | None, list]:
    """Returns (classification, target_revision, unexplained_entries).
    classification is 'match' (target_revision is where to stamp) or
    'unknown' (target_revision is None)."""
    _validate_coverage(chain)
    flat = flatten_diff(diff)

    # Try each possible "already at revision chain[i]" hypothesis, from
    # head (i.e. no further additions expected) backwards to the very
    # first revision. The first one whose expected-addition-set exactly
    # accounts for every entry in the diff (nothing left unexplained),
    # AND whose every boundary is either fully missing or fully applied
    # (never partial — see _has_partially_applied_boundary), wins.
    for i in range(len(chain) - 1, -1, -1):
        if _has_partially_applied_boundary(chain, i, flat):
            continue
        expected_tables, expected_columns, expected_fk_tables = _expected_additions_from(chain, i)
        _expected, unexplained = _split_diff(diff, expected_tables, expected_columns, expected_fk_tables)
        if not unexplained:
            return "match", chain[i], []

    # Nothing matched — report against the HEAD hypothesis (the
    # strictest/most informative diff — expects nothing beyond tolerated
    # legacy indexes) so the admin sees the full picture.
    _, unexplained = _split_diff(diff, set(), set(), set())
    return "unknown", None, unexplained


def _classify_known_production_variant(diff: list, chain: list[str]) -> dict | None:
    """Recognizes the ONE specific known production legacy variant (see
    module docstring) — interop Phase 1 applied, Phase 3 hardening not
    yet, plus the exact named legacy extras/missing indexes documented in
    scripts/_alembic_baseline_fingerprint.py. Returns None if the live
    diff doesn't match this exact fingerprint (still refused as unknown by
    the caller) — never a loose "close enough" match."""
    _validate_coverage(chain)
    if KNOWN_PRODUCTION_VARIANT_LOGICAL_REVISION not in chain:
        return None
    i = chain.index(KNOWN_PRODUCTION_VARIANT_LOGICAL_REVISION)
    flat = flatten_diff(diff)

    if _has_partially_applied_boundary(chain, i, flat):
        return None  # e.g. a partially-applied Phase 3 — not this variant either

    expected_tables, expected_columns, expected_fk_tables = _expected_additions_from(chain, i)
    _expected, unexplained = _split_diff(diff, expected_tables, expected_columns, expected_fk_tables)

    still_unexplained: list = []
    preserved_columns: list[tuple[str, str]] = []
    preserved_indexes: list[str] = []
    indexes_to_repair: list[dict] = []
    indexes_by_name = {spec["name"]: spec for spec in MISSING_BASELINE_INDEXES}

    for entry in unexplained:
        kind = entry[0]

        if kind == "remove_index":
            index_name = getattr(entry[1], "name", None)
            if index_name in KNOWN_PRODUCTION_LEGACY_EXTRA_INDEXES:
                preserved_indexes.append(index_name)
                continue
            still_unexplained.append(entry)
            continue

        if kind == "remove_column":
            # Same 4-tuple shape as add_column: (kind, schema, table_name, column).
            table_name, column = entry[2], entry[3]
            column_name = column.name
            if (table_name, column_name) in KNOWN_PRODUCTION_LEGACY_EXTRA_COLUMNS:
                preserved_columns.append((table_name, column_name))
                continue
            still_unexplained.append(entry)
            continue

        if kind == "add_index":
            index = entry[1]
            index_name = index.name
            spec = indexes_by_name.get(index_name)
            if spec is not None:
                actual_table = index.table.name if index.table is not None else None
                actual_columns = tuple(index.columns.keys())
                actual_unique = bool(index.unique)
                if actual_table == spec["table"] and actual_columns == spec["columns"] and actual_unique == spec["unique"]:
                    indexes_to_repair.append(spec)
                    continue
            still_unexplained.append(entry)
            continue

        still_unexplained.append(entry)

    if still_unexplained:
        return None

    # Require EVERY known missing baseline index to be accounted for —
    # this is a fixed, exact fingerprint, not "however many happen to be
    # missing." If production is only missing 3 of the 4, that's a
    # different (unrecognized) situation, not this variant.
    if len(indexes_to_repair) != len(MISSING_BASELINE_INDEXES):
        return None

    return {
        "logical_revision": KNOWN_PRODUCTION_VARIANT_LOGICAL_REVISION,
        "missing_phase_additions": sorted(f"{t}.{c}" for t, c in expected_columns) + sorted(expected_tables),
        "preserved_columns": preserved_columns,
        "preserved_indexes": sorted(preserved_indexes),
        "indexes_to_repair": indexes_to_repair,
    }


def _report_known_variant(variant: dict, url: str) -> None:
    print("KNOWN LEGACY PRODUCTION VARIANT")
    print(f"\nCompatible logical revision:\n{variant['logical_revision']}")
    print("\nExpected Phase 3+ additions missing (will apply normally via `alembic upgrade head` after stamping):")
    for item in variant["missing_phase_additions"]:
        print(f"  - {item}")
    print("\nKnown tolerated legacy extras (preserved, never dropped):")
    for table, column in variant["preserved_columns"]:
        print(f"  - column: {table}.{column}")
    for index_name in variant["preserved_indexes"]:
        print(f"  - index: {index_name}")
    print("\nMissing baseline indexes to repair:")
    for spec in variant["indexes_to_repair"]:
        unique = "UNIQUE " if spec["unique"] else ""
        print(f"  - {unique}{spec['name']} ON {spec['table']}({', '.join(spec['columns'])})")
    print("\nWould:")
    n = len(variant["indexes_to_repair"])
    print(f"  1. create {n} missing index(es);")
    for table, column in variant["preserved_columns"]:
        print(f"  2. preserve {table}.{column};")
    print("  3. preserve verified redundant legacy indexes;")
    print(f"  4. stamp {variant['logical_revision']};")
    print("  5. allow normal `alembic upgrade head` to apply Phase 3+.")
    print(f"\nTarget: {_mask_credentials(url)}")


def _apply_known_variant(engine, cfg: Config, url: str, variant: dict) -> int:
    """Stage B: the explicit, narrow repair — create ONLY the recognized
    missing indexes, verify safety immediately before mutating, stamp the
    one logical revision this variant matches, then STOP. Never chains
    into `alembic upgrade head` itself."""
    with engine.connect() as conn:
        # Requirement: refuse if an Alembic version already exists.
        if engine.dialect.has_table(conn, "alembic_version"):
            result = conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchone()
            if result and result[0]:
                print(f"Database is already stamped at revision {result[0]!r} — refusing to repair/re-stamp.")
                return 1

        # Requirement: re-inspect the schema immediately before mutation,
        # and require the exact known fingerprint still holds.
        migration_context = MigrationContext.configure(conn)
        from app import models

        diff = compare_metadata(migration_context, models.Base.metadata)
        cfg_chain = _revision_chain(cfg)
        reclassified = _classify_known_production_variant(diff, cfg_chain)
        if reclassified is None:
            print("Schema no longer matches the known production legacy variant on re-inspection — refusing to repair.")
            return 1

        # Requirement: verify emergency_access_sessions.public_id has no
        # duplicates before creating its UNIQUE index.
        dup = conn.execute(
            text(
                "SELECT public_id, COUNT(*) FROM emergency_access_sessions "
                "WHERE public_id IS NOT NULL GROUP BY public_id HAVING COUNT(*) > 1"
            )
        ).fetchall()
        if dup:
            print(
                f"REFUSING: {len(dup)} duplicate emergency_access_sessions.public_id value(s) found — "
                "creating a UNIQUE index would fail (or worse, silently pick one row) if it succeeded on "
                "duplicate data. Resolve the duplicates manually, then re-run."
            )
            return 1

        # Requirement: verify the columns underlying every missing index
        # actually exist, and that no same-name index already exists with
        # a different definition (defense in depth — already implied by
        # the diff-based classification above, checked again directly).
        inspector = inspect(conn)
        for spec in reclassified["indexes_to_repair"]:
            table_columns = {c["name"] for c in inspector.get_columns(spec["table"])}
            missing_columns = set(spec["columns"]) - table_columns
            if missing_columns:
                print(f"REFUSING: {spec['table']} is missing column(s) {sorted(missing_columns)} required by index {spec['name']!r}.")
                return 1
            existing_index_names = {ix["name"] for ix in inspector.get_indexes(spec["table"])}
            if spec["name"] in existing_index_names:
                print(f"REFUSING: an index named {spec['name']!r} already exists on {spec['table']} — will not blindly recreate it.")
                return 1

        # All checks passed — create ONLY the recognized missing indexes.
        reflected_meta = MetaData()
        for spec in reclassified["indexes_to_repair"]:
            table = Table(spec["table"], reflected_meta, autoload_with=conn)
            index = Index(spec["name"], *[table.c[c] for c in spec["columns"]], unique=spec["unique"])
            index.create(bind=conn)
            print(f"Created index {spec['name']} on {spec['table']}({', '.join(spec['columns'])}).")
        conn.commit()

    # Stamp — explicit sqlalchemy.url, same reasoning as the ordinary
    # match path below (a bare Config has no url set; env.py's own
    # _database_url() reads DATABASE_URL directly and would stamp the
    # real default database instead of `url`).
    cfg.set_main_option("sqlalchemy.url", url)
    command.stamp(cfg, reclassified["logical_revision"])
    print(f"Stamped database at revision {reclassified['logical_revision']} (known production legacy variant, repaired).")
    print("Run `python scripts/run_migrations.py` next to apply Phase 3+ and reach head.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually stamp the database. Without this, only reports the classification.")
    parser.add_argument(
        "--repair-known-legacy",
        action="store_true",
        help=(
            "Required together with --apply to repair+stamp the one known production legacy "
            "variant (see module docstring). Has no effect for an ordinary exact-revision match — "
            "a bare --apply alone never creates or alters any schema object, only stamps."
        ),
    )
    args = parser.parse_args()

    from app import models  # deferred: needs sys.path set up above

    url = _database_url()
    engine = create_engine(url)
    cfg = Config(str(ALEMBIC_INI))
    chain = _revision_chain(cfg)
    _validate_coverage(chain)
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

    if classification == "match":
        label = "head" if target_revision == head_revision else f"revision {target_revision} (not yet head — `alembic upgrade head` will carry it forward)"
        print(f"Database matches {label} exactly.")

        if not args.apply:
            print(f"Would stamp: alembic stamp {target_revision}")
            print("Re-run with --apply to actually stamp.")
            return 0

        # Explicit — a bare Config(alembic_ini) has no sqlalchemy.url set, and
        # env.py's own _database_url() (a DIFFERENT function, reading the real
        # DATABASE_URL env var) would silently stamp the real default database
        # instead of `url` above.
        cfg.set_main_option("sqlalchemy.url", url)
        command.stamp(cfg, target_revision)
        print(f"Stamped database at revision {target_revision} ({label}).")
        return 0

    # Not an exact chain match — try the one known production legacy variant
    # before giving up.
    variant = _classify_known_production_variant(diff, chain)
    if variant is not None:
        _report_known_variant(variant, url)
        if not (args.apply and args.repair_known_legacy):
            print("\nNO CHANGES MADE.")
            print("Re-run with --repair-known-legacy --apply to actually repair and stamp.")
            return 0
        return _apply_known_variant(engine, cfg, url, variant)

    print("UNKNOWN/DRIFTED SCHEMA — refusing to stamp.")
    print(f"Target: {_mask_credentials(url)}")
    print(f"\n{len(unexplained)} unexplained difference(s) between the live database and app/models.py:")
    for entry in unexplained:
        print(f"  - {entry_label(entry)}")
    print(
        "\nThis database does not match any known revision in the migration chain "
        f"({', '.join(chain)}), nor the one known production legacy variant, exactly. "
        "Do not stamp blindly — investigate the difference(s) above, fix the database or "
        "the models, and re-run this tool."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
