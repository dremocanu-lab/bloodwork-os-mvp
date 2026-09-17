"""One-off, LOCAL-ONLY seed helper for the processing-indicator dot
geometry Playwright regression (frontend/e2e/processing-indicator.spec.ts).

Creates a real patient account + one UploadJob row directly via the ORM
with status="processing" (bypassing the real upload/classification
pipeline entirely) so the "N document(s) is/are being processed" banner
on My Records renders deterministically, with zero external API cost and
no dependency on a real file actually completing processing.

Prints one JSON line to stdout: {token, patient_id}. The Playwright spec
shells out to this script, seeds via stdout, and deletes the account via
DELETE /my/account when done (which cascades and removes the job too).

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
from app.core.utils import now_iso  # noqa: E402
from app.db import SessionLocal  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:10]
        email = f"pw-e2e-processing-{suffix}@example.com"
        user = models.User(
            email=email,
            full_name="Playwright E2E Processing",
            password_hash=hash_password("TestPass123!"),
            role="patient",
        )
        db.add(user)
        db.flush()

        patient = models.Patient(
            linked_user_id=user.id,
            full_name="Playwright E2E Processing",
            cnp=f"600010{suffix[:7]}",
            public_id=f"brg-pat-e2e-{suffix}",
        )
        db.add(patient)
        db.flush()

        job = models.UploadJob(
            user_id=user.id,
            patient_id=patient.id,
            section="bloodwork",
            filename="in_progress.pdf",
            content_type="application/pdf",
            saved_to="/tmp/does-not-need-to-exist.pdf",
            status="processing",
            progress=40,
            message="Classifying document...",
            created_at=now_iso(),
            started_at=now_iso(),
        )
        db.add(job)
        db.commit()

        token = create_access_token({"sub": str(user.id), "role": "patient"})
        print(
            json.dumps(
                {
                    "token": token,
                    "user": {"id": user.id, "email": email, "full_name": user.full_name, "role": "patient"},
                    "patient_id": patient.id,
                }
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
