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

import json
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
from app.services import source_evidence as source_evidence_service
from app.services.document_taxonomy import (
    AUTO_CLASSIFY_SECTION,
    document_type_choices,
    is_valid_document_type,
    legacy_section_for,
)

router = APIRouter()

# File-upload hardening — see docs/security/THREAT_MODEL.md "malicious
# upload" and docs/ingestion/FORMAT_CAPABILITY_MATRIX.md. The extension
# allowlist is now DERIVED from app.services.ingestion.capability_registry
# — the one source of truth for every format this product accepts —
# rather than a second, independently-maintained list. In particular, no
# executable/script/archive/macro-enabled-Office extension is ever
# accepted, regardless of what Content-Type a client claims (see the
# registry's own EXPLICITLY_REJECTED_EXTENSIONS for the named list of
# what's deliberately excluded).
from app.services.ingestion.capability_registry import FORMAT_CAPABILITIES, allowed_upload_extensions

ALLOWED_UPLOAD_EXTENSIONS = set(allowed_upload_extensions())
# Real byte-signature ("magic number") prefixes for the formats above that
# have one — a client-supplied filename/Content-Type can lie, but the
# actual first bytes of the file are real. Formats with no simple
# fixed-offset prefix (legacy .doc/.xls's OLE container is shared with
# genuinely different real formats; HEIC/HEIF's ISO-BMFF box format; a
# spreadsheet/text/JSON/XML format with no magic number at all) are
# intentionally excluded here — their risk is bounded by the extension
# allowlist, the size cap, and (for the zip/OLE-based Office formats) the
# decompression-bomb/macro/encryption checks every ingestion adapter runs
# before real parsing — see app/services/ingestion/security.py.
UPLOAD_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    ext: cap.magic_bytes for ext, cap in FORMAT_CAPABILITIES.items() if cap.magic_bytes
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

