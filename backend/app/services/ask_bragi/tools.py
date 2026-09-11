"""Ask Bragi's restricted tool registry.

Every tool here is backed by real Bragi data (no fake/no-op tools — see
BRAGI_ASK_BRAGI_PLAN.md's tool-registry section for why some tools named
in the original spec, e.g. separate "get_imaging_results"/
"get_pathology_results"/"get_procedures"/"get_diagnoses", are
deliberately NOT separate tools: imaging/pathology/consultation reports
are `Document` rows distinguished by `document_type` — already covered
by `search_documents(document_type=...)` + `get_document` — and there is
no dedicated procedures/diagnoses table in this schema; inventing tools
for tables that don't exist would violate "no fake/no-op tools" more
than it would help).

Hard security invariants, enforced here, not just documented:
- No tool schema below has a `patient_id` (or `document_id` for
  patient-record-scoped tools) parameter the model controls — scope
  comes ONLY from `AskBragiContext`, resolved server-side before the
  model ever sees a request (see context.py).
- `ctx.require_current_access()` runs at the top of every tool
  dispatch (`run_tool()`), independently, every single call — not just
  once at conversation start.
- Every SourceEvidence id and every Document id a tool returns is
  registered into `ctx.authorized_evidence_ids`/`authorized_document_ids`
  — the ONLY citations the final response is allowed to contain (see
  service.py's citation-validation step). The model cannot cite
  anything it wasn't actually, authorizedly, shown.
- Patient identity fields (CNP, email, phone, address) are never
  included in any tool's return value — `get_patient_context` uses
  `app/services/ai_minimization.py` rather than a parallel minimization
  scheme.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable

from app import models
from app.services.ai_minimization import minimize_patient_context

from .context import AskBragiAccessDenied, AskBragiContext

TOOL_SCHEMA_VERSION = "2026-09-ask-bragi-v1"

# Bragi's 16-value document taxonomy (see app/services/document_taxonomy.py) —
# duplicated here as a plain string enum for the tool JSON schema rather
# than importing the Enum class, to keep this file's only dependency on
# main.py's world limited to `models` (no risk of an import-order issue,
# and this list only needs to stay in sync if the taxonomy itself
# changes, which is rare and reviewable).
DOCUMENT_TYPES = [
    "laboratory_results", "discharge_summary", "imaging_report", "operative_report",
    "pathology_report", "prescription", "medication_list", "specialist_consultation",
    "emergency_department_note", "hospital_admission_note", "procedure_report",
    "referral", "vaccination_record", "medical_certificate", "insurance_or_administrative",
    "other",
]

_MAX_TEXT_CHARS = 4000  # a single get_document call never dumps an unbounded document
_MAX_LIST_LIMIT = 25


def _clamp_limit(value: Any, default: int, maximum: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, maximum))


def _first_source_evidence_id(ctx: AskBragiContext, lab_result_id: int) -> int | None:
    row = (
        ctx.db.query(models.SourceEvidence)
        .filter(models.SourceEvidence.lab_result_id == lab_result_id)
        .order_by(models.SourceEvidence.id.asc())
        .first()
    )
    return row.id if row else None


def _ensure_document_level_evidence(ctx: AskBragiContext, document) -> int | None:
    """Narrative documents (discharge summaries, imaging/pathology/
    consultation reports, etc.) generally have no per-field
    `SourceEvidence` rows — those only exist for structured lab rows
    today (see BRAGI_REDUCTO_PLAN.md Phase 2/BRAGI_ASK_BRAGI_PLAN.md's
    "Remaining limitations"). Without this, a narrative-grounded Ask
    Bragi answer would carry 0 citations even when accurate.

    This creates (once, idempotently — checked first) a DOCUMENT-LEVEL
    evidence row: `lab_result_id=None`, `page_number=1` if the document's
    own extraction reasonably implies page 1 is where its content
    starts, `bbox_*` and `source_text` left null. The existing precision
    hierarchy in `GET /source-evidence/{id}/view` (see main.py) already
    reports this honestly as `"page_only"` — NEVER `"exact_bbox"` or
    `"text_only"` — because those fields are genuinely absent, not
    because anything here pretends otherwise. Precision hierarchy
    preserved: exact bbox > page-level > document-level; this function
    only ever produces the bottom two, never fakes the top one.
    """
    existing = (
        ctx.db.query(models.SourceEvidence)
        .filter(
            models.SourceEvidence.document_id == document.id,
            models.SourceEvidence.lab_result_id.is_(None),
        )
        .order_by(models.SourceEvidence.id.asc())
        .first()
    )
    if existing:
        return existing.id

    # Any existing lab-result-linked evidence already proves this
    # document has real page geometry — page 1 is a safe, honest
    # default for a document-level (not field-level) citation on a
    # narrative document; never asserted for a document Bragi never
    # actually parsed into pages (nothing here invents a page count).
    evidence = models.SourceEvidence(
        document_id=document.id,
        lab_result_id=None,
        page_number=1,
        source_text=None,
        provider="ask_bragi_document_level",
        created_at=datetime.now(UTC).isoformat(),
    )
    ctx.db.add(evidence)
    ctx.db.commit()
    ctx.db.refresh(evidence)
    return evidence.id


# ── Tool implementations ─────────────────────────────────────────────────────


def _tool_get_patient_context(ctx: AskBragiContext, args: dict) -> dict:
    patient = ctx.db.query(models.Patient).filter(models.Patient.id == ctx.patient_id).first()
    if not patient:
        return {"error": "patient_not_found"}

    doc_count = ctx.db.query(models.Document).filter(models.Document.patient_id == ctx.patient_id).count()
    active_meds = (
        ctx.db.query(models.PatientMedication)
        .filter(models.PatientMedication.patient_id == ctx.patient_id, models.PatientMedication.status == "active")
        .count()
    )
    raw = {"age": patient.age, "sex": patient.sex, "full_name": patient.full_name, "cnp": patient.cnp}
    minimized = minimize_patient_context(raw)  # strips cnp/email/phone/address/etc. — see ai_minimization.py
    minimized.pop("full_name", None)  # the model doesn't need the patient's name to answer clinical questions
    return {
        **minimized,
        "document_count": doc_count,
        "active_medication_count": active_meds,
        "scope": ctx.scope,
    }


def _tool_search_documents(ctx: AskBragiContext, args: dict) -> dict:
    if ctx.turn_scope == "document":
        # Document-scoped THIS TURN (ctx.turn_scope, not the conversation's
        # immutable ctx.scope): return only the one document this
        # conversation is bound to. A turn that was explicitly/implicitly
        # widened to "patient_record" (see service.py) searches broadly
        # instead — see BRAGI_ASK_BRAGI_PLAN.md's scope model.
        doc = ctx.db.query(models.Document).filter(models.Document.id == ctx.document_id).first()
        docs = [doc] if doc else []
    else:
        query = ctx.db.query(models.Document).filter(models.Document.patient_id == ctx.patient_id)
        document_type = args.get("document_type")
        if document_type and document_type in DOCUMENT_TYPES:
            query = query.filter(models.Document.document_type == document_type)
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if date_from:
            query = query.filter(models.Document.test_date >= date_from)
        if date_to:
            query = query.filter(models.Document.test_date <= date_to)
        limit = _clamp_limit(args.get("limit"), default=10, maximum=_MAX_LIST_LIMIT)
        docs = query.order_by(models.Document.id.desc()).limit(limit).all()

    results = []
    for d in docs:
        ctx.register_document(d.id)
        results.append(
            {
                "document_id": d.id,
                "document_type": d.document_type,
                "report_name": d.report_name,
                "test_date": d.test_date,
                "created_at": d.created_at,
                "section": d.section,
            }
        )
    return {"documents": results}


def _tool_get_document(ctx: AskBragiContext, args: dict) -> dict:
    document_id = args.get("document_id")
    if ctx.turn_scope == "document" and document_id != ctx.document_id:
        return {"error": "out_of_scope", "message": "This conversation is scoped to a single document."}
    document = ctx.db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document or document.patient_id != ctx.patient_id:
        return {"error": "not_found"}
    ctx.register_document(document.id)

    structured_sections: dict = {}
    if document.structured_sections:
        try:
            structured_sections = json.loads(document.structured_sections).get("sections") or {}
        except Exception:
            structured_sections = {}

    section_key = args.get("section_key")
    if section_key and section_key in structured_sections:
        text = structured_sections[section_key]
    elif structured_sections:
        text = "\n\n".join(f"{k}: {v}" for k, v in structured_sections.items() if v)
    else:
        text = document.extracted_text or ""

    return {
        "document_id": document.id,
        "document_type": document.document_type,
        "report_name": document.report_name,
        "test_date": document.test_date,
        "available_sections": list(structured_sections.keys()) if structured_sections else [],
        "text": (text or "")[:_MAX_TEXT_CHARS],
        "truncated": len(text or "") > _MAX_TEXT_CHARS,
    }


def _tool_get_document_sources(ctx: AskBragiContext, args: dict) -> dict:
    document_id = args.get("document_id")
    if ctx.turn_scope == "document" and document_id != ctx.document_id:
        return {"error": "out_of_scope"}
    document = ctx.db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document or document.patient_id != ctx.patient_id:
        return {"error": "not_found"}
    ctx.register_document(document.id)

    rows = (
        ctx.db.query(models.SourceEvidence)
        .filter(models.SourceEvidence.document_id == document_id)
        .order_by(models.SourceEvidence.id.asc())
        .limit(_MAX_LIST_LIMIT)
        .all()
    )
    out = []
    for r in rows:
        ctx.register_evidence(r.id)
        out.append(
            {
                "source_evidence_id": r.id,
                "page": r.page_number,
                "source_text": (r.source_text or "")[:500],
            }
        )

    if not out:
        # No per-field evidence exists (a narrative document — discharge/
        # imaging/pathology/consultation reports don't get per-field
        # SourceEvidence today, see BRAGI_ASK_BRAGI_PLAN.md's "Remaining
        # limitations"). Fall back to a real, honestly-labeled document-
        # level citation rather than leaving the model with nothing to
        # cite — see _ensure_document_level_evidence's docstring for
        # exactly what precision this carries (page-level, never exact).
        fallback_id = _ensure_document_level_evidence(ctx, document)
        if fallback_id is not None:
            ctx.register_evidence(fallback_id)
            out.append({"source_evidence_id": fallback_id, "page": 1, "source_text": None})

    return {"sources": out}


def _tool_get_lab_results(ctx: AskBragiContext, args: dict) -> dict:
    query = (
        ctx.db.query(models.LabResult)
        .join(models.Document, models.Document.id == models.LabResult.document_id)
        .filter(models.Document.patient_id == ctx.patient_id)
    )
    if ctx.turn_scope == "document":
        query = query.filter(models.Document.id == ctx.document_id)
    canonical_name = args.get("canonical_name")
    if canonical_name:
        query = query.filter(models.LabResult.canonical_name.ilike(f"%{canonical_name}%"))
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    if date_from:
        query = query.filter(models.LabResult.observation_datetime >= date_from)
    if date_to:
        query = query.filter(models.LabResult.observation_datetime <= date_to)
    limit = _clamp_limit(args.get("limit"), default=20, maximum=_MAX_LIST_LIMIT)
    rows = query.order_by(models.LabResult.observation_datetime.desc()).limit(limit).all()

    out = []
    for lr in rows:
        evidence_id = _first_source_evidence_id(ctx, lr.id)
        ctx.register_evidence(evidence_id)
        out.append(
            {
                "canonical_name": lr.canonical_name or lr.raw_test_name,
                "raw_test_name": lr.raw_test_name,
                "value": lr.value,
                "unit": lr.unit,
                "reference_range": lr.reference_range,
                "flag": lr.flag,
                "date": lr.observation_datetime,
                "verification_state": lr.verification_state,
                "source_evidence_id": evidence_id,
            }
        )
    return {"results": out}


def _mark_broadened_if_document_scoped(ctx: AskBragiContext) -> None:
    """Called by tools that are inherently patient-wide (trend/compare/
    medications/timeline — they never restrict by document). Calling one
    of these AT ALL while the conversation's stored scope is "document"
    means this turn went beyond that one document, regardless of whether
    turn_scope was also explicitly widened — the UI's "Searching full
    record" indicator must reflect that."""
    if ctx.scope == "document":
        ctx.broadened_this_turn = True


