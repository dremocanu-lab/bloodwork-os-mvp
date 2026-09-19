"""One-off, LOCAL-ONLY seed helper for the Source Geometry + Clinical
Table Intelligence V3 Playwright regression
(frontend/e2e/source-geometry-table-intelligence-v3.spec.ts).

Unlike every earlier E2E seed script in this repo, this one attaches a
REAL PDF file (`Document.saved_to` -> a real file under `UPLOAD_DIR`) so
`GET /documents/{id}/file` actually serves real bytes and the frontend's
PDF.js-backed source viewer genuinely renders pages and highlights,
instead of the "no real file, page-only precision, honest notice only"
boundary every prior E2E fixture in this repo deliberately stayed within
(see source-intelligence-provenance-v2.spec.ts's own header comment).

Builds the REAL synthetic 8-page PDF (tests/fixtures/
clinical_reader_v3_pdf_fixture.py, Part 54) and its matching legacy
payload (page_payloads[*]["geometry"] included — real PyMuPDF-extracted
block/table/cell geometry, not hand-typed), writes the PDF to disk, then
runs the WHOLE thing through the REAL `reprocess_discharge_document`
pipeline (real table classification/routing, real geometry alignment,
real SourceEvidence bbox/field_bboxes_json) with only the AI
interpreter's model call swapped for a deterministic mocked response
(never live OpenAI) — same mocking convention as
seed_e2e_clinical_reader_v2_document.py. Every SourceEvidence row this
produces is the SAME shape/precision a real document would get; nothing
here hand-builds frontend evidence data.

Prints one JSON line to stdout: {token, user, patient_id, document_id}.
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
from app.main import UPLOAD_DIR  # noqa: E402
from app.services.clinical_document import ai_interpreter  # noqa: E402
from app.services.clinical_document.discharge_parser import parse_legacy_discharge_payload  # noqa: E402
from app.services.clinical_document.reprocessing import reprocess_discharge_document  # noqa: E402
from tests.fixtures.clinical_reader_v3_pdf_fixture import (  # noqa: E402
    ADMISSION_TEXT,
    ANOMALOUS_DATE_TEXT,
    BCR_ABL_TEXT,
    BONE_MARROW_TEXT,
    D45_TEXT,
    JAK2_TEXT,
    RECOMMENDATION_TEXT,
    ULTRASOUND_TEXT,
    build_synthetic_discharge_v3_fixture,
)


def _event_id_containing(document, text: str) -> str:
    return next(e.source_event_id for e in document.dated_events if text in e.raw_text)


def _section_id(document, canonical_key: str) -> str:
    return next(s.id for s in document.sections if s.canonical_key == canonical_key)


def _segment_id_containing(document, text: str) -> str:
    """Mirrors seed_e2e_clinical_reader_v2_document.py's own helper of
    the same name exactly — finds the specific segment id for a fact
    with no parseable date to anchor a ClinicalEvent to (the four
    page-4 narrative facts here: ultrasound/JAK2/bone marrow/BCR-ABL)."""
    for section in document.sections:
        paragraph_texts = [b.text for b in section.blocks if getattr(b, "type", None) == "paragraph"]
        if len(paragraph_texts) != len(section.source_segment_ids):
            continue
        for segment_id, block_text in zip(section.source_segment_ids, paragraph_texts):
            if text in block_text:
                return segment_id
    raise ValueError(f"No segment found containing {text!r}")


def _build_mock_interpretation(legacy_payload: dict):
    probe = parse_legacy_discharge_payload(legacy_payload)
    diagnoses_id = _section_id(probe, "diagnoses")
    clinical_course_id = _section_id(probe, "clinical_course")
    investigations_section_id = _section_id(probe, "investigations")

    admission_event_id = _event_id_containing(probe, "04.03.2026")
    anomalous_date_event_id = _event_id_containing(probe, ANOMALOUS_DATE_TEXT)

    d45_segment_id = _segment_id_containing(probe, D45_TEXT)
    ultrasound_segment_id = _segment_id_containing(probe, ULTRASOUND_TEXT)
    jak2_segment_id = _segment_id_containing(probe, JAK2_TEXT)
    bone_marrow_segment_id = _segment_id_containing(probe, BONE_MARROW_TEXT)
    bcr_abl_segment_id = _segment_id_containing(probe, BCR_ABL_TEXT)
    recommendation_segment_id = _segment_id_containing(probe, RECOMMENDATION_TEXT)

    def raw(_input):
        return {
            "diagnoses": [
                {
                    "code": "D45", "text": "Policitemie vera", "role": "principal",
                    "source_section_id": diagnoses_id, "source_event_ids": [],
                    "source_segment_ids": [d45_segment_id],
                },
            ],
            "investigations": [
                {
                    "investigation_type": "imaging", "title": "Ecografie abdominala",
                    "findings": "Splenomegalie moderata, diametru longitudinal 14 cm.", "conclusion": None,
                    "source_section_id": investigations_section_id, "source_event_ids": [],
                    "source_segment_ids": [ultrasound_segment_id],
                },
                {
                    "investigation_type": "molecular", "title": "JAK2 V617F",
                    "findings": "Mutatia JAK2 V617F pozitiva.", "conclusion": None,
                    "source_section_id": investigations_section_id, "source_event_ids": [],
                    "source_segment_ids": [jak2_segment_id],
                },
                {
                    "investigation_type": "pathology", "title": "Biopsie osteomedulara",
                    "findings": "Hipercelularitate cu hiperplazie a seriei eritroide.", "conclusion": None,
                    "source_section_id": investigations_section_id, "source_event_ids": [],
                    "source_segment_ids": [bone_marrow_segment_id],
                },
                {
                    "investigation_type": "molecular", "title": "BCR-ABL",
                    "findings": "Rezultat negativ.", "conclusion": "Exclude leucemia mieloida cronica.",
                    "source_section_id": investigations_section_id, "source_event_ids": [],
                    "source_segment_ids": [bcr_abl_segment_id],
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
                    "source_section_id": clinical_course_id, "source_event_ids": [admission_event_id],
                },
            ],
            "recommendations": [
                {
                    "category": "medication_recommendation",
                    "text": "Continuare tratament cu Besremi 150 micrograme subcutanat la doua saptamani.",
                    "source_section_id": None, "source_event_ids": [],
                    "source_segment_ids": [recommendation_segment_id],
                },
            ],
            "treatment_eras": [],
            "current_encounter": {
                "admission_date": "2026-03-04", "discharge_date": "2026-03-05",
                "section_ids": [], "event_ids": [admission_event_id],
            },
            "encounter_scope_assignments": [
                {"target_type": "event", "target_id": admission_event_id, "scope": "current"},
            ],
            "warnings": [],
        }

    return raw


def main() -> None:
    pdf_bytes, legacy_payload = build_synthetic_discharge_v3_fixture()
    ai_interpreter._call_model = _build_mock_interpretation(legacy_payload)

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:10]
        email = f"pw-e2e-geomv3-{suffix}@example.com"
        user = models.User(
            email=email,
            full_name="Playwright E2E Source Geometry V3",
            password_hash=hash_password("TestPass123!"),
            role="patient",
        )
        db.add(user)
        db.flush()

        patient = models.Patient(
            linked_user_id=user.id,
            full_name="Playwright E2E Source Geometry V3",
            cnp=f"600010{suffix[:7]}",
            public_id=f"brg-pat-e2e-{suffix}",
        )
        db.add(patient)
        db.flush()

        saved_filename = f"e2e-geometry-v3-{suffix}.pdf"
        saved_path = UPLOAD_DIR / saved_filename
        saved_path.write_bytes(pdf_bytes)

        doc = models.Document(
            patient_id=patient.id,
            uploaded_by_user_id=user.id,
            section="discharge_summary",
            filename="discharge-geometry-v3-fixture.pdf",
            content_type="application/pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary (Source Geometry V3 fixture)",
            created_at="2026-03-05T00:00:00Z",
            is_verified=True,
            saved_to=str(saved_path),
            note_body=json.dumps(legacy_payload, ensure_ascii=False),
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
