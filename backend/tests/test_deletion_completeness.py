"""Role deletion-completeness regression suite (DELETE /my/account across
roles) — see BRAGI_SECURITY_GDPR_PLAN.md §19/Priority 8 and
docs/privacy/DSAR_RUNBOOK.md.

Same DB-required convention as test_idor_regression.py (see that file's
docstring).
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

from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"deletion-test-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    password = "TestPass123!"
    payload = {
        "email": email,
        "full_name": f"Deletion Test {role}",
        "password": password,
        "role": role,
        **extra,
    }
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["access_token"], "user": data["user"], "email": email, "password": password}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_doctor_self_deletion_disables_login_and_token():
    account = _signup("doctor")
    user_id = account["user"]["id"]

    response = client.delete("/my/account", headers=_auth(account["token"]))
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": True}

    # The row still exists (soft delete) — direct DB check.
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        assert user is not None, "doctor row must survive its own soft-delete"
        assert user.deleted_at is not None
        assert user.email != account["email"], "email must be anonymized, not left as real PII"
    finally:
        db.close()

    # Old JWT no longer works.
    response = client.get("/auth/me", headers=_auth(account["token"]))
    assert response.status_code == 401

    # Old credentials no longer log in.
    response = client.post(
        "/auth/login", json={"email": account["email"], "password": account["password"]}
    )
    assert response.status_code == 401


def test_admin_self_deletion_disables_login_and_token():
    account = _signup("admin")
    response = client.delete("/my/account", headers=_auth(account["token"]))
    assert response.status_code == 200, response.text

    response = client.get("/auth/me", headers=_auth(account["token"]))
    assert response.status_code == 401

    response = client.post(
        "/auth/login", json={"email": account["email"], "password": account["password"]}
    )
    assert response.status_code == 401


def test_doctor_soft_deletion_ends_active_patient_access_no_500():
    patient = _signup("patient", cnp="6000101999921")
    doctor = _signup("doctor")

    # Grant access directly via the DB (the real access-request/approval
    # HTTP flow is already covered by test_idor_regression.py) — isolates
    # what THIS test actually checks: that deletion ends active grants
    # and never 500s.
    db = SessionLocal()
    try:
        patient_row = (
            db.query(models.Patient)
            .filter(models.Patient.linked_user_id == patient["user"]["id"])
            .first()
        )
        access = models.DoctorPatientAccess(
            doctor_user_id=doctor["user"]["id"],
            patient_id=patient_row.id,
            granted_at="2026-01-01T00:00:00Z",
            is_active=1,
        )
        db.add(access)
        db.commit()
        access_id = access.id
    finally:
        db.close()

    response = client.delete("/my/account", headers=_auth(doctor["token"]))
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        access = db.query(models.DoctorPatientAccess).filter(models.DoctorPatientAccess.id == access_id).first()
        assert access is not None, "the access grant row itself must survive (patient's own care history)"
        assert access.is_active == 0, "an active grant must be ended when the doctor deletes their account"
        assert access.ended_at is not None
    finally:
        db.close()

    # The patient's own document-list view must still work with no 500,
    # even though the doctor who once had access is now deactivated.
    patient_profile = client.get("/my/profile", headers=_auth(patient["token"]))
    assert patient_profile.status_code == 200

    client.delete("/my/account", headers=_auth(patient["token"]))


def test_care_partner_self_deletion_is_a_real_row_delete():
    patient = _signup("patient", cnp="6000101999922")
    code_response = client.get("/my/care-partner-code", headers=_auth(patient["token"]))
    assert code_response.status_code == 200, code_response.text
    code = code_response.json()["code"]

    care_partner = _signup("care_partner", care_partner_code=code)
    cp_user_id = care_partner["user"]["id"]

    db = SessionLocal()
    try:
        link_count_before = (
            db.query(models.CarePartnerPatientLink)
            .filter(models.CarePartnerPatientLink.care_partner_user_id == cp_user_id)
            .count()
        )
        assert link_count_before >= 1
    finally:
        db.close()

    response = client.delete("/my/account", headers=_auth(care_partner["token"]))
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == cp_user_id).first()
        assert user is None, "care_partner deletion must be a real row delete, not a soft-delete"
        remaining_links = (
            db.query(models.CarePartnerPatientLink)
            .filter(models.CarePartnerPatientLink.care_partner_user_id == cp_user_id)
            .count()
        )
        assert remaining_links == 0, "no orphaned CarePartnerPatientLink rows"
    finally:
        db.close()

    # Login must fail cleanly (401, not 500) — no orphaned FK anywhere
    # blocking downstream queries.
    response = client.post(
        "/auth/login", json={"email": care_partner["email"], "password": care_partner["password"]}
    )
    assert response.status_code == 401

    client.delete("/my/account", headers=_auth(patient["token"]))


def test_emergency_worker_self_deletion_not_offered():
    account = _signup("emergency_worker")
    response = client.delete("/my/account", headers=_auth(account["token"]))
    # Deliberate product/legal decision, not a bug — see
    # docs/privacy/DSAR_RUNBOOK.md. require_role() rejects it the same
    # way it would reject any role not in the allowed list: a clean 403,
    # never a 500 or a silent no-op.
    assert response.status_code == 403


def test_doctor_double_deletion_is_idempotent_no_500():
    account = _signup("doctor")
    first = client.delete("/my/account", headers=_auth(account["token"]))
    assert first.status_code == 200
    # The JWT is now rejected by get_current_user (deleted_at set), so a
    # second call with the same token must 401, not 500 — it can no
    # longer reach the deletion logic at all.
    second = client.delete("/my/account", headers=_auth(account["token"]))
    assert second.status_code == 401
