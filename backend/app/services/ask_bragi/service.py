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


def run_turn(
    *,
    ctx: AskBragiContext,
    audience: str,
    user_message: str,
    prior_turns: list[tuple[str, str]],
) -> AskBragiTurnResult:
    if not ASK_BRAGI_ENABLED:
        raise AskBragiError("Ask Bragi is not enabled in this environment.")

    client = _client()
    system_prompt = build_system_prompt(audience=audience, scope=ctx.scope)
    history_text = _history_as_text(prior_turns[-ASK_BRAGI_HISTORY_TURNS:])

    input_items: list[dict] = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
    ]
    if history_text:
        input_items.append({"role": "user", "content": [{"type": "input_text", "text": history_text}]})
    input_items.append({"role": "user", "content": [{"type": "input_text", "text": user_message}]})

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
                source_evidence_id=p.get("source_evidence_id"),
            )
            for p in trend.get("points", [])
        ]
        chart = Chart(canonical_name=model_output.chart_request.canonical_name, points=points)

    return AskBragiResponse(
        answer=model_output.answer,
        citations=valid_citations,
        chart=chart,
        follow_ups=model_output.follow_ups[:5],
        status=model_output.status,
        dropped_citation_count=dropped,
    )