# A doctor/care-partner manual upload (POST /upload/background) picks a
# legacy `section` from a coarse 6-value picklist, never runs the real
# classifier (see process_upload_job's `if job.section ==
# AUTO_CLASSIFY_SECTION` gate), and so has always left `document_type`
# NULL even when the user's own choice is completely unambiguous — a
# real, previously-deferred gap (docs/clinical_document_v3/
# ROUTER_AUDIT.md's "Deliberately not changed"), not a guess. Only
# `discharge_summary`/`bloodwork` map 1:1 onto exactly one
# `DocumentType` each (`document_taxonomy.LEGACY_SECTION_BY_DOCUMENT_
# TYPE`'s own inverse); `medications`/`scans`/`hospitalizations`/`other`
# each cover multiple real document types and are deliberately NOT
# guessed here.
UNAMBIGUOUS_SECTION_DOCUMENT_TYPE = {
    "discharge_summary": "discharge_summary",
    "bloodwork": "laboratory_results",
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


def _log_upload_job_pool_exception(job_id: int, future) -> None:
    """`ThreadPoolExecutor.submit()`'s own well-known footgun: an
    exception raised by the submitted callable is captured on the
    returned `Future` but never surfaced anywhere unless something calls
    `.result()`/`.exception()` on it — nothing in this codebase did,
    before this session (P0 upload-reliability). In practice
    `process_upload_job`'s own top-level try/except already catches and
    terminal-izes almost everything (see its own docstring/handoff
    notes), so this is a narrow safety net for the one real gap: an
    exception raised BEFORE that try even starts (e.g. `SessionLocal()`
    itself failing). Without this callback, that failure would silently
    vanish and the job would stay stuck at "queued"/"processing" forever
    with nothing in any log explaining why. Best-effort: if marking the
    job failed ALSO fails (e.g. the DB is genuinely unreachable), this
    only logs — there is nothing further it can safely do from a worker
    thread's done-callback.
    """
    error = future.exception()
    if error is None:
        return

    print(f"UPLOAD JOB {job_id}: uncaught exception escaped the worker pool entirely: {error!r}")

    from app.db import SessionLocal

    try:
        db = SessionLocal()
        try:
            job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()
            if job and job.status not in ("done", "error", "needs_confirmation", "needs_identity_confirmation", "quarantined", "security_quarantined", "duplicate"):
                job.status = "error"
                job.progress = 100
                job.message = "Upload failed."
                job.error = "An unexpected error occurred before processing could start. Please try again."
                job.finished_at = now_iso()
                db.commit()
        finally:
            db.close()
    except Exception as persist_error:
        print(f"UPLOAD JOB {job_id}: failed to persist terminal error state from pool callback: {persist_error!r}")


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
        "classification_source": job.classification_source,
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
    from app.main import resolve_derived_artifact_contexts, serialize_document_card

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

    derived_contexts = resolve_derived_artifact_contexts(db, documents)

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
        "documents": [
            serialize_document_card(
                db,
                document,
                current_user,
                parent_document=derived_contexts.get(document.id, {}).get("parent_document"),
                has_abnormal_override=derived_contexts.get(document.id, {}).get("has_abnormal_override"),
            )
            for document in documents
        ],
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

    unambiguous_document_type = UNAMBIGUOUS_SECTION_DOCUMENT_TYPE.get(section)

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
        # Real classification never runs on this path (see the module
        # docstring on UNAMBIGUOUS_SECTION_DOCUMENT_TYPE above) — this is
        # not a guess, only ever set for the two section values that
        # already mean exactly one document_type.
        document_type=unambiguous_document_type,
        classification_status="classified" if unambiguous_document_type else None,
        classification_confidence=1.0 if unambiguous_document_type else None,
        classification_source="user_selected" if unambiguous_document_type else None,
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


@router.get("/upload/capabilities")
def get_upload_capabilities(current_user=Depends(get_current_user)):
    """The single source of truth for what the upload UI should advertise
    as supported — see app/services/ingestion/capability_registry.py.
    The frontend derives its `accept` attribute and support copy from
    this endpoint rather than maintaining an independent list that could
    silently drift from what the backend actually does."""
    from app.services.ingestion.capability_registry import capability_matrix_for_api

    return {"formats": capability_matrix_for_api()}


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
        future = UPLOAD_JOB_POOL.submit(process_upload_job, job.id)
        future.add_done_callback(lambda f, job_id=job.id: _log_upload_job_pool_exception(job_id, f))
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


@router.get("/documents/{document_id}/clinical-reader")
def get_clinical_reader_payload(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Clinical Document Intelligence V3, Phase 8: the one deliberate
    reader payload for the rebuilt discharge/clinical-document reader —
    a validated `StructuredClinicalDocument` (via the sanctioned
    `parse_structured_document` read path, which transparently
    upconverts an existing LEGACY discharge `note_body` payload in
    memory, so old documents render through the exact same contract as
    a real one without any reprocessing) plus every canonical fact it
    references: `LabResult` rows (Phase 6), `PatientMedication` rows
    (Phase 7), and a source-evidence id per fact for the existing
    `openSourceEvidence` viewer. Never a copy of clinical judgement —
    every value here is read straight from the canonical tables that
    already own it.

    Authorization is IDENTICAL to `GET /documents/{document_id}` above
    (same two-branch care_partner/can_access_patient check) — this is a
    read-shape difference, not a new access rule.
    """
    from app.services.clinical_document.persistence import parse_structured_document

    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if current_user.role == "care_partner":
        if not care_partner_can_access_document(db, current_user.id, document_id):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    # Clinical Document Intelligence V3 Phase 9: a derived lab-report
    # artifact's own note_body is a JSON pointer (group_key,
    # source_section_id, lab_result_ids — see lab_persistence.py), not a
    # StructuredClinicalDocument, so there is nothing to parse; its
    # canonical LabResult rows live on the PARENT document (Phase 6's
    # ownership rule), never on the artifact's own id, so they must be
    # resolved via the pointer's lab_result_ids, not `LabResult.
    # document_id == document.id` (which is always empty here).
    derived_artifact_payload = None
    if document.derived_artifact_kind:
        try:
            note_data = json.loads(document.note_body or "{}")
        except (TypeError, ValueError):
            note_data = {}
        lab_result_ids = [lab_id for lab_id in (note_data.get("lab_result_ids") or []) if isinstance(lab_id, int)]

        structured_document = None
        labs = (
            db.query(models.LabResult)
            .filter(models.LabResult.id.in_(lab_result_ids))
            .order_by(models.LabResult.id.asc())
            .all()
            if lab_result_ids
            else []
        )
        medications: list = []

        parent = (
            db.query(models.Document).filter(models.Document.id == document.parent_document_id).first()
            if document.parent_document_id
            else None
        )
        derived_artifact_payload = {
            "kind": document.derived_artifact_kind,
            "group_key": note_data.get("group_key"),
            "source_section_id": note_data.get("source_section_id"),
            "parent_document_id": document.parent_document_id,
            "parent_report_name": parent.report_name if parent else None,
            "parent_filename": parent.filename if parent else None,
            "parent_document_type": parent.document_type if parent else None,
            # The derived artifact itself has no file/content_type of its
            # own (see lab_persistence.py) — ReaderSourceAction's PDF-vs-
            # non-PDF honesty check must gate on the PARENT's real file
            # type, since "View source" always opens the parent's file.
            "parent_content_type": parent.content_type if parent else None,
        }
    else:
        structured_document = parse_structured_document(document.note_body)

        labs = (
            db.query(models.LabResult)
            .filter(models.LabResult.document_id == document.id)
            .order_by(models.LabResult.id.asc())
            .all()
        )
        medications = (
            db.query(models.PatientMedication)
            .filter(models.PatientMedication.source_document_id == document.id)
            .order_by(models.PatientMedication.id.asc())
            .all()
        )

    lab_payload = [
        {
            "id": lab.id,
            "raw_test_name": lab.raw_test_name,
            "canonical_name": lab.canonical_name,
            "display_name": lab.display_name,
            "category": lab.category,
            "source_section": lab.source_section,
            "value": lab.value,
            "flag": lab.flag,
            "reference_range": lab.reference_range,
            "unit": lab.unit,
            "observation_datetime": lab.observation_datetime,
            "verification_state": lab.verification_state,
            "source_evidence_id": source_evidence_service.first_source_evidence_id(db, lab_result_id=lab.id),
        }
        for lab in labs
    ]

    medication_payload = [
        {
            "id": med.id,
            "name": med.name,
            "dose_strength": med.dose_strength,
            "frequency": med.frequency,
            "route_form": med.route_form,
            "status": med.status,
            "is_uncertain": bool(med.is_uncertain),
            "start_date": med.start_date,
            "stop_date": med.stop_date,
            "stop_date_basis": med.stop_date_basis,
            "extra_info": med.extra_info,
            "source_segment_id": med.source_segment_id,
            "source_evidence_id": source_evidence_service.first_source_evidence_id(db, medication_id=med.id),
        }
        for med in medications
    ]

    # A document-level evidence anchor — the discharge reader's "View
    # original"/"Open original file" header action resolves through this
    # id, exactly like every other openSourceEvidence() call site. Never
    # a fabricated PDF page/bbox: see ensure_document_level_evidence's
    # own docstring for the honest page_only/document_only precision
    # this always produces.
    #
    # A derived lab artifact has no `saved_to`/real file of its own
    # (see lab_persistence.py's _get_or_create_derived_document — it is
    # a pointer row, never an upload), so anchoring evidence to its OWN
    # id would create a phantom row pointing at nothing. "View source"
    # for a derived artifact always resolves against the PARENT
    # document's real file instead.
    evidence_target_document = parent if document.derived_artifact_kind and parent else document
    document_level_evidence = source_evidence_service.ensure_document_level_evidence(
        db, evidence_target_document, provider="clinical_reader"
    )

    return {
        "document": {
            "id": document.id,
            "public_id": document.public_id,
            # Post-Phase-10 integration fix: the discharge reader's own
            # Ask Bragi target previously had no authoritative patient id
            # to read at all and passed `document.id` in its place (a
            # real bug — see the frontend commit). This mirrors the
            # generic /documents/{id} payload's own `patient_id` field
            # exactly, the one every other Ask Bragi target already uses.
            "patient_id": document.patient_id,
            "filename": document.filename,
            "content_type": document.content_type,
            "document_type": document.document_type,
            "report_name": document.report_name,
            "report_type": document.report_type,
            "source_language": document.source_language,
            "test_date": document.test_date,
            "created_at": document.created_at,
            "is_verified": bool(document.is_verified),
            "document_level_source_evidence_id": document_level_evidence.id,
            "derived_artifact_kind": document.derived_artifact_kind,
        },
        "structured_document": structured_document.model_dump() if structured_document else None,
        "labs": lab_payload,
        "medications": medication_payload,
        "derived_artifact": derived_artifact_payload,
    }


@router.post("/documents/{document_id}/reprocess-clinical-structure")
def reprocess_document_clinical_structure(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=10, window_seconds=3600, key_prefix="clinical_reprocess")),
):
    """Clinical Reader Intelligence V2: upgrades an EXISTING discharge
    document to the full pipeline (real Clinical Course event
    extraction, canonical LabResult/PatientMedication persistence,
    Timeline projection, AI Clinical Document Interpreter) without
    requiring the user to re-upload it — see
    app/services/clinical_document/reprocessing.py.

    Same authorization as editing a document (`PUT /documents/{id}`) —
    a patient reprocessing their OWN record, or a doctor/admin/care-
    partner already authorized for this patient. Rate-limited (this can
    trigger a real, billed AI call) — never unauthenticated, never an
    arbitrary-document admin bypass.
    """
    from app.services.clinical_document.reprocessing import ReprocessingError, reprocess_discharge_document

    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if current_user.role == "care_partner":
        if not care_partner_can_access_document(db, current_user.id, document_id):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        result = reprocess_discharge_document(db, document=document, actor_user_id=current_user.id)
    except ReprocessingError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {
        "document_id": result.document_id,
        "dated_events_count": result.dated_events_count,
        "lab_results_created": result.lab_results_created,
        "lab_results_reused": result.lab_results_reused,
        "medications_created": result.medications_created,
        "medications_reused": result.medications_reused,
        "timeline_events_created": result.timeline_events_created,
        "timeline_events_retracted": result.timeline_events_retracted,
        "interpretation_status": result.interpretation_status,
        "interpretation_warnings": result.interpretation_warnings,
        "diagnoses_count": result.diagnoses_count,
        "investigations_count": result.investigations_count,
        "anomalies_count": result.anomalies_count,
    }


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

    # Clinical Document Intelligence V3 Phase 9: a derived lab-report
    # artifact is a pointer into the parent document's own canonical
    # LabResult rows, not an independent upload — deleting it directly
    # would silently desynchronize Documents from the parent's real
    # content without actually removing any clinical data. It is only
    # ever removed as a side effect of its parent's deletion (the cascade
    # a few lines below, unchanged from Phase 6).
    if document.derived_artifact_kind:
        raise HTTPException(
            status_code=400,
            detail="Derived artifacts cannot be deleted directly — delete the source document instead.",
        )

    saved_to = document.saved_to

    # Clinical Document Intelligence V3, Phase 6: a derived lab-report
    # artifact (models.Document.derived_artifact_kind is set) must be
    # REMOVED, not orphaned, when its parent is deleted — unlike an
    # ordinary Reducto Split page-range child, which intentionally keeps
    # `parent_document_id`'s existing `ondelete="SET NULL"` behavior
    # (survives its split parent's deletion). The derived artifact's own
    # LabResult/SourceEvidence rows are NOT deleted here: Phase 6
    # attaches those to the AUTHORITATIVE parent document, not to the
    # derived artifact, so they are already covered by `document.
    # lab_results`' existing cascade below when `document` IS that
    # parent — deleting this pointer-only artifact row never deletes
    # another, unrelated source's LabResult.
    db.query(models.Document).filter(
        models.Document.parent_document_id == document.id,
        models.Document.derived_artifact_kind.isnot(None),
    ).delete(synchronize_session=False)

    # Clinical Document Intelligence V3, Phase 7: a document-derived
    # PatientMedication row is NOT deleted when its source document is
    # (SET NULL, not cascade — see models.py's source_document_id
    # docstring: the medication fact stays independently meaningful).
    # But its SourceEvidence.document_id column is NOT NULL, so any
    # medication-linked evidence row for THIS document must be removed
    # explicitly before the document itself is deleted, or the delete
    # would violate that FK constraint. Scoped to medication-linked,
    # non-lab-linked rows only — lab-linked evidence is already covered
    # by the LabResult cascade below when `document` IS a lab's parent.
    db.query(models.SourceEvidence).filter(
        models.SourceEvidence.document_id == document.id,
        models.SourceEvidence.lab_result_id.is_(None),
        models.SourceEvidence.medication_id.isnot(None),
    ).delete(synchronize_session=False)

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
