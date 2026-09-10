"""Unit tests for app/rate_limit.py — no DB required (unlike most of this
repo's security regression suite, which needs DATABASE_URL to import
app.main). See BRAGI_SECURITY_GDPR_PLAN.md §9.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app import rate_limit
from app.rate_limit import RateLimiter, _InMemoryBackend


def _fake_request(ip: str = "1.2.3.4", forwarded: str | None = None):
    request = MagicMock()
    request.client.host = ip
    request.headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return request


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch):
    # conftest.py sets RATE_LIMIT_DISABLED=true for the whole test session
    # (see its docstring) — these tests exist specifically to exercise
    # real enforcement, so re-enable it here regardless of that default.
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_DISABLED", False)
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


def test_in_memory_backend_allows_up_to_limit():
    backend = _InMemoryBackend()
    for _ in range(5):
        decision = backend.check("k", limit=5, window_seconds=60)
        assert decision.allowed
    decision = backend.check("k", limit=5, window_seconds=60)
    assert not decision.allowed
    assert decision.retry_after > 0


def test_in_memory_backend_resets_after_window(monkeypatch):
    backend = _InMemoryBackend()
    backend.check("k", limit=1, window_seconds=1)
    decision = backend.check("k", limit=1, window_seconds=1)
    assert not decision.allowed

    # Simulate the window elapsing rather than sleeping in a test.
    import time as time_module

    real_time = time_module.time
    monkeypatch.setattr(time_module, "time", lambda: real_time() + 2)
    decision = backend.check("k", limit=1, window_seconds=1)
    assert decision.allowed


def test_in_memory_backend_keys_are_independent():
    backend = _InMemoryBackend()
    backend.check("a", limit=1, window_seconds=60)
    decision_a = backend.check("a", limit=1, window_seconds=60)
    decision_b = backend.check("b", limit=1, window_seconds=60)
    assert not decision_a.allowed
    assert decision_b.allowed


def test_rate_limiter_dependency_raises_429_over_limit():
    limiter = RateLimiter(limit=2, window_seconds=60, key_prefix="test_endpoint")
    req = _fake_request(ip="9.9.9.9")
    limiter(req)
    limiter(req)
    with pytest.raises(HTTPException) as excinfo:
        limiter(req)
    assert excinfo.value.status_code == 429
    assert "Retry-After" in excinfo.value.headers


def test_rate_limiter_keys_by_client_ip_independently():
    limiter = RateLimiter(limit=1, window_seconds=60, key_prefix="per_ip_test")
    limiter(_fake_request(ip="1.1.1.1"))
    # Different IP must not be affected by the first IP's quota.
    limiter(_fake_request(ip="2.2.2.2"))


def test_rate_limiter_honors_x_forwarded_for():
    limiter = RateLimiter(limit=1, window_seconds=60, key_prefix="xff_test")
    limiter(_fake_request(ip="10.0.0.1", forwarded="203.0.113.5, 10.0.0.1"))
    with pytest.raises(HTTPException):
        # Same real client (first XFF hop) hitting through a different
        # proxy hop still shares the same quota.
        limiter(_fake_request(ip="10.0.0.2", forwarded="203.0.113.5, 10.0.0.2"))


def test_rate_limiter_fails_open_on_backend_error(monkeypatch):
    def _broken_backend():
        raise RuntimeError("simulated Redis outage")

    monkeypatch.setattr(rate_limit, "_get_backend", _broken_backend)
    limiter = RateLimiter(limit=1, window_seconds=60, key_prefix="broken_backend_test")
    req = _fake_request(ip="5.5.5.5")
    # Must not raise — a rate-limiter backend outage must never block
    # legitimate traffic.
    limiter(req)
    limiter(req)
    limiter(req)


def test_rate_limiter_disabled_kill_switch(monkeypatch):
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_DISABLED", True)
    limiter = RateLimiter(limit=1, window_seconds=60, key_prefix="disabled_test")
    req = _fake_request(ip="6.6.6.6")
    for _ in range(10):
        limiter(req)  # never raises while disabled


def test_is_distributed_false_without_redis_configured(monkeypatch):
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_REDIS_URL", None)
    assert rate_limit.is_distributed() is False
