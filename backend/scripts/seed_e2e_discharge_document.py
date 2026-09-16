"""One-off, LOCAL-ONLY seed helper for the Phase 8 clinical-reader
Playwright regression (frontend/e2e/clinical-reader.spec.ts).

Creates a real patient account + one discharge_summary Document, built
via the REAL Phase 4/5 forward parser (discharge_parser.py) against a
synthetic payload exercising: repeated EPICRIZĂ headings, a suspicious
future date (14/09/3036), an implausible vital sign (AV 1008 bpm), and
a chronologically misplaced event — plus real, canonically-persisted
LabResult rows (via lab_extraction/lab_persistence, including the MCH
conflict case) and PatientMedication rows (via medication_extraction/
medication_persistence, including a finite-duration course and a
same-drug status conflict) — all DIRECTLY via the ORM/service layer,
NOT through Reducto/OpenAI, so this costs zero external API calls
(mirrors seed_e2e_lab_document.py's own established pattern).

Prints one JSON line to stdout: {token, patient_id, document_id}. The
Playwright spec shells out to this script, seeds via stdout, and
deletes the account via DELETE /my/account when done.

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
from app.services.clinical_document.discharge_parser import parse_legacy_discharge_payload  # noqa: E402
from app.services.clinical_document.lab_extraction import extract_lab_candidates_from_segment  # noqa: E402
from app.services.clinical_document.lab_persistence import persist_lab_candidates  # noqa: E402
from app.services.clinical_document.medication_duration import parse_duration  # noqa: E402
from app.services.clinical_document.medication_extraction import MedicationCandidate  # noqa: E402
from app.services.clinical_document.medication_persistence import persist_medication_candidates  # noqa: E402
from app.services.clinical_document.persistence import serialize_structured_document  # noqa: E402
from app.services.clinical_document.segments import SourceSegment  # noqa: E402

DISCHARGE_PAYLOAD = {
    "document_type": "discharge_summary",
    "hospital_name": "Spitalul Clinic Județean",
    "admission_date": "10.01.2026",
    "discharge_date": "20.01.2026",
    "sections": [
        {
            "key": "epicriza",
            "title": "EPICRIZĂ",
            "body": (
                "Internat la 10.01.2026 pentru dureri abdominale, cu AV 1008 bpm la internare. "
                "Control programat pentru 14/09/3036 (dată suspectă, păstrată nemodificată)."
            ),
        },
        {"key": "epicriza", "title": "EPICRIZĂ", "body": "Externat la 20.01.2026, ameliorat."},
        {"key": "diagnoses", "title": "Diagnostic principal", "body": "K80.2 Colelitiaza"},
        # Headings only — the real lab/medication VALUES are attached
        # separately below via lab_persistence/medication_persistence
        # (Phase 6/7's own canonical tables, not this payload's prose).
        # These entries exist purely so consolidate_segments produces
        # real laboratory_results/discharge_medications/medications
        # ClinicalSections, so the reader's outline has real buttons
        # for them to navigate to.
        {"key": "laborator", "title": "EXAMENE DE LABORATOR", "body": "Vezi rezultatele structurate de mai jos."},
        {
            "key": "medicatie_externare",
            "title": "MEDICAȚIE LA EXTERNARE",
            "body": "Vezi medicația structurată de mai jos.",
        },
        {"key": "medicatie", "title": "MEDICAȚIE CURENTĂ", "body": "Vezi medicația structurată de mai jos."},
    ],
}

HEMATOLOGY_FIXTURE_TEXT = """\
Nr. cerere: LAB-2026-0091
Data recoltarii: 10.01.2026

Valori normale:
WBC 5.51 10^3/uL (4.0-10.0)
HGB 14.0 g/dL (13.0-17.0)
PLT 349 10^3/uL (150-400)
MCH 29.0 pg (27-33)

Valori patologice:
ALT 56 U/L (10-40) H
MCH 31.5 pg (27-33)
"""


def main() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:10]
        email = f"pw-e2e-discharge-{suffix}@example.com"
        user = models.User(
            email=email,
            full_name="Playwright E2E Discharge",
            password_hash=hash_password("TestPass123!"),
            role="patient",
        )
        db.add(user)
        db.flush()

        patient = models.Patient(
            linked_user_id=user.id,
            full_name="Playwright E2E Discharge",
            cnp=f"600010{suffix[:7]}",
            public_id=f"brg-pat-e2e-{suffix}",
        )
        db.add(patient)
        db.flush()

        structured = parse_legacy_discharge_payload(DISCHARGE_PAYLOAD)
        doc = models.Document(
            patient_id=patient.id,
            uploaded_by_user_id=user.id,
            section="discharge_summary",
            filename="discharge.pdf",
            content_type="application/pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary",
            created_at="2026-01-20T00:00:00Z",
            is_verified=True,
            note_body=serialize_structured_document(structured),
            public_id=f"brg-doc-e2e-{suffix}",
        )
        db.add(doc)
        db.flush()

        lab_segment = SourceSegment(
            segment_id="seg-000-laborator", index=0, raw_heading="EXAMENE DE LABORATOR", raw_text=HEMATOLOGY_FIXTURE_TEXT
        )
        lab_candidates = extract_lab_candidates_from_segment(lab_segment)
        persist_lab_candidates(db, document=doc, candidates=lab_candidates)

        med_candidates = [
            MedicationCandidate(
                source_segment_id="seg-001-medicatie",
                canonical_key="discharge_medications",
                raw_text="Amoxicilina 500mg 1-1-1, 14 zile, incepand de azi.",
                raw_medication_name="Amoxicilina",
                status_context="started",
                starts_at_discharge_or_encounter=True,
                raw_duration="14 zile",
                parsed_duration=parse_duration("14 zile"),
                source_evidence_text="Amoxicilina 500mg 1-1-1, 14 zile, incepand de azi.",
            ),
            MedicationCandidate(
                source_segment_id="seg-001-medicatie",
                canonical_key="discharge_medications",
                raw_text="Ibuprofen 400mg la nevoie pentru durere.",
                raw_medication_name="Ibuprofen",
                status_context="continued",
                prn=True,
                source_evidence_text="Ibuprofen 400mg la nevoie pentru durere.",
            ),
            MedicationCandidate(
                source_segment_id="seg-002-medicatie",
                canonical_key="medications",
                raw_text="BESREMI 250mcg continua.",
                raw_medication_name="BESREMI",
                status_context="continued",
                source_evidence_text="BESREMI 250mcg continua.",
            ),
            MedicationCandidate(
                source_segment_id="seg-003-medicatie",
                canonical_key="medications",
                raw_text="BESREMI oprit.",
                raw_medication_name="BESREMI",
                status_context="stopped",
                source_evidence_text="BESREMI oprit.",
            ),
        ]
        persist_medication_candidates(
            db, document=doc, created_by_user_id=user.id, candidates=med_candidates,
            admission_date=DISCHARGE_PAYLOAD["admission_date"], discharge_date=DISCHARGE_PAYLOAD["discharge_date"],
        )

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
