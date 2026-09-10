"""DSAR export regression suite (POST /my/export) — see
BRAGI_SECURITY_GDPR_PLAN.md §7/Priority 7 and docs/privacy/DSAR_RUNBOOK.md.

Same DB-required convention as test_idor_regression.py (see that file's
docstring).
"""

import io
import json
import os
import uuid
import zipfile

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
    return f"dsar-test-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"DSAR Test {role}",
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
    account = _signup("patient", cnp="6000101999911")
    yield account
    _delete_account(account["token"])


@pytest.fixture
def patient_b():
    account = _signup("patient", cnp="6000101999912")
    yield account
    _delete_account(account["token"])


def _export_zip(token: str) -> zipfile.ZipFile:
    response = client.post("/my/export", headers=_auth(token))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_export_requires_authentication():
    response = client.post("/my/export")
    assert response.status_code == 401


def test_export_rejects_non_patient_roles():
    doctor = _signup("doctor")
    response = client.post("/my/export", headers=_auth(doctor["token"]))
    assert response.status_code == 403


def test_export_contains_expected_files(patient_a):
    zf = _export_zip(patient_a["token"])
    names = set(zf.namelist())
    for expected in (
        "README.txt",
        "profile.json",
        "lab_results.json",
        "medications.json",
        "events.json",
        "access_relationships.json",
        "emergency_contacts.json",
        "documents_manifest.json",
        "ai_conversations.json",
    ):
        assert expected in names, f"{expected} missing from export: {names}"


def test_export_profile_matches_own_account(patient_a):
    zf = _export_zip(patient_a["token"])
    profile = json.loads(zf.read("profile.json"))
    assert profile["account_email"] == patient_a["email"]
    assert profile["cnp"] == "6000101999911"  # full value — this is the patient's own export


def test_export_ai_conversations_empty_not_applicable(patient_a):
    zf = _export_zip(patient_a["token"])
    assert json.loads(zf.read("ai_conversations.json")) == []


def test_export_includes_own_medication(patient_a):
    med = {
        "name": "Metformin",
        "dose_strength": "500mg",
        "frequency": "twice daily",
    }
    response = client.post("/my/medications", json=med, headers=_auth(patient_a["token"]))
    assert response.status_code == 201, response.text

    zf = _export_zip(patient_a["token"])
    medications = json.loads(zf.read("medications.json"))
    assert any(m["name"] == "Metformin" for m in medications)


def test_export_never_contains_another_patients_data(patient_a, patient_b):
    med_a = {"name": "OnlyPatientA_Drug", "dose_strength": "1mg"}
    client.post("/my/medications", json=med_a, headers=_auth(patient_a["token"]))

    zf_b = _export_zip(patient_b["token"])
    medications_b = json.loads(zf_b.read("medications.json"))
    assert not any(m["name"] == "OnlyPatientA_Drug" for m in medications_b)

    profile_b = json.loads(zf_b.read("profile.json"))
    assert profile_b["cnp"] == "6000101999912"
    assert profile_b["account_email"] == patient_b["email"]


def test_export_includes_own_document_file_and_manifest(patient_a, tmp_path):
    # Insert a Document row directly (bypassing the upload/Reducto
    # pipeline, which needs real file processing infra not relevant to
    # this test) with patient_id set to this patient's own row, backed by
    # a real file on disk — exercises the export's file-embedding path.
    db = SessionLocal()
    try:
        profile_resp = client.get("/my/profile", headers=_auth(patient_a["token"]))
        patient_id = profile_resp.json()["patient"]["id"]

        real_file = tmp_path / "synthetic_report.txt"
        real_file.write_text("synthetic non-PHI test content")

        doc = models.Document(
            patient_id=patient_id,
            section="other",
            filename="synthetic_report.txt",
            content_type="text/plain",
            saved_to=str(real_file),
            created_at="2026-01-01T00:00:00Z",
            is_verified=False,
            public_id="brg-doc-dsartest",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id
    finally:
        db.close()

    try:
        zf = _export_zip(patient_a["token"])
        manifest = json.loads(zf.read("documents_manifest.json"))
        entry = next((m for m in manifest if m["document_id"] == doc_id), None)
        assert entry is not None, f"document {doc_id} missing from manifest: {manifest}"
        assert entry["included_in_documents_folder"] is True
        arcname = f"documents/{doc_id}_synthetic_report.txt"
        assert arcname in zf.namelist()
        assert zf.read(arcname) == b"synthetic non-PHI test content"
    finally:
        db2 = SessionLocal()
        try:
            db2.query(models.AuditLog).filter(models.AuditLog.document_id == doc_id).delete()
            db2.query(models.Document).filter(models.Document.id == doc_id).delete()
            db2.commit()
        finally:
            db2.close()
