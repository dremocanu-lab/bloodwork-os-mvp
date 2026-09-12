"""Ask Bragi conversation routes (BRAGI backend modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"Ask Bragi" domain — high risk; the streaming route and server-owned-
context invariants make this the most behaviorally delicate domain to
move among the "normal" (non-auth) domains, extracted last among them
for exactly that reason).

Nothing about the prompt/tool semantics, server-controlled patient
context resolution, conversation ownership re-checks, source-evidence
validation, or streaming/cancellation behavior changed. In particular,
preserved exactly:

- Server-owned patient context: no route or request body accepts a
  caller-supplied patient id directly — `resolve_patient_id_for_new_conversation`
  / `resolve_document_scope` (app.services.ask_bragi.context) are the
  only paths that establish it, both already patient-access-checked.
- `_load_ask_bragi_conversation_for_owner`'s double check (ownership
  AND a fresh `recheck_access` against the patient) — a conversation id
  is not itself authorization.
- The streaming route's trust boundary: only the final, fully-validated
  `completed` payload is ever parsed for citations/chart/follow_ups/
  status, and a stopped/errored turn is never persisted.
- The PHI-free audit/metrics print lines (counts/categories only, never
  question/answer text) on both the streaming and non-streaming routes.

Every dependency here (`ASK_BRAGI_ENABLED`, `AskBragiError`, `run_turn`,
`run_turn_streaming`, `AskBragiAccessDenied`, `AskBragiContext`,
`recheck_access`, `resolve_document_scope`,
`resolve_patient_id_for_new_conversation`) is a service-level import
from app.services.ask_bragi.*, not something living in app.main — so
unlike every other router this phase, nothing here needs a lazy
`from app.main import ...`.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_db, require_role
from app.core.utils import generate_public_id, now_iso
from app.rate_limit import RateLimiter
from app.services.ask_bragi.context import (
    AskBragiAccessDenied,
    AskBragiContext,
    recheck_access,
    resolve_document_scope,
    resolve_patient_id_for_new_conversation,
)
from app.services.ask_bragi.service import ASK_BRAGI_ENABLED, AskBragiError, run_turn, run_turn_streaming

router = APIRouter()


def require_ask_bragi_enabled():
    if not ASK_BRAGI_ENABLED:
        raise HTTPException(status_code=404, detail="Ask Bragi is not enabled in this environment.")


class AskBragiConversationCreateRequest(BaseModel):
    # Patients never supply this — their own patient_id is always
    # resolved server-side (see resolve_patient_id_for_new_conversation).
    # Doctors must supply it, validated against a real active
    # DoctorPatientAccess grant, identically to every other doctor-facing
    # patient route in this app.
    patient_id: int | None = None
    # Optional: scope this conversation to one document instead of the
    # full record (see BRAGI_ASK_BRAGI_PLAN.md's scope model).
    document_id: int | None = None


class AskBragiMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # Explicit scope toggle from the contextual UI ("This document" /
    # "Full record") — optional; when omitted, the server falls back to
    # keyword-based intent detection (see service.py's
    # _resolve_turn_scope). Only ever WIDENS a document-scoped
    # conversation; has no effect on a patient_record-scoped one.
    requested_scope: str | None = None


def _serialize_ask_bragi_conversation(conversation) -> dict:
    return {
        "id": conversation.id,
        "public_id": conversation.public_id,
        "patient_id": conversation.patient_id,
        "scope": conversation.scope,
        "document_id": conversation.document_id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def _serialize_ask_bragi_message(message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "citations": json.loads(message.citations_json) if message.citations_json else [],
        "chart": json.loads(message.chart_json) if message.chart_json else None,
        "follow_ups": json.loads(message.follow_ups_json) if message.follow_ups_json else [],
        "status": message.status,
        "scope_used": message.scope_used,
        "created_at": message.created_at,
    }


def _load_ask_bragi_conversation_for_owner(db: Session, conversation_id: int, current_user):
    conversation = (
        db.query(models.AskBragiConversation)
        .filter(models.AskBragiConversation.id == conversation_id)
        .first()
    )
    if not conversation or conversation.owner_user_id != current_user.id or conversation.archived_at:
        # Same non-existence-leaking shape as every other resource lookup
        # in this app (test_idor_regression.py's convention) — a
        # conversation ID that exists but isn't yours reads identically
        # to one that doesn't exist at all.
        raise HTTPException(status_code=404, detail="Conversation not found.")
    # Conversation ownership is NOT the same as current patient access —
    # re-check both independently every time (Priority: "conversation ID
    # is not authorization").
    if not recheck_access(
        db,
        requester_user_id=current_user.id,
        requester_role=current_user.role,
        patient_id=conversation.patient_id,
    ):
        raise HTTPException(status_code=403, detail="Access to this patient's record is no longer authorized.")
    return conversation


@router.post("/ask-bragi/conversations")
def create_ask_bragi_conversation(
    payload: AskBragiConversationCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="ask_bragi_conversation")),
):
    try:
        patient_id = resolve_patient_id_for_new_conversation(
            db, current_user=current_user, requested_patient_id=payload.patient_id
        )
    except AskBragiAccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    scope = "patient_record"
    document_id = None
    if payload.document_id is not None:
        try:
            document_id = resolve_document_scope(db, patient_id=patient_id, document_id=payload.document_id)
        except AskBragiAccessDenied as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        scope = "document"

    conversation = models.AskBragiConversation(
        public_id=generate_public_id("brg-chat"),
        owner_user_id=current_user.id,
        patient_id=patient_id,
        scope=scope,
        document_id=document_id,
        owner_role=current_user.role,
        created_at=now_iso(),
    )
    db.add(conversation)
    db.commit()
    return _serialize_ask_bragi_conversation(conversation)


@router.get("/ask-bragi/conversations")
def list_ask_bragi_conversations(
    patient_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
):
    """Without `patient_id`: every conversation this user owns, across
    every patient — used by the patient's own /ask-bragi history and (for
    a doctor) as a fallback. With `patient_id`: only that patient's
    conversations — how a doctor's per-patient history sidebar stays
    scoped to the patient they're actually looking at (BRAGI product
    spec: doctor history must be PATIENT-SCOPED, never a mixed list
    across every patient they've ever asked about). Authorization is
    re-checked here independently of `owner_user_id`, same convention as
    _load_ask_bragi_conversation_for_owner — a doctor whose access to
    this patient has since been revoked gets an empty list, not a 403,
    matching how every other "list what I can currently see" endpoint in
    this app degrades (no existence/authorization signal leaked either
    way).

    Excludes conversations with zero messages: with lazy conversation
    creation (a row is only ever created once a first user message is
    actually sent — see POST /ask-bragi/conversations/{id}/messages and
    /messages/stream), a real zero-message row should no longer occur in
    normal use, but this filter is kept as a defense-in-depth backstop
    (e.g. a client that creates a conversation and then crashes/loses
    connectivity before ever sending a message) so history never shows a
    "New conversation" entry with nothing in it."""
    query = db.query(models.AskBragiConversation).filter(
        models.AskBragiConversation.owner_user_id == current_user.id,
        models.AskBragiConversation.archived_at.is_(None),
        models.AskBragiConversation.messages.any(),
    )
    if patient_id is not None:
        if not recheck_access(
            db,
            requester_user_id=current_user.id,
            requester_role=current_user.role,
            patient_id=patient_id,
        ):
            return []
        query = query.filter(models.AskBragiConversation.patient_id == patient_id)
    conversations = query.order_by(models.AskBragiConversation.id.desc()).all()
    return [_serialize_ask_bragi_conversation(c) for c in conversations]


@router.get("/ask-bragi/conversations/{conversation_id}")
def get_ask_bragi_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
):
    conversation = _load_ask_bragi_conversation_for_owner(db, conversation_id, current_user)
    return {
        **_serialize_ask_bragi_conversation(conversation),
        "messages": [_serialize_ask_bragi_message(m) for m in conversation.messages],
    }


@router.delete("/ask-bragi/conversations/{conversation_id}")
def delete_ask_bragi_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
):
    conversation = _load_ask_bragi_conversation_for_owner(db, conversation_id, current_user)
    db.delete(conversation)  # cascades to messages — see models.py relationship
    db.commit()
    return {"deleted": True}


@router.post("/ask-bragi/conversations/{conversation_id}/messages")
def send_ask_bragi_message(
    conversation_id: int,
    payload: AskBragiMessageRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
    _rl=Depends(RateLimiter(limit=20, window_seconds=3600, key_prefix="ask_bragi_message")),
):
    conversation = _load_ask_bragi_conversation_for_owner(db, conversation_id, current_user)

    prior_messages = list(conversation.messages)
    prior_turns = [(m.role, m.content) for m in prior_messages]

    ctx = AskBragiContext(
        db=db,
        patient_id=conversation.patient_id,
        requester_user_id=current_user.id,
        requester_role=current_user.role,
        scope=conversation.scope,
        document_id=conversation.document_id,
    )
    audience = "patient" if current_user.role == "patient" else "doctor"

    try:
        result = run_turn(
            ctx=ctx,
            audience=audience,
            user_message=payload.message,
            prior_turns=prior_turns,
            requested_scope=payload.requested_scope,
        )
    except AskBragiError as exc:
        # Never the raw provider error/secret — a generic, safe message.
        print(f"ASK BRAGI: turn failed for conversation {conversation_id}: {exc}")
        raise HTTPException(status_code=502, detail="Ask Bragi could not process this message. Please try again.")
    except Exception as exc:  # provider SDK exceptions (auth/429/timeout/500/etc.)
        print(f"ASK BRAGI: unexpected error for conversation {conversation_id}: {type(exc).__name__}")
        raise HTTPException(status_code=502, detail="Ask Bragi could not process this message. Please try again.")

    now = now_iso()
    user_row = models.AskBragiMessage(
        conversation_id=conversation.id,
        role="user",
        content=payload.message,
        created_at=now,
    )
    assistant_row = models.AskBragiMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=result.response.answer,
        citations_json=json.dumps([c.model_dump() for c in result.response.citations]),
        chart_json=json.dumps(result.response.chart.model_dump()) if result.response.chart else None,
        follow_ups_json=json.dumps(result.response.follow_ups),
        status=result.response.status,
        scope_used=result.response.scope_used,
        tool_categories_json=json.dumps(result.tool_categories),
        prompt_version=result.prompt_version,
        tool_schema_version=result.tool_schema_version,
        model=result.model,
        created_at=now_iso(),
    )
    db.add(user_row)
    db.add(assistant_row)
    conversation.updated_at = now_iso()
    if not conversation.title:
        conversation.title = payload.message[:80]
    db.add(conversation)
    db.commit()

    # PHI-free audit/metrics line (counts and categories only — never the
    # question/answer text or raw tool output, per Priority "audit"/"cost
    # controls"). The durable, queryable audit trail is
    # tool_categories_json on the message row itself.
    print(
        f"ASK BRAGI: conversation={conversation.id} user_id={current_user.id} "
        f"tool_rounds={result.tool_rounds} tools={result.tool_categories} "
        f"citations={len(result.response.citations)} dropped_citations={result.response.dropped_citation_count} "
        f"input_tokens={result.input_tokens} output_tokens={result.output_tokens} model={result.model}"
    )

    return _serialize_ask_bragi_message(assistant_row)


def _sse(event: str, data: dict) -> str:
    """One Server-Sent Event frame. `data` is always a JSON object — never
    raw text — so the frontend has one parsing path for every event type."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/ask-bragi/conversations/{conversation_id}/messages/stream")
