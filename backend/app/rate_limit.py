"""Production rate limiting.

Architecture (see BRAGI_SECURITY_GDPR_PLAN.md §9 for the full rationale):

- If `RATE_LIMIT_REDIS_URL` (falls back to `REDIS_URL`) is set, counters
  are stored in Redis — correct across however many Render instances are
  actually running (real, shared-state, horizontally-scale-safe rate
  limiting). This is the only backend that should be considered
  "distributed" protection.
- If neither is set, counters fall back to a per-process, in-memory
  store. This is NOT distributed — it only protects the single instance
  it runs in. It is still real protection for a single-instance
  deployment (correct today; re-verify the instance count before relying
  on it — see `docs/security/RATE_LIMITING.md`), but it must never be
  described as distributed protection, and it silently becomes weaker
  (each instance gets its own independent quota) the moment the backend
  is horizontally scaled without also configuring Redis.
- Fails OPEN: any unexpected error talking to the configured backend
  (a Redis connection failure, timeout, DNS blip) allows the request
  through rather than raising a 500 or blocking legitimate traffic. A
  rate-limiter outage must never become an application outage for a
  clinical-records system — see `_check_and_increment()`.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

RATE_LIMIT_REDIS_URL = os.getenv("RATE_LIMIT_REDIS_URL") or os.getenv("REDIS_URL")
# Global kill-switch: set RATE_LIMIT_DISABLED=true to bypass entirely
# (e.g. a load-test environment, or an incident where the limiter itself
# is misbehaving). Defaults to enabled.
RATE_LIMIT_DISABLED = os.getenv("RATE_LIMIT_DISABLED", "").strip().lower() in {"1", "true", "yes"}


@dataclass
class _Decision:
    allowed: bool
    retry_after: int


class _InMemoryBackend:
    """Fixed-window counter, one dict entry per key. Per-process only —
    see module docstring. Thread-safe (a single uvicorn worker process
    can still serve requests across a small threadpool for sync route
    handlers)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, tuple[int, float]] = {}  # key -> (count, window_start)

    def check(self, key: str, limit: int, window_seconds: int) -> _Decision:
        now = time.time()
        with self._lock:
            count, window_start = self._counters.get(key, (0, now))
            if now - window_start >= window_seconds:
                count, window_start = 0, now
            count += 1
            self._counters[key] = (count, window_start)
            if count > limit:
                retry_after = max(1, int(window_start + window_seconds - now))
                return _Decision(False, retry_after)
            return _Decision(True, 0)


class _RedisBackend:
    """Fixed-window counter using Redis INCR+EXPIRE. Shared across every
    process/instance pointed at the same Redis — this is the real
    distributed backend. INCR+EXPIRE (rather than a Lua script) is a
    deliberate simplicity choice: the tiny race it admits (two concurrent
    first-requests in the same window both setting the expiry) only ever
    makes the effective window marginally longer, never shorter — it
    cannot be used to bypass the limit, only to be marginally more
    lenient at a window boundary, which is an acceptable trade for a rate
    limiter (as opposed to, say, a financial ledger)."""

    def __init__(self, url: str) -> None:
        import redis  # local import: only required if Redis is actually configured

        self._client = redis.Redis.from_url(url, socket_connect_timeout=1.5, socket_timeout=1.5)

    def check(self, key: str, limit: int, window_seconds: int) -> _Decision:
        redis_key = f"bragi:ratelimit:{key}"
        count = self._client.incr(redis_key)
        if count == 1:
            self._client.expire(redis_key, window_seconds)
        if count > limit:
            ttl = self._client.ttl(redis_key)
            return _Decision(False, ttl if ttl and ttl > 0 else window_seconds)
        return _Decision(True, 0)


_backend = None
_backend_lock = threading.Lock()


def _get_backend():
    global _backend
    if _backend is not None:
        return _backend
    with _backend_lock:
        if _backend is not None:
            return _backend
        if RATE_LIMIT_REDIS_URL:
            try:
                _backend = _RedisBackend(RATE_LIMIT_REDIS_URL)
            except Exception as exc:  # pragma: no cover - defensive, exercised via fail-open test
                print(f"RATE LIMIT: Redis backend init failed ({exc}); falling back to in-memory (per-instance only).")
                _backend = _InMemoryBackend()
        else:
            _backend = _InMemoryBackend()
        return _backend


def is_distributed() -> bool:
    """True only when a real, shared Redis backend is active. Used by
    /ops/rate-limit-status (and tests) to assert the deployment isn't
    silently relying on a per-instance limiter while believing it's
    shared — never inferred from the presence of an env var alone."""
    return isinstance(_get_backend(), _RedisBackend)


def _client_ip(request: Request) -> str:
    # Render terminates TLS and proxies to the app; it sets X-Forwarded-For.
    # Trust it only for identifying the caller for rate-limiting purposes
    # (coarse abuse mitigation, not an authorization decision) — take the
    # left-most (original client) entry.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def RateLimiter(limit: int, window_seconds: int, key_prefix: str):
    """Returns a FastAPI dependency: `Depends(RateLimiter(limit=10, window_seconds=300, key_prefix="login"))`.

    A plain closure-returning factory rather than a class with `__call__`
    — deliberately: FastAPI introspects a dependency's parameters via
    `inspect.signature()`, and a callable *instance*'s `request: Request`
    parameter was not reliably recognized as the special injectable
    `Request` type in this codebase's FastAPI/Starlette version (it fell
    through to being treated as a required query parameter, breaking
    every route it was added to — caught by this file's own tests before
    ever reaching production). A plain function is the well-established,
    unambiguous FastAPI dependency shape.

    Keys by client IP by default. Fails open on any backend error.
    """

    def _dependency(request: Request) -> None:
        if RATE_LIMIT_DISABLED:
            return
        identity = _client_ip(request)
        key = f"{key_prefix}:{identity}"
        try:
            decision = _get_backend().check(key, limit, window_seconds)
        except Exception as exc:
            # Fail open — see module docstring. A rate-limiter backend
            # outage must never take the app down with it.
            print(f"RATE LIMIT: backend check failed for {key_prefix} ({exc}); allowing request through (fail-open).")
            return
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait and try again.",
                headers={"Retry-After": str(decision.retry_after)},
            )

    return _dependency


def reset_for_tests() -> None:
    """Test-only helper: drop the cached backend so a new one (with a
    fresh in-memory counter, or re-reading env vars) is created on next
    use."""
    global _backend
    with _backend_lock:
        _backend = None
