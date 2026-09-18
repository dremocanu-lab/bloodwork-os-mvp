"""Source Intelligence + Provenance V2, Part 5 — per-page failure
isolation and extraction-coverage bookkeeping in
discharge_summary_pipeline.py. Pure-function tests only (no PyMuPDF/
OpenAI calls) — `_call_openai_for_page_safe` mocks the one function that
actually calls OpenAI, `_normalize_payload`/`_build_warnings` are called
directly with constructed inputs.
"""

from __future__ import annotations

import pytest

from app.services import discharge_summary_pipeline as pipeline


def test_normalize_payload_reports_complete_extraction_when_nothing_failed():
    page_payloads = [
        {"page_number": 1, "sections": [{"key": "diagnoses", "title": "Diagnostic", "body": "D45"}]},
        {"page_number": 2, "sections": [{"key": "epicriza", "title": "EPICRIZĂ", "body": "text"}]},
    ]
    payload = pipeline._normalize_payload(page_payloads, actual_page_count=2, failed_pages={})
    coverage = payload["extraction_coverage"]
    assert coverage["total_pages"] == 2
    assert coverage["attempted_pages"] == 2
    assert coverage["successful_pages"] == 2
    assert coverage["failed_pages"] == []
    assert coverage["extraction_complete"] is True


def test_normalize_payload_never_claims_complete_when_pages_failed():
    page_payloads = [
        {"page_number": 1, "sections": [{"key": "diagnoses", "title": "Diagnostic", "body": "D45"}]},
    ]
    failed_pages = {2: "Timed out", 3: "Provider error"}
    payload = pipeline._normalize_payload(page_payloads, actual_page_count=3, failed_pages=failed_pages)
    coverage = payload["extraction_coverage"]
    assert coverage["total_pages"] == 3
    assert coverage["attempted_pages"] == 3
    assert coverage["successful_pages"] == 1
    assert coverage["failed_pages"] == [2, 3]
    assert coverage["extraction_complete"] is False
    # The failure is also surfaced in the human-readable warnings, not
    # only in the structured coverage block.
    assert any("Page 2" in w and "Timed out" in w for w in payload["warnings"])
    assert any("Page 3" in w and "Provider error" in w for w in payload["warnings"])


def test_call_openai_for_page_safe_retries_once_then_succeeds():
    calls = {"count": 0}

    def flaky(_client, page):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient provider error")
        return {"page_number": page["page_number"], "sections": []}

    original = pipeline._call_openai_for_page
    pipeline._call_openai_for_page = flaky
    try:
        result, page_number, error = pipeline._call_openai_for_page_safe(None, {"page_number": 7})
    finally:
        pipeline._call_openai_for_page = original

    assert calls["count"] == 2
    assert result == {"page_number": 7, "sections": []}
    assert page_number == 7
    assert error is None


def test_call_openai_for_page_safe_gives_up_after_two_failures_isolating_this_page_only():
    calls = {"count": 0}

    def always_fails(_client, _page):
        calls["count"] += 1
        raise RuntimeError(f"provider error #{calls['count']}")

    original = pipeline._call_openai_for_page
    pipeline._call_openai_for_page = always_fails
    try:
        result, page_number, error = pipeline._call_openai_for_page_safe(None, {"page_number": 4})
    finally:
        pipeline._call_openai_for_page = original

    assert calls["count"] == 2  # one retry, not more, not zero
    assert result is None  # never raises — isolates THIS page's failure
    assert page_number == 4
    assert "provider error" in error
