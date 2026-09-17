"""Pre-Phase-11 Romanian discharge classification closure session.

The real bug boundary the prior routing-consolidation pass never tested
(docs/clinical_document_v3/ROUTER_AUDIT.md): every existing "discharge
routing" test starts from a Document/UploadJob with document_type/section
already hardcoded to "discharge_summary" — never from real Romanian
source text run through the actual classifier. This file closes that
gap: real text -> classifier -> persisted UploadJob/Document -> serialized
metadata -> GET /documents/{id}/clinical-reader, using the patient
self-upload auto-classify path (POST /upload/batch), the only path that
actually invokes classification.

REDUCTO_ENABLED is forced off for the duration of every test here
(`monkeypatch.setenv`) so this suite is deterministic and never makes a
real, costly Reducto API call regardless of the ambient environment's
own .env — it exercises the deterministic legacy classifier
(`document_classifier.classify_document_text`), the same decision logic
`test_document_classifier.py` unit-tests in isolation, but here through
the REAL upload pipeline and REAL persistence, not called directly.

OCR is monkeypatched to return the fixture text verbatim instead of
actually reading pixels from a file — the upload still goes through
real upload validation, a real UploadJob, real classification, and real
Document/LabResult persistence; only the "read text out of a PDF" step
is stubbed, since exercising the real OCR/Tesseract path deterministically
would need a real rendered PDF fixture this repo doesn't have infrastructure
to build safely yet (see the handoff for this session's honest accounting).

Same skip-gracefully-without-a-real-DB convention as test_upload_validation.py.
"""

import io
import os
import time
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
from tests.fixtures.synthetic_documents import ROMANIAN_DISCHARGE_BILET_DE_IESIRE  # noqa: E402

client = TestClient(app)

REAL_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

_TERMINAL_STATUSES = {"done", "error", "needs_confirmation", "needs_identity_confirmation", "quarantined", "duplicate"}


