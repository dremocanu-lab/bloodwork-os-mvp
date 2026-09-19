"""Shared, DB-only SourceEvidence helpers — usable by any caller that
already has a `Session`, not just Ask Bragi's `AskBragiContext`.

`app/services/ask_bragi/tools.py::_ensure_document_level_evidence` was
the first real use of `SourceEvidence`'s own long-documented "generalize
beyond lab rows" intent for a whole-document (not per-field) citation.
Clinical Document Intelligence V3 Phase 8 needs the exact same
mechanism for the discharge reader's document-level "View original"
action — extracted here rather than duplicated, per this project's own
"no parallel product logic" convention (see the Phase 4 canonical-
heading-classifier unification for the established precedent of
extracting a shared implementation once two call sites need the same
behavior). `ask_bragi/tools.py` now calls this module; its own
behavior is unchanged (proven by its existing, unmodified test suite
staying green).
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app import models
from app.core.utils import now_iso


def ensure_document_level_evidence(
    db: Session, document: "models.Document", *, provider: str = "document_level"
) -> "models.SourceEvidence":
    """Idempotent (checks for an existing document-level row first,
    regardless of which caller originally created it — `provider` only
    labels a NEW row's origin, it is never part of the lookup key). See
    the original docstring this was extracted from
    (`ask_bragi/tools.py`'s prior `_ensure_document_level_evidence`) for
    the full precision-hierarchy reasoning: this only ever produces
    `page_only`/`document_only`-precision evidence, never a fabricated
    exact bbox. `ask_bragi/tools.py` passes its own historical
    `provider="ask_bragi_document_level"` explicitly to keep existing
    stored/tested values unchanged; a new caller (e.g. the Phase 8
    clinical-reader endpoint) can pass its own honest label."""
    existing = (
        db.query(models.SourceEvidence)
        .filter(
            models.SourceEvidence.document_id == document.id,
            models.SourceEvidence.lab_result_id.is_(None),
            models.SourceEvidence.medication_id.is_(None),
        )
        .order_by(models.SourceEvidence.id.asc())
        .first()
    )
    if existing:
        return existing

    evidence = models.SourceEvidence(
        document_id=document.id,
        lab_result_id=None,
        page_number=1,
        source_text=None,
        provider=provider,
        created_at=now_iso(),
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def ensure_segment_evidence(
    db: Session,
    document: "models.Document",
    *,
    source_block_id: str,
    page_number: int | None,
    source_text: str | None,
    provider: str = "discharge_segment",
    bbox: dict[str, float] | None = None,
    field_bboxes: list[dict] | None = None,
) -> tuple["models.SourceEvidence", bool]:
    """Source Intelligence + Provenance V2 (block/page precision) —
    extended by Source Geometry + Clinical Table Intelligence V3 to
    optionally carry real block/table/cell geometry when a caller has it
    (`bbox` — the primary/exact normalized rect; `field_bboxes` — every
    supporting rect, e.g. a table row's individual cells, reusing the
    SAME `field_bboxes_json` shape Provenance V2 already established for
    lab field citations — see models.py::SourceEvidence). `bbox`/
    `field_bboxes` are never fabricated by a caller — they only ever come
    from real extracted geometry (source_geometry.py) or a confident
    text-alignment match (geometry_alignment.py); omitted entirely, this
    still degrades gracefully to block/page precision exactly as before.

    Idempotent per `(document_id, source_block_id)` — reprocessing the
    same document reuses the existing row rather than creating a
    duplicate. Upgrade semantics (Part 44): when the existing row has NO
    bbox yet and this call supplies one, the row is updated IN PLACE
    (page_only@pageN -> block/table/cell@pageN+bbox) — the same
    SourceEvidence id, never a second button for the same fact. An
    already-geometry-bearing row is left untouched (never regressed by a
    later pass that happens to find weaker/no geometry, and never
    silently replaced by a DIFFERENT bbox for the same block id, which
    would risk masking a genuine extraction change rather than an
    upgrade). Returns `(evidence, was_new)` so a caller that reports
    reprocessing stats (created vs. reused) doesn't need a second query
    to find out which happened."""
    existing = (
        db.query(models.SourceEvidence)
        .filter(
            models.SourceEvidence.document_id == document.id,
            models.SourceEvidence.source_block_id == source_block_id,
        )
        .order_by(models.SourceEvidence.id.asc())
        .first()
    )
    if existing:
        if bbox is not None and existing.bbox_x is None:
            existing.bbox_x = bbox.get("x")
            existing.bbox_y = bbox.get("y")
            existing.bbox_width = bbox.get("width")
            existing.bbox_height = bbox.get("height")
            if field_bboxes:
                existing.field_bboxes_json = json.dumps(field_bboxes)
            if page_number is not None and existing.page_number is None:
                existing.page_number = page_number
            db.commit()
            db.refresh(existing)
        return existing, False

    evidence = models.SourceEvidence(
        document_id=document.id,
        lab_result_id=None,
        medication_id=None,
        page_number=page_number,
        source_block_id=source_block_id,
        source_text=(source_text or "")[:4000] or None,  # bounded — provenance display text, not a full-text store
        provider=provider,
        bbox_x=bbox.get("x") if bbox else None,
        bbox_y=bbox.get("y") if bbox else None,
        bbox_width=bbox.get("width") if bbox else None,
        bbox_height=bbox.get("height") if bbox else None,
        field_bboxes_json=json.dumps(field_bboxes) if field_bboxes else None,
        created_at=now_iso(),
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence, True


def first_source_evidence_id(
    db: Session, *, lab_result_id: int | None = None, medication_id: int | None = None
) -> int | None:
    """Mirrors `ask_bragi/tools.py::_first_source_evidence_id`'s exact
    convention (earliest-id row wins) — generalized to also accept
    `medication_id` (Phase 7's addition to `SourceEvidence`). Exactly
    one of the two kwargs should be supplied."""
    query = db.query(models.SourceEvidence)
    if lab_result_id is not None:
        query = query.filter(models.SourceEvidence.lab_result_id == lab_result_id)
    if medication_id is not None:
        query = query.filter(models.SourceEvidence.medication_id == medication_id)
    row = query.order_by(models.SourceEvidence.id.asc()).first()
    return row.id if row else None
