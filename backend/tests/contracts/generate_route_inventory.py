#!/usr/bin/env python
"""Generates a machine-readable route inventory (method, path, route name,
tags, and the auth dependency actually wired to each route) directly from
the live FastAPI app — the ground truth for BRAGI_INTEROP_PLAN.md Phase
4's "API contract" safety boundary (BACKEND_MODULARIZATION_BASELINE.md).

Usage: `python tests/contracts/generate_route_inventory.py <output.json>`
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "x" * 40)

from app.main import app  # noqa: E402


def _describe_dependency(call) -> str:
    """Best-effort description of one dependency callable. `require_role`
    returns a locally-defined closure named "dependency" for every route,
    which is useless on its own — introspect its __closure__ to recover
    the REAL allowed_roles tuple it was created with, so the authorization
    map reflects actual enforced roles, not a generic closure name."""
    name = getattr(call, "__name__", None) or str(call)
    if name == "dependency" and getattr(call, "__closure__", None):
        freevars = call.__code__.co_freevars
        try:
            idx = freevars.index("allowed_roles")
            roles = call.__closure__[idx].cell_contents
            return f"require_role{tuple(roles)}"
        except (ValueError, IndexError):
            pass
    return name


def _dependency_names(route) -> list[str]:
    """Best-effort extraction of the auth/authorization dependency callable
    names actually wired to a route (e.g. "require_role('admin')",
    "get_current_user") — read from the route's own dependant tree, not
    re-derived/guessed."""
    names = []
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return names
    for dep in dependant.dependencies:
        call = getattr(dep, "call", None)
        if call is not None:
            names.append(_describe_dependency(call))
    return names


def build_inventory() -> list[dict]:
    entries = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", None) or [])
        if not methods:
            continue  # non-HTTP routes (e.g. mounted sub-apps) — none expected here
        entries.append(
            {
                "path": route.path,
                "methods": methods,
                "name": getattr(route, "name", None),
                "tags": sorted(getattr(route, "tags", None) or []),
                "dependencies": sorted(set(_dependency_names(route))),
            }
        )
    entries.sort(key=lambda e: (e["path"], e["methods"]))
    return entries


def main() -> int:
    inventory = build_inventory()
    output_path = sys.argv[1] if len(sys.argv) > 1 else "tests/contracts/route_inventory_pre_modularization.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2, sort_keys=False)
    print(f"Wrote {len(inventory)} route entries to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
