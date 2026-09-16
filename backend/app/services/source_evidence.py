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
