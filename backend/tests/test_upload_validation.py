"""Regression tests for upload file-type/content validation (see
BRAGI_SECURITY_GDPR_PLAN.md, "file upload security"). Same DB-connectivity
requirement/skip behavior as test_idor_regression.py — see its docstring.
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

client = TestClient(app)

REAL_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


_TERMINAL_STATUSES = {"done", "error", "needs_confirmation", "needs_identity_confirmation", "quarantined", "duplicate"}


@pytest.fixture
def patient():
    email = f"upload-test-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/auth/signup",
        json={"email": email, "full_name": "Upload Test", "password": "TestPass123!", "role": "patient"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    yield headers

    # Real race found by this exact test suite, not a hypothetical: /upload/
    # background's BackgroundTasks processing can still be running
    # (process_upload_job, its own DB session, its own UPDATE upload_jobs
    # statement) when DELETE /my/account removes that same job row out
    # from under it — a StaleDataError deep in SQLAlchemy that a real
    # user could in principle also hit by deleting their account within
    # moments of an upload (see BRAGI_SECURITY_GDPR_PLAN.md's residual-
    # risks section). Waiting for every job this test started to reach a
    # terminal status avoids it here; the underlying race is still real
    # and undocumented as a fix, only worked around in this test.
    for _ in range(20):
        jobs = client.get("/upload-jobs", headers=headers).json()
        if all(j.get("status") in _TERMINAL_STATUSES for j in jobs):
            break
        time.sleep(0.25)

    client.delete("/my/account", headers=headers)


def test_real_pdf_accepted(patient):
    response = client.post(
        "/upload/background",
        headers=patient,
        files={"file": ("real.pdf", io.BytesIO(REAL_PDF_BYTES), "application/pdf")},
        data={"section": "bloodwork"},
    )
    assert response.status_code == 200
    assert response.json()["status"] in ("queued", "processing", "done")


def test_manual_discharge_section_pick_sets_canonical_document_type(patient):
    # Pre-Phase-11 Romanian discharge classification closure: a doctor/
    # care-partner manual upload never runs the real classifier (see
    # process_upload_job's AUTO_CLASSIFY_SECTION gate) and previously
    # left document_type NULL forever even when the user's own choice —
    # "Discharge Summary" — is completely unambiguous. Real, previously-
    # deferred gap now closed for the two section values that map to
    # exactly one document_type each.
    response = client.post(
        "/upload/background",
        headers=patient,
        files={"file": ("real.pdf", io.BytesIO(REAL_PDF_BYTES), "application/pdf")},
        data={"section": "discharge_summary"},
    )
    assert response.status_code == 200
    assert response.json()["document_type"] == "discharge_summary"
    assert response.json()["classification_status"] == "classified"


def test_manual_bloodwork_section_pick_sets_canonical_document_type(patient):
    response = client.post(
        "/upload/background",
        headers=patient,
        files={"file": ("real.pdf", io.BytesIO(REAL_PDF_BYTES), "application/pdf")},
        data={"section": "bloodwork"},
    )
    assert response.status_code == 200
    assert response.json()["document_type"] == "laboratory_results"


def test_manual_ambiguous_section_pick_leaves_document_type_null(patient):
    # "scans"/"medications"/"hospitalizations"/"other" each cover more
    # than one real document_type — must never be guessed.
    response = client.post(
        "/upload/background",
        headers=patient,
        files={"file": ("real.pdf", io.BytesIO(REAL_PDF_BYTES), "application/pdf")},
        data={"section": "hospitalizations"},
    )
    assert response.status_code == 200
    assert response.json()["document_type"] is None


def test_disallowed_extension_rejected(patient):
    response = client.post(
        "/upload/background",
        headers=patient,
        files={"file": ("malware.exe", io.BytesIO(b"MZ\x90\x00fake"), "application/octet-stream")},
        data={"section": "bloodwork"},
    )
    assert response.status_code == 400
    assert ".exe" in response.json()["detail"]


def test_html_disguised_as_pdf_rejected_by_magic_bytes(patient):
    fake_pdf = b"<html><script>alert(1)</script></html>"
    response = client.post(
        "/upload/background",
        headers=patient,
        files={"file": ("spoofed.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        data={"section": "bloodwork"},
    )
    assert response.status_code == 400
    assert "match" in response.json()["detail"].lower()


def test_no_extension_rejected(patient):
    response = client.post(
        "/upload/background",
        headers=patient,
        files={"file": ("noextension", io.BytesIO(REAL_PDF_BYTES), "application/octet-stream")},
        data={"section": "bloodwork"},
    )
    assert response.status_code == 400


def test_real_png_accepted(patient):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    response = client.post(
        "/upload/background",
        headers=patient,
        files={"file": ("scan.png", io.BytesIO(png_bytes), "image/png")},
        data={"section": "bloodwork"},
    )
    assert response.status_code == 200


def test_batch_endpoint_rejects_bad_file_without_failing_whole_batch(patient):
    response = client.post(
        "/upload/batch",
        headers=patient,
        files=[
            ("files", ("good.pdf", io.BytesIO(REAL_PDF_BYTES), "application/pdf")),
            ("files", ("bad.exe", io.BytesIO(b"MZ fake"), "application/octet-stream")),
        ],
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 2
    statuses = [r.get("status") for r in results]
    assert "error" in statuses
    assert any(s != "error" for s in statuses)
