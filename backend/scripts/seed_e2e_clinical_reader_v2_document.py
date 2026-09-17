"""One-off, LOCAL-ONLY seed helper for the Clinical Reader Intelligence
V2 Playwright regression (frontend/e2e/clinical-reader-intelligence-v2.
spec.ts).

Creates a real patient account + one discharge_summary Document from the
full synthetic Romanian fixture (tests/fixtures/clinical_reader_v2_
fixture.py, Part 28), then runs it through the REAL reprocessing
pipeline (`reprocess_discharge_document` — real lab/medication
extraction+persistence, real Timeline projection) with the AI
interpreter's model call swapped for a deterministic, realistic mocked
response (never a live OpenAI call — mirrors the mocking convention used
throughout the backend test suite), so the seeded document has the SAME
diagnoses/investigations/anomalies/treatment_eras/current_encounter a
real interpretation pass would grounded-produce for this text, without
costing an external API call.

Prints one JSON line to stdout: {token, user, patient_id, document_id}.
The Playwright spec shells out to this script, seeds via stdout, and
deletes the account via DELETE /my/account when done — same pattern as
seed_e2e_discharge_document.py.

NOT wired into CI, not imported by any application code — a standalone
dev/test utility only.
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
from app.services.clinical_document import ai_interpreter  # noqa: E402
from app.services.clinical_document.discharge_parser import parse_legacy_discharge_payload  # noqa: E402
from app.services.clinical_document.persistence import serialize_structured_document  # noqa: E402
from app.services.clinical_document.reprocessing import reprocess_discharge_document  # noqa: E402
from tests.fixtures.clinical_reader_v2_fixture import SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD  # noqa: E402


def _event_id_containing(document, text: str) -> str:
    return next(e.source_event_id for e in document.dated_events if text in e.raw_text)


def _section_id(document, canonical_key: str) -> str:
    return next(s.id for s in document.sections if s.canonical_key == canonical_key)


def _build_mock_interpretation():
    """A dry-run parse of the SAME payload — deterministic ids, so these
    match exactly what `reprocess_discharge_document` derives internally
    when it later re-parses this document for real."""
    probe = parse_legacy_discharge_payload(SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD)
    clinical_course_id = _section_id(probe, "clinical_course")
    diagnoses_id = _section_id(probe, "diagnoses")
    admission_event_id = _event_id_containing(probe, "AV 1008")
    discharge_event_id = _event_id_containing(probe, "in stare ameliorata")
    current_investigations_event_id = _event_id_containing(probe, "ecografie abdominala")
    ruxolitinib_event_id = _event_id_containing(probe, "trecerea de la Hidroxiuree la Ruxolitinib")
    besremi_start_id = _event_id_containing(probe, "s-a initiat tratament cu Besremi")
    besremi_dose_id = _event_id_containing(probe, "doza de Besremi a fost crescuta")
    anomalous_date_event_id = _event_id_containing(probe, "14.09.3036")
    historical_phlebotomy_id = _event_id_containing(probe, "10.05.2019")

    def raw(_input):
        return {
            "diagnoses": [
                {"code": "D45", "text": "Policitemie vera", "role": "principal", "source_section_id": diagnoses_id, "source_event_ids": []},
            ],
            "investigations": [
                {
                    "investigation_type": "molecular", "title": "JAK2 V617F",
                    "findings": "Mutatia JAK2 V617F pozitiva.", "conclusion": None,
                    "source_section_id": clinical_course_id, "source_event_ids": [],
                },
                {
                    "investigation_type": "pathology", "title": "Biopsie osteomedulara",
                    "findings": None, "conclusion": None,
                    "source_section_id": clinical_course_id, "source_event_ids": [],
                },
                {
                    "investigation_type": "imaging", "title": "Ecografie abdominala",
                    "findings": "Splenomegalie moderata, fara alte modificari semnificative.", "conclusion": None,
                    "source_section_id": clinical_course_id, "source_event_ids": [current_investigations_event_id],
                },
                {
                    "investigation_type": "molecular", "title": "BCR-ABL",
                    "findings": "Rezultat negativ.", "conclusion": "Exclude leucemia mieloida cronica.",
                    "source_section_id": clinical_course_id, "source_event_ids": [current_investigations_event_id],
                },
            ],
            "anomalies": [
                {
                    "anomaly_type": "impossible_or_unusual_date",
                    "message": "Prescription date falls far outside any plausible range.",
                    "original_value": "14.09.3036",
                    "source_section_id": None, "source_event_ids": [anomalous_date_event_id],
                },
                {
                    "anomaly_type": "physiologically_implausible_value",
                    "message": "Heart rate of 1008/min is not physiologically possible.",
                    "original_value": "AV 1008/min",
                    "source_section_id": clinical_course_id, "source_event_ids": [],
                },
            ],
            "recommendations": [],
            "treatment_eras": [
                {
                    "label": "Ruxolitinib", "start_date": "2022-09-18", "end_date": "2024-02-05",
                    "description": "Trecere de la Hidroxiuree la Ruxolitinib pentru intoleranta digestiva.",
                    "event_ids": [ruxolitinib_event_id],
                },
                {
                    "label": "Besremi (ropeginterferon alfa-2b)", "start_date": "2024-02-05", "end_date": None,
                    "description": "Initiere Besremi 100mcg, ulterior titrare la 150mcg.",
                    "event_ids": [besremi_start_id, besremi_dose_id],
                },
            ],
            "current_encounter": {
                "admission_date": "2026-03-04", "discharge_date": "2026-03-05",
                "section_ids": [], "event_ids": [admission_event_id, discharge_event_id, current_investigations_event_id],
            },
            "encounter_scope_assignments": [
                {"target_type": "event", "target_id": admission_event_id, "scope": "current"},
                {"target_type": "event", "target_id": discharge_event_id, "scope": "current"},
                {"target_type": "event", "target_id": current_investigations_event_id, "scope": "current"},
                {"target_type": "event", "target_id": historical_phlebotomy_id, "scope": "historical"},
            ],
            "warnings": [],
        }

    return raw


def main() -> None:
    ai_interpreter._call_model = _build_mock_interpretation()

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:10]
        email = f"pw-e2e-clinreaderv2-{suffix}@example.com"
        user = models.User(
            email=email,
            full_name="Playwright E2E Clinical Reader V2",
            password_hash=hash_password("TestPass123!"),
            role="patient",
        )
        db.add(user)
        db.flush()

        patient = models.Patient(
            linked_user_id=user.id,
            full_name="Playwright E2E Clinical Reader V2",
            cnp=f"600010{suffix[:7]}",
            public_id=f"brg-pat-e2e-{suffix}",
        )
        db.add(patient)
        db.flush()

        structured = parse_legacy_discharge_payload(SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD)
        doc = models.Document(
            patient_id=patient.id,
            uploaded_by_user_id=user.id,
            section="discharge_summary",
            filename="synthetic-discharge-fixture.pdf",
            content_type="application/pdf",
            document_type="discharge_summary",
            report_name="Synthetic Discharge Fixture",
            created_at="2026-03-05T00:00:00Z",
            is_verified=True,
            note_body=serialize_structured_document(structured),
            public_id=f"brg-doc-e2e-{suffix}",
        )
        db.add(doc)
        db.flush()

        reprocess_discharge_document(db, document=doc, actor_user_id=user.id)
        db.commit()

        token = create_access_token({"sub": str(user.id), "role": "patient"})
        print(
            json.dumps(
                {
                    "token": token,
                    "user": {"id": user.id, "email": email, "full_name": user.full_name, "role": "patient"},
                    "patient_id": patient.id,
                    "document_id": doc.id,
                }
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
