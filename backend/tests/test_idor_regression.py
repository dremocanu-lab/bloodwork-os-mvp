"""Permanent IDOR / cross-patient authorization regression suite (see
BRAGI_SECURITY_GDPR_PLAN.md and docs/security/AUTHORIZATION_MATRIX.md).

Like test_security_headers.py, this needs real DB connectivity (skipped
gracefully without DATABASE_URL — see that file's docstring for why) and
creates/deletes real synthetic accounts and a real document against
whatever database DATABASE_URL points at. Never run this against a
database that could contain real PHI — dev/CI only. Every account/document
this file creates is deleted in a fixture teardown, but a mid-run crash
could leave synthetic (non-PHI, clearly-named `idor-test-*@example.com`)
rows behind — safe to delete by hand if that ever happens.
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
    # example.com (RFC 2606) is accepted by email-validator; bragi.test's
    # .test TLD is flagged as a reserved/special-use domain and rejected.
    return f"idor-test-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"IDOR Test {role}",
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


def _delete_account(token: str):
    client.delete("/my/account", headers=_auth(token))


@pytest.fixture
def patient_a():
    account = _signup("patient", cnp="6000101999901")
    yield account
    _delete_account(account["token"])


@pytest.fixture
def patient_b():
    account = _signup("patient", cnp="6000101999902")
    yield account
    _delete_account(account["token"])


@pytest.fixture
def doctor_a():
    account = _signup("doctor")
    yield account
    # DELETE /my/account now exists for doctors (see
    # test_deletion_completeness.py) — it's a soft-delete (row persists,
    # deactivated) rather than a hard delete, so this just anonymizes the
    # synthetic account's email/password rather than removing the row;
    # still synthetic/non-PHI and clearly labeled either way.
    _delete_account(account["token"])


def _patient_id_for(token: str) -> int:
    response = client.get("/my/profile", headers=_auth(token))
    assert response.status_code == 200, response.text
    return response.json()["patient"]["id"]


# --- Unauthenticated access -------------------------------------------------


def test_unauthenticated_request_rejected():
    response = client.get("/patients/1/profile")
    assert response.status_code == 401


def test_malformed_token_rejected():
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


# --- Cross-patient IDOR ------------------------------------------------------


def test_patient_cannot_read_another_patients_profile(patient_a, patient_b):
    patient_b_id = _patient_id_for(patient_b["token"])
    response = client.get(f"/patients/{patient_b_id}/profile", headers=_auth(patient_a["token"]))
    assert response.status_code == 403


def test_patient_cannot_list_another_patients_documents(patient_a, patient_b):
    patient_b_id = _patient_id_for(patient_b["token"])
    response = client.get(f"/patients/{patient_b_id}/documents", headers=_auth(patient_a["token"]))
    assert response.status_code == 403


def test_patient_cannot_read_another_patients_bloodwork_trends(patient_a, patient_b):
    patient_b_id = _patient_id_for(patient_b["token"])
    response = client.get(
        f"/patients/{patient_b_id}/bloodwork-trends", headers=_auth(patient_a["token"])
    )
    assert response.status_code == 403


def test_nonexistent_document_is_404_not_500_or_leak():
    # Any authenticated user, arbitrary/guessed document id — must never
    # succeed and must never distinguish "exists but forbidden" from
    # "doesn't exist" in a way that helps enumerate real document ids.
    account = _signup("patient")
    try:
        response = client.get("/documents/999999999", headers=_auth(account["token"]))
        assert response.status_code == 404
    finally:
        _delete_account(account["token"])


# --- Doctor assignment scope + revocation -----------------------------------


def test_unassigned_doctor_cannot_access_patient(patient_a, doctor_a):
    patient_a_id = _patient_id_for(patient_a["token"])
    response = client.get(f"/patients/{patient_a_id}/documents", headers=_auth(doctor_a["token"]))
    assert response.status_code == 403


def test_revoked_doctor_access_is_denied_immediately(patient_a, doctor_a):
    patient_a_id = _patient_id_for(patient_a["token"])
    doctor_user_id = doctor_a["user"]["id"]

    # Patient grants access directly (request/approve flow) via the admin-
    # style direct grant is not exposed to patients; use the doctor access
    # request + a patient never approves) — instead, exercise the exact
    # code path this test cares about (an existing DoctorPatientAccess row
    # with is_active flipped to 0) using the DB directly, matching how
    # main.py's own revoke/end-assignment endpoints do it — see
    # can_access_patient's is_active filter.
    from app.db import SessionLocal
    from app import models

    db = SessionLocal()
    try:
        db.add(
            models.DoctorPatientAccess(
                doctor_user_id=doctor_user_id,
                patient_id=patient_a_id,
                granted_by_user_id=patient_a["user"]["id"],
                granted_at="2026-01-01T00:00:00+00:00",
                is_active=1,
            )
        )
        db.commit()
    finally:
        db.close()

    # Active: doctor can see the patient in their list and access documents.
    response = client.get(f"/patients/{patient_a_id}/documents", headers=_auth(doctor_a["token"]))
    assert response.status_code == 200
    response = client.get("/my-patients", headers=_auth(doctor_a["token"]))
    assert response.status_code == 200
    assert any(p.get("patient", {}).get("id") == patient_a_id for p in response.json())

    # Revoke.
    db = SessionLocal()
    try:
        db.query(models.DoctorPatientAccess).filter(
            models.DoctorPatientAccess.doctor_user_id == doctor_user_id,
            models.DoctorPatientAccess.patient_id == patient_a_id,
        ).update({"is_active": 0})
        db.commit()
    finally:
        db.close()

    # Revoked: both the detail route AND the list route must reflect it
    # immediately (see the is_active fix in /patients and /my-patients —
    # this is the exact regression this test guards).
    response = client.get(f"/patients/{patient_a_id}/documents", headers=_auth(doctor_a["token"]))
    assert response.status_code == 403
    response = client.get("/my-patients", headers=_auth(doctor_a["token"]))
    assert response.status_code == 200
    assert not any(p.get("patient", {}).get("id") == patient_a_id for p in response.json())


# --- Care partner scope ------------------------------------------------------


def _care_partner_code_for(patient_token: str) -> str:
    response = client.get("/my/care-partner-code", headers=_auth(patient_token))
    assert response.status_code == 200, response.text
    return response.json()["code"]


def test_care_partner_cannot_access_raw_file_even_for_a_real_document_id(patient_a):
    # A care_partner is unconditionally denied /documents/{id}/file for a
    # REAL document (a nonexistent id would 404 before the role check ever
    # runs — see get_document_file's check order — which is also secure,
    # but doesn't exercise the role-based denial this test is actually
    # for). Insert a minimal real Document row directly rather than going
    # through the full upload/extraction pipeline, to keep this test fast
    # and deterministic — it's the authorization check being tested, not
    # ingestion.
    from datetime import datetime, timezone

    from app.db import SessionLocal
    from app import models

    patient_a_id = _patient_id_for(patient_a["token"])
    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_a_id,
            uploaded_by_user_id=patient_a["user"]["id"],
            section="bloodwork",
            filename="idor-test.pdf",
            content_type="application/pdf",
            saved_to="idor-test-nonexistent-on-disk.pdf",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        document_id = doc.id
    finally:
        db.close()

    code = _care_partner_code_for(patient_a["token"])
    account = _signup("care_partner", care_partner_code=code)
    response = client.get(f"/documents/{document_id}/file", headers=_auth(account["token"]))
    assert response.status_code == 403

    db = SessionLocal()
    try:
        db.query(models.Document).filter(models.Document.id == document_id).delete()
        db.commit()
    finally:
        db.close()


def test_care_partner_has_no_general_patient_access(patient_a):
    code = _care_partner_code_for(patient_a["token"])
    account = _signup("care_partner", care_partner_code=code)
    patient_a_id = _patient_id_for(patient_a["token"])
    response = client.get(f"/patients/{patient_a_id}/documents", headers=_auth(account["token"]))
    assert response.status_code == 403
