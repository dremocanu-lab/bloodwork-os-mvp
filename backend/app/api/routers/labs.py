"""Labs / bloodwork-trends routes (BRAGI backend modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"labs/bloodwork trends" domain — small, one route family, read-only). This
must not regress canonical lab alias/name matching (e.g. "WBC" vs "White
Blood Cell Count" resolving to the same trend line via
`lab.canonical_name`) — the resolution itself happens upstream, in
app/services/lab_resolver.py at ingestion time; this route only groups
already-resolved LabResult rows by `canonical_name` (falling back to
`display_name`/`raw_test_name`), unchanged from the original.

`get_best_document_date` and `lab_value_to_float` were used ONLY by this
route in app/main.py, so they moved here rather than into a shared
module — no other domain currently calls them.
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_current_user, get_db
from app.policies.access import can_access_patient

router = APIRouter()


def get_best_document_date(document) -> str | None:
    return (
        document.test_date
        or document.collected_on
        or document.reported_on
        or document.generated_on
        or document.registered_on
        or document.created_at
    )


def lab_value_to_float(value) -> float | None:
    if value is None:
        return None

    cleaned = str(value).strip().lower()
    cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.replace("−", "-")
    cleaned = cleaned.replace("—", "-").replace("–", "-")

    if cleaned in {"", "-", "--", "---", "nil", "n/a", "na", "null", "none"}:
        return None

    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)

    if not match:
        return None

    try:
        return float(match.group(0))
    except Exception:
        return None


@router.get("/patients/{patient_id}/bloodwork-trends")
def get_patient_bloodwork_trends(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not can_access_patient(db, current_user, patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    documents = (
        db.query(models.Document)
        .filter(
            models.Document.patient_id == patient_id,
            models.Document.section == "bloodwork",
        )
        .order_by(models.Document.id.asc())
        .all()
    )

    document_by_id = {document.id: document for document in documents}
    document_ids = list(document_by_id.keys())

    if not document_ids:
        return []

    labs = (
        db.query(models.LabResult)
        .filter(
            models.LabResult.document_id.in_(document_ids),
            # Rows linked as Level-3 duplicate observations describe the
            # same real-world measurement as an earlier row — counting both
            # would plot the same value twice.
            models.LabResult.duplicate_of_lab_result_id.is_(None),
        )
        .all()
    )

    trends = {}

    for lab in labs:
        numeric_value = lab_value_to_float(lab.value)

        # Missing / nil / --- values must never enter trend graphs.
        if numeric_value is None:
            continue

        test_key = (
            lab.canonical_name
            or lab.display_name
            or lab.raw_test_name
            or ""
        ).strip()

        if not test_key:
            continue

        document = document_by_id.get(lab.document_id)

        if not document:
            continue

        display_name = lab.display_name or lab.canonical_name or lab.raw_test_name or test_key
        date = get_best_document_date(document) or ""

        if test_key not in trends:
            trends[test_key] = {
                "test_key": test_key,
                "display_name": display_name,
                "canonical_name": lab.canonical_name,
                "category": lab.category,
                "unit": lab.unit,
                "points": [],
            }

        trends[test_key]["points"].append(
            {
                "document_id": document.id,
                "lab_result_id": lab.id,
                "date": date,
                "value": numeric_value,
                "value_display": str(lab.value).strip(),
                "flag": lab.flag,
                "report_name": document.report_name or document.filename,
                "reference_range": lab.reference_range,
            }
        )

    results = []

    for trend in trends.values():
        points = trend["points"]

        # Sort by clinical date when possible, then document id as a stable fallback.
        def point_sort_key(point):
            raw_date = point.get("date") or ""

            try:
                parsed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                return (parsed.timestamp(), point.get("document_id") or 0)
            except Exception:
                return (0, point.get("document_id") or 0)

        points.sort(key=point_sort_key)

        # Only the 5 most recent real numeric points.
        points = points[-5:]

        if not points:
            continue

        latest = points[-1]
        previous = points[-2] if len(points) >= 2 else None
        delta = None

        if previous:
            delta = round(latest["value"] - previous["value"], 2)

        trend["points"] = points
        trend["latest"] = latest
        trend["previous"] = previous
        trend["delta"] = delta

        results.append(trend)

    results.sort(
        key=lambda trend: (
            0
            if trend["latest"].get("flag")
            and str(trend["latest"].get("flag")).strip().lower() not in {"", "normal", "none", "ok"}
            else 1,
            trend["display_name"] or "",
        )
    )

    return results
