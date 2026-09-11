"""Ask Bragi security regression suite — the highest-priority tests for
this feature (see BRAGI_ASK_BRAGI_PLAN.md's security model). Same
DB-connectivity requirement/skip behavior as test_idor_regression.py.

Deliberately does NOT call the real OpenAI API (these are authorization/
IDOR tests, not model-behavior tests — see test_ask_bragi_service.py for
mocked-model tests and the live-eval script for real API verification).
Feature-flag tests monkeypatch ASK_BRAGI_ENABLED directly since the real
env var is (correctly) unset in this test environment.
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

from app import main as app_main  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"askbragi-sec-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"AskBragi Sec Test {role}",
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


def _patient_id_for(token: str) -> int:
    response = client.get("/my/profile", headers=_auth(token))
    assert response.status_code == 200, response.text
    return response.json()["patient"]["id"]


@pytest.fixture(autouse=True)
def _enable_ask_bragi(monkeypatch):
    # Real activation is an env var this test environment correctly
    # doesn't set (see docs — production stays off unless explicitly
    # enabled). These tests exist to verify the AUTHORIZATION architecture
    # holds when it IS enabled, so flip the flag for this file only.
    monkeypatch.setattr(app_main, "ASK_BRAGI_ENABLED", True)
    yield


@pytest.fixture
def patient_a():
    account = _signup("patient", cnp="6000101999941")
    yield account
    client.delete("/my/account", headers=_auth(account["token"]))


@pytest.fixture
def patient_b():
    account = _signup("patient", cnp="6000101999942")
    yield account
    client.delete("/my/account", headers=_auth(account["token"]))


@pytest.fixture
def doctor_a():
    account = _signup("doctor")
    yield account
    client.delete("/my/account", headers=_auth(account["token"]))


def _grant_doctor_access(patient_id: int, doctor_user_id: int) -> None:
    from app import models
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        access = models.DoctorPatientAccess(
            doctor_user_id=doctor_user_id,
            patient_id=patient_id,
            granted_at="2026-01-01T00:00:00Z",
            is_active=1,
        )
        db.add(access)
        db.commit()
    finally:
        db.close()


def _revoke_doctor_access(patient_id: int, doctor_user_id: int) -> None:
    from app import models
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        db.query(models.DoctorPatientAccess).filter(
            models.DoctorPatientAccess.patient_id == patient_id,
            models.DoctorPatientAccess.doctor_user_id == doctor_user_id,
        ).update({"is_active": 0})
        db.commit()
    finally:
        db.close()


# --- Feature flag ------------------------------------------------------------


def test_feature_flag_off_rejects_conversation_creation(patient_a, monkeypatch):
    monkeypatch.setattr(app_main, "ASK_BRAGI_ENABLED", False)
    response = client.post("/ask-bragi/conversations", json={}, headers=_auth(patient_a["token"]))
    assert response.status_code == 404


# --- Conversation creation: server owns patient scope ------------------------


def test_patient_conversation_is_scoped_to_own_patient_id_regardless_of_body(patient_a):
    own_patient_id = _patient_id_for(patient_a["token"])
    # Even if a patient tries to supply a patient_id in the body, the
    # server ignores it and resolves their own — there is no way for a
    # patient-role caller to point a conversation at anyone else.
    response = client.post(
        "/ask-bragi/conversations", json={"patient_id": 999999}, headers=_auth(patient_a["token"])
    )
    assert response.status_code == 200, response.text
    assert response.json()["patient_id"] == own_patient_id


def test_doctor_without_access_cannot_create_conversation_for_patient(patient_a, doctor_a):
    patient_id = _patient_id_for(patient_a["token"])
    response = client.post(
        "/ask-bragi/conversations", json={"patient_id": patient_id}, headers=_auth(doctor_a["token"])
    )
    assert response.status_code == 403


def test_doctor_with_access_can_create_conversation(patient_a, doctor_a):
    patient_id = _patient_id_for(patient_a["token"])
    _grant_doctor_access(patient_id, doctor_a["user"]["id"])
    response = client.post(
        "/ask-bragi/conversations", json={"patient_id": patient_id}, headers=_auth(doctor_a["token"])
    )
    assert response.status_code == 200, response.text
    assert response.json()["patient_id"] == patient_id


def test_doctor_conversation_requires_a_patient_id(doctor_a):
    response = client.post("/ask-bragi/conversations", json={}, headers=_auth(doctor_a["token"]))
    assert response.status_code == 403


def test_care_partner_and_admin_cannot_create_conversations(patient_a):
    code_response = client.get("/my/care-partner-code", headers=_auth(patient_a["token"]))
    assert code_response.status_code == 200, code_response.text
    code = code_response.json()["code"]

    care_partner = _signup("care_partner", care_partner_code=code)
    try:
        response = client.post("/ask-bragi/conversations", json={}, headers=_auth(care_partner["token"]))
        assert response.status_code == 403
    finally:
        client.delete("/my/account", headers=_auth(care_partner["token"]))

    admin = _signup("admin")
    try:
        response = client.post(
            "/ask-bragi/conversations", json={"patient_id": 1}, headers=_auth(admin["token"])
        )
        assert response.status_code == 403
    finally:
        client.delete("/my/account", headers=_auth(admin["token"]))


# --- Conversation ID is not authorization ------------------------------------


def test_conversation_id_guessing_across_patients_is_denied(patient_a, patient_b):
    resp_a = client.post("/ask-bragi/conversations", json={}, headers=_auth(patient_a["token"]))
    conversation_id = resp_a.json()["id"]

    # Patient B guesses/enumerates patient A's real conversation id.
    response = client.get(f"/ask-bragi/conversations/{conversation_id}", headers=_auth(patient_b["token"]))
    assert response.status_code == 404  # not 403 — no existence leak, matches this app's IDOR convention

    response = client.post(
        f"/ask-bragi/conversations/{conversation_id}/messages",
        json={"message": "hello"},
        headers=_auth(patient_b["token"]),
    )
    assert response.status_code == 404

    response = client.delete(f"/ask-bragi/conversations/{conversation_id}", headers=_auth(patient_b["token"]))
    assert response.status_code == 404


def test_nonexistent_conversation_id_is_404():
    account = _signup("patient")
    response = client.get("/ask-bragi/conversations/99999999", headers=_auth(account["token"]))
    assert response.status_code == 404
    client.delete("/my/account", headers=_auth(account["token"]))


def test_unassigned_doctor_cannot_read_another_doctors_conversation(patient_a, doctor_a):
    patient_id = _patient_id_for(patient_a["token"])
    _grant_doctor_access(patient_id, doctor_a["user"]["id"])
    resp = client.post("/ask-bragi/conversations", json={"patient_id": patient_id}, headers=_auth(doctor_a["token"]))
    conversation_id = resp.json()["id"]

    other_doctor = _signup("doctor")
    try:
        response = client.get(f"/ask-bragi/conversations/{conversation_id}", headers=_auth(other_doctor["token"]))
        assert response.status_code == 404
    finally:
        client.delete("/my/account", headers=_auth(other_doctor["token"]))


# --- Revoked access mid-conversation must fail the very next request --------


def test_revoked_doctor_access_denies_the_next_message(patient_a, doctor_a):
    patient_id = _patient_id_for(patient_a["token"])
    doctor_user_id = doctor_a["user"]["id"]
    _grant_doctor_access(patient_id, doctor_user_id)

    resp = client.post("/ask-bragi/conversations", json={"patient_id": patient_id}, headers=_auth(doctor_a["token"]))
    assert resp.status_code == 200, resp.text
    conversation_id = resp.json()["id"]

    # Access is revoked after the conversation already exists.
    _revoke_doctor_access(patient_id, doctor_user_id)

    response = client.get(f"/ask-bragi/conversations/{conversation_id}", headers=_auth(doctor_a["token"]))
    assert response.status_code == 403

    response = client.post(
        f"/ask-bragi/conversations/{conversation_id}/messages",
        json={"message": "What are the latest labs?"},
        headers=_auth(doctor_a["token"]),
    )
    assert response.status_code == 403


# --- Tool-level re-authorization (defense in depth even past the route gate) -


def test_tool_dispatch_reraises_on_revoked_access(patient_a, doctor_a):
    from app.services.ask_bragi.context import AskBragiAccessDenied, AskBragiContext
    from app.services.ask_bragi.tools import run_tool
    from app.db import SessionLocal

    patient_id = _patient_id_for(patient_a["token"])
    doctor_user_id = doctor_a["user"]["id"]
    _grant_doctor_access(patient_id, doctor_user_id)

    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=patient_id,
            requester_user_id=doctor_user_id,
            requester_role="doctor",
            scope="patient_record",
        )
        # Works while access is active.
        run_tool(ctx, "get_patient_context", {})

        _revoke_doctor_access(patient_id, doctor_user_id)

        with pytest.raises(AskBragiAccessDenied):
            run_tool(ctx, "get_patient_context", {})
    finally:
        db.close()


# --- Document scope is enforced, never silently broadened --------------------


def test_document_scope_conversation_cannot_be_created_for_foreign_document(patient_a, patient_b):
    from app import models
    from app.db import SessionLocal

    patient_b_id = _patient_id_for(patient_b["token"])
    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_b_id,
            section="other",
            filename="b_report.txt",
            created_at="2026-01-01T00:00:00Z",
            is_verified=False,
            public_id="brg-doc-askbragi-sec-test",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id
    finally:
        db.close()

    try:
        # Patient A tries to scope a conversation to patient B's document.
        response = client.post(
            "/ask-bragi/conversations", json={"document_id": doc_id}, headers=_auth(patient_a["token"])
        )
        assert response.status_code == 404
    finally:
        db2 = SessionLocal()
        try:
            db2.query(models.Document).filter(models.Document.id == doc_id).delete()
            db2.commit()
        finally:
            db2.close()


# --- Source-evidence handle security ------------------------------------------


def test_source_evidence_id_not_surfaced_this_turn_is_rejected(patient_a):
    from app.services.ask_bragi.context import AskBragiContext
    from app.services.ask_bragi.tools import run_tool
    from app.db import SessionLocal

    patient_id = _patient_id_for(patient_a["token"])
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=patient_id,
            requester_user_id=patient_a["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        # The model "guesses" an id it was never actually shown.
        result = run_tool(ctx, "get_source_evidence", {"source_evidence_id": 1})
        assert result == {"error": "not_authorized_this_turn"}
    finally:
        db.close()