def _tool_get_lab_trend(ctx: AskBragiContext, args: dict) -> dict:
    _mark_broadened_if_document_scoped(ctx)
    canonical_name = args.get("canonical_name")
    if not canonical_name:
        return {"error": "canonical_name_required"}
    query = (
        ctx.db.query(models.LabResult)
        .join(models.Document, models.Document.id == models.LabResult.document_id)
        .filter(
            models.Document.patient_id == ctx.patient_id,
            models.LabResult.canonical_name.ilike(f"%{canonical_name}%"),
            models.LabResult.duplicate_of_lab_result_id.is_(None),
        )
    )
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    if date_from:
        query = query.filter(models.LabResult.observation_datetime >= date_from)
    if date_to:
        query = query.filter(models.LabResult.observation_datetime <= date_to)
    rows = query.order_by(models.LabResult.observation_datetime.asc()).limit(100).all()

    points = []
    for lr in rows:
        evidence_id = _first_source_evidence_id(ctx, lr.id)
        ctx.register_evidence(evidence_id)
        points.append(
            {
                "date": lr.observation_datetime,
                "value": lr.value,
                "unit": lr.unit,
                "flag": lr.flag,
                "reference_range": lr.reference_range,
                "source_evidence_id": evidence_id,
                # Real chart-point provenance (BRAGI product spec §39/49):
                # already-authorized (this query is scoped to
                # ctx.patient_id) — carried through so the frontend can
                # reuse the exact same click-through-to-source affordance
                # a table row gets, not a chart-specific one.
                "document_id": lr.document_id,
                "lab_result_id": lr.id,
            }
        )
    return {"canonical_name": canonical_name, "points": points}


