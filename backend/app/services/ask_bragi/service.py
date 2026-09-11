"""Ask Bragi orchestration: the real OpenAI Responses API tool-calling
loop, citation validation, and chart resolution.

Architecture (see BRAGI_ASK_BRAGI_PLAN.md):

    authenticated Bragi user
      -> server-controlled patient context (context.py)
      -> Ask Bragi service (this file)
      -> OpenAI Responses API (real function/tool calling, not JSON-in-prose)
      -> restricted Bragi tools (tools.py)
      -> authorized canonical Bragi data
      -> SourceEvidence
      -> grounded, server-validated response
      -> existing openSourceEvidence(sourceEvidenceId) viewer (frontend)

OpenAI controls only language reasoning and which allowed tool to call.
Bragi controls patient scope, tool execution/authorization, citation
validation, and chart data. `store=False` on every call — Bragi owns
persistent conversation state (AskBragiConversation/AskBragiMessage),
never OpenAI-hosted conversation state (see BRAGI_SECURITY_GDPR_PLAN.md
§21 and docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md — no ZDR/special
retention setting is claimed or assumed here).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

from pydantic import ValidationError

from app.services.ai_minimization import redact_direct_identifiers

from .context import AskBragiContext
from .prompts import PROMPT_VERSION, build_system_prompt
from .schemas import (
    MODEL_OUTPUT_JSON_SCHEMA,
    AskBragiResponse,
    Chart,
    ChartPoint,
    ModelOutput,
)
from .tools import TOOL_SCHEMA_VERSION, TOOL_SCHEMAS, run_tool

ASK_BRAGI_ENABLED = os.getenv("ASK_BRAGI_ENABLED", "").strip().lower() in {"1", "true", "yes"}
ASK_BRAGI_MODEL = os.getenv("ASK_BRAGI_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1"))
ASK_BRAGI_MAX_TOOL_ROUNDS = int(os.getenv("ASK_BRAGI_MAX_TOOL_ROUNDS", "4"))
ASK_BRAGI_MAX_OUTPUT_TOKENS = int(os.getenv("ASK_BRAGI_MAX_OUTPUT_TOKENS", "1200"))
ASK_BRAGI_TIMEOUT_SECONDS = float(os.getenv("ASK_BRAGI_TIMEOUT_SECONDS", "45"))
# Bounded conversation replay — Bragi does not send the whole conversation
# history on every turn (§35/§62 of the build spec: minimum necessary
# data, no giant prompt). Only the last N turns are replayed as plain
# text context; older turns are summarized away entirely (dropped, not
# compressed by an extra model call, for V1 simplicity).
ASK_BRAGI_HISTORY_TURNS = int(os.getenv("ASK_BRAGI_HISTORY_TURNS", "6"))


class AskBragiError(Exception):
    """Raised for any provider/config failure the route layer should turn
    into a safe, generic error response — never a raw provider error or
    secret to the browser."""


@dataclass
class AskBragiTurnResult:
    response: AskBragiResponse
    tool_categories: list[str]
    model: str
    prompt_version: str
    tool_schema_version: str
    input_tokens: int | None
    output_tokens: int | None
    tool_rounds: int
    latency_ms: dict[str, float]


def _client():
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AskBragiError("OPENAI_API_KEY is not configured.")
    return OpenAI(api_key=api_key, timeout=ASK_BRAGI_TIMEOUT_SECONDS)


def _async_client():
    """Streaming's own client — async so run_turn_streaming can `async for`
    the provider's events and cooperatively check for a client disconnect
    between them (see main.py's streaming route), instead of blocking a
    worker thread inside a long-running sync call. run_turn() (the
    existing, non-streaming path) is untouched and keeps using the sync
    client above."""
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AskBragiError("OPENAI_API_KEY is not configured.")
    return AsyncOpenAI(api_key=api_key, timeout=ASK_BRAGI_TIMEOUT_SECONDS)


# Maps a tool name to the restrained, non-technical status line shown next
# to the thinking indicator while that tool's results are pending — never
# the tool name itself, and never raw arguments/output (see BRAGI_ASK_
# BRAGI_PLAN.md's "no chain-of-thought/raw tool payloads to the browser").
_TOOL_STATUS_LABELS: dict[str, str] = {
    "get_patient_context": "Checking your record…",
    "search_documents": "Searching your documents…",
    "get_document": "Reviewing this report…",
    "get_document_sources": "Reviewing this report…",
    "get_lab_results": "Reviewing laboratory results…",
    "get_lab_trend": "Reviewing laboratory results…",
    "compare_lab_results": "Comparing results…",
    "get_medications": "Checking medications…",
    "get_patient_timeline": "Reviewing your timeline…",
    "get_source_evidence": "Checking the source…",
}
_DEFAULT_STATUS_LABEL = "Checking your record…"


def status_label_for_tool(tool_name: str) -> str:
    return _TOOL_STATUS_LABELS.get(tool_name, _DEFAULT_STATUS_LABEL)


# Recognized JSON string escapes (RFC 8259 §7) for the incremental
# extractor below — deliberately NOT a general JSON parser.
_JSON_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def extract_streaming_answer_prefix(buffer: str) -> str:
    """Best-effort, incremental extraction of the growing `"answer"`
    string value from a PARTIAL (not yet complete, possibly truncated
    mid-character) JSON object the model is still streaming — used ONLY
    to show progressive text to the user while a turn is in progress.

    This is deliberately NOT a general JSON parser: it looks for the
    literal `"answer"` key, then decodes a JSON string value character by
    character (handling the standard escapes), stopping the instant it
    hits anything it cannot yet fully resolve (an incomplete `\\uXXXX`
    escape at the very end of the buffer, e.g.) rather than guessing —
    under-reporting a few pending characters is invisible to the user;
    ever producing more than what's actually confirmed is not the goal.

    The MODEL_OUTPUT_JSON_SCHEMA lists "answer" as the FIRST property,
    which in practice makes structured-output generation emit it first —
    this function only ever needs to look at the start of the buffer as
    a result, not scan for a key that could appear anywhere.

    Never used for anything the server trusts: the actual answer,
    citations, chart, follow_ups, and status always come from parsing
    the COMPLETE final JSON via ModelOutput.model_validate once the
    round finishes (see run_turn_streaming) — a wrong or incomplete
    extraction here can only ever affect what's shown mid-stream, never
    what's validated, cited, or persisted.
    """
    idx = buffer.find('"answer"')
    if idx == -1:
        return ""
    idx += len('"answer"')
    while idx < len(buffer) and buffer[idx] in " \t\r\n:":
        idx += 1
    if idx >= len(buffer) or buffer[idx] != '"':
        return ""
    idx += 1  # past the opening quote

    out: list[str] = []
    i = idx
    n = len(buffer)
    while i < n:
        ch = buffer[i]
        if ch == '"':
            break  # the string value is fully closed
        if ch == "\\":
            if i + 1 >= n:
                break  # escape sequence cut off — wait for more buffer
            nxt = buffer[i + 1]
            if nxt in _JSON_SIMPLE_ESCAPES:
                out.append(_JSON_SIMPLE_ESCAPES[nxt])
                i += 2
                continue
            if nxt == "u":
                if i + 6 > n:
                    break  # incomplete \uXXXX — wait for more buffer
                hex_part = buffer[i + 2 : i + 6]
                try:
                    out.append(chr(int(hex_part, 16)))
                except ValueError:
                    break
                i += 6
                continue
            break  # not a recognized escape (shouldn't happen for valid JSON)
        out.append(ch)
        i += 1
    return "".join(out)


def _history_as_text(prior_turns: list[tuple[str, str]]) -> str:
    """`prior_turns`: list of (role, content) tuples, oldest first, already
    bounded to ASK_BRAGI_HISTORY_TURNS by the caller. Plain text, not the
    Responses API's own multi-turn state — see module docstring."""
    if not prior_turns:
        return ""
    lines = ["Recent conversation history (most recent turns only):"]
    for role, content in prior_turns:
        speaker = "User" if role == "user" else "Ask Bragi"
        # Defense in depth: prior assistant/user turns are still just
        # conversation text by the time they're replayed — redact any
        # identifier shape that shouldn't be here regardless.
        lines.append(f"{speaker}: {redact_direct_identifiers(content)}")
    return "\n".join(lines)


# Server-authoritative scope-intent detection (never delegated to the
# model — see BRAGI_ASK_BRAGI_PLAN.md's "Scope broadening" section: "the
# server remains authoritative"). Deliberately a plain keyword/phrase
# match, not an LLM call — deterministic, free, and auditable. Only ever
# WIDENS a document-scoped turn to patient_record; there is no reverse
# ("only in this report") target to narrow to, since a patient_record
# conversation carries no single document_id to narrow onto — documented
# as a known limitation, not silently attempted.
_FULL_RECORD_INTENT_PATTERNS = [
    r"\bover time\b", r"\bever\b", r"\bhistory of\b", r"\bmedical history\b",
    r"\bhas this happened before\b", r"\bsimilar before\b", r"\bhappened before\b",
    r"\bpatient overall\b", r"\btrend\b", r"\bpreviously\b", r"\ball my (labs|results|records|documents)\b",
    r"\b(my|the) (whole|entire|full) record\b", r"\bacross my (whole|entire) record\b",
    r"\brepeatedly\b", r"\bin general\b",
]


def _detect_full_record_intent(message: str) -> bool:
    lowered = message.lower()
    return any(re.search(pattern, lowered) for pattern in _FULL_RECORD_INTENT_PATTERNS)


def _resolve_turn_scope(ctx: AskBragiContext, user_message: str, requested_scope: str | None) -> None:
    """Mutates ctx.turn_scope/ctx.broadened_this_turn BEFORE the model ever
    sees the request — an explicit UI scope toggle (`requested_scope`)
    always wins over keyword detection; both only ever apply when the
    conversation's stored scope is "document" (a patient_record
    conversation is already at its broadest)."""
    if ctx.scope != "document":
        return
    if requested_scope == "patient_record":
        ctx.turn_scope = "patient_record"
        ctx.broadened_this_turn = True
        return
    if requested_scope == "document":
        return  # explicit request to stay narrow — already the default
    if _detect_full_record_intent(user_message):
        ctx.turn_scope = "patient_record"
        ctx.broadened_this_turn = True


def _build_input_items(*, audience: str, scope: str, prior_turns: list[tuple[str, str]], user_message: str) -> list[dict]:
    """Shared by run_turn() and run_turn_streaming() so the two paths
    build the model's input identically — streaming must never see a
    different prompt/history/scope than the non-streaming path would."""
    system_prompt = build_system_prompt(audience=audience, scope=scope)
    history_text = _history_as_text(prior_turns[-ASK_BRAGI_HISTORY_TURNS:])
    input_items: list[dict] = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
    ]
    if history_text:
        input_items.append({"role": "user", "content": [{"type": "input_text", "text": history_text}]})
    input_items.append({"role": "user", "content": [{"type": "input_text", "text": user_message}]})
    return input_items


