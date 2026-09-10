"""CNP / direct-identifier minimization regression suite — Priority 1 and
Priority 10 of the security/GDPR follow-up round. See
BRAGI_SECURITY_GDPR_PLAN.md §8. Same DB-connectivity requirement/skip
behavior as test_idor_regression.py.
"""

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip(
        "DATABASE_URL not configured — this file needs real DB connectivity.",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"cnp-test-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"CNP Test {role}",
        "password": "TestPass123!",
        "role": role,
        **extra,
    }
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["access_token"], "user": data["user"], "email": email}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


CNP = "6000101999931"


@pytest.fixture
def patient_with_cnp():
    account = _signup("patient", cnp=CNP)
    yield account
    client.delete("/my/account", headers=_auth(account["token"]))


@pytest.fixture
def doctor():
    account = _signup("doctor")
    yield account
    client.delete("/my/account", headers=_auth(account["token"]))


@pytest.fixture
def admin():
    account = _signup("admin")
    yield account
    client.delete("/my/account", headers=_auth(account["token"]))


def _grant_doctor_access(patient_id: int, doctor_token: str) -> None:
    from app import models
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        access = models.DoctorPatientAccess(
            doctor_user_id=_current_user_id(doctor_token),
            patient_id=patient_id,
            granted_at="2026-01-01T00:00:00Z",
            is_active=1,
        )
        db.add(access)
        db.commit()
    finally:
        db.close()


def _current_user_id(token: str) -> int:
    response = client.get("/auth/me", headers=_auth(token))
    return response.json()["id"]


def _patient_id_for(token: str) -> int:
    response = client.get("/my/profile", headers=_auth(token))
    return response.json()["patient"]["id"]


# --- CNP must never travel in a URL query string ---------------------------


def test_emergency_search_get_rejects_cnp_query_param():
    emergency = _signup("emergency_worker")
    try:
        response = client.get("/emergency/search", params={"type": "cnp", "q": CNP}, headers=_auth(emergency["token"]))
        assert response.status_code == 400
        assert "POST" in response.json()["detail"]
    finally:
        client.delete("/my/account", headers=_auth(emergency["token"]))  # 403 expected, harmless


def test_emergency_search_get_still_allows_non_identifier_types():
    emergency = _signup("emergency_worker")
    response = client.get("/emergency/search", params={"type": "name", "q": "nonexistent-name-xyz"}, headers=_auth(emergency["token"]))
    assert response.status_code == 200


def test_emergency_search_post_allows_cnp_and_finds_the_patient(patient_with_cnp):
    # Enable emergency discoverability first (opt-in, existing feature).
    response = client.put(
        "/my/settings/emergency-access",
        json={"emergency_search_enabled": True},
        headers=_auth(patient_with_cnp["token"]),
    )
    assert response.status_code == 200, response.text

    emergency = _signup("emergency_worker")
    try:
        response = client.post(
            "/emergency/search",
            json={"type": "cnp", "q": CNP},
            headers=_auth(emergency["token"]),
        )
        assert response.status_code == 200, response.text
        results = response.json()
        assert len(results) == 1
        # The CNP-search functional path still works (patient found), and
        # the response itself only ever carries a masked identifier, never
        # the raw CNP — see _serialize_emergency_search_result.
        assert results[0]["masked_identifier"] is not None
        assert CNP not in str(results[0])
    finally:
        client.delete("/my/account", headers=_auth(emergency["token"]))  # 403, harmless


# --- CNP must be masked in list/search views ---------------------------------


def test_patients_list_masks_cnp_for_doctor(patient_with_cnp, doctor):
    patient_id = _patient_id_for(patient_with_cnp["token"])
    _grant_doctor_access(patient_id, doctor["token"])

    response = client.get("/patients", headers=_auth(doctor["token"]))
    assert response.status_code == 200
    row = next(p for p in response.json() if p["id"] == patient_id)
    assert row["cnp"] != CNP
    assert CNP not in (row["cnp"] or "")


def test_my_patients_masks_cnp_for_doctor(patient_with_cnp, doctor):
    patient_id = _patient_id_for(patient_with_cnp["token"])
    _grant_doctor_access(patient_id, doctor["token"])

    response = client.get("/my-patients", headers=_auth(doctor["token"]))
    assert response.status_code == 200
    row = next(p for p in response.json() if p["patient"]["id"] == patient_id)
    assert row["patient"]["cnp"] != CNP


def test_patients_search_masks_cnp_for_doctor(patient_with_cnp, doctor):
    response = client.get("/patients/search", params={"q": "CNP Test patient"}, headers=_auth(doctor["token"]))
    assert response.status_code == 200
    matches = [p for p in response.json() if p["id"] == _patient_id_for(patient_with_cnp["token"])]
    assert matches, "expected the synthetic patient to appear in search results"
    assert matches[0]["cnp"] != CNP


def test_admin_patients_search_masks_cnp(patient_with_cnp, admin):
    response = client.get("/admin/patients/search", params={"q": "CNP Test patient"}, headers=_auth(admin["token"]))
    assert response.status_code == 200
    matches = [p for p in response.json() if p["id"] == _patient_id_for(patient_with_cnp["token"])]
    assert matches, "expected the synthetic patient to appear in admin search results"
    assert matches[0]["cnp"] != CNP


def test_patient_documents_view_masks_cnp_for_doctor(patient_with_cnp, doctor):
    patient_id = _patient_id_for(patient_with_cnp["token"])
    _grant_doctor_access(patient_id, doctor["token"])

    response = client.get(f"/patients/{patient_id}/documents", headers=_auth(doctor["token"]))
    assert response.status_code == 200
    assert response.json()["patient"]["cnp"] != CNP


# --- Full CNP is still available where genuinely needed ---------------------


def test_patient_sees_own_full_cnp_on_my_profile(patient_with_cnp):
    response = client.get("/my/profile", headers=_auth(patient_with_cnp["token"]))
    assert response.status_code == 200
    assert response.json()["patient"]["cnp"] == CNP


def test_doctor_viewing_patient_profile_gets_masked_cnp_not_full(patient_with_cnp, doctor):
    patient_id = _patient_id_for(patient_with_cnp["token"])
    _grant_doctor_access(patient_id, doctor["token"])

    response = client.get(f"/patients/{patient_id}/profile", headers=_auth(doctor["token"]))
    assert response.status_code == 200
    assert response.json()["patient"]["cnp"] != CNP