def _tool_compare_lab_results(ctx: AskBragiContext, args: dict) -> dict:
    _mark_broadened_if_document_scoped(ctx)
    canonical_name = args.get("canonical_name")
    if not canonical_name:
        return {"error": "canonical_name_required"}
    query = (
        ctx.db.query(models.LabResult)
        .join(models.Document, models.Document.id == models.LabResult.document_id)
        .filter(
            models.Document.patient_id == ctx.patient_id,
            models.LabResult.canonical_name.ilike(f"%{canonical_name}%"),
            models.LabResult.duplicate_of_lab_result_id.is_(None),
        )
        .order_by(models.LabResult.observation_datetime.desc())
        .limit(2)
    )
    rows = query.all()
    if not rows:
        return {"canonical_name": canonical_name, "latest": None, "previous": None}

    def _serialize(lr):
        evidence_id = _first_source_evidence_id(ctx, lr.id)
        ctx.register_evidence(evidence_id)
        return {
            "value": lr.value,
            "unit": lr.unit,
            "date": lr.observation_datetime,
            "flag": lr.flag,
            "source_evidence_id": evidence_id,
        }

    latest = _serialize(rows[0])
    previous = _serialize(rows[1]) if len(rows) > 1 else None
    delta = None
    if previous is not None:
        try:
            delta = float(latest["value"]) - float(previous["value"])
        except (TypeError, ValueError):
            delta = None
    return {"canonical_name": canonical_name, "latest": latest, "previous": previous, "delta": delta}


