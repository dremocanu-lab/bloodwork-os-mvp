"""One-off, LOCAL-ONLY seed helper for the RightWorkspace Playwright
geometry regression (frontend/e2e/right-workspace-geometry.spec.ts).

Creates a real patient account + one laboratory_results Document + one
LabResult + one SourceEvidence row DIRECTLY via the ORM — deliberately
NOT through the real upload API, so this costs zero Reducto/OpenAI calls
and needs no external provider keys (mirrors the exact pattern
backend/tests/test_ask_bragi_service.py's own `patient_with_data`
fixture already uses for the same reason).

Prints one JSON line to stdout: {token, patient_id, document_id,
lab_id}. The Playwright spec shells out to this script, seeds via
stdout, and deletes the account via DELETE /my/account when done (which
cascades and removes everything created here) — see that spec file for
the corresponding teardown.

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


def main() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:10]
        email = f"pw-e2e-labdoc-{suffix}@example.com"
        user = models.User(
            email=email,
            full_name="Playwright E2E Lab Doc",
            password_hash=hash_password("TestPass123!"),
            role="patient",
        )
        db.add(user)
        db.flush()

        patient = models.Patient(
            linked_user_id=user.id,
            full_name="Playwright E2E Lab Doc",
            cnp=f"600010{suffix[:7]}",
            public_id=f"brg-pat-e2e-{suffix}",
        )
        db.add(patient)
        db.flush()

        doc = models.Document(
            patient_id=patient.id,
            section="bloodwork",
            filename="cbc.pdf",
            document_type="laboratory_results",
            report_name="Complete Blood Count",
            test_date="2026-01-01",
            created_at="2026-01-01T00:00:00Z",
            is_verified=True,
            public_id=f"brg-doc-e2e-{suffix}",
        )
        db.add(doc)
        db.flush()

        lab = models.LabResult(
            document_id=doc.id,
            raw_test_name="Platelets",
            canonical_name="platelet_count",
            display_name="Platelet Count",
            value="250",
            unit="10^3/uL",
            reference_range="150-400",
            observation_datetime="2026-01-01",
        )
        db.add(lab)
        db.flush()

        evidence = models.SourceEvidence(
            document_id=doc.id,
            lab_result_id=lab.id,
            page_number=1,
            source_text="Platelets 250 10^3/uL",
            created_at="2026-01-01T00:00:00Z",
        )
        db.add(evidence)
        db.commit()

        token = create_access_token({"sub": str(user.id), "role": "patient"})
        print(
            json.dumps(
                {
                    "token": token,
                    "user": {"id": user.id, "email": email, "full_name": user.full_name, "role": "patient"},
                    "patient_id": patient.id,
                    "document_id": doc.id,
                    "lab_id": lab.id,
                }
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
