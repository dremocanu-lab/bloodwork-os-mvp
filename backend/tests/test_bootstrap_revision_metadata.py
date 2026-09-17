"""Regression test for the exact staleness bug bootstrap_alembic.py's
REVISION_ADDITIONS used to have: it was a POSITIONAL list, so adding new
migrations to the chain without adding a matching entry silently made
`classify()` treat every revision from the last-covered boundary onward
as "already at head" (nothing left to add) — a database that had only
reached, say, 2398fbce8a2c (Phase 3 hardening) would have been
misclassified as matching head. No real DB connectivity needed — this is
pure metadata/chain-shape validation.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

ALEMBIC_INI = str(BACKEND_DIR / "alembic.ini")


def _real_chain() -> list[str]:
    script = ScriptDirectory.from_config(Config(ALEMBIC_INI))
    revisions = list(script.walk_revisions(base="base", head="head"))
    revisions.reverse()
    return [r.revision for r in revisions]


def test_revision_additions_covers_every_non_head_revision():
    """Every revision in the REAL chain except head must have a
    REVISION_ADDITIONS entry — if a future developer adds a migration
    without updating REVISION_ADDITIONS, this fails immediately instead of
    letting bootstrap_alembic.py silently misclassify a real database."""
    bootstrap = importlib.import_module("scripts.bootstrap_alembic")
    importlib.reload(bootstrap)

    chain = _real_chain()
    required = set(chain[:-1])
    known = set(bootstrap.REVISION_ADDITIONS.keys())

    missing = required - known
    assert not missing, (
        f"REVISION_ADDITIONS is missing entries for {sorted(missing)} — "
        "a migration was added to alembic/versions/ without a matching REVISION_ADDITIONS "
        "entry in scripts/bootstrap_alembic.py. See that module's REVISION_ADDITIONS comment."
    )

    stale = known - set(chain)
    assert not stale, (
        f"REVISION_ADDITIONS references revision(s) {sorted(stale)} that no longer exist in "
        "alembic/versions/ — a migration file was removed/renamed without updating "
        "REVISION_ADDITIONS in scripts/bootstrap_alembic.py."
    )


def test_validate_coverage_raises_on_incomplete_metadata():
    """Direct unit check of the fail-closed guard itself: an artificially
    incomplete REVISION_ADDITIONS must raise, not silently proceed."""
    bootstrap = importlib.import_module("scripts.bootstrap_alembic")
    importlib.reload(bootstrap)

    chain = _real_chain()
    assert len(chain) >= 2, "expected at least 2 revisions in the real chain for this test to be meaningful"

    original = bootstrap.REVISION_ADDITIONS
    try:
        incomplete = dict(original)
        incomplete.pop(chain[0])  # drop coverage for the earliest boundary
        bootstrap.REVISION_ADDITIONS = incomplete
        try:
            bootstrap._validate_coverage(chain)
            raised = False
        except RuntimeError:
            raised = True
        assert raised, "_validate_coverage() must raise when REVISION_ADDITIONS is missing a boundary"
    finally:
        bootstrap.REVISION_ADDITIONS = original


def test_known_production_variant_logical_revision_is_in_chain():
    """KNOWN_PRODUCTION_VARIANT_LOGICAL_REVISION must always name a real
    revision in the chain — if 0002_interop_phase1 were ever renumbered,
    this catches it instead of _classify_known_production_variant()
    silently returning None forever."""
    bootstrap = importlib.import_module("scripts.bootstrap_alembic")
    importlib.reload(bootstrap)

    chain = _real_chain()
    assert bootstrap.KNOWN_PRODUCTION_VARIANT_LOGICAL_REVISION in chain