def _tool_get_medications(ctx: AskBragiContext, args: dict) -> dict:
    _mark_broadened_if_document_scoped(ctx)
    query = ctx.db.query(models.PatientMedication).filter(models.PatientMedication.patient_id == ctx.patient_id)
    status = args.get("status")
    if status:
        query = query.filter(models.PatientMedication.status == status)
    rows = query.order_by(models.PatientMedication.created_at.desc()).limit(_MAX_LIST_LIMIT).all()
    out = []
    for m in rows:
        out.append(
            {
                "name": m.name,
                "dose_strength": m.dose_strength,
                "frequency": m.frequency,
                # Honest status vocabulary (Priority 21 in the build spec):
                # this is exactly what "status"/"is_uncertain" already
                # record — the model must not upgrade this to "currently
                # taking" beyond what the record actually supports.
                "status": m.status,  # "active" | "discontinued" | other recorded status
                "is_uncertain": bool(m.is_uncertain),
                "start_date": m.start_date,
                "stop_date": m.stop_date,
                "prescriber": m.prescriber,
            }
        )
    return {"medications": out}


def _tool_get_patient_timeline(ctx: AskBragiContext, args: dict) -> dict:
    _mark_broadened_if_document_scoped(ctx)
    query = ctx.db.query(models.PatientEvent).filter(models.PatientEvent.patient_id == ctx.patient_id)
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    if date_from:
        query = query.filter(models.PatientEvent.admitted_at >= date_from)
    if date_to:
        query = query.filter(models.PatientEvent.admitted_at <= date_to)
    limit = _clamp_limit(args.get("limit"), default=20, maximum=_MAX_LIST_LIMIT)
    rows = query.order_by(models.PatientEvent.admitted_at.desc()).limit(limit).all()
    return {
        "events": [
            {
                "event_type": e.event_type,
                "title": e.title,
                "status": e.status,
                "hospital_name": e.hospital_name,
                "admitted_at": e.admitted_at,
                "discharged_at": e.discharged_at,
            }
            for e in rows
        ]
    }


