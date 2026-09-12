"""Source-evidence / provenance routes (BRAGI backend modularization,
Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"source evidence" domain — small but authorization-sensitive). Both
routes are the canonical citation/"View original" resolution endpoints
(see BRAGI_REDUCTO_PLAN.md) used by Analize/charts today and intended
for Ask Bragi's citation opening too — this move changes neither route's
authorization (`can_access_patient`, explicit care_partner exclusion)
nor response shape.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_current_user, get_db
from app.policies.access import can_access_patient
from app.rate_limit import RateLimiter

router = APIRouter()


@router.get("/source-evidence/{source_evidence_id}/view")
def get_source_evidence_view(
    source_evidence_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=120, window_seconds=300, key_prefix="source_retrieval")),
):
    """Resolve one SourceEvidence row into everything the shared Bragi
    source viewer needs to open it — the general-purpose
    `openSourceEvidence(sourceEvidenceId)` backend contract (see
    BRAGI_REDUCTO_PLAN.md), used today by Analize/charts and intended as
    the canonical citation-resolution endpoint for future Ask Bragi too.

    Authorization is identical to the existing `/documents/{id}/file`
    route (`can_access_patient`, no care-partner access) — this endpoint
    exposes bbox/page metadata, never a bare/public file URL; the actual
    PDF bytes are still fetched through the existing authenticated file
    route using the `document_id` this returns.
    """
    evidence = db.query(models.SourceEvidence).filter(models.SourceEvidence.id == source_evidence_id).first()

    if not evidence:
        raise HTTPException(status_code=404, detail="Source evidence not found")

    document = db.query(models.Document).filter(models.Document.id == evidence.document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Source document not found")

    if current_user.role == "care_partner":
        raise HTTPException(status_code=403, detail="Care partners cannot access source evidence.")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    has_bbox = evidence.bbox_x is not None and evidence.bbox_y is not None
    if evidence.page_number and has_bbox:
        precision = "exact_bbox"
    elif evidence.page_number:
        precision = "page_only"
    elif evidence.source_text:
        precision = "text_only"
    else:
        precision = "document_only"

    return {
        "source_evidence_id": evidence.id,
        "document_id": document.id,
        "document_filename": document.filename,
        "document_type": document.document_type,
        "report_name": document.report_name,
        "lab_result_id": evidence.lab_result_id,
        "page_number": evidence.page_number,
        "bbox_x": evidence.bbox_x,
        "bbox_y": evidence.bbox_y,
        "bbox_width": evidence.bbox_width,
        "bbox_height": evidence.bbox_height,
        "row_bbox_x": evidence.row_bbox_x,
        "row_bbox_y": evidence.row_bbox_y,
        "row_bbox_width": evidence.row_bbox_width,
        "row_bbox_height": evidence.row_bbox_height,
        "source_text": evidence.source_text,
        "provider": evidence.provider,
        "precision": precision,
    }


@router.get("/lab-results/{lab_result_id}/source")
def get_lab_result_source(
    lab_result_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=120, window_seconds=300, key_prefix="source_retrieval")),
):
    """Provenance for one structured lab row — the "View original" flagship
    feature's data source (see BRAGI_REDUCTO_PLAN.md Phase 3).

    Returns every SourceEvidence row for this lab result (there can be
    more than one once Level-3 duplicate-observation linking has
    attached evidence from more than one document to the same
    observation). Page/bbox fields are present but null until a real
    Reducto Parse integration can supply them — never fabricated.
    """
    lab = db.query(models.LabResult).filter(models.LabResult.id == lab_result_id).first()

    if not lab:
        raise HTTPException(status_code=404, detail="Lab result not found")

    document = db.query(models.Document).filter(models.Document.id == lab.document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if current_user.role == "care_partner":
        raise HTTPException(status_code=403, detail="Care partners cannot access source evidence.")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    evidence_rows = (
        db.query(models.SourceEvidence)
        .filter(models.SourceEvidence.lab_result_id == lab_result_id)
        .order_by(models.SourceEvidence.id.asc())
        .all()
    )

    return {
        "lab_result_id": lab.id,
        "document_id": document.id,
        "document_filename": document.filename,
        "evidence": [
            {
                "id": row.id,
                "document_id": row.document_id,
                "page_number": row.page_number,
                "bbox_x": row.bbox_x,
                "bbox_y": row.bbox_y,
                "bbox_width": row.bbox_width,
                "bbox_height": row.bbox_height,
                "source_text": row.source_text,
                "extraction_confidence": row.extraction_confidence,
                "provider": row.provider,
            }
            for row in evidence_rows
        ],
    }
