"""External FHIR server compatibility validation (BRAGI_INTEROP_PLAN.md
Phase 3 §3.24). Synthetic in-process servers (test_interop_e2e.py) are
necessary but not sufficient — this validates the SAME, unmodified
connector code against real, independent, third-party public FHIR R4
test servers, using only their own public synthetic test data (read-only:
capability discovery + a bounded `_count=1` Patient search — never a
write, never a full sync against a real production dataset).

Network-dependent and explicitly optional: skipped (not failed) per-
server when that server is unreachable, since a public sandbox's uptime
is outside this repository's control — see BRAGI_INTEROP_PLAN.md's
acceptance-question answers for how "EXTERNAL VALIDATION BLOCKED" is
reported honestly when none are reachable, rather than faking success.
"""

from __future__ import annotations

import pytest

from app import models
from app.services.interop.capability import CapabilityDiscoveryError, build_compatibility_report, discover_capabilities
from app.services.interop.fhir_connector import run_connection_test
from app.services.interop.ssrf import SSRFBlocked

EXTERNAL_SERVERS = {
    "hapi": ("HAPI FHIR R4 public test server", "https://hapi.fhir.org/baseR4"),
    "smart_health_it": ("SMART Health IT R4 public sandbox", "https://r4.smarthealthit.org"),
    "firely": ("Firely public test server", "https://server.fire.ly/r4"),
}


def _try_discover(url: str):
    try:
        return discover_capabilities(url, allow_private_network=False), None
    except (CapabilityDiscoveryError, SSRFBlocked) as exc:
        return None, str(exc)


@pytest.mark.parametrize("key", list(EXTERNAL_SERVERS))
def test_external_server_capability_discovery(key):
    name, url = EXTERNAL_SERVERS[key]
    discovered, error = _try_discover(url)
    if discovered is None:
        pytest.skip(f"[EXTERNAL VALIDATION BLOCKED] {name} ({url}) unreachable: {error}")

    assert discovered.get("fhir_version"), f"{name}: no FHIR version advertised"
    report = build_compatibility_report(discovered)
    # Zero-code target (§3.24/§3.29): the SAME build_compatibility_report
    # used for the synthetic servers and every real admin connection —
    # no branch anywhere keyed on which server this is.
    assert report["resources"]["Patient"]["status"] in ("SUPPORTED", "PARTIALLY SUPPORTED")
    assert report["resources"]["Observation"]["status"] in ("SUPPORTED", "PARTIALLY SUPPORTED")
    print(f"[EXTERNAL VALIDATION] {name}: FHIR {discovered.get('fhir_version')}, score={report['compatibility_score_percent']}%")


@pytest.mark.parametrize("key", list(EXTERNAL_SERVERS))
def test_external_server_bounded_connection_test(key):
    """Runs the exact same `run_connection_test` non-mutating pipeline
    every real admin connection's [Test Connection] button uses — auth
    resolution, capability fetch, resource/search-param checks, and one
    bounded (`_count=1`) Patient search — against a real external server."""
    name, url = EXTERNAL_SERVERS[key]
    _, error = _try_discover(url)
    if error:
        pytest.skip(f"[EXTERNAL VALIDATION BLOCKED] {name} ({url}) unreachable: {error}")

    connection = models.InteropConnection(
        id=-1,
        name=name,
        base_url=url,
        allow_private_network=False,
        auth_type="none",
        auth_config_json="{}",
        secret_ref=None,
    )
    stages = run_connection_test(connection)
    stage_by_name = {s.stage: s for s in stages}
    assert stage_by_name["authentication"].passed
    assert stage_by_name["capability_statement"].passed
    # A bounded query is only attempted if Patient search is advertised —
    # some servers restrict unauthenticated search, which is a legitimate
    # "not testable anonymously" outcome, not a connector defect.
    if "bounded_query" in stage_by_name:
        print(f"[EXTERNAL VALIDATION] {name}: bounded query passed={stage_by_name['bounded_query'].passed}")