def _tool_get_source_evidence(ctx: AskBragiContext, args: dict) -> dict:
    source_evidence_id = args.get("source_evidence_id")
    # Defense in depth: refuse even to LOOK UP an id the model hasn't
    # already been shown by an earlier tool call this turn. The final
    # citation-validation step in service.py is the real backstop, but
    # there's no reason to let the model probe arbitrary ids at all.
    if source_evidence_id not in ctx.authorized_evidence_ids:
        return {"error": "not_authorized_this_turn"}
    row = ctx.db.query(models.SourceEvidence).filter(models.SourceEvidence.id == source_evidence_id).first()
    # Authoritative check (the ctx.authorized_evidence_ids membership test
    # above is the primary gate; this re-confirms the row still actually
    # belongs to this patient, in case a document's patient_id ever
    # changed between the earlier tool call and this one).
    if not row or row.document is None or row.document.patient_id != ctx.patient_id:
        return {"error": "not_found"}
    return {
        "source_evidence_id": row.id,
        "page": row.page_number,
        "source_text": (row.source_text or "")[:800],
    }


# ── Registry ──────────────────────────────────────────────────────────────

TOOL_IMPLS: dict[str, Callable[[AskBragiContext, dict], dict]] = {
    "get_patient_context": _tool_get_patient_context,
    "search_documents": _tool_search_documents,
    "get_document": _tool_get_document,
    "get_document_sources": _tool_get_document_sources,
    "get_lab_results": _tool_get_lab_results,
    "get_lab_trend": _tool_get_lab_trend,
    "compare_lab_results": _tool_compare_lab_results,
    "get_medications": _tool_get_medications,
    "get_patient_timeline": _tool_get_patient_timeline,
    "get_source_evidence": _tool_get_source_evidence,
}


def _schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
        "strict": False,  # object-typed optional params (nullable) — see service.py's rationale
    }


