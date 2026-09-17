"""One-off, LOCAL-ONLY seed helper for the Romanian discharge
classification closure Playwright regression
(frontend/e2e/romanian-discharge-classification.spec.ts).

Unlike seed_e2e_discharge_document.py (which hardcodes document_type=
"discharge_summary" directly on the Document row), this script derives
document_type/section from a REAL call to the legacy classifier
(document_classifier.classify_document_text) against the exact
"BILET DE IEȘIRE DIN SPITAL / SCRISOARE MEDICALĂ" + dense embedded-labs
text this session's fixture uses (tests/fixtures/synthetic_documents.py
ROMANIAN_DISCHARGE_BILET_DE_IESIRE) — the real bug boundary the prior
routing-consolidation pass never exercised (every existing "discharge
routing" Playwright/backend fixture starts from already-correct
hardcoded metadata; see docs/clinical_document_v3/ROUTER_AUDIT.md and
this session's own handoff section for the full accounting).

Asserts the classifier actually returns CLASSIFIED/discharge_summary
before persisting anything — if a future change ever regresses the
classifier, this script fails loudly instead of silently reverting to
hardcoded metadata and masking the regression.

Structured reader CONTENT reuses the already-proven-correct legacy
discharge JSON payload shape (parse_legacy_discharge_payload) — this
fixture is deliberately NOT about proving structured-parsing
correctness (covered elsewhere), only that a document whose
document_type/section came from REAL classification renders in the
real Phase 8 reader exactly like one with hardcoded metadata does.

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
from app.services.document_classifier import CLASSIFIED, classify_document_text  # noqa: E402
from app.services.document_taxonomy import legacy_section_for  # noqa: E402
from app.services.clinical_document.discharge_parser import parse_legacy_discharge_payload  # noqa: E402
from app.services.clinical_document.persistence import serialize_structured_document  # noqa: E402
from tests.fixtures.synthetic_documents import ROMANIAN_DISCHARGE_BILET_DE_IESIRE  # noqa: E402

DISCHARGE_PAYLOAD = {
    "document_type": "discharge_summary",
    "hospital_name": "Spitalul Clinic Județean de Urgență",
    "admission_date": "04.03.2026",
    "discharge_date": "05.03.2026",
    "sections": [
        {
            "key": "epicriza",
            "title": "EPICRIZĂ",
            "body": (
                "Pacienta s-a internat in sectia de Hematologie pentru evaluarea "
                "unui sindrom anemic cronic. S-a stabilit diagnosticul de "
                "Policitemia vera (D45)."
            ),
        },
        {"key": "diagnoses", "title": "Diagnostic la externare", "body": "D45 Policitemia vera."},
        {
            "key": "recomandari",
            "title": "Recomandări la externare",
            "body": "Control hematologic peste 4 saptamani, continuarea tratamentului cu hidroxiuree.",
        },
    ],
}


def main() -> None:
    # The real bug boundary this fixture exists to close: derive
    # document_type/section from the ACTUAL classifier, never hardcode it.
    classification = classify_document_text(ROMANIAN_DISCHARGE_BILET_DE_IESIRE)
    assert classification.status == CLASSIFIED, (
        f"expected the real classifier to confidently classify the BILET DE IEȘIRE "
        f"fixture, got status={classification.status!r} candidates={classification.candidates!r} "
        f"— this fixture depends on that classification, not a hardcoded assumption"
    )
    assert classification.document_type.value == "discharge_summary", (
        f"expected discharge_summary, got {classification.document_type.value!r}"
    )

    document_type = classification.document_type.value
    section = legacy_section_for(classification.document_type)

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:10]
        email = f"pw-e2e-bilet-{suffix}@example.com"
        user = models.User(
            email=email,
            full_name="Playwright E2E Bilet De Iesire",
            password_hash=hash_password("TestPass123!"),
            role="patient",
        )
        db.add(user)
        db.flush()

        patient = models.Patient(
            linked_user_id=user.id,
            full_name="Playwright E2E Bilet De Iesire",
            cnp=f"600010{suffix[:7]}",
            public_id=f"brg-pat-e2e-{suffix}",
        )
        db.add(patient)
        db.flush()

        structured = parse_legacy_discharge_payload(DISCHARGE_PAYLOAD)
        doc = models.Document(
            patient_id=patient.id,
            uploaded_by_user_id=user.id,
            section=section,
            filename="bilet_de_iesire.pdf",
            content_type="application/pdf",
            document_type=document_type,
            classification_status=classification.status,
            classification_confidence=classification.confidence,
            classification_source="legacy_rules",
            report_name="Bilet de ieșire din spital",
            created_at="2026-03-05T00:00:00Z",
            is_verified=True,
            note_body=serialize_structured_document(structured),
            public_id=f"brg-doc-e2e-{suffix}",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        token = create_access_token({"sub": str(user.id), "role": "patient"})
        print(
            json.dumps(
                {
                    "token": token,
                    "user": {"id": user.id, "email": email, "full_name": user.full_name, "role": "patient"},
                    "patient_id": patient.id,
                    "document_id": doc.id,
                    "classification_candidates": classification.candidates,
                }
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
