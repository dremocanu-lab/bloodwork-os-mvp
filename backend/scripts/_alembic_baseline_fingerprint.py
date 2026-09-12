"""Shared reference data for backend/scripts/bootstrap_alembic.py and
backend/scripts/check_migration_drift.py — see docs/database/MIGRATIONS.md.

KNOWN_LEGACY_DUPLICATE_INDEXES: real, harmless index-name duplication that
exists on every database this application has ever run against (see
alembic/versions/0001_legacy_baseline.py's own comment for the full
history: the OLD run_migrations() raw SQL created these BEFORE/ALONGSIDE
the declarative models' own `index=True` columns, and they were never
cleaned up). Not a schema bug, not drift — an intentional, narrow
allowlist so the drift check doesn't cry wolf on a database that's
actually fine. Every excluded name is listed explicitly here, never a
blanket "ignore unknown extras."
"""

KNOWN_LEGACY_DUPLICATE_INDEXES = frozenset(
    {
        "ix_eas_user",
        "ix_eas_patient",
        "ix_eas_public_id",
        "ix_eal_user",
        "ix_eal_patient",
        "ix_eal_session",
        "ix_eal_action",
        "ix_ec_patient",
    }
)


def flatten_diff(diff: list) -> list[tuple]:
    """alembic.autogenerate.compare_metadata groups "modify column"
    operations (type/nullable/server_default/comment changes) into a
    nested list of one-or-more tuples per column, unlike every other diff
    kind (add_table, add_column, add_index, add_fk, remove_index, ...)
    which are flat tuples directly in the top-level list. Normalize to a
    flat list of plain tuples so callers can treat every entry uniformly."""
    flat: list[tuple] = []
    for item in diff:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    return flat


def entry_label(entry: tuple) -> str:
    """Human-readable label for one flattened compare_metadata diff entry —
    handles every kind's differing tuple shape (add_column's table/column
    name sit at different positions than add_table/add_index/add_fk/
    remove_index/modify_*)."""
    kind = entry[0]
    if kind == "add_column":
        return f"{kind}: {entry[2]}.{entry[3].name}"
    if kind.startswith("modify_"):
        table_name, column_name = entry[2], entry[3]
        return f"{kind}: {table_name}.{column_name}"
    target = entry[1] if len(entry) > 1 else None
    name = getattr(target, "name", None) or (entry[2] if len(entry) > 2 else str(target))
    return f"{kind}: {name}"