def run_turn(
    *,
    ctx: AskBragiContext,
    audience: str,
    user_message: str,
    prior_turns: list[tuple[str, str]],
    requested_scope: str | None = None,
) -> AskBragiTurnResult:
    if not ASK_BRAGI_ENABLED:
        raise AskBragiError("Ask Bragi is not enabled in this environment.")

    _resolve_turn_scope(ctx, user_message, requested_scope)

    client = _client()
    input_items = _build_input_items(
        audience=audience, scope=ctx.turn_scope, prior_turns=prior_turns, user_message=user_message
    )

    tool_categories: list[str] = []
    latency_ms: dict[str, float] = {}
    input_tokens = None
    output_tokens = None

    round_index = 0
    final_output_text: str | None = None

    while round_index < ASK_BRAGI_MAX_TOOL_ROUNDS:
        round_index += 1
        round_started = time.monotonic()
        response = client.responses.create(
            model=ASK_BRAGI_MODEL,
            input=input_items,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            max_output_tokens=ASK_BRAGI_MAX_OUTPUT_TOKENS,
            store=False,  # Bragi owns conversation state — see module docstring
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ask_bragi_response",
                    "schema": MODEL_OUTPUT_JSON_SCHEMA,
                    "strict": False,
                }
            },
        )
        latency_ms[f"model_round_{round_index}"] = (time.monotonic() - round_started) * 1000
        if getattr(response, "usage", None):
            input_tokens = (input_tokens or 0) + (response.usage.input_tokens or 0)
            output_tokens = (output_tokens or 0) + (response.usage.output_tokens or 0)

        function_calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]

        if not function_calls:
            final_output_text = response.output_text
            break

        # Append the assistant's own function_call items, then this
        # round's tool outputs, before looping back — the standard
        # Responses API multi-turn-tool-calling shape.
        for call in function_calls:
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
            )
            try:
                args = json.loads(call.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_started = time.monotonic()
            result = run_tool(ctx, call.name, args)
            latency_ms[f"tool_{call.name}_{round_index}"] = (time.monotonic() - tool_started) * 1000
            tool_categories.append(call.name)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                }
            )

    if final_output_text is None:
        # Ran out of tool rounds without a final answer — fail safely
        # rather than looping forever (Priority "tool loop limits").
        raise AskBragiError("Ask Bragi could not complete this request (too many tool calls).")

    try:
        parsed = json.loads(final_output_text)
        model_output = ModelOutput.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AskBragiError(f"Ask Bragi returned an invalid response: {exc}") from exc

    validated_response = _validate_and_resolve(ctx, model_output)

    return AskBragiTurnResult(
        response=validated_response,
        tool_categories=tool_categories,
        model=ASK_BRAGI_MODEL,
        prompt_version=PROMPT_VERSION,
        tool_schema_version=TOOL_SCHEMA_VERSION,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_rounds=round_index,
        latency_ms=latency_ms,
    )


