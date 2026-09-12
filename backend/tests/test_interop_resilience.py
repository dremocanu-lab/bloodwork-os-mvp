"""Retry/backoff + circuit-breaker tests (BRAGI_INTEROP_PLAN.md Phase 3
§3.5/§3.6). No DB; network is mocked (unittest.mock) — these exercise the
REAL request_with_retry/circuit-breaker code paths, not a re-implementation."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.services.interop.resilience import (
    DEGRADE_AFTER_CONSECUTIVE_FAILURES,
    ConnectorAuthError,
    ConnectorTransientError,
    apply_failure,
    apply_success,
    connection_should_degrade,
    is_within_auto_recovery_cooldown,
    request_with_retry,
)


def _fake_response(status_code, headers=None):
    resp = requests.Response()
    resp.status_code = status_code
    resp.headers.update(headers or {})
    resp._content = b"{}"
    return resp


def test_success_on_first_try_no_retry():
    with patch("app.services.interop.resilience.safe_request", return_value=_fake_response(200)) as mock_req:
        response = request_with_retry("GET", "https://partner.example/fhir", allow_private_network=False, _sleep=lambda *a: None)
        assert response.status_code == 200
        assert mock_req.call_count == 1


def test_retries_transient_5xx_then_succeeds():
    responses = [_fake_response(503), _fake_response(503), _fake_response(200)]
    with patch("app.services.interop.resilience.safe_request", side_effect=responses):
        response = request_with_retry("GET", "https://partner.example/fhir", allow_private_network=False, _sleep=lambda *a: None)
        assert response.status_code == 200


def test_exhausts_retries_and_raises_transient_error():
    with patch("app.services.interop.resilience.safe_request", return_value=_fake_response(503)):
        with pytest.raises(ConnectorTransientError):
            request_with_retry("GET", "https://partner.example/fhir", allow_private_network=False, max_retries=2, _sleep=lambda *a: None)


def test_401_never_retried():
    call_count = {"n": 0}

    def _responder(*a, **k):
        call_count["n"] += 1
        return _fake_response(401)

    with patch("app.services.interop.resilience.safe_request", side_effect=_responder):
        with pytest.raises(ConnectorAuthError):
            request_with_retry("GET", "https://partner.example/fhir", allow_private_network=False, _sleep=lambda *a: None)
    assert call_count["n"] == 1  # never retried


def test_403_never_retried():
    with patch("app.services.interop.resilience.safe_request", return_value=_fake_response(403)):
        with pytest.raises(ConnectorAuthError):
            request_with_retry("GET", "https://partner.example/fhir", allow_private_network=False, _sleep=lambda *a: None)


def test_429_retried_and_honors_retry_after():
    responses = [_fake_response(429, headers={"Retry-After": "1"}), _fake_response(200)]
    sleep_calls = []
    with patch("app.services.interop.resilience.safe_request", side_effect=responses):
        request_with_retry(
            "GET", "https://partner.example/fhir", allow_private_network=False, _sleep=lambda attempt, retry_after: sleep_calls.append(retry_after)
        )
    assert sleep_calls == [1.0]


def test_connection_error_retried_then_succeeds():
    with patch(
        "app.services.interop.resilience.safe_request",
        side_effect=[requests.exceptions.ConnectionError("boom"), _fake_response(200)],
    ):
        response = request_with_retry("GET", "https://partner.example/fhir", allow_private_network=False, _sleep=lambda *a: None)
        assert response.status_code == 200


def test_ssrf_blocked_never_retried():
    from app.services.interop.ssrf import SSRFBlocked

    call_count = {"n": 0}

    def _responder(*a, **k):
        call_count["n"] += 1
        raise SSRFBlocked("nope")

    with patch("app.services.interop.resilience.safe_request", side_effect=_responder):
        with pytest.raises(SSRFBlocked):
            request_with_retry("GET", "http://169.254.169.254/", allow_private_network=False, _sleep=lambda *a: None)
    assert call_count["n"] == 1


# --- Circuit breaker ---------------------------------------------------


def _fake_connection():
    return SimpleNamespace(consecutive_failures=0, last_failure_at=None, last_failure_reason=None)


def test_apply_failure_increments_and_apply_success_resets():
    conn = _fake_connection()
    apply_failure(conn, "timeout")
    apply_failure(conn, "timeout")
    assert conn.consecutive_failures == 2
    assert conn.last_failure_reason == "timeout"
    assert conn.last_failure_at is not None

    apply_success(conn)
    assert conn.consecutive_failures == 0
    assert conn.last_failure_at is None
    assert conn.last_failure_reason is None


def test_degrade_threshold():
    conn = _fake_connection()
    for _ in range(DEGRADE_AFTER_CONSECUTIVE_FAILURES - 1):
        apply_failure(conn, "timeout")
    assert connection_should_degrade(conn) is False
    apply_failure(conn, "timeout")
    assert connection_should_degrade(conn) is True


def test_auto_recovery_cooldown():
    from app.services.interop.resilience import CircuitState

    fresh_failure = CircuitState(consecutive_failures=1, last_failure_at=__import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(), last_failure_reason="timeout")
    assert is_within_auto_recovery_cooldown(fresh_failure) is True

    no_failure = CircuitState(consecutive_failures=0, last_failure_at=None, last_failure_reason=None)
    assert is_within_auto_recovery_cooldown(no_failure) is False