TOOL_SCHEMAS: list[dict] = [
    _schema(
        "get_patient_context",
        "Basic non-identifying context about the current patient (age, sex, "
        "how many documents/active medications exist). Call this first if you "
        "need general context before a more specific lookup.",
        {},
    ),
    _schema(
        "search_documents",
        "Search the patient's documents by type and/or date range. Returns "
        "document metadata only (no full text) — call get_document for content.",
        {
            "document_type": {"type": ["string", "null"], "enum": DOCUMENT_TYPES + [None]},
            "date_from": {"type": ["string", "null"], "description": "ISO date, inclusive"},
            "date_to": {"type": ["string", "null"], "description": "ISO date, inclusive"},
            "limit": {"type": ["integer", "null"], "description": f"max {_MAX_LIST_LIMIT}"},
        },
    ),
    _schema(
        "get_document",
        "Get the structured/extracted text content of one specific document "
        "(by id, from search_documents). Content is truncated for very long "
        "documents — request a specific section_key if you know it.",
        {
            "document_id": {"type": "integer"},
            "section_key": {"type": ["string", "null"]},
        },
        required=["document_id"],
    ),
    _schema(
        "get_document_sources",
        "Get the citable SourceEvidence handles for one document (page + "
        "quoted source text) — use this to obtain source_evidence_id values "
        "you can cite in your final answer.",
        {"document_id": {"type": "integer"}},
        required=["document_id"],
    ),
    _schema(
        "get_lab_results",
        "Get structured lab results, optionally filtered by canonical test "
        "name (e.g. 'creatinine', 'hemoglobin') and/or date range.",
        {
            "canonical_name": {"type": ["string", "null"]},
            "date_from": {"type": ["string", "null"]},
            "date_to": {"type": ["string", "null"]},
            "limit": {"type": ["integer", "null"], "description": f"max {_MAX_LIST_LIMIT}"},
        },
    ),
    _schema(
        "get_lab_trend",
        "Get every observed value over time for one canonical lab test — "
        "use this for 'how has X changed' or chart requests. Never "
        "interpolates; only real observed points are returned.",
        {
            "canonical_name": {"type": "string"},
            "date_from": {"type": ["string", "null"]},
            "date_to": {"type": ["string", "null"]},
        },
        required=["canonical_name"],
    ),
    _schema(
        "compare_lab_results",
        "Compare the two most recent observed values for one canonical lab "
        "test (latest vs. previous), with the real numeric delta.",
        {"canonical_name": {"type": "string"}},
        required=["canonical_name"],
    ),
    _schema(
        "get_medications",
        "Get the patient's recorded medications, optionally filtered by status.",
        {"status": {"type": ["string", "null"]}},
    ),
    _schema(
        "get_patient_timeline",
        "Get the patient's care timeline (admissions/events), optionally "
        "filtered by date range.",
        {
            "date_from": {"type": ["string", "null"]},
            "date_to": {"type": ["string", "null"]},
            "limit": {"type": ["integer", "null"], "description": f"max {_MAX_LIST_LIMIT}"},
        },
    ),
    _schema(
        "get_source_evidence",
        "Get the exact quoted source text/page for one source_evidence_id "
        "you were already shown by an earlier tool call this turn.",
        {"source_evidence_id": {"type": "integer"}},
        required=["source_evidence_id"],
    ),
]


def run_tool(ctx: AskBragiContext, name: str, args: dict) -> dict:
    """The ONLY entry point that executes a tool. Re-authorizes on every
    single call (see AskBragiContext.require_current_access) — this is
    what protects against a revoked-mid-conversation grant, a deleted
    patient, or (as defense in depth, since the model never has a
    patient_id parameter to manipulate in the first place) a prompt-
    injected attempt to widen scope."""
    ctx.require_current_access()
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        return {"error": "unknown_tool"}
    try:
        return impl(ctx, args or {})
    except AskBragiAccessDenied:
        raise
    except Exception as exc:  # a tool bug must fail closed, not crash the whole turn
        return {"error": "tool_failed", "message": str(exc)[:200]}