async def run_turn_streaming(
    *,
    ctx: AskBragiContext,
    audience: str,
    user_message: str,
    prior_turns: list[tuple[str, str]],
    requested_scope: str | None = None,
    should_stop,
):
    """Async-generator counterpart to run_turn() — same scope resolution,
    same prompt/history construction (_build_input_items), same bounded
    tool-calling loop, same final validation (_validate_and_resolve).
    Streaming changes ONLY how the answer reaches the caller: instead of
    one return value at the end, this yields (event_name, payload) tuples
    as the turn progresses, so the browser can show progressive text
    instead of a full-answer plop.

    `should_stop`: an async zero-arg callable the caller passes in (see
    main.py), checked between provider events and between tool calls —
    this is how a client-side Stop actually halts further OpenAI/tool
    work here, not just hides the answer while the backend keeps going.

    Trust boundary is IDENTICAL to run_turn(): the only thing ever shown
    to the user AS IT STREAMS is a best-effort, non-authoritative prefix
    of the "answer" string (see extract_streaming_answer_prefix's own
    docstring for exactly why that's safe) — citations, chart, follow_ups
    and status are only ever taken from the COMPLETE final JSON, parsed
    and validated via ModelOutput.model_validate + _validate_and_resolve,
    exactly as run_turn() already does. Streaming never short-circuits
    that validation.
    """
    if not ASK_BRAGI_ENABLED:
        yield ("error", {"message": "Ask Bragi is not enabled in this environment."})
        return

    _resolve_turn_scope(ctx, user_message, requested_scope)
    yield ("started", {})

    client = _async_client()
    input_items = _build_input_items(
        audience=audience, scope=ctx.turn_scope, prior_turns=prior_turns, user_message=user_message
    )

    tool_categories: list[str] = []
    latency_ms: dict[str, float] = {}
    input_tokens = None
    output_tokens = None
    turn_started = time.monotonic()
    first_delta_at: float | None = None
    round_index = 0
    final_output_text: str | None = None

    while round_index < ASK_BRAGI_MAX_TOOL_ROUNDS:
        round_index += 1
        if await should_stop():
            yield ("stopped", {})
            return

        round_started = time.monotonic()
        stream = await client.responses.create(
            model=ASK_BRAGI_MODEL,
            input=input_items,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            max_output_tokens=ASK_BRAGI_MAX_OUTPUT_TOKENS,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ask_bragi_response",
                    "schema": MODEL_OUTPUT_JSON_SCHEMA,
                    "strict": False,
                }
            },
            stream=True,
        )

        text_buffer = ""
        emitted_len = 0
        function_calls: list = []
        stopped = False

        async for event in stream:
            if await should_stop():
                stopped = True
                break
            etype = getattr(event, "type", "")
            if etype == "response.output_text.delta":
                if first_delta_at is None:
                    first_delta_at = time.monotonic()
                text_buffer += event.delta
                prefix = extract_streaming_answer_prefix(text_buffer)
                if len(prefix) > emitted_len:
                    yield ("text_delta", {"delta": prefix[emitted_len:]})
                    emitted_len = len(prefix)
            elif etype == "response.output_item.done" and getattr(event.item, "type", None) == "function_call":
                function_calls.append(event.item)
            elif etype == "response.completed":
                usage = getattr(event.response, "usage", None)
                if usage:
                    input_tokens = (input_tokens or 0) + (usage.input_tokens or 0)
                    output_tokens = (output_tokens or 0) + (usage.output_tokens or 0)

        latency_ms[f"model_round_{round_index}"] = (time.monotonic() - round_started) * 1000

        if stopped:
            await stream.close()
            yield ("stopped", {})
            return

        if not function_calls:
            final_output_text = text_buffer
            break

        yield ("status", {"label": status_label_for_tool(function_calls[0].name)})
        for call in function_calls:
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
            )
            try:
                args = json.loads(call.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = run_tool(ctx, call.name, args)
            tool_categories.append(call.name)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                }
            )

    if final_output_text is None:
        yield ("error", {"message": "Ask Bragi could not complete this request (too many tool calls)."})
        return

    try:
        parsed = json.loads(final_output_text)
        model_output = ModelOutput.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError):
        yield ("error", {"message": "Ask Bragi returned an invalid response."})
        return

    validated_response = _validate_and_resolve(ctx, model_output)

    if validated_response.citations:
        yield ("citations", {"citations": [c.model_dump() for c in validated_response.citations]})
    if validated_response.chart:
        yield ("chart", {"chart": validated_response.chart.model_dump()})

    yield (
        "completed",
        {
            "answer": validated_response.answer,
            "citations": [c.model_dump() for c in validated_response.citations],
            "chart": validated_response.chart.model_dump() if validated_response.chart else None,
            "follow_ups": validated_response.follow_ups,
            "status": validated_response.status,
            "scope_used": validated_response.scope_used,
            "dropped_citation_count": validated_response.dropped_citation_count,
            "tool_categories": tool_categories,
            "model": ASK_BRAGI_MODEL,
            "prompt_version": PROMPT_VERSION,
            "tool_schema_version": TOOL_SCHEMA_VERSION,
            "tool_rounds": round_index,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "time_to_first_token_ms": (first_delta_at - turn_started) * 1000 if first_delta_at else None,
            "total_latency_ms": (time.monotonic() - turn_started) * 1000,
        },
    )


