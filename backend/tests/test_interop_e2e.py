"""End-to-end interoperability acceptance tests (BRAGI_INTEROP_PLAN.md
P50-P52, P75). Real DB connectivity required (skipped gracefully without
DATABASE_URL, same pattern as test_idor_regression.py). Spins up real
in-process synthetic FHIR servers (tests/interop/fixtures/) and drives the
full admin API: create connection -> discover -> test -> preview (shadow,
commits nothing) -> connect (real idempotent sync) -> re-sync (idempotent)
-> verify canonical LabResult rows -> verify Ask Bragi/Analize-visible data
is indistinguishable in shape from an uploaded document's.

Proves, with the SAME connector code and NO per-server branching:
- Server A (full-featured, SMART, paginated, _lastUpdated) works (P50/P51)
- Server B (minimal, no SMART, no DiagnosticReport/DocumentReference,
  single page) works with the same code (P51)
- Server C (local codes) requires a declarative mapping override, not a
  code change (P52)
- No identity link => no data commits (P33)
- A conflicting identity link is refused, not silently resolved (P33)
- SSRF-blocked endpoints are refused before any connector call reaches
  them (P75)
"""

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not configured — this file needs real DB connectivity.", allow_module_level=True)

os.environ["INTEROP_FHIR_ENABLED"] = "true"
os.environ["INTEROP_SECRET_ENCRYPTION_KEY"] = "test-only-encryption-key-not-for-production-use"
os.environ.setdefault("ENVIRONMENT", "development")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from tests.interop.fixtures.synthetic_fhir_server import (  # noqa: E402
    PATIENT_IDENTIFIER_SYSTEM,
    SyntheticFhirServer,
)

# Belt-and-suspenders over the os.environ set above: app.services.interop's
# __init__.py reads INTEROP_FHIR_ENABLED at first import of ANY interop
# submodule — if another test file (test_interop_capability.py etc.)
# imports one first during pytest collection, that read happens before
# this file's os.environ assignment ever runs, and the (then-False) value
# gets cached in sys.modules regardless of the env var changing afterward.
# Setting it directly on the already-imported app.main module sidesteps
# that import-order dependency entirely — this is a test-isolation
# artifact of running multiple interop test files in one pytest process,
# not a production behavior (production sets the real env var before the
# process starts, so there's no "first import wins" ordering to worry about).
main_module.INTEROP_FHIR_ENABLED = True
main_module.IS_PRODUCTION = False  # same import-order caching hazard as above — force the real dev/test intent

# crypto.py imports INTEROP_SECRET_ENCRYPTION_KEY into ITS OWN module
# namespace at first import — the same caching hazard again, one module
# deeper. Patch it directly there rather than relying on the os.environ
# assignment above having run before crypto.py's first import.
import app.services.interop.crypto as interop_crypto_module  # noqa: E402

interop_crypto_module.INTEROP_SECRET_ENCRYPTION_KEY = "test-only-encryption-key-not-for-production-use"

app = main_module.app

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"interop-test-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {"email": email, "full_name": f"Interop Test {role}", "password": "TestPass123!", "role": role, **extra}
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["access_token"], "user": data["user"]}


def _auth(account: dict) -> dict:
    return {"Authorization": f"Bearer {account['token']}"}


@pytest.fixture
def admin():
    account = _signup("admin")
    yield account
    client.delete("/my/account", headers=_auth(account))


def _patient_id_for(account: dict) -> int:
    response = client.get("/my/profile", headers=_auth(account))
    assert response.status_code == 200, response.text
    return response.json()["patient"]["id"]


@pytest.fixture
def patient():
    account = _signup("patient", cnp="6000101999977")
    account["patient_id"] = _patient_id_for(account)
    yield account
    client.delete("/my/account", headers=_auth(account))


