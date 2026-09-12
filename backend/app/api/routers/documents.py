"""Documents / uploads routes (BRAGI backend modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"documents/uploads" domain — large, high fan-out, upload pipeline). This
is the largest domain extracted so far in Phase 4; extra care was taken
to map every dependency before moving anything (see below).

Includes GET /patients/by-public-id/{public_id}, which conceptually
belongs to the "patients (core/PCP/search)" domain per
docs/refactor/AUTHORIZATION_MAP.md — it is grouped here because the
original code itself groups it with GET /documents/by-public-id/{public_id}
under one "Public-ID lookup endpoints (pretty URL resolution)" comment,
and it shares no other state with this domain. Moving both together
(rather than splitting a two-route comment block across two extraction
commits) follows both routes' own physical/logical pairing in the
source.

Several helpers stay in app.main and are imported lazily (inside each
function body, not at module load time) because they are still shared
with domains not yet extracted, or with the pipeline entry point itself:

- `process_upload_job` — the ~700-line upload-processing pipeline
  (Reducto/OCR/security-scan/classification/identity-check). It is
  triggered by routes here (via BackgroundTasks or the worker pool) but
  is not itself route-handling logic, and per Phase 4's own instruction
  not to combine "move route" with "rewrite architecture," it is left
  in place rather than moved or re-homed in this pass.
- `serialize_document_card` — shared with the not-yet-extracted
  patients/account domain's profile response.
- `get_document_payload` — shared with the not-yet-extracted emergency
  domain's `/emergency/documents/{id}` route.
- `add_audit_log` — a general-purpose audit helper used across nearly
  every domain (per docs/refactor/BACKEND_DECOMPOSITION_PLAN.md's own
  "stays in main.py" list).
- `ensure_patient_for_user` — belongs with the not-yet-extracted
  care-partner-code creation cluster (same reasoning as in
  app/api/routers/medications.py and assignments.py).
- `UPLOAD_DIR` — a plain Path constant, but also read by
  `process_upload_job` in app.main, so it is defined exactly once there
  (including its one-time `mkdir` side effect) rather than duplicated.

`care_partner_can_access_document` is NOT lazily imported: it had no
caller outside this domain, so it was relocated (not merely
lazy-referenced) into app/policies/access.py, alongside its sibling
IDOR-prevention helpers `can_access_patient`/`doctor_has_patient_access`
— per docs/refactor/AUTHORIZATION_MAP.md, all three are the canonical
checks any future centralization must call, never re-implement.

Upload-validation config/logic that had no caller outside this domain
(`_validate_upload_extension`, `_read_and_validate_upload`,
`ALLOWED_UPLOAD_EXTENSIONS`, `UPLOAD_MAGIC_BYTES`,
`MAX_UPLOAD_SIZE_BYTES`, `ALLOWED_SECTIONS`, `UPLOAD_JOB_POOL`,
`resolve_upload_patient`, `_save_incoming_file`, `serialize_upload_job`)
moved here in full, unchanged.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_current_user, get_db, require_role
from app.core.utils import _mask_cnp, now_iso
from app.policies.access import (
    can_access_patient,
    care_partner_can_access_document,
    doctor_has_patient_access,
    get_patient_for_user,
)
from app.rate_limit import RateLimiter
from app.services.document_taxonomy import (
    AUTO_CLASSIFY_SECTION,
    document_type_choices,
    is_valid_document_type,
    legacy_section_for,
)

router = APIRouter()

# File-upload hardening — see docs/security/THREAT_MODEL.md "malicious
# upload." Every format the product actually offers today (the frontend's
# getFileBadge()/accept list): PDF, common raster images, and
# doc/docx (accepted even though no current extraction path reads them,
# to avoid narrowing an already-advertised upload capability). Nothing
# else — in particular, no executable/script/archive extension is ever
# accepted, regardless of what Content-Type a client claims.
ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".doc", ".docx",
}
# Real byte-signature ("magic number") prefixes for the formats above that
# have one — a client-supplied filename/Content-Type can lie, but the
# actual first bytes of the file are real. doc/docx aren't included: doc
# is an OLE/CFB container and docx is a zip, both crossing into "worth a
# real parsing library, not a hand-rolled prefix check" territory — their
# risk is already bounded by the extension allowlist above plus the
# separate size cap, so this is intentionally scoped to formats a simple,
# unambiguous prefix genuinely identifies.
UPLOAD_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),  # full container check (RIFF....WEBP) below
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
}
MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024

ALLOWED_SECTIONS = {
    "notes",
    "bloodwork",
    "discharge_summary",
    "medications",
    "scans",
    "hospitalizations",
    "other",
}

# Bounded concurrency for multi-file batch uploads (POST /upload/batch): a
# batch's files are dispatched to this pool instead of FastAPI's
# BackgroundTasks, which runs tasks strictly one-at-a-time in-process — a
# fast file (e.g. a 1-page prescription) had to wait for every earlier file
# in the batch to fully finish (each making several real Reducto HTTP
# calls) before it even started. A small fixed pool gives real, bounded
# parallelism — not unbounded concurrent Reducto requests — while
# process_upload_job stays exactly as safe to call from a worker thread as
# it already was from BackgroundTasks (it opens its own SessionLocal()
# per call; no shared mutable state between jobs).
UPLOAD_JOB_POOL = ThreadPoolExecutor(
    max_workers=int(os.getenv("UPLOAD_JOB_CONCURRENCY", "3")), thread_name_prefix="upload-job"
)


def _validate_upload_extension(original_filename: str) -> str:
    """Returns the lowercased, validated extension or raises 400. Extension
    is what decides ACCEPT/REJECT — Content-Type is client-supplied and
    only used later for the response's Content-Type header (unchanged
    behavior), never for this decision."""
    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix or '(none)'}'. Allowed: {allowed}.",
        )
    return suffix


async def _read_and_validate_upload(file: UploadFile, suffix: str) -> bytes:
    """Reads the whole upload into memory, enforcing the size cap while
    reading (never trusts a Content-Length header, which a client can
    misstate) and, where a real signature exists for this extension,
    verifying the first bytes actually match it — a spoofed extension on
    an unrelated file type is rejected before ever touching disk."""
    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB upload limit.",
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    signatures = UPLOAD_MAGIC_BYTES.get(suffix)
    if signatures:
        if suffix == ".webp":
            valid = data.startswith(b"RIFF") and data[8:12] == b"WEBP"
        else:
            valid = any(data.startswith(sig) for sig in signatures)
        if not valid:
            raise HTTPException(
                status_code=400,
                detail=f"File content doesn't match its '{suffix}' extension.",
            )
    return data


def serialize_upload_job(job) -> dict:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "patient_id": job.patient_id,
        "section": job.section if job.section != AUTO_CLASSIFY_SECTION else None,
        "filename": job.filename,
        "content_type": job.content_type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "document_id": job.document_id,
        "document_type": job.document_type,
        "classification_status": job.classification_status,
        "classification_confidence": job.classification_confidence,
        "identity_status": job.identity_status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def resolve_upload_patient(db: Session, current_user: models.User, patient_id: int | None = None):
    from app.main import ensure_patient_for_user

    if current_user.role == "patient":
        patient = ensure_patient_for_user(db, current_user)

        if not patient:
            raise HTTPException(status_code=404, detail="Patient profile not found.")

        return patient

    if current_user.role == "doctor":
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required for doctor uploads.")

        patient = (
            db.query(models.Patient)
            .filter(models.Patient.id == patient_id)
            .first()
        )

        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        if not doctor_has_patient_access(db, current_user.id, patient.id):
            raise HTTPException(status_code=403, detail="You do not have access to this patient.")

        return patient

    if current_user.role == "admin":
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required for admin uploads.")

        patient = (
            db.query(models.Patient)
            .filter(models.Patient.id == patient_id)
            .first()
        )

        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        return patient

    if current_user.role == "care_partner":
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required for care partner uploads.")

        patient = (
            db.query(models.Patient)
            .filter(models.Patient.id == patient_id)
            .first()
        )

        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        link = (
            db.query(models.CarePartnerPatientLink)
            .filter(
                models.CarePartnerPatientLink.care_partner_user_id == current_user.id,
                models.CarePartnerPatientLink.patient_id == patient_id,
            )
            .first()
        )

        if not link:
            raise HTTPException(status_code=403, detail="You are not linked to this patient.")

        return patient

    raise HTTPException(status_code=403, detail="Invalid user role.")


async def _save_incoming_file(file: UploadFile) -> tuple[str, str]:
    """Save an uploaded file to UPLOAD_DIR under a randomized name.

    Returns (original_filename, saved_path). Shared by the batch upload
    endpoint; the single-file endpoints above intentionally keep their
    own inline copy of this logic unchanged.
    """
    import uuid

    from app.main import UPLOAD_DIR

    original_filename = file.filename or "uploaded_document"
    _safe_ext = _validate_upload_extension(original_filename)
    file_data = await _read_and_validate_upload(file, _safe_ext)
    saved_filename = f"{uuid.uuid4().hex}{_safe_ext}"
    saved_path = UPLOAD_DIR / saved_filename

    try:
        saved_path.write_bytes(file_data)
    except Exception as save_error:
        # Full detail (which can include server-side I/O/OS error text — e.g.
        # actual filesystem paths) goes to server logs only; the client gets
        # a generic message. See docs/security/THREAT_MODEL.md — "verbose
        # error disclosure."
        print(f"UPLOAD SAVE FAILED: {save_error}")
        raise HTTPException(status_code=500, detail="Could not save uploaded file.")
    finally:
        try:
            await file.close()
        except Exception:
            pass

    return original_filename, str(saved_path)


@router.get("/patients/{patient_id}/documents")
def get_patient_documents(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    from app.main import serialize_document_card

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if current_user.role == "doctor" and not doctor_has_patient_access(db, current_user.id, patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    documents = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient_id)
        .order_by(models.Document.id.desc())
        .all()
    )

    return {
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age": patient.age,
            "sex": patient.sex,
            # Masked — this is a document-list view, not an identity/edit
            # workflow; see build_patient_profile_response for the one
            # place the full value is returned.
            "cnp": _mask_cnp(patient.cnp),
            "patient_identifier": patient.patient_identifier,
        },
        "documents": [serialize_document_card(db, document, current_user) for document in documents],
    }


@router.post("/upload/background")
async def create_background_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    section: str = Form("bloodwork"),
    patient_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="upload")),
):
    import uuid

    from app.main import UPLOAD_DIR, process_upload_job

    if section not in ALLOWED_SECTIONS:
        raise HTTPException(status_code=400, detail="Invalid document section")

    patient = resolve_upload_patient(db, current_user, patient_id)

    original_filename = file.filename or "uploaded_document"
    _safe_ext = _validate_upload_extension(original_filename)
    file_data = await _read_and_validate_upload(file, _safe_ext)
    saved_filename = f"{uuid.uuid4().hex}{_safe_ext}"
    saved_path = UPLOAD_DIR / saved_filename

    try:
        saved_path.write_bytes(file_data)
    except Exception as save_error:
        # Full detail (which can include server-side I/O/OS error text — e.g.
        # actual filesystem paths) goes to server logs only; the client gets
        # a generic message. See docs/security/THREAT_MODEL.md — "verbose
        # error disclosure."
        print(f"UPLOAD SAVE FAILED: {save_error}")
        raise HTTPException(status_code=500, detail="Could not save uploaded file.")
    finally:
        try:
            await file.close()
        except Exception:
            pass

    job = models.UploadJob(
        user_id=current_user.id,
        patient_id=patient.id,
        section=section,
        filename=original_filename,
        content_type=file.content_type,
        saved_to=str(saved_path),
        status="queued",
        progress=0,
        message="Queued for processing.",
        error=None,
        document_id=None,
        created_at=now_iso(),
        started_at=None,
        finished_at=None,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(process_upload_job, job.id)

    return serialize_upload_job(job)


@router.post("/upload")
async def upload_compatibility_route(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    section: str = Form("bloodwork"),
    patient_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="upload")),
):
    return await create_background_upload(
        background_tasks=background_tasks,
        file=file,
        section=section,
        patient_id=patient_id,
        db=db,
        current_user=current_user,
    )


@router.get("/document-types")
def get_document_types(current_user=Depends(get_current_user)):
    return document_type_choices()


@router.post("/upload/batch")
async def create_batch_upload(
    files: list[UploadFile] = File(...),
    patient_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="upload")),
):
    """Independent multi-file ingestion.

    Each file becomes its own UploadJob and is classified + processed
    independently (see process_upload_job) — one bad or ambiguous file
    never blocks the others. No `section` is accepted here: document type
    is always determined from content.
    """
    from app.main import process_upload_job

    if not files:
        raise HTTPException(status_code=400, detail="No files were provided.")

    patient = resolve_upload_patient(db, current_user, patient_id)

    created_jobs = []

    for file in files:
        try:
            original_filename, saved_path = await _save_incoming_file(file)
        except HTTPException as save_error:
            created_jobs.append(
                {
                    "filename": file.filename or "uploaded_document",
                    "status": "error",
                    "error": save_error.detail,
                }
            )
            continue

        job = models.UploadJob(
            user_id=current_user.id,
            patient_id=patient.id,
            section=AUTO_CLASSIFY_SECTION,
            filename=original_filename,
            content_type=file.content_type,
            saved_to=saved_path,
            status="queued",
            progress=0,
            message="Queued for processing.",
            error=None,
            document_id=None,
            created_at=now_iso(),
            started_at=None,
            finished_at=None,
        )

        db.add(job)
        db.commit()
        db.refresh(job)

        # Bounded worker pool, not BackgroundTasks — see UPLOAD_JOB_POOL's
        # definition. Each file starts processing as soon as a worker slot
        # frees up, instead of strictly after every earlier file in the
        # batch has fully finished.
        UPLOAD_JOB_POOL.submit(process_upload_job, job.id)
        created_jobs.append(serialize_upload_job(job))

    return created_jobs


class ConfirmDocumentTypeRequest(BaseModel):
    document_type: str


@router.post("/upload-jobs/{job_id}/confirm-type")
def confirm_upload_job_document_type(
    job_id: int,
    payload: ConfirmDocumentTypeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Resolve a needs_confirmation upload job with a user-chosen type.

    This is the only path that resumes a job stuck in needs_confirmation —
    see the classification block in process_upload_job.
    """
    from app.main import process_upload_job

    job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Upload job not found")

    if job.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    if job.status != "needs_confirmation":
        raise HTTPException(status_code=400, detail="This upload is not awaiting confirmation.")

    if not is_valid_document_type(payload.document_type):
        raise HTTPException(status_code=400, detail="Unknown document type.")

    job.document_type = payload.document_type
    job.section = legacy_section_for(payload.document_type)
    job.classification_status = "classified"
    job.classification_source = "user_confirmed"
    job.status = "queued"
    job.progress = 0
    job.message = "Confirmed. Processing..."
    job.error = None
    db.commit()
    db.refresh(job)

    background_tasks.add_task(process_upload_job, job.id)

    return serialize_upload_job(job)