def _validate_and_resolve(ctx: AskBragiContext, model_output: ModelOutput) -> AskBragiResponse:
    """The model's output is NEVER trusted as-is. Citations are filtered
    to ctx.authorized_evidence_ids (populated only by real tool calls
    this turn — see tools.py); any chart_request is resolved into real
    server-fetched data, never the model's own numbers."""
    valid_citations = [c for c in model_output.citations if c.source_evidence_id in ctx.authorized_evidence_ids]
    dropped = len(model_output.citations) - len(valid_citations)

    chart: Chart | None = None
    if model_output.chart_request is not None:
        from .tools import _tool_get_lab_trend  # local import: avoid a module-level tools<->service coupling surprise

        trend = _tool_get_lab_trend(
            ctx,
            {
                "canonical_name": model_output.chart_request.canonical_name,
                "date_from": model_output.chart_request.date_from,
                "date_to": model_output.chart_request.date_to,
            },
        )
        points = [
            ChartPoint(
                date=p.get("date"),
                value=p.get("value"),
                unit=p.get("unit"),
                flag=p.get("flag"),
                reference_range=p.get("reference_range"),
                document_id=p.get("document_id"),
                lab_result_id=p.get("lab_result_id"),
                source_evidence_id=p.get("source_evidence_id"),
            )
            for p in trend.get("points", [])
        ]
        chart = Chart(canonical_name=model_output.chart_request.canonical_name, points=points)

    scope_used = "patient_record" if ctx.broadened_this_turn else ctx.turn_scope

    return AskBragiResponse(
        scope_used=scope_used,
        answer=model_output.answer,
        citations=valid_citations,
        chart=chart,
        follow_ups=model_output.follow_ups[:5],
        status=model_output.status,
        dropped_citation_count=dropped,
    )
