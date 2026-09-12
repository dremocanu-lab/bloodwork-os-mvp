"""Phase 3 FHIR production-hardening integration tests
(BRAGI_INTEROP_PLAN.md §3.1/§3.2/§3.3/§3.7/§3.12). Real DB connectivity
required — reuses test_interop_e2e.py's client/fixtures/synthetic-server
setup rather than duplicating it (importing a fixture function into
another test module is how pytest intends fixture reuse across files).
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not configured — this file needs real DB connectivity.", allow_module_level=True)

from tests.test_interop_e2e import (  # noqa: E402
    PATIENT_IDENTIFIER_SYSTEM,
    SyntheticFhirServer,
    _auth,
    _create_connection,
    _patient_id_for,
    _signup,
    admin,  # noqa: F401 — pytest fixture, imported for reuse
    client,
    patient,  # noqa: F401 — pytest fixture, imported for reuse
)


def test_illegal_lifecycle_transition_is_rejected(admin):
    """§3.1 — a DRAFT connection can't be paused (paused is only legal
    from active/degraded) — the server rejects it rather than silently
    accepting a bogus state."""
    connection = _create_connection(admin, base_url="http://127.0.0.1:1/unused", mrn="MRN-LIFECYCLE-1")
    response = client.post(f"/admin/interop/connections/{connection['id']}/pause", headers=_auth(admin))
    assert response.status_code == 400, response.text
    assert "draft" in response.json()["detail"].lower()


def test_preview_rejected_before_discover_and_test(admin):
    """§3.1 — preview (shadow sync) is illegal from DRAFT; the admin must
    discover + test first."""
    connection = _create_connection(admin, base_url="http://127.0.0.1:1/unused", mrn="MRN-LIFECYCLE-2")
    response = client.post(f"/admin/interop/connections/{connection['id']}/preview", headers=_auth(admin))
    assert response.status_code == 400, response.text


def test_connect_rejected_before_shadow_preview(admin):
    """§3.1/P53 — activation gate: connect is illegal before a connection
    has been shadow-previewed at least once."""
    connection = _create_connection(admin, base_url="http://127.0.0.1:1/unused", mrn="MRN-LIFECYCLE-3")
    response = client.post(f"/admin/interop/connections/{connection['id']}/connect", headers=_auth(admin))
    assert response.status_code == 400, response.text


def test_disable_is_terminal_and_distinct_from_pause(admin):
    """§3.12 — disable is reachable from draft (a connection an admin
    decides never to use), and once disabled, no further lifecycle
    transition is legal without a fresh flow."""
    connection = _create_connection(admin, base_url="http://127.0.0.1:1/unused", mrn="MRN-LIFECYCLE-4")
    response = client.post(f"/admin/interop/connections/{connection['id']}/disable", headers=_auth(admin))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "disabled"
    assert response.json()["disabled_at"] is not None

    # Disabled is terminal — even re-discovering must be refused.
    redisc = client.post(f"/admin/interop/connections/{connection['id']}/discover", headers=_auth(admin))
    assert redisc.status_code == 400, redisc.text

    # And pausing an already-disabled connection is also illegal.
    repause = client.post(f"/admin/interop/connections/{connection['id']}/pause", headers=_auth(admin))
    assert repause.status_code == 400, repause.text


def test_full_pipeline_reaches_active_with_correct_lifecycle_states(admin, patient):
    """Walks discover -> test -> preview -> identity link -> connect and
    asserts the connection's status advances through the exact expected
    lifecycle states at each step (not just that the calls succeed)."""
    with SyntheticFhirServer("server_b") as server:
        connection = _create_connection(admin, base_url=server.base_url, mrn="MRN-B-2002")
        connection_id = connection["id"]
        assert connection["status"] == "draft"

        discover = client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin))
        assert discover.status_code == 200, discover.text
        after_discover = client.get(f"/admin/interop/connections/{connection_id}", headers=_auth(admin)).json()
        assert after_discover["status"] == "discovered"
        assert after_discover["capability_fingerprint"] is not None
        assert after_discover["consecutive_failures"] == 0

        test = client.post(f"/admin/interop/connections/{connection_id}/test", headers=_auth(admin))
        assert test.status_code == 200, test.text
        after_test = client.get(f"/admin/interop/connections/{connection_id}", headers=_auth(admin)).json()
        assert after_test["status"] == "validated"

        link = client.post(
            f"/admin/interop/connections/{connection_id}/identity/links",
            json={"patient_id": patient["patient_id"], "identifier_system": PATIENT_IDENTIFIER_SYSTEM, "identifier_value": "MRN-B-2002"},
            headers=_auth(admin),
        )
        assert link.status_code == 200, link.text

        preview = client.post(f"/admin/interop/connections/{connection_id}/preview", headers=_auth(admin))
        assert preview.status_code == 200, preview.text
        after_preview = client.get(f"/admin/interop/connections/{connection_id}", headers=_auth(admin)).json()
        assert after_preview["status"] == "shadow"

        connect = client.post(f"/admin/interop/connections/{connection_id}/connect", headers=_auth(admin))
        assert connect.status_code == 200, connect.text
        after_connect = client.get(f"/admin/interop/connections/{connection_id}", headers=_auth(admin)).json()
        assert after_connect["status"] == "active"


def test_breaking_capability_drift_degrades_active_connection(admin, patient):
    """§3.2 — re-discovering a connection that has become ACTIVE, against
    a server that has since lost a resource the first discovery saw, must
    mark it DEGRADED rather than silently continuing."""
    with SyntheticFhirServer("server_a") as server:
        connection = _create_connection(admin, base_url=server.base_url, mrn="MRN-A-1001")
        connection_id = connection["id"]
        assert client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin)).status_code == 200
        assert client.post(f"/admin/interop/connections/{connection_id}/test", headers=_auth(admin)).status_code == 200

        link = client.post(
            f"/admin/interop/connections/{connection_id}/identity/links",
            json={"patient_id": patient["patient_id"], "identifier_system": PATIENT_IDENTIFIER_SYSTEM, "identifier_value": "MRN-A-1001"},
            headers=_auth(admin),
        )
        assert link.status_code == 200, link.text
        assert client.post(f"/admin/interop/connections/{connection_id}/preview", headers=_auth(admin)).status_code == 200
        assert client.post(f"/admin/interop/connections/{connection_id}/connect", headers=_auth(admin)).status_code == 200
        assert client.get(f"/admin/interop/connections/{connection_id}", headers=_auth(admin)).json()["status"] == "active"

    # Server A is now stopped. Point the connection at Server B instead
    # (materially fewer resources/capabilities — a real breaking
    # regression from Server A's perspective) and re-discover.
    with SyntheticFhirServer("server_b") as server_b:
        client.patch(f"/admin/interop/connections/{connection_id}", json={"base_url": server_b.base_url}, headers=_auth(admin))
        redisc = client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin))
        assert redisc.status_code == 200, redisc.text
        assert redisc.json()["drift"]["breaking"] is True

    after = client.get(f"/admin/interop/connections/{connection_id}", headers=_auth(admin)).json()
    assert after["status"] == "degraded"

    # Recovery: a passing /test call moves it back to active.
    with SyntheticFhirServer("server_b") as server_b2:
        client.patch(f"/admin/interop/connections/{connection_id}", json={"base_url": server_b2.base_url}, headers=_auth(admin))
        recover = client.post(f"/admin/interop/connections/{connection_id}/test", headers=_auth(admin))
        assert recover.status_code == 200, recover.text
    recovered = client.get(f"/admin/interop/connections/{connection_id}", headers=_auth(admin)).json()
    assert recovered["status"] == "active"


def test_incremental_sync_cursor_persists_after_real_sync(admin, patient):
    """§3.3 — Server A advertises `_lastUpdated` support for Observation;
    after a real (connect) sync, the connection's per-resource cursor
    should be set."""
    with SyntheticFhirServer("server_a") as server:
        connection = _create_connection(admin, base_url=server.base_url, mrn="MRN-A-1001")
        connection_id = connection["id"]
        assert client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin)).status_code == 200
        assert client.post(f"/admin/interop/connections/{connection_id}/test", headers=_auth(admin)).status_code == 200
        link = client.post(
            f"/admin/interop/connections/{connection_id}/identity/links",
            json={"patient_id": patient["patient_id"], "identifier_system": PATIENT_IDENTIFIER_SYSTEM, "identifier_value": "MRN-A-1001"},
            headers=_auth(admin),
        )
        assert link.status_code == 200, link.text
        assert client.post(f"/admin/interop/connections/{connection_id}/preview", headers=_auth(admin)).status_code == 200
        connect = client.post(f"/admin/interop/connections/{connection_id}/connect", headers=_auth(admin))
        assert connect.status_code == 200, connect.text

    # sync_cursor_json isn't in the public serializer (internal state) —
    # verify it directly via the DB.
    from app import models
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(models.InteropConnection).filter(models.InteropConnection.id == connection_id).first()
        cursor = __import__("json").loads(row.sync_cursor_json or "{}")
        assert "Observation" in cursor
        assert cursor["Observation"]  # a real ISO timestamp string
    finally:
        db.close()


def test_pagination_loop_is_detected_not_followed_forever(admin, monkeypatch):
    """§3.4/§3.28 — a server serving the same `next` link forever must be
    detected and refused, not followed until MAX_PAGES silently caps it
    (which would still make MAX_PAGES real, slow requests to a
    misbehaving/malicious server first)."""
    from app.services.interop import fhir_connector
    from app import models as models_module

    call_count = {"n": 0}

    class _FakeResponse:
        status_code = 200

        def json(self):
            call_count["n"] += 1
            return {
                "resourceType": "Bundle",
                "entry": [],
                "link": [{"relation": "next", "url": "https://partner.example/Observation?page=loop"}],
            }

        @property
        def content(self):
            return b"{}"

    def _fake_request_with_retry(method, url, **kwargs):
        return _FakeResponse()

    monkeypatch.setattr(fhir_connector.resilience, "request_with_retry", _fake_request_with_retry)

    fake_connection = models_module.InteropConnection(allow_private_network=True)
    with pytest.raises(fhir_connector.ConnectorError, match="loop"):
        fhir_connector._fetch_bundle_pages("https://partner.example/Observation?page=1", fake_connection, {})
    # page=1 is fetched once, then page=loop is fetched once — the THIRD
    # attempt (page=loop again) is caught before ever making a request.
    # Two real fetches total, never MAX_PAGES (20).
    assert call_count["n"] == 2


def test_oversized_bundle_is_bounded_not_loaded_fully(admin, monkeypatch):
    """§3.4/§3.28 — a response bigger than MAX_SYNC_BYTES must be refused,
    never fully buffered/processed first."""
    from app.services.interop import fhir_connector
    from app import models as models_module

    class _FakeResponse:
        status_code = 200
        content = b"x" * (fhir_connector.MAX_SYNC_BYTES + 1)

        def json(self):
            return {"resourceType": "Bundle", "entry": [], "link": []}

    def _fake_request_with_retry(method, url, **kwargs):
        return _FakeResponse()

    monkeypatch.setattr(fhir_connector.resilience, "request_with_retry", _fake_request_with_retry)

    fake_connection = models_module.InteropConnection(allow_private_network=True)
    with pytest.raises(fhir_connector.ConnectorError, match="bounded response size"):
        fhir_connector._fetch_bundle_pages("https://partner.example/Observation", fake_connection, {})


def test_phi_never_appears_in_interop_metric_log_lines(admin, patient, capsys):
    """§3.13/§3.28 — operational metric lines produced by a real sync run
    (discover/test/preview/connect all touch this patient's data
    internally) must never contain their name/CNP/email — only
    connection_id and counts."""
    with SyntheticFhirServer("server_b") as server:
        connection = _create_connection(admin, base_url=server.base_url, mrn="MRN-B-2002")
        connection_id = connection["id"]
        client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin))
        client.post(f"/admin/interop/connections/{connection_id}/test", headers=_auth(admin))
        client.post(
            f"/admin/interop/connections/{connection_id}/identity/links",
            json={"patient_id": patient["patient_id"], "identifier_system": PATIENT_IDENTIFIER_SYSTEM, "identifier_value": "MRN-B-2002"},
            headers=_auth(admin),
        )
        client.post(f"/admin/interop/connections/{connection_id}/preview", headers=_auth(admin))
        client.post(f"/admin/interop/connections/{connection_id}/connect", headers=_auth(admin))

    captured = capsys.readouterr()
    for marker in (patient["user"]["email"], patient["user"]["full_name"], "MRN-B-2002"):
        assert marker not in captured.out, f"{marker!r} leaked into stdout"


def test_concurrent_sync_against_same_connection_is_refused(admin, patient):
    """§3.7 — two overlapping sync attempts against the SAME connection
    must not both proceed; the second one is refused (409), never queued
    silently or allowed to race the first."""
    from app.services.interop.concurrency import connection_sync_lock
    from app.db import SessionLocal

    with SyntheticFhirServer("server_b") as server:
        connection = _create_connection(admin, base_url=server.base_url, mrn="MRN-B-2002")
        connection_id = connection["id"]
        assert client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin)).status_code == 200

        # Hold the lock from a separate DB session, simulating another
        # worker's in-progress sync, then attempt a real request through
        # the API — it must be refused rather than proceeding concurrently.
        holder_db = SessionLocal()
        try:
            with connection_sync_lock(holder_db, connection_id):
                response = client.post(f"/admin/interop/connections/{connection_id}/test", headers=_auth(admin))
                assert response.status_code == 409, response.text
        finally:
            holder_db.close()

        # Lock released — the same call now succeeds normally.
        response = client.post(f"/admin/interop/connections/{connection_id}/test", headers=_auth(admin))
        assert response.status_code == 200, response.text