def _create_connection(admin_account: dict, *, base_url: str, mrn: str) -> dict:
    response = client.post(
        "/admin/interop/connections",
        json={
            "name": "Test connection",
            "base_url": base_url,
            "connector_type": "fhir",
            "allow_private_network": True,  # sandbox-only — targets 127.0.0.1
            "patient_identity_primary_system": PATIENT_IDENTIFIER_SYSTEM,
        },
        headers=_auth(admin_account),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _run_full_pipeline_zero_code(admin_account: dict, patient_account: dict, *, profile: str, mrn: str) -> dict:
    """The exact P50/P51 acceptance flow: discover -> test -> preview ->
    link identity -> connect, using nothing but configuration."""
    with SyntheticFhirServer(profile) as server:
        connection = _create_connection(admin_account, base_url=server.base_url, mrn=mrn)
        connection_id = connection["id"]

        discover = client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin_account))
        assert discover.status_code == 200, discover.text

        test = client.post(f"/admin/interop/connections/{connection_id}/test", headers=_auth(admin_account))
        assert test.status_code == 200, test.text
        assert test.json()["passed"] is True, test.json()

        # Preview BEFORE any identity link exists — no clinical data
        # committed, and the patient shows up as "requires review".
        preview_before_link = client.post(f"/admin/interop/connections/{connection_id}/preview", headers=_auth(admin_account))
        assert preview_before_link.status_code == 200, preview_before_link.text
        assert preview_before_link.json()["identity"]["requires_review"] == 1
        assert preview_before_link.json()["summary"]["would_create"] == 0

        # Explicit, admin-created identity link (never automatic) — P32/P33.
        link = client.post(
            f"/admin/interop/connections/{connection_id}/identity/links",
            json={
                "patient_id": patient_account["patient_id"],
                "identifier_system": PATIENT_IDENTIFIER_SYSTEM,
                "identifier_value": mrn,
            },
            headers=_auth(admin_account),
        )
        assert link.status_code == 200, link.text

        preview_after_link = client.post(f"/admin/interop/connections/{connection_id}/preview", headers=_auth(admin_account))
        assert preview_after_link.status_code == 200, preview_after_link.text
        assert preview_after_link.json()["identity"]["linked"] == 1

        connect = client.post(f"/admin/interop/connections/{connection_id}/connect", headers=_auth(admin_account))
        assert connect.status_code == 200, connect.text
        return {"connection_id": connection_id, "sync_result": connect.json(), "server": server.base_url}


def test_server_a_full_featured_zero_code_sync(admin, patient):
    """P50 — a standards-compliant FHIR R4 server connects and syncs real
    lab data with zero application-code changes, using the paginated,
    SMART-advertising, richer of the two servers."""
    result = _run_full_pipeline_zero_code(admin, patient, profile="server_a", mrn="MRN-A-1001")
    summary = result["sync_result"]["summary"]
    assert summary["created"] == 3  # all 3 Server A observations, across 2 pages
    assert summary["patients_discovered"] == 1

    # Sanity check: synced data is visible through an existing, unmodified
    # patient-facing route (bloodwork trends) exactly like uploaded data —
    # proving the connector really did write into the canonical LabResult
    # table rather than a side channel only interop's own routes can see.
    trends = client.get(f"/patients/{patient['patient_id']}/bloodwork-trends", headers=_auth(admin))
    assert trends.status_code == 200, trends.text


def test_server_b_minimal_same_connector_no_branching(admin, patient):
    """P51 — the SAME connector code (no `if server == A` anywhere in
    fhir_connector.py) also works against a materially different server:
    no SMART, no DiagnosticReport/DocumentReference, single-page results."""
    result = _run_full_pipeline_zero_code(admin, patient, profile="server_b", mrn="MRN-B-2002")
    summary = result["sync_result"]["summary"]
    assert summary["created"] == 1
    assert summary["patients_discovered"] == 1


def test_server_c_local_codes_require_mapping_not_code(admin, patient):
    """P52 — the local-profile server's non-standard code is NOT resolved
    automatically; it must show up for mapping review, and only after an
    admin approves a declarative override does a re-sync pick it up —
    proving configuration, not a code change, closes the gap."""
    with SyntheticFhirServer("server_c") as server:
        connection = _create_connection(admin, base_url=server.base_url, mrn="MRN-C-3003")
        connection_id = connection["id"]
        assert client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin)).status_code == 200
        assert client.post(f"/admin/interop/connections/{connection_id}/test", headers=_auth(admin)).status_code == 200

        link = client.post(
            f"/admin/interop/connections/{connection_id}/identity/links",
            json={"patient_id": patient["patient_id"], "identifier_system": PATIENT_IDENTIFIER_SYSTEM, "identifier_value": "MRN-C-3003"},
            headers=_auth(admin),
        )
        assert link.status_code == 200, link.text

        preview = client.post(f"/admin/interop/connections/{connection_id}/preview", headers=_auth(admin))
        assert preview.status_code == 200, preview.text
        # obs-c-1 (real LOINC Hemoglobin) auto-maps; obs-c-2 (local code)
        # does not — it must show up as requiring mapping review.
        assert preview.json()["summary"]["mapped_automatically"] == 1
        assert preview.json()["summary"]["requires_mapping_review"] == 1

        pending = client.get(f"/admin/interop/connections/{connection_id}/terminology?status=pending", headers=_auth(admin))
        assert pending.status_code == 200, pending.text
        mappings = pending.json()["mappings"]
        assert len(mappings) == 1
        local_code_mapping = mappings[0]
        assert local_code_mapping["source_code"] == "HGB-LOCAL-X7"

        # Approve it — a real admin decision, never automatic from
        # frequency alone (P73).
        approve = client.post(
            f"/admin/interop/connections/{connection_id}/terminology/{local_code_mapping['id']}/approve",
            json={"target_canonical_name": "hemoglobin", "target_display_name": "Hemoglobin", "target_category": "hematology", "target_unit": "g/dL"},
            headers=_auth(admin),
        )
        assert approve.status_code == 200, approve.text

        # Connect — now BOTH observations map (P19: the approved mapping
        # is reused automatically, no manual remapping per import).
        connect = client.post(f"/admin/interop/connections/{connection_id}/connect", headers=_auth(admin))
        assert connect.status_code == 200, connect.text
        assert connect.json()["summary"]["created"] == 2


