"""One-off, LOCAL-ONLY seed helper for the security-quarantine status
Playwright regression (frontend/e2e/upload-reliability.spec.ts).

Creates a real patient account + one UploadJob row directly via the ORM
with status="security_quarantined" (the real backend terminal state
process_upload_job's security-scan block sets — see app/main.py, the
`if scan_result.blocks_processing:` branch) — bypassing the real
upload/scan pipeline entirely so this renders deterministically, with
zero external API cost.

Prints one JSON line to stdout: {token, patient_id}. The Playwright spec
shells out to this script, seeds via stdout, and deletes the account via
DELETE /my/account when done.

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
        email = f"pw-e2e-quarantine-{suffix}@example.com"
        user = models.User(
            email=email,
            full_name="Playwright E2E Quarantine",
            password_hash=hash_password("TestPass123!"),
            role="patient",
        )
        db.add(user)
        db.flush()

        patient = models.Patient(
            linked_user_id=user.id,
            full_name="Playwright E2E Quarantine",
            cnp=f"600010{suffix[:7]}",
            public_id=f"brg-pat-e2e-{suffix}",
        )
        db.add(patient)
        db.flush()

        job = models.UploadJob(
            user_id=user.id,
            patient_id=patient.id,
            section="bloodwork",
            filename="suspicious.pdf",
            content_type="application/pdf",
            saved_to="/tmp/does-not-need-to-exist.pdf",
            status="security_quarantined",
            progress=100,
            message="This file could not be processed and has been set aside for security review.",
            error="security_scan:heuristic",
            created_at=now_iso(),
            started_at=now_iso(),
            # Deliberately left unset: the real backend always sets this
            # for a genuinely finished job, but the frontend's own
            # "hide a finished upload row after 7s" cleanup
            # (shouldShowFinished, upload-provider.tsx) is a SEPARATE,
            # already-correct, unrelated behavior this fixture isn't
            # about — setting finished_at here would make this e2e test
            # racy against that 7-second window for no reason. This
            # fixture exists to prove status="security_quarantined"
            # itself maps to the right UI state, not to re-prove the
            # unrelated cleanup timer works.
            finished_at=None,
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