class ConfirmIdentityRequest(BaseModel):
    confirmed: bool


@router.post("/upload-jobs/{job_id}/confirm-identity")
def confirm_upload_job_identity(
    job_id: int,
    payload: ConfirmIdentityRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Resolve a needs_identity_confirmation upload job.

    `confirmed=True` is an audited manual override: the uploader asserts
    this document is really theirs despite the ambiguous signal, and
    reprocessing skips the identity check this one time
    (UploadJob.identity_override). `confirmed=False` sets the job aside —
    nothing was persisted yet (see process_upload_job), so there is
    nothing to quarantine.
    """
    from app.main import process_upload_job

    job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Upload job not found")

    if job.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    if job.status != "needs_identity_confirmation":
        raise HTTPException(status_code=400, detail="This upload is not awaiting identity confirmation.")

    if not payload.confirmed:
        job.status = "quarantined"
        job.progress = 100
        job.message = "Set aside — not associated with your record."
        job.finished_at = now_iso()
        db.commit()
        return serialize_upload_job(job)

    job.identity_override = 1
    job.identity_status = None
    job.status = "queued"
    job.progress = 0
    job.message = "Confirmed. Processing..."
    job.error = None
    db.commit()
    db.refresh(job)

    background_tasks.add_task(process_upload_job, job.id)

    return serialize_upload_job(job)


class IdentityReviewRequest(BaseModel):
    action: str  # "confirm_mine" | "reject"


@router.get("/documents/quarantined")
def get_quarantined_documents(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Documents set aside for a wrong-patient identity mismatch.

    Patients see quarantined documents intended for their own record;
    admins see everything. Doctors do not have a review surface here yet
    (out of scope for this phase — see BRAGI_REDUCTO_PLAN.md).
    """
    from app.main import ensure_patient_for_user

    query = db.query(models.Document).filter(models.Document.review_status == "quarantined")

    if current_user.role == "admin":
        pass
    elif current_user.role == "patient":
        patient = ensure_patient_for_user(db, current_user)
        if not patient:
            return []
        query = query.filter(models.Document.intended_patient_id == patient.id)
    else:
        raise HTTPException(status_code=403, detail="Forbidden")

    documents = query.order_by(models.Document.id.desc()).all()

    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "document_type": doc.document_type,
            "created_at": doc.created_at,
            "identity_status": doc.identity_status,
        }
        for doc in documents
    ]