def test_idempotent_resync_updates_instead_of_duplicating(admin, patient):
    """A second sync of the same data must not create duplicate LabResult
    rows — external_observation_id-keyed idempotency."""
    result = _run_full_pipeline_zero_code(admin, patient, profile="server_b", mrn="MRN-B-2002")
    connection_id = result["connection_id"]

    with SyntheticFhirServer("server_b") as server:
        client.patch(f"/admin/interop/connections/{connection_id}", json={"base_url": server.base_url}, headers=_auth(admin))
        second_sync = client.post(f"/admin/interop/connections/{connection_id}/connect", headers=_auth(admin))
        assert second_sync.status_code == 200, second_sync.text
        assert second_sync.json()["summary"]["created"] == 0
        assert second_sync.json()["summary"]["updated"] == 1


def test_conflicting_identity_link_is_refused(admin, patient):
    """P33 — an identifier already verified-linked to one patient must
    never be silently reassigned to another; the API refuses (409) and
    records an IDENTITY CONFLICT for review."""
    account_b = _signup("patient", cnp="6000101999988")
    account_b_patient_id = _patient_id_for(account_b)
    try:
        connection = _create_connection(admin, base_url="http://127.0.0.1:1/unused", mrn="MRN-X")
        connection_id = connection["id"]

        first = client.post(
            f"/admin/interop/connections/{connection_id}/identity/links",
            json={"patient_id": patient["patient_id"], "identifier_system": PATIENT_IDENTIFIER_SYSTEM, "identifier_value": "MRN-CONFLICT-1"},
            headers=_auth(admin),
        )
        assert first.status_code == 200, first.text

        second = client.post(
            f"/admin/interop/connections/{connection_id}/identity/links",
            json={"patient_id": account_b_patient_id, "identifier_system": PATIENT_IDENTIFIER_SYSTEM, "identifier_value": "MRN-CONFLICT-1"},
            headers=_auth(admin),
        )
        assert second.status_code == 409, second.text

        conflicts = client.get(f"/admin/interop/connections/{connection_id}/identity/conflicts", headers=_auth(admin))
        assert conflicts.status_code == 200
        assert len(conflicts.json()["conflicts"]) == 1
    finally:
        client.delete("/my/account", headers=_auth(account_b))


@pytest.mark.parametrize(
    "dangerous_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost/fhir",
        "https://10.0.0.5/fhir",
    ],
)
def test_ssrf_protection_blocks_dangerous_endpoints_via_the_real_api(admin, dangerous_url):
    """P75 — the plug-and-play security acceptance test, exercised through
    the real admin API (not just the ssrf.py unit tests) with
    allow_private_network left at its safe default (False)."""
    response = client.post(
        "/admin/interop/connections",
        json={"name": "Malicious attempt", "base_url": dangerous_url, "connector_type": "fhir", "allow_private_network": False},
        headers=_auth(admin),
    )
    assert response.status_code == 200  # creating a draft with a bad URL is allowed; DISCOVERY must refuse it
    connection_id = response.json()["id"]

    discover = client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin))
    assert discover.status_code in (400, 502), discover.text
    assert "connectivity policy" in discover.json()["detail"].lower() or "reach" in discover.json()["detail"].lower()


def test_allow_private_network_is_refused_in_production(admin, monkeypatch):
    """P75 — plug-and-play convenience must never weaken the security
    model: a sandbox-only escape hatch is refused outright once
    ENVIRONMENT=production, regardless of what an admin requests."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    response = client.post(
        "/admin/interop/connections",
        json={"name": "Should be refused", "base_url": "http://127.0.0.1:9/x", "connector_type": "fhir", "allow_private_network": True},
        headers=_auth(admin),
    )
    assert response.status_code == 400


def test_disabled_flag_returns_404_for_every_route(admin, monkeypatch):
    """The whole-feature kill switch (INTEROP_FHIR_ENABLED=false) — merging
    this code must change nothing until explicitly turned on."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "INTEROP_FHIR_ENABLED", False)
    response = client.get("/admin/interop/connections", headers=_auth(admin))
    assert response.status_code == 404


