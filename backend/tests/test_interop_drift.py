"""Capability drift-detection tests (BRAGI_INTEROP_PLAN.md Phase 3 §3.2).
No DB, no network."""

from app.services.interop.drift import compute_fingerprint, diff_fingerprints, normalize_discovery

SERVER_A = {
    "fhir_version": "4.0.1",
    "smart_supported": True,
    "bulk_data_supported": False,
    "resources": {
        "Patient": {"searchable": True, "search_params": ["_id", "identifier"], "supports_last_updated": False, "profiles": []},
        "Observation": {
            "searchable": True,
            "search_params": ["patient", "category", "code", "date", "_lastUpdated"],
            "supports_last_updated": True,
            "profiles": ["http://example.org/StructureDefinition/lab-obs"],
        },
    },
}


def test_fingerprint_is_deterministic_and_order_independent():
    a = compute_fingerprint(SERVER_A)
    # Same content, dict key insertion order shuffled — must fingerprint identically.
    reordered = {"resources": SERVER_A["resources"], **{k: v for k, v in SERVER_A.items() if k != "resources"}}
    b = compute_fingerprint(reordered)
    assert a == b


def test_fingerprint_changes_on_real_change():
    modified = {**SERVER_A, "fhir_version": "4.0.0"}
    assert compute_fingerprint(SERVER_A) != compute_fingerprint(modified)


def test_no_previous_discovery_is_never_drift():
    report = diff_fingerprints(None, normalize_discovery(SERVER_A))
    assert report.changed is False
    assert report.breaking is False


def test_fhir_version_change_is_breaking():
    current = {**SERVER_A, "fhir_version": "4.0.0"}
    report = diff_fingerprints(normalize_discovery(SERVER_A), normalize_discovery(current))
    assert report.breaking is True
    assert any(e.kind == "fhir_version_changed" for e in report.entries)


def test_resource_removed_is_breaking():
    current = {**SERVER_A, "resources": {"Patient": SERVER_A["resources"]["Patient"]}}  # Observation dropped
    report = diff_fingerprints(normalize_discovery(SERVER_A), normalize_discovery(current))
    assert report.breaking is True
    assert any(e.kind == "resource_removed" and "Observation" in e.detail for e in report.entries)


def test_required_search_param_removed_is_breaking():
    current = {
        **SERVER_A,
        "resources": {
            **SERVER_A["resources"],
            "Observation": {**SERVER_A["resources"]["Observation"], "search_params": ["category", "code", "date"]},  # "patient" dropped
        },
    }
    report = diff_fingerprints(normalize_discovery(SERVER_A), normalize_discovery(current))
    assert report.breaking is True
    assert any(e.kind == "search_param_removed" for e in report.entries)


def test_bulk_data_removed_is_not_breaking():
    """Bulk Data is optional (P49) — its removal is informational, never
    a breaking/degrade-triggering change."""
    with_bulk = {**SERVER_A, "bulk_data_supported": True}
    report = diff_fingerprints(normalize_discovery(with_bulk), normalize_discovery(SERVER_A))
    assert report.changed is True
    assert report.breaking is False
    assert any(e.kind == "bulk_data_removed" and not e.breaking for e in report.entries)


def test_resource_added_is_not_breaking():
    current = {
        **SERVER_A,
        "resources": {**SERVER_A["resources"], "DiagnosticReport": {"searchable": True, "search_params": ["patient"], "supports_last_updated": False, "profiles": []}},
    }
    report = diff_fingerprints(normalize_discovery(SERVER_A), normalize_discovery(current))
    assert report.changed is True
    assert report.breaking is False
    assert any(e.kind == "resource_added" and not e.breaking for e in report.entries)


def test_software_version_string_never_triggers_drift():
    """Excluded from the fingerprint on purpose (see module docstring) —
    a partner deploying a new build shouldn't look like a compatibility
    regression."""
    with_software = {**SERVER_A, "software": {"name": "SomeServer", "version": "1.2.3"}}
    with_different_software = {**SERVER_A, "software": {"name": "SomeServer", "version": "9.9.9"}}
    assert compute_fingerprint(with_software) == compute_fingerprint(with_different_software)


def test_no_drift_when_nothing_changed():
    report = diff_fingerprints(normalize_discovery(SERVER_A), normalize_discovery(dict(SERVER_A)))
    assert report.changed is False
    assert report.breaking is False