@router.post("/documents/{document_id}/identity-review")
def review_quarantined_document(
    document_id: int,
    payload: IdentityReviewRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.main import add_audit_log, ensure_patient_for_user, process_upload_job

    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.review_status != "quarantined":
        raise HTTPException(status_code=400, detail="This document is not awaiting identity review.")

    if current_user.role == "admin":
        pass
    elif current_user.role == "patient":
        patient = ensure_patient_for_user(db, current_user)
        if not patient or document.intended_patient_id != patient.id:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        raise HTTPException(status_code=403, detail="Forbidden")

    if payload.action == "reject":
        document.review_status = "resolved_rejected"
        db.commit()

        add_audit_log(
            db=db,
            document_id=document.id,
            action="quarantine_rejected",
            actor=current_user.full_name,
            details="Uploader confirmed this document does not belong to them.",
        )
        db.commit()

        return {"ok": True, "document_id": document.id, "review_status": document.review_status}

    if payload.action == "confirm_mine":
        if not document.intended_patient_id:
            raise HTTPException(status_code=400, detail="This document has no intended patient to confirm.")

        job = models.UploadJob(
            user_id=current_user.id,
            patient_id=document.intended_patient_id,
            section=(legacy_section_for(document.document_type) if document.document_type else AUTO_CLASSIFY_SECTION),
            filename=document.filename,
            content_type=document.content_type,
            saved_to=document.saved_to,
            status="queued",
            progress=0,
            message="Reprocessing after identity confirmation...",
            error=None,
            document_id=None,
            file_sha256=document.file_sha256,
            identity_override=1,
            created_at=now_iso(),
            started_at=None,
            finished_at=None,
        )

        db.add(job)
        document.review_status = "resolved_confirmed"
        db.commit()
        db.refresh(job)

        add_audit_log(
            db=db,
            document_id=document.id,
            action="identity_manually_confirmed",
            actor=current_user.full_name,
            details=f"Uploader confirmed this document is theirs; reprocessing as upload job {job.id}.",
        )
        db.commit()

        background_tasks.add_task(process_upload_job, job.id)

        return {"ok": True, "document_id": document.id, "new_upload_job": serialize_upload_job(job)}

    raise HTTPException(status_code=400, detail="Unknown action.")


@router.get("/upload-jobs")
def get_my_upload_jobs(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    jobs = (
        db.query(models.UploadJob)
        .filter(models.UploadJob.user_id == current_user.id)
        .order_by(models.UploadJob.id.desc())
        .limit(30)
        .all()
    )

    return [serialize_upload_job(job) for job in jobs]


@router.get("/upload-jobs/{job_id}")
def get_upload_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Upload job not found")

    if job.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    return serialize_upload_job(job)


@router.get("/documents/{document_id}")
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.main import get_document_payload, mark_doctor_reviewed_document

    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if current_user.role == "care_partner":
        if not care_partner_can_access_document(db, current_user.id, document_id):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if current_user.role == "doctor":
        mark_doctor_reviewed_document(db, current_user.id, document.id)
        db.commit()

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    audit_logs = db.query(models.AuditLog).filter(models.AuditLog.document_id == document.id).all()

    return get_document_payload(db, document, labs, audit_logs, current_user)


# ── Public-ID lookup endpoints (pretty URL resolution) ────────────────────────

@router.get("/patients/by-public-id/{public_id}")
def get_patient_by_public_id(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.public_id == public_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    if current_user.role == "patient":
        if patient.linked_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied.")
    elif current_user.role in ("doctor",):
        if not doctor_has_patient_access(db, current_user.id, patient.id):
            raise HTTPException(status_code=403, detail="No active access to this patient.")
    elif current_user.role == "care_partner":
        link = (
            db.query(models.CarePartnerPatientLink)
            .filter(
                models.CarePartnerPatientLink.care_partner_user_id == current_user.id,
                models.CarePartnerPatientLink.patient_id == patient.id,
            )
            .first()
        )
        if not link:
            raise HTTPException(status_code=403, detail="Access denied.")
    elif current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied.")
    return {"id": patient.id, "public_id": patient.public_id}


@router.get("/documents/by-public-id/{public_id}")
def get_document_by_public_id(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.public_id == public_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    if current_user.role == "care_partner":
        if not care_partner_can_access_document(db, current_user.id, document.id):
            raise HTTPException(status_code=403, detail="Forbidden.")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden.")
    return {"id": document.id, "public_id": document.public_id}


@router.get("/documents/{document_id}/file")
def get_document_file(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=120, window_seconds=300, key_prefix="source_retrieval")),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if current_user.role == "care_partner":
        raise HTTPException(status_code=403, detail="Care partners cannot access raw document files.")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not document.saved_to:
        raise HTTPException(status_code=404, detail="File path not found")

    file_path = Path(document.saved_to)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")

    return FileResponse(
        path=str(file_path),
        filename=document.filename,
        media_type=document.content_type or "application/octet-stream",
    )


class LabResultUpdate(BaseModel):
    raw_test_name: str | None = None
    canonical_name: str | None = None
    display_name: str | None = None
    category: str | None = None
    source_section: str | None = None
    value: str | None = None
    flag: str | None = None
    reference_range: str | None = None
    unit: str | None = None


class ParsedDataUpdate(BaseModel):
    patient_name: str | None = None
    date_of_birth: str | None = None
    age: str | None = None
    sex: str | None = None
    cnp: str | None = None
    patient_identifier: str | None = None
    lab_name: str | None = None
    sample_type: str | None = None
    referring_doctor: str | None = None
    report_name: str | None = None
    report_type: str | None = None
    source_language: str | None = None
    test_date: str | None = None
    collected_on: str | None = None
    reported_on: str | None = None
    registered_on: str | None = None
    generated_on: str | None = None
    note_body: str | None = None
    labs: list[LabResultUpdate] = Field(default_factory=list)


class DocumentUpdateRequest(BaseModel):
    parsed_data: ParsedDataUpdate
    editor_name: str | None = "Manual User"


class VerifyRequest(BaseModel):
    verifier_name: str | None = "Manual Reviewer"


@router.put("/documents/{document_id}")
def update_document(
    document_id: int,
    payload: DocumentUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.main import add_audit_log, get_document_payload

    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    parsed = payload.parsed_data

    document.patient_name = parsed.patient_name
    document.date_of_birth = parsed.date_of_birth
    document.age = parsed.age
    document.sex = parsed.sex
    document.cnp = parsed.cnp
    document.patient_identifier = parsed.patient_identifier
    document.lab_name = parsed.lab_name
    document.sample_type = parsed.sample_type
    document.referring_doctor = parsed.referring_doctor
    document.report_name = parsed.report_name
    document.report_type = parsed.report_type
    document.source_language = parsed.source_language
    document.test_date = parsed.test_date
    document.collected_on = parsed.collected_on
    document.reported_on = parsed.reported_on
    document.registered_on = parsed.registered_on
    document.generated_on = parsed.generated_on
    document.note_body = parsed.note_body
    document.last_edited_at = now_iso()

    db.query(models.LabResult).filter(models.LabResult.document_id == document.id).delete()

    for lab in parsed.labs:
        db.add(
            models.LabResult(
                document_id=document.id,
                raw_test_name=lab.raw_test_name,
                canonical_name=lab.canonical_name,
                display_name=lab.display_name,
                category=lab.category,
                source_section=lab.source_section,
                value=lab.value,
                flag=lab.flag,
                reference_range=lab.reference_range,
                unit=lab.unit,
            )
        )

    add_audit_log(
        db=db,
        document_id=document.id,
        action="edited",
        actor=payload.editor_name or current_user.full_name,
        details="Structured fields were manually edited.",
    )

    db.commit()
    db.refresh(document)

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    audit_logs = db.query(models.AuditLog).filter(models.AuditLog.document_id == document.id).all()

    return get_document_payload(db, document, labs, audit_logs, current_user)


@router.post("/documents/{document_id}/verify")
def verify_document(
    document_id: int,
    payload: VerifyRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.main import add_audit_log, get_document_payload

    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    document.is_verified = True
    document.verified_by = payload.verifier_name or current_user.full_name
    document.verified_at = now_iso()

    add_audit_log(
        db=db,
        document_id=document.id,
        action="verified",
        actor=document.verified_by,
        details="Document was verified.",
    )

    db.commit()
    db.refresh(document)

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    audit_logs = db.query(models.AuditLog).filter(models.AuditLog.document_id == document.id).all()

    return get_document_payload(db, document, labs, audit_logs, current_user)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if current_user.role == "patient":
        patient = get_patient_for_user(db, current_user.id)

        if not patient or patient.id != document.patient_id:
            raise HTTPException(status_code=403, detail="Forbidden")

    saved_to = document.saved_to

    db.query(models.NoteDocumentLink).filter(
        (models.NoteDocumentLink.note_document_id == document.id)
        | (models.NoteDocumentLink.linked_document_id == document.id)
    ).delete(synchronize_session=False)

    db.query(models.DoctorDocumentReview).filter(
        models.DoctorDocumentReview.document_id == document.id
    ).delete(synchronize_session=False)

    db.query(models.UploadJob).filter(
        models.UploadJob.document_id == document.id
    ).update({"document_id": None}, synchronize_session=False)

    db.delete(document)
    db.commit()

    if saved_to:
        try:
            path = Path(saved_to)
            if path.exists():
                path.unlink()
        except Exception:
            pass

    return {"ok": True, "deleted_document_id": document_id}