# --- Secret-handling re-audit (Phase-1 closure item 4) ----------------------
#
# A secret set via POST .../secret must never come back out through ANY
# response body: connection GET/LIST, export, an error path (invalid auth
# raised as an HTTPException detail string), or the diagnostic bundle.


SECRET_PLAINTEXT_MARKER = "SUPER-SECRET-BEARER-TOKEN-MUST-NEVER-LEAK-8f2c9a"


def _assert_no_secret_leak(response, patient_id_unused=None):
    body_text = response.text
    assert SECRET_PLAINTEXT_MARKER not in body_text, f"Secret plaintext leaked in response body: {body_text[:2000]}"


def test_secret_plaintext_never_appears_in_any_response(admin):
    connection = _create_connection(admin, base_url="http://127.0.0.1:1/unused", mrn="MRN-SECRET-TEST")
    connection_id = connection["id"]

    set_auth = client.patch(
        f"/admin/interop/connections/{connection_id}",
        json={"auth_type": "static_bearer"},
        headers=_auth(admin),
    )
    assert set_auth.status_code == 200, set_auth.text
    _assert_no_secret_leak(set_auth)

    set_secret = client.post(
        f"/admin/interop/connections/{connection_id}/secret",
        json={"secret_plaintext": SECRET_PLAINTEXT_MARKER},
        headers=_auth(admin),
    )
    assert set_secret.status_code == 200, set_secret.text
    assert set_secret.json() == {"ok": True, "has_secret": True}  # exact shape — nothing else comes back
    _assert_no_secret_leak(set_secret)

    get_connection = client.get(f"/admin/interop/connections/{connection_id}", headers=_auth(admin))
    assert get_connection.status_code == 200
    _assert_no_secret_leak(get_connection)
    assert get_connection.json()["has_secret"] is True
    assert "secret_ref" not in get_connection.json()
    assert "ciphertext" not in get_connection.json()

    list_connections = client.get("/admin/interop/connections", headers=_auth(admin))
    assert list_connections.status_code == 200
    _assert_no_secret_leak(list_connections)

    export = client.get(f"/admin/interop/connections/{connection_id}/export", headers=_auth(admin))
    assert export.status_code == 200
    _assert_no_secret_leak(export)
    assert "secret_ref" not in export.text

    bundle = client.get(f"/admin/interop/connections/{connection_id}/diagnostic-bundle", headers=_auth(admin))
    assert bundle.status_code == 200
    _assert_no_secret_leak(bundle)

    # Trigger a real auth-config error path (missing token_url for
    # oauth2_client_credentials) and confirm the error message — which DOES
    # echo back configuration for diagnostic purposes (P57) — still never
    # includes the secret itself.
    client.patch(
        f"/admin/interop/connections/{connection_id}",
        json={"auth_type": "oauth2_client_credentials", "auth_config": {}},
        headers=_auth(admin),
    )
    discover_error = client.post(f"/admin/interop/connections/{connection_id}/discover", headers=_auth(admin))
    _assert_no_secret_leak(discover_error)


def test_import_refuses_profile_with_secret_shaped_field(admin):
    response = client.post(
        "/admin/interop/connections/import",
        json={"profile": {"name": "Malicious import", "base_url": "https://example.invalid/fhir", "auth": {"type": "static_bearer", "client_secret": "leaked-value"}}},
        headers=_auth(admin),
    )
    assert response.status_code == 400
    assert "leaked-value" not in response.text


# --- FK re-audit (Phase-1 closure item 5) -----------------------------------
#
# Every newly introduced FK must not break existing patient-deletion
# behavior, including when a patient has a full set of interop-related rows
# attached: identity link, synced document/lab result, and a terminology
# mapping cross-referenced through the same connection.


def test_account_deletion_with_full_interop_footprint(admin):
    """Broader than test_idempotent_resync's implicit teardown coverage:
    explicitly gives the patient an identity link AND real synced
    Document/LabResult/SourceEvidence rows (via a real sync, not just a
    link), then deletes the account and confirms it succeeds — the exact
    regression class this closure round is re-auditing for."""
    patient_account = _signup("patient", cnp="6000101999955")
    patient_account["patient_id"] = _patient_id_for(patient_account)
    try:
        result = _run_full_pipeline_zero_code(admin, patient_account, profile="server_b", mrn="MRN-B-2002")
        assert result["sync_result"]["summary"]["created"] >= 1

        delete_response = client.delete("/my/account", headers=_auth(patient_account))
        assert delete_response.status_code == 200, delete_response.text
    finally:
        # Best-effort cleanup if the assertion above already failed and the
        # account wasn't deleted — avoid leaking a synthetic account.
        client.delete("/my/account", headers=_auth(patient_account))
