"""Unit tests for app/services/ask_bragi/tools.py's data-scoping and
evidence-handle registration. Same DB-connectivity requirement/skip
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

from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.ask_bragi.context import AskBragiContext  # noqa: E402
from app.services.ask_bragi.tools import run_tool  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"askbragi-tools-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"AskBragi Tools Test {role}",
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


@pytest.fixture
def two_document_patient():
    account = _signup("patient", cnp="6000101999961")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc_a = models.Document(
            patient_id=patient_id, section="bloodwork", filename="a.pdf",
            document_type="laboratory_results", created_at="2026-01-01T00:00:00Z",
            is_verified=False, public_id=f"brg-doc-{uuid.uuid4().hex[:8]}",
        )
        doc_b = models.Document(
            patient_id=patient_id, section="other", filename="b.pdf",
            document_type="imaging_report", created_at="2026-01-02T00:00:00Z",
            is_verified=False, public_id=f"brg-doc-{uuid.uuid4().hex[:8]}",
        )
        db.add_all([doc_a, doc_b])
        db.commit()
        yield {"account": account, "patient_id": patient_id, "doc_a": doc_a.id, "doc_b": doc_b.id}

        db.query(models.Document).filter(models.Document.id.in_([doc_a.id, doc_b.id])).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()

    client.delete("/my/account", headers=_auth(account["token"]))


def test_document_scoped_conversation_search_documents_returns_only_that_document(two_document_patient):
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=two_document_patient["patient_id"],
            requester_user_id=two_document_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="document",
            document_id=two_document_patient["doc_a"],
        )
        result = run_tool(ctx, "search_documents", {})
        ids = [d["document_id"] for d in result["documents"]]
        assert ids == [two_document_patient["doc_a"]]
        assert two_document_patient["doc_b"] not in ids
    finally:
        db.close()


def test_get_document_rejects_out_of_scope_document(two_document_patient):
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=two_document_patient["patient_id"],
            requester_user_id=two_document_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="document",
            document_id=two_document_patient["doc_a"],
        )
        result = run_tool(ctx, "get_document", {"document_id": two_document_patient["doc_b"]})
        assert result == {"error": "out_of_scope", "message": "This conversation is scoped to a single document."}
    finally:
        db.close()


def test_patient_record_scope_returns_both_documents(two_document_patient):
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=two_document_patient["patient_id"],
            requester_user_id=two_document_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = run_tool(ctx, "search_documents", {})
        ids = {d["document_id"] for d in result["documents"]}
        assert ids == {two_document_patient["doc_a"], two_document_patient["doc_b"]}
    finally:
        db.close()


def test_search_documents_registers_document_ids_in_context(two_document_patient):
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=two_document_patient["patient_id"],
            requester_user_id=two_document_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        run_tool(ctx, "search_documents", {})
        assert two_document_patient["doc_a"] in ctx.authorized_document_ids
        assert two_document_patient["doc_b"] in ctx.authorized_document_ids
    finally:
        db.close()


def test_get_patient_context_never_includes_cnp_or_name(two_document_patient):
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=two_document_patient["patient_id"],
            requester_user_id=two_document_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = run_tool(ctx, "get_patient_context", {})
        assert "cnp" not in result
        assert "full_name" not in result
        assert "email" not in result
        assert "phone" not in result
        assert "address" not in result
    finally:
        db.close()


def test_medication_status_reflects_recorded_status_honestly(two_document_patient):
    db = SessionLocal()
    try:
        med = models.PatientMedication(
            patient_id=two_document_patient["patient_id"],
            created_by_user_id=two_document_patient["account"]["user"]["id"],
            name="Metformin",
            status="discontinued",
            is_uncertain=1,
            created_at="2026-01-01T00:00:00Z",
        )
        db.add(med)
        db.commit()

        ctx = AskBragiContext(
            db=db,
            patient_id=two_document_patient["patient_id"],
            requester_user_id=two_document_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = run_tool(ctx, "get_medications", {})
        entry = next(m for m in result["medications"] if m["name"] == "Metformin")
        assert entry["status"] == "discontinued"
        assert entry["is_uncertain"] is True

        db.query(models.PatientMedication).filter(models.PatientMedication.id == med.id).delete()
        db.commit()
    finally:
        db.close()


def test_unknown_tool_name_fails_safely(two_document_patient):
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=two_document_patient["patient_id"],
            requester_user_id=two_document_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = run_tool(ctx, "get_environment_variables", {})
        assert result == {"error": "unknown_tool"}
    finally:
        db.close()
