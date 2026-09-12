"""CapabilityStatement parsing / compatibility-report unit tests
(BRAGI_INTEROP_PLAN.md P5/P11/P12/P49). No DB, no network — operates on the
synthetic servers' static CapabilityStatement fixtures directly."""

from app.services.interop.capability import _parse_capability_statement, build_compatibility_report
from tests.interop.fixtures.synthetic_fhir_server import SERVER_A_CAPABILITY, SERVER_B_CAPABILITY, SERVER_C_CAPABILITY


def test_server_a_full_featured_report():
    discovered = _parse_capability_statement(SERVER_A_CAPABILITY)
    report = build_compatibility_report(discovered)

    assert report["resources"]["Patient"]["status"] == "SUPPORTED"
    assert report["resources"]["Observation"]["status"] == "SUPPORTED"
    assert report["resources"]["DiagnosticReport"]["status"] in ("SUPPORTED", "PARTIALLY SUPPORTED")
    assert report["resources"]["Observation"]["bragi_import_support"] is True
    assert report["checks"]["SMART authentication"] == "PASS"
    assert report["checks"]["Incremental synchronization"] == "PASS"
    assert report["checks"]["Bulk Data"] == "UNSUPPORTED"  # optional, never reported as an error


def test_server_b_minimal_report_has_no_smart_or_documents():
    discovered = _parse_capability_statement(SERVER_B_CAPABILITY)
    report = build_compatibility_report(discovered)

    assert report["resources"]["Patient"]["status"] == "SUPPORTED"
    assert report["resources"]["Observation"]["status"] == "SUPPORTED"
    assert report["resources"]["DiagnosticReport"]["status"] == "UNSUPPORTED"
    assert report["resources"]["DocumentReference"]["status"] == "UNSUPPORTED"
    assert report["checks"]["SMART authentication"] == "FAIL"
    assert report["checks"]["Incremental synchronization"] == "FAIL"
    # Core patient retrieval and lab observations — the two things Bragi
    # actually depends on — still both pass on the minimal server.
    assert report["checks"]["Core patient retrieval"] == "PASS"
    assert report["checks"]["Laboratory observations"] == "PASS"


def test_server_c_local_profile_report_still_supports_core_resources():
    discovered = _parse_capability_statement(SERVER_C_CAPABILITY)
    report = build_compatibility_report(discovered)

    assert report["resources"]["Patient"]["status"] == "SUPPORTED"
    assert report["resources"]["Observation"]["status"] == "SUPPORTED"


def test_score_is_deterministic_and_bounded():
    for capability in (SERVER_A_CAPABILITY, SERVER_B_CAPABILITY, SERVER_C_CAPABILITY):
        report = build_compatibility_report(_parse_capability_statement(capability))
        assert 0 <= report["compatibility_score_percent"] <= 100
        # Re-running against the same input gives the same score — no
        # hidden randomness/timing dependency.
        report2 = build_compatibility_report(_parse_capability_statement(capability))
        assert report["compatibility_score_percent"] == report2["compatibility_score_percent"]
