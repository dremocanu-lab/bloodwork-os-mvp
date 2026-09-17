"""Reprocessing/enrichment orchestration tests — Clinical Reader
Intelligence V2. Needs real DB connectivity (same skip-gracefully
convention as the other clinical_document persistence test files).
"""

import json
import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not configured — this file needs real DB connectivity.", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.clinical_document import ai_interpreter  # noqa: E402
from app.services.clinical_document.reprocessing import ReprocessingError, reprocess_discharge_document  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"clindoc-reproc-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {"email": email, "full_name": f"Reprocess Test {role}", "password": "TestPass123!", "role": role, **extra}
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["access_token"], "user": data["user"], "email": email}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


_LEGACY_PAYLOAD = {
    "document_type": "discharge_summary",
    "patient_name": "Test Patient",
    "admission_date": "2026-03-04",
    "discharge_date": "2026-03-05",
    "sections": [
        {
            "key": "epicriza",
            "title": "EPICRIZĂ",
            "body": "Pacient internat la 04.03.2026. Externat la 05.03.2026, ameliorat.",
        },
        {
            "key": "diagnostics",
            "title": "Diagnostic principal",
            "body": "D45 Policitemie esentiala",
        },
        {
            "key": "laboratory_abnormal",
            "title": "Examen de laborator cu valori patologice",
            "body": "WBC 15.2 10^3/uL (4.0-10.0) H",
        },
        {
            "key": "recommended_treatment",
            "title": "Tratament recomandat",
            "body": "Hidroxiuree 500mg, 1 comprimat dimineata si 1 comprimat seara, continuu.",
        },
    ],
}


@pytest.fixture
def discharge_document():
    account = _signup("patient", cnp="6000101999982")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_id,
            section="discharge_summary",
            filename="discharge.pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary",
            created_at="2026-03-05T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-reproc-{uuid.uuid4().hex[:8]}",
            note_body=json.dumps(_LEGACY_PAYLOAD),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        document_id = doc.id
    finally:
        db.close()

    yield {"account": account, "patient_id": patient_id, "document_id": document_id}

    client.delete("/my/account", headers=_auth(account["token"]))


def _fake_call_model(_input):
    return {
        "diagnoses": [], "investigations": [], "anomalies": [], "recommendations": [], "treatment_eras": [],
        "current_encounter": {"admission_date": "2026-03-04", "discharge_date": "2026-03-05", "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }


def test_reprocessing_creates_real_canonical_rows(discharge_document, monkeypatch):
    monkeypatch.setattr(ai_interpreter, "_call_model", _fake_call_model)
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == discharge_document["document_id"]).first()
        result = reprocess_discharge_document(db, document=document, actor_user_id=discharge_document["account"]["user"]["id"])

        assert result.dated_events_count >= 2  # admission + discharge, real Clinical Course extraction
        assert result.lab_results_created == 1
        assert result.medications_created == 1
        assert result.interpretation_status == "complete"

        labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
        assert len(labs) == 1
        meds = db.query(models.PatientMedication).filter(models.PatientMedication.source_document_id == document.id).all()
        assert len(meds) == 1
    finally:
        db.close()


def test_reprocessing_twice_does_not_duplicate_canonical_rows(discharge_document, monkeypatch):
    """Part Z: reprocessing is idempotent — running it again must reuse
    the existing LabResult/PatientMedication rows, never create a second
    copy."""
    monkeypatch.setattr(ai_interpreter, "_call_model", _fake_call_model)
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == discharge_document["document_id"]).first()

        first = reprocess_discharge_document(db, document=document, actor_user_id=discharge_document["account"]["user"]["id"])
        assert first.lab_results_created == 1
        assert first.medications_created == 1

        second = reprocess_discharge_document(db, document=document, actor_user_id=discharge_document["account"]["user"]["id"])
        assert second.lab_results_created == 0
        assert second.lab_results_reused == 1
        assert second.medications_created == 0
        assert second.medications_reused == 1

        labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
        assert len(labs) == 1  # still exactly one row, not two
        meds = db.query(models.PatientMedication).filter(models.PatientMedication.source_document_id == document.id).all()
        assert len(meds) == 1
    finally:
        db.close()


def test_reprocessing_non_discharge_document_rejected():
    db = SessionLocal()
    try:
        account = _signup("patient", cnp="6000101999983")
        profile = client.get("/my/profile", headers=_auth(account["token"])).json()
        doc = models.Document(
            patient_id=profile["patient"]["id"],
            section="notes",
            filename="note.pdf",
            created_at="2026-01-01T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-reproc-nondischarge-{uuid.uuid4().hex[:8]}",
            note_body="Just a plain text note, not a structured payload.",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        with pytest.raises(ReprocessingError):
            reprocess_discharge_document(db, document=doc, actor_user_id=profile["patient"]["id"])

        client.delete("/my/account", headers=_auth(account["token"]))
    finally:
        db.close()


def test_reprocess_endpoint_requires_ownership(discharge_document, monkeypatch):
    monkeypatch.setattr(ai_interpreter, "_call_model", _fake_call_model)
    other_account = _signup("patient", cnp="6000101999984")
    try:
        response = client.post(
            f"/documents/{discharge_document['document_id']}/reprocess-clinical-structure",
            headers=_auth(other_account["token"]),
        )
        assert response.status_code == 403
    finally:
        client.delete("/my/account", headers=_auth(other_account["token"]))


def test_reprocess_endpoint_updates_reader_payload(discharge_document, monkeypatch):
    monkeypatch.setattr(ai_interpreter, "_call_model", _fake_call_model)
    headers = _auth(discharge_document["account"]["token"])

    response = client.post(f"/documents/{discharge_document['document_id']}/reprocess-clinical-structure", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dated_events_count"] >= 2
    assert body["lab_results_created"] == 1
    assert body["medications_created"] == 1
    assert body["interpretation_status"] == "complete"

    reader = client.get(f"/documents/{discharge_document['document_id']}/clinical-reader", headers=headers)
    assert reader.status_code == 200
    structured = reader.json()["structured_document"]
    assert structured is not None
    assert len(structured["dated_events"]) >= 2
    assert structured["parser_version"] == "discharge-parser-phase4-5-v1"  # the REAL parser, not the legacy-upconversion label
    assert structured["interpretation"]["status"] == "complete"