async def stream_ask_bragi_message(
    conversation_id: int,
    payload: AskBragiMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
    _rl=Depends(RateLimiter(limit=20, window_seconds=3600, key_prefix="ask_bragi_message")),
):
    """Streaming counterpart to POST .../messages — same authorization,
    same persistence, same validated final content; the only difference
    is the answer text reaches the browser progressively (Server-Sent
    Events) instead of all at once. See run_turn_streaming's own
    docstring for the trust-boundary argument (unchanged from the
    non-streaming route: only the FINAL, fully-validated JSON is ever
    parsed for citations/chart/follow_ups/status).

    Real cancellation: `should_stop` is checked between provider events
    and between tool-call rounds inside run_turn_streaming — a client
    that aborts its fetch (Stop button, navigating away, switching
    patients) closes this connection, `request.is_disconnected()` starts
    returning True, and the provider stream is closed from our side
    (stream.close()) rather than left running unread. A stopped turn is
    NOT persisted — its text never passed citation/chart validation, so
    nothing about it is trustworthy enough to store; the conversation
    simply has no assistant reply for that turn, exactly as if the
    request had never been made.
    """
    conversation = _load_ask_bragi_conversation_for_owner(db, conversation_id, current_user)
    prior_messages = list(conversation.messages)
    prior_turns = [(m.role, m.content) for m in prior_messages]

    ctx = AskBragiContext(
        db=db,
        patient_id=conversation.patient_id,
        requester_user_id=current_user.id,
        requester_role=current_user.role,
        scope=conversation.scope,
        document_id=conversation.document_id,
    )
    audience = "patient" if current_user.role == "patient" else "doctor"

    async def should_stop() -> bool:
        return await request.is_disconnected()

    async def event_stream():
        completed_payload: dict | None = None
        try:
            async for event_name, data in run_turn_streaming(
                ctx=ctx,
                audience=audience,
                user_message=payload.message,
                prior_turns=prior_turns,
                requested_scope=payload.requested_scope,
                should_stop=should_stop,
            ):
                if event_name == "completed":
                    completed_payload = data
                yield _sse(event_name, data)
        except Exception as exc:  # provider SDK exceptions (auth/429/timeout/500/etc.)
            print(f"ASK BRAGI STREAM: unexpected error for conversation {conversation_id}: {type(exc).__name__}")
            yield _sse("error", {"message": "Ask Bragi could not process this message. Please try again."})
            return

        if completed_payload is None:
            return  # stopped or errored — nothing to persist, see docstring above

        now = now_iso()
        user_row = models.AskBragiMessage(
            conversation_id=conversation.id,
            role="user",
            content=payload.message,
            created_at=now,
        )
        assistant_row = models.AskBragiMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=completed_payload["answer"],
            citations_json=json.dumps(completed_payload["citations"]),
            chart_json=json.dumps(completed_payload["chart"]) if completed_payload["chart"] else None,
            follow_ups_json=json.dumps(completed_payload["follow_ups"]),
            status=completed_payload["status"],
            scope_used=completed_payload["scope_used"],
            tool_categories_json=json.dumps(completed_payload["tool_categories"]),
            prompt_version=completed_payload["prompt_version"],
            tool_schema_version=completed_payload["tool_schema_version"],
            model=completed_payload["model"],
            created_at=now_iso(),
        )
        db.add(user_row)
        db.add(assistant_row)
        conversation.updated_at = now_iso()
        if not conversation.title:
            conversation.title = payload.message[:80]
        db.add(conversation)
        db.commit()

        # Same PHI-free audit/metrics line as the non-streaming route.
        print(
            f"ASK BRAGI: conversation={conversation.id} user_id={current_user.id} "
            f"tool_rounds={completed_payload.get('tool_rounds')} tools={completed_payload['tool_categories']} "
            f"citations={len(completed_payload['citations'])} "
            f"dropped_citations={completed_payload['dropped_citation_count']} "
            f"input_tokens={completed_payload.get('input_tokens')} output_tokens={completed_payload.get('output_tokens')} "
            f"model={completed_payload['model']}"
        )
        # The message's own real id/created_at only exist after this
        # commit — tell the frontend so it can reconcile its optimistic,
        # in-progress bubble with the persisted row (citation click-
        # through, React key, etc. all key off the real id).
        yield _sse("saved", {"message": _serialize_ask_bragi_message(assistant_row)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx and similar) so deltas flush immediately
            "Connection": "keep-alive",
        },
    )
