#!/usr/bin/env python
"""CI gate (BRAGI_INTEROP_PLAN.md / docs/database/MIGRATIONS.md item:
migration drift check): fails if `app/models.py` has changed but no
migration represents that change.

Run against a database that is fully migrated to `head`
(`alembic upgrade head` first — see ci.yml) — this compares that DB's
REAL structure to the CURRENT models via Alembic's own autogenerate
diffing (the same engine `alembic revision --autogenerate` uses), so "a
model changed but nobody wrote a migration for it" shows up as a nonzero
exit here instead of silently reaching production.

The only tolerated diff is the known, explicitly-named set of legacy
duplicate indexes (see _alembic_baseline_fingerprint.py) — never a
blanket "ignore everything," and any new/different diff still fails.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from dotenv import load_dotenv
from sqlalchemy import create_engine

from scripts._alembic_baseline_fingerprint import KNOWN_LEGACY_DUPLICATE_INDEXES, entry_label, flatten_diff

load_dotenv()


def _database_url() -> str:
    raw = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:dreams@localhost:5432/mvp1_phase1")
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


def _is_tolerated(diff_entry: tuple) -> bool:
    kind = diff_entry[0]
    if kind != "remove_index":
        return False
    index_obj = diff_entry[1]
    name = getattr(index_obj, "name", None)
    return name in KNOWN_LEGACY_DUPLICATE_INDEXES


def main() -> int:
    from app import models  # deferred: needs sys.path set up above

    engine = create_engine(_database_url())
    with engine.connect() as conn:
        migration_context = MigrationContext.configure(conn)
        diff = flatten_diff(compare_metadata(migration_context, models.Base.metadata))

    real_drift = [d for d in diff if not _is_tolerated(d)]

    if not real_drift:
        tolerated = len(diff) - len(real_drift)
        print(f"No migration drift detected ({tolerated} known/tolerated legacy-index difference(s) ignored).")
        return 0

    print(f"MIGRATION DRIFT DETECTED — {len(real_drift)} model/database difference(s) with no migration:")
    for entry in real_drift:
        print(f"  - {entry_label(entry)}")
    print(
        "\nA model in app/models.py changed but no Alembic revision represents it. "
        "Run `alembic revision --autogenerate -m \"<description>\"` from backend/ and commit the result, "
        "or revert the model change."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
