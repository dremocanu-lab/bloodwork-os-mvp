"""Pre-Phase-11 Romanian discharge classification closure session.

Real/mocked Reducto classification decision logic (`_build_classification`/
`_decide_status`, `reducto_extraction.py`) was previously never exercised
by any test in this repo — every existing Reducto-adjacent test covers
config/enablement gating or lab extraction, never the classify response
shape itself. This file constructs realistic Reducto `/classify` response
bodies (the exact shape `_build_classification` reads:
`body["result"]["category"]` + `body["response_confidence"]["categories"]`)
and proves the ambiguity-detection thresholds behave as documented,
including the real, previously-observed discharge/lab confidence tie
(see reducto_schemas.py's own module docstring).
"""

from app.services.reducto_extraction import _build_classification


def _response(winner: str, category_confidences: dict[str, float]) -> dict:
    return {
        "result": {"category": winner},
        "response_confidence": {
            "categories": [{"category": cat, "confidence": conf} for cat, conf in category_confidences.items()]
        },
        "job_id": "test-job",
    }


def test_clear_discharge_winner_classifies_confidently():
    body = _response("discharge_summary", {"discharge_summary": 1.0, "laboratory_results": 0.0})
    result = _build_classification("file-1", body)
    assert result.document_type.value == "discharge_summary"
    assert result.status == "classified"
    assert result.confidence == 1.0


def test_real_documented_discharge_lab_tie_needs_confirmation():
    # The exact tie shape reducto_schemas.py's own docstring documents as
    # observed live against the real API for "a discharge letter with an
    # embedded lab table" — the case needs_confirmation exists to catch.
    body = _response("discharge_summary", {"discharge_summary": 1.0, "laboratory_results": 1.0})
    result = _build_classification("file-2", body)
    assert result.document_type.value == "discharge_summary"
    assert result.status == "needs_confirmation"


def test_discharge_with_a_real_but_non_dominant_runner_up_still_classifies():
    # A discharge letter whose embedded lab table is real but clearly
    # secondary to the discharge letter itself (winner confidence well
    # clear of the runner-up) must NOT be forced into confirmation just
    # because a second category scored anything at all.
    body = _response("discharge_summary", {"discharge_summary": 0.9, "laboratory_results": 0.3})
    result = _build_classification("file-3", body)
    assert result.document_type.value == "discharge_summary"
    assert result.status == "classified"


def test_low_confidence_winner_status_is_other_not_auto_accepted():
    # document_type still reflects the (weak) winning category for
    # audit/display purposes, but status="other" is what actually gates
    # auto-acceptance — never silently auto-classified on thin signal.
    body = _response("discharge_summary", {"discharge_summary": 0.3, "laboratory_results": 0.1})
    result = _build_classification("file-4", body)
    assert result.status == "other"


def test_unknown_category_from_provider_falls_back_to_other_safely():
    # Defensive: Reducto returning a category string outside our own
    # taxonomy must never raise or silently misroute.
    body = _response("some_future_category_bragi_does_not_know", {"some_future_category_bragi_does_not_know": 0.95})
    result = _build_classification("file-5", body)
    assert result.document_type.value == "other"


def test_hospital_admission_note_stays_distinct_from_discharge_summary():
    body = _response("hospital_admission_note", {"hospital_admission_note": 0.95, "discharge_summary": 0.05})
    result = _build_classification("file-6", body)
    assert result.document_type.value == "hospital_admission_note"
    assert result.status == "classified"


def test_category_scores_are_preserved_for_downstream_confirmation_ui():
    body = _response("discharge_summary", {"discharge_summary": 1.0, "laboratory_results": 1.0})
    result = _build_classification("file-7", body)
    assert result.category_scores == {"discharge_summary": 1.0, "laboratory_results": 1.0}
