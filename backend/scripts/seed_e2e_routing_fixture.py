"""One-off, LOCAL-ONLY seed helper for the post-Phase-10 integration-
correction Playwright regression (frontend/e2e/routing-and-integration-
fixes.spec.ts).

Creates a real patient account with:
- a "new-style" classified discharge document (`document_type=
  "discharge_summary"`, but `section="other"` — deliberately mismatched,
  so only the `document_type` signal can route it correctly, proving the
  real fix, not the pre-existing fallback);
- a "legacy" discharge document (`section="discharge_summary"`,
  `document_type=None` — the shape every pre-Phase-10 upload has),
  proving the fallback still works, not just the new signal;
- a derived lab artifact off the new-style document (Phase 6/9), to
  prove the Timeline pages' own missing derived-artifact-routing gap is
  fixed;

plus a doctor account with an active `DoctorPatientAccess` grant for
that patient, to test the discharge reader's own Ask Bragi target
(`patient_id`, not `document.id`) fix from a doctor's perspective.

Prints one JSON line to stdout. NOT wired into CI, not imported by any
application code — a standalone dev/test utility only, same convention
as seed_e2e_discharge_document.py.
"""

from __future__ import annotations

import json
import sys
import uuid

sys.path.insert(0, __file__.rsplit("\\", 2)[0] if "\\" in __file__ else __file__.rsplit("/", 2)[0])

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import models  # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services.clinical_document.discharge_parser import parse_legacy_discharge_payload  # noqa: E402
from app.services.clinical_document.lab_extraction import extract_lab_candidates_from_segment  # noqa: E402
from app.services.clinical_document.lab_persistence import persist_lab_candidates  # noqa: E402
from app.services.clinical_document.persistence import serialize_structured_document  # noqa: E402
from app.services.clinical_document.segments import SourceSegment  # noqa: E402

DISCHARGE_PAYLOAD = {
    "document_type": "discharge_summary",
    "hospital_name": "Spitalul Clinic Județean",
    "admission_date": "10.01.2026",
    "discharge_date": "20.01.2026",
    "sections": [
        {"key": "epicriza", "title": "EPICRIZĂ", "body": "Internat la 10.01.2026 pentru dureri abdominale."},
        {"key": "diagnoses", "title": "Diagnostic principal", "body": "K80.2 Colelitiaza"},
        {"key": "laborator", "title": "EXAMENE DE LABORATOR", "body": "Vezi rezultatele structurate de mai jos."},
    ],
}

HEMATOLOGY_FIXTURE_TEXT = """\
Nr. cerere: LAB-2026-0091
Data recoltarii: 10.01.2026

WBC 5.51 10^3/uL (4.0-10.0)
PLT 349 10^3/uL (150-400)
"""


def main() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:10]
        email = f"pw-e2e-routing-{suffix}@example.com"
        user = models.User(
            email=email,
            full_name="Playwright E2E Routing",
            password_hash=hash_password("TestPass123!"),
            role="patient",
        )
        db.add(user)
        db.flush()

        patient = models.Patient(
            linked_user_id=user.id,
            full_name="Playwright E2E Routing",
            cnp=f"600011{suffix[:7]}",
            public_id=f"brg-pat-e2e-rt-{suffix}",
        )
        db.add(patient)
        db.flush()

        structured = parse_legacy_discharge_payload(DISCHARGE_PAYLOAD)

        # New-style classified document: document_type is the ONLY
        # signal that correctly identifies this as discharge-shaped —
        # section is deliberately "other" (mismatched), the exact shape
        # a real classifier-driven upload can produce (see
        # ROUTER_AUDIT.md's own root-cause finding).
        new_style_doc = models.Document(
            patient_id=patient.id,
            uploaded_by_user_id=user.id,
            section="other",
            filename="discharge-new.pdf",
            content_type="application/pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary (new-style)",
            report_type=None,
            created_at="2026-01-20T00:00:00Z",
            is_verified=True,
            note_body=serialize_structured_document(structured),
            public_id=f"brg-doc-e2e-rt-new-{suffix}",
        )
        db.add(new_style_doc)
        db.flush()

        lab_segment = SourceSegment(
            segment_id="seg-000-laborator", index=0, raw_heading="EXAMENE DE LABORATOR", raw_text=HEMATOLOGY_FIXTURE_TEXT
        )
        lab_result = persist_lab_candidates(
            db, document=new_style_doc, candidates=extract_lab_candidates_from_segment(lab_segment)
        )
        derived_document_id = lab_result.groups[0].derived_document_id if lab_result.groups else None

        # Legacy-shaped document: section/report_type say discharge,
        # document_type is null — the shape EVERY pre-Phase-10 upload has.
        # Must still route correctly (the fallback, not the new signal).
        legacy_doc = models.Document(
            patient_id=patient.id,
            uploaded_by_user_id=user.id,
            section="discharge_summary",
            filename="discharge-legacy.pdf",
            content_type="application/pdf",
            document_type=None,
            report_name="Discharge Summary (legacy-style)",
            report_type="discharge_summary",
            created_at="2026-01-10T00:00:00Z",
            is_verified=True,
            note_body=serialize_structured_document(parse_legacy_discharge_payload(DISCHARGE_PAYLOAD)),
            public_id=f"brg-doc-e2e-rt-legacy-{suffix}",
        )
        db.add(legacy_doc)
        db.flush()

        db.commit()

        # A doctor with an active grant, to test the discharge reader's
        # own Ask Bragi target (patient_id, not document.id) fix.
        doctor_email = f"pw-e2e-routing-doctor-{suffix}@example.com"
        doctor = models.User(
            email=doctor_email,
            full_name="Playwright E2E Routing Doctor",
            password_hash=hash_password("TestPass123!"),
            role="doctor",
        )
        db.add(doctor)
        db.flush()
        db.add(
            models.DoctorPatientAccess(
                doctor_user_id=doctor.id,
                patient_id=patient.id,
                granted_by_user_id=user.id,
                granted_at="2026-01-01T00:00:00+00:00",
                is_active=1,
            )
        )
        db.commit()

        token = create_access_token({"sub": str(user.id), "role": "patient"})
        doctor_token = create_access_token({"sub": str(doctor.id), "role": "doctor"})
        print(
            json.dumps(
                {
                    "token": token,
                    "user": {"id": user.id, "email": email, "full_name": user.full_name, "role": "patient"},
                    "doctor_token": doctor_token,
                    "doctor_user": {
                        "id": doctor.id,
                        "email": doctor_email,
                        "full_name": doctor.full_name,
                        "role": "doctor",
                    },
                    "patient_id": patient.id,
                    "new_style_document_id": new_style_doc.id,
                    "legacy_document_id": legacy_doc.id,
                    "derived_document_id": derived_document_id,
                }
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