@pytest.fixture
def patient():
    email = f"ro-discharge-e2e-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/auth/signup",
        json={"email": email, "full_name": "RO Discharge E2E", "password": "TestPass123!", "role": "patient"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    yield headers

    for _ in range(40):
        jobs = client.get("/upload-jobs", headers=headers).json()
        if all(j.get("status") in _TERMINAL_STATUSES for j in jobs):
            break
        time.sleep(0.25)

    client.delete("/my/account", headers=headers)


def _upload_and_wait(headers, monkeypatch, fixture_text: str, timeout_s: float = 20.0) -> dict:
    monkeypatch.setenv("REDUCTO_ENABLED", "false")
    monkeypatch.setattr("app.main.ocr_extract_text", lambda **kwargs: {"text": fixture_text})
    # The real discharge_summary_pipeline needs a configured OPENAI_API_KEY
    # (a separate, unrelated dev-environment gap — not what this test is
    # about). Stubbed with a minimal valid pipeline_result shape so
    # persistence + the clinical-reader endpoint can be exercised for
    # real; structured-content correctness is already covered by the
    # Phase 8 reader's own dedicated tests.
    monkeypatch.setattr(
        "app.main.process_uploaded_discharge_summary",
        lambda **kwargs: {"extracted_text": fixture_text, "note_body": None, "parsed_data": {}},
    )

    response = client.post(
        "/upload/batch",
        headers=headers,
        files={"files": ("discharge.pdf", io.BytesIO(REAL_PDF_BYTES), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    job_id = response.json()[0]["id"]

    deadline = time.time() + timeout_s
    job = None
    while time.time() < deadline:
        jobs = client.get("/upload-jobs", headers=headers).json()
        job = next((j for j in jobs if j["id"] == job_id), None)
        if job and job["status"] in _TERMINAL_STATUSES:
            break
        time.sleep(0.25)

    assert job is not None, "upload job never appeared"
    return job


def test_real_bilet_de_iesire_text_classifies_and_persists_as_discharge_summary(patient, monkeypatch):
    job = _upload_and_wait(patient, monkeypatch, ROMANIAN_DISCHARGE_BILET_DE_IESIRE)

    assert job["status"] == "done", (
        f"expected the dense-but-clear discharge letter to auto-classify without a confirmation "
        f"detour, got status={job['status']!r} message={job.get('message')!r}"
    )
    assert job["document_type"] == "discharge_summary"
    assert job["classification_status"] == "classified"
    assert job["document_id"] is not None

    document = client.get(f"/documents/{job['document_id']}", headers=patient).json()
    assert document["document_type"] == "discharge_summary"
    assert document["section"] == "discharge_summary"


def test_persisted_romanian_discharge_document_reaches_clinical_reader_endpoint(patient, monkeypatch):
    job = _upload_and_wait(patient, monkeypatch, ROMANIAN_DISCHARGE_BILET_DE_IESIRE)
    assert job["document_id"] is not None

    reader = client.get(f"/documents/{job['document_id']}/clinical-reader", headers=patient)
    assert reader.status_code == 200, reader.text
    assert reader.json()["document"]["document_type"] == "discharge_summary"


# --- AI-classifier-in-the-loop (P0 upload-reliability session) ----------
#
# The tests above exercise the LEGACY classifier only (no OPENAI_API_KEY
# configured in this dev environment) — this section proves the AI path
# specifically: real upload pipeline, mocked OpenAI response only.


def _mock_ai_confident_discharge(monkeypatch):
    import json as _json
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services import ai_document_classifier as classifier_module

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    fake_client = MagicMock()
    fake_client.responses.create.return_value = SimpleNamespace(
        output_text=_json.dumps(
            {
                "document_type": "discharge_summary",
                "confidence": 0.96,
                "ambiguous": False,
                "alternative_document_type": None,
                "reason_codes": ["DISCHARGE_TITLE", "EPICRISIS"],
            }
        ),
        output=[],
    )
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)
    return fake_client


def test_ai_classification_becomes_the_persisted_final_result(patient, monkeypatch):
    _mock_ai_confident_discharge(monkeypatch)

    job = _upload_and_wait(patient, monkeypatch, ROMANIAN_DISCHARGE_BILET_DE_IESIRE)

    assert job["status"] == "done"
    assert job["document_type"] == "discharge_summary"
    assert job["classification_status"] == "classified"

    document = client.get(f"/documents/{job['document_id']}", headers=patient).json()
    assert document["document_type"] == "discharge_summary"
    assert document["section"] == "discharge_summary"

    classification_entries = [
        e for e in document["parsed_data"]["audit_logs"] if e.get("action") == "classification_completed"
    ]
    assert classification_entries, "expected a classification_completed audit entry"
    assert "ai=discharge_summary" in classification_entries[0].get("details", "")


def test_ai_timeout_falls_back_and_upload_still_completes(patient, monkeypatch):
    from unittest.mock import MagicMock

    from app.services import ai_document_classifier as classifier_module

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    class FakeTimeout(Exception):
        pass

    fake_client = MagicMock()
    fake_client.responses.create.side_effect = FakeTimeout("timed out")
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)

    job = _upload_and_wait(patient, monkeypatch, ROMANIAN_DISCHARGE_BILET_DE_IESIRE)

    # An AI outage must never fail the upload — it falls back to the
    # legacy classifier (already fixed to handle this exact fixture
    # confidently, see test_document_classifier.py).
    assert job["status"] == "done"
    assert job["document_type"] == "discharge_summary"
    assert job["classification_source"] in ("legacy_rules", "legacy_rules_fallback")


def test_ai_not_configured_upload_still_completes_via_legacy(patient, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    job = _upload_and_wait(patient, monkeypatch, ROMANIAN_DISCHARGE_BILET_DE_IESIRE)

    assert job["status"] == "done"
    assert job["document_type"] == "discharge_summary"
    assert job["classification_source"] in ("legacy_rules", "legacy_rules_fallback")
