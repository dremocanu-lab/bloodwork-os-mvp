"""End-to-end regression for the real production incident (BRAGI —
UNIVERSAL DOCUMENT INGESTION): BRAGI_EXTERNATION_EXAMPLE.docx, a Romanian
hospital discharge letter, was uploaded, sent to Google Document AI
(which rejected its MIME type — "raw_document.mime_type: Unsupported
mime type"), extracted no text, and was silently classified as
document_type=other, classification_source=reducto, confidence=1.0
instead of failing loudly or routing to a capable extractor.

Proves, through the REAL upload pipeline (not a unit test of the router
in isolation — see test_ingestion_router.py for that): DOCX -> local text
extraction succeeds -> Romanian content survives -> the semantic
classifier (here, the legacy keyword classifier, since this environment
has neither REDUCTO_ENABLED nor OPENAI_API_KEY configured — see
ROUTER_AUDIT.md's account of the Romanian discharge-letter keywords
already added there) receives meaningful text -> discharge_summary ->
persisted as the job's canonical document_type -> never "other".

Same DB-connectivity requirement/skip behavior as test_upload_validation.py.
"""

import io
import os
import time
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not configured — this file needs real DB connectivity.", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests.fixtures.synthetic_documents import ROMANIAN_DISCHARGE_BILET_DE_IESIRE  # noqa: E402

client = TestClient(app)

_TERMINAL_STATUSES = {
    "done",
    "error",
    "needs_confirmation",
    "needs_identity_confirmation",
    "quarantined",
    "security_quarantined",
    "duplicate",
    "unsupported_format",
    "extraction_failed",
    "encrypted",
}


def _build_docx_bytes(paragraphs: list[str]) -> bytes:
    import docx

    document = docx.Document()
    for line in paragraphs:
        if line.strip():
            document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def patient():
    email = f"docx-regression-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/auth/signup",
        json={"email": email, "full_name": "DOCX Regression Test", "password": "TestPass123!", "role": "patient"},
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


def _poll_job(headers, job_id: int, timeout_s: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout_s
    job = client.get(f"/upload-jobs/{job_id}", headers=headers).json()
    while job.get("status") not in _TERMINAL_STATUSES and time.monotonic() < deadline:
        time.sleep(0.25)
        job = client.get(f"/upload-jobs/{job_id}", headers=headers).json()
    return job


def test_docx_bilet_de_iesire_reaches_discharge_summary_not_other(patient):
    docx_bytes = _build_docx_bytes(ROMANIAN_DISCHARGE_BILET_DE_IESIRE.strip().splitlines())

    response = client.post(
        "/upload/batch",
        headers=patient,
        files=[("files", ("BRAGI_EXTERNATION_EXAMPLE.docx", io.BytesIO(docx_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert len(created) == 1
    job_id = created[0]["id"]

    job = _poll_job(patient, job_id)

    # The exact regression, ALWAYS true regardless of this environment's
    # OPENAI_API_KEY configuration: classification itself must NEVER be
    # "other" (silently, via an extraction failure masquerading as a real
    # semantic classification), never unsupported/failed/encrypted — a
    # real .docx with real, well-formed content is fully supported and is
    # classified BEFORE the (separate, OpenAI-vision-based)
    # discharge_summary_pipeline extraction step even starts.
    assert job["status"] != "unsupported_format", job
    assert job["status"] != "extraction_failed", job
    assert job["status"] != "encrypted", job
    assert job["document_type"] == "discharge_summary", job
    assert job["classification_source"] not in (None, "reducto", "reducto_fallback"), job
    assert job["classification_confidence"] is not None

    if not os.environ.get("OPENAI_API_KEY"):
        # discharge_summary_pipeline.py's OWN extraction step (a SEPARATE,
        # pre-existing, OpenAI-vision-based pipeline — unrelated to this
        # session's ingestion-router work, and already true for a PDF
        # discharge summary in this same environment) requires
        # OPENAI_API_KEY; this local/CI environment has none configured.
        # This is exactly the same, already-documented environment gap
        # every earlier session in this engagement hit (ASK_BRAGI_ENABLED/
        # OPENAI_API_KEY) — not a defect this test exists to catch. The
        # regression this test proves (classification never silently
        # resolves to "other") is already fully verified above.
        assert job["status"] == "error"
        assert "configuration" in (job.get("error") or "").lower()  # main.py's "missing_openai_config" category message
        return

    assert job["status"] == "done", job
    document_id = job["document_id"]
    assert document_id is not None

    reader = client.get(f"/documents/{document_id}/clinical-reader", headers=patient)
    if reader.status_code == 200:
        payload = reader.json()
        assert payload.get("document_type") == "discharge_summary"
