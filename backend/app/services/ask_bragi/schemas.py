"""Ask Bragi's response contracts.

Two distinct shapes, deliberately not conflated (see
BRAGI_ASK_BRAGI_PLAN.md's "Citation architecture" section):

- `ModelOutput` — what the model is asked to produce (structured output,
  `text.format=json_schema`, see service.py). `chart_request` here is a
  request/intent (a concept name), never real data points — the model
  cannot generate a chart's numbers.
- `AskBragiResponse` — what the API actually returns to the frontend,
  built by the SERVER from `ModelOutput` after validating every citation
  against `ctx.authorized_evidence_ids` and resolving `chart_request`
  into a real `Chart` (real DB rows, via get_lab_trend) — see
  service.py. The model's raw output is never sent to the frontend
  as-is.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MODEL_OUTPUT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_evidence_id": {"type": "integer"},
                    "label": {"type": "string"},
                    "document_type": {"type": ["string", "null"]},
                    "date": {"type": ["string", "null"]},
                    "page": {"type": ["integer", "null"]},
                },
                "required": ["source_evidence_id", "label"],
            },
        },
        "chart_request": {
            "type": ["object", "null"],
            "properties": {
                "canonical_name": {"type": "string"},
                "date_from": {"type": ["string", "null"]},
                "date_to": {"type": ["string", "null"]},
            },
            "required": ["canonical_name"],
        },
        "follow_ups": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": ["complete", "insufficient_data", "needs_clarification"]},
    },
    "required": ["answer", "citations", "follow_ups", "status"],
}


class ModelCitation(BaseModel):
    source_evidence_id: int
    label: str
    document_type: str | None = None
    date: str | None = None
    page: int | None = None


class ModelChartRequest(BaseModel):
    canonical_name: str
    date_from: str | None = None
    date_to: str | None = None


class ModelOutput(BaseModel):
    """The model's raw structured output — validated with Pydantic before
    the server trusts ANY of it (never assumed correct just because the
    API enforced a JSON schema — see service.py)."""

    answer: str
    citations: list[ModelCitation] = Field(default_factory=list)
    chart_request: ModelChartRequest | None = None
    follow_ups: list[str] = Field(default_factory=list)
    status: Literal["complete", "insufficient_data", "needs_clarification"] = "complete"


class ChartPoint(BaseModel):
    date: str | None
    value: str | None
    unit: str | None
    flag: str | None
    source_evidence_id: int | None = None


class Chart(BaseModel):
    canonical_name: str
    points: list[ChartPoint]


class AskBragiResponse(BaseModel):
    """The server-validated response actually sent to the frontend."""

    answer: str
    citations: list[ModelCitation]
    chart: Chart | None = None
    follow_ups: list[str]
    status: str
    dropped_citation_count: int = 0
    # "document" | "patient_record" — the scope THIS TURN ACTUALLY USED
    # (see context.py's `turn_scope`/`broadened_this_turn` and service.py's
    # `_resolve_turn_scope`). Always visible to the frontend so a document-
    # scoped conversation that broadened for one turn shows that
    # transition rather than silently searching wider than the UI implies.
    scope_used: str = "document"
