"""Capability fingerprint / drift detection (BRAGI_INTEROP_PLAN.md Phase 3
§3.2). A partner's CapabilityStatement can change between discoveries —
a FHIR version bump, a resource quietly disappearing, a required search
parameter dropped, SMART/auth metadata changing, an advertised profile
changing. Silently continuing to sync as if nothing changed risks
missing data or, worse, assuming support that no longer exists.

`compute_fingerprint()` normalizes the discovery dict (from
capability.py's `discover_capabilities()`/`run_discovery()`) into a
stable, order-independent hash. `diff_fingerprints()` compares the
PREVIOUS discovery's normalized shape against the CURRENT one and
reports exactly what changed, classified as breaking or informational.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# Only these fields matter for "did anything a real sync depends on
# change" — software version strings, timestamps, etc. are deliberately
# excluded from the fingerprint (they change harmlessly on every partner
# deploy and would make every re-discovery look like drift).
_TRACKED_TOP_LEVEL = ("fhir_version", "bulk_data_supported", "smart_supported")


def _normalize_resource(name: str, resource: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "searchable": bool(resource.get("searchable")),
        "search_params": sorted(resource.get("search_params", [])),
        "supports_last_updated": bool(resource.get("supports_last_updated")),
        "profiles": sorted(resource.get("profiles", [])),
    }


def normalize_discovery(discovered: dict[str, Any]) -> dict[str, Any]:
    """A stable, order-independent shape of the parts of a discovery
    result that matter for sync behavior — see module docstring for what
    is deliberately excluded."""
    resources = discovered.get("resources", {})
    return {
        **{k: discovered.get(k) for k in _TRACKED_TOP_LEVEL},
        "resources": {name: _normalize_resource(name, r) for name, r in sorted(resources.items())},
    }


def compute_fingerprint(discovered: dict[str, Any]) -> str:
    normalized = normalize_discovery(discovered)
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class DriftEntry:
    kind: str  # e.g. "fhir_version_changed", "resource_removed", "search_param_removed", ...
    breaking: bool
    detail: str


@dataclass
class DriftReport:
    changed: bool
    breaking: bool
    entries: list[DriftEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "breaking": self.breaking,
            "entries": [{"kind": e.kind, "breaking": e.breaking, "detail": e.detail} for e in self.entries],
        }


def diff_fingerprints(previous: dict[str, Any] | None, current: dict[str, Any]) -> DriftReport:
    """Compares two NORMALIZED discovery shapes (from `normalize_discovery`)
    and reports what changed. `previous=None` (first-ever discovery) is
    never drift."""
    if previous is None:
        return DriftReport(changed=False, breaking=False)

    entries: list[DriftEntry] = []

    if previous.get("fhir_version") != current.get("fhir_version"):
        entries.append(
            DriftEntry(
                "fhir_version_changed",
                breaking=True,
                detail=f"{previous.get('fhir_version')!r} -> {current.get('fhir_version')!r}",
            )
        )

    if previous.get("smart_supported") and not current.get("smart_supported"):
        entries.append(DriftEntry("smart_support_removed", breaking=True, detail="SMART security metadata no longer advertised"))
    elif not previous.get("smart_supported") and current.get("smart_supported"):
        entries.append(DriftEntry("smart_support_added", breaking=False, detail="SMART security metadata newly advertised"))

    if previous.get("bulk_data_supported") and not current.get("bulk_data_supported"):
        entries.append(DriftEntry("bulk_data_removed", breaking=False, detail="$export no longer advertised (optional capability)"))
    elif not previous.get("bulk_data_supported") and current.get("bulk_data_supported"):
        entries.append(DriftEntry("bulk_data_added", breaking=False, detail="$export newly advertised"))

    prev_resources = previous.get("resources", {})
    cur_resources = current.get("resources", {})

    for name in sorted(set(prev_resources) - set(cur_resources)):
        entries.append(DriftEntry("resource_removed", breaking=True, detail=f"{name} no longer advertised"))
    for name in sorted(set(cur_resources) - set(prev_resources)):
        entries.append(DriftEntry("resource_added", breaking=False, detail=f"{name} newly advertised"))

    for name in sorted(set(prev_resources) & set(cur_resources)):
        prev_r, cur_r = prev_resources[name], cur_resources[name]
        if prev_r.get("searchable") and not cur_r.get("searchable"):
            entries.append(DriftEntry("resource_search_removed", breaking=True, detail=f"{name} no longer searchable"))
        removed_params = sorted(set(prev_r.get("search_params", [])) - set(cur_r.get("search_params", [])))
        if removed_params:
            entries.append(
                DriftEntry(
                    "search_param_removed",
                    breaking=True,
                    detail=f"{name}: {', '.join(removed_params)} no longer supported",
                )
            )
        if prev_r.get("supports_last_updated") and not cur_r.get("supports_last_updated"):
            entries.append(DriftEntry("last_updated_removed", breaking=False, detail=f"{name}: _lastUpdated no longer supported (falls back to bounded full sync)"))
        removed_profiles = sorted(set(prev_r.get("profiles", [])) - set(cur_r.get("profiles", [])))
        if removed_profiles:
            entries.append(DriftEntry("profile_changed", breaking=False, detail=f"{name}: profile(s) {', '.join(removed_profiles)} no longer advertised"))

    breaking = any(e.breaking for e in entries)
    return DriftReport(changed=bool(entries), breaking=breaking, entries=entries)
