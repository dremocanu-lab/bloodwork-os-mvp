"""Retry/backoff and circuit-breaker helpers (BRAGI_INTEROP_PLAN.md Phase 3
§3.5/§3.6). Wraps `ssrf.safe_request` — never bypasses it; every retried
call still goes through the same SSRF-guarded path.

Retry policy: bounded exponential backoff + jitter for transient
failures (connection/read timeout, 408, 429, 502/503/504). `Retry-After`
is honored when present and reasonable (bounded — never blocks for an
absurd partner-supplied duration). 401/403 are never retried — those are
authentication/authorization failures, not transient conditions, and
hammering a server that's actively rejecting credentials helps no one.

Circuit breaker: `record_failure`/`record_success` are pure functions
over an `InteropConnection`-shaped object's `consecutive_failures`/
`last_failure_at` fields — the caller (fhir_connector.py) persists the
mutation. Crossing `DEGRADE_AFTER_CONSECUTIVE_FAILURES` transient
failures marks the connection DEGRADED (via the caller checking
`should_degrade()`), stopping automatic sync attempts until either a
manual "Test Connection" (which is allowed to try regardless of circuit
state — see P62) or time-based recovery eligibility.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

from app.services.interop.ssrf import SSRFBlocked, safe_request

RETRYABLE_STATUS_CODES = {408, 429, 502, 503, 504}
NON_RETRYABLE_AUTH_STATUS_CODES = {401, 403}

MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 8.0
MAX_RETRY_AFTER_SECONDS = 30.0  # never honor an absurdly long partner-supplied Retry-After

DEGRADE_AFTER_CONSECUTIVE_FAILURES = 5
# After this many minutes since the last failure, an automatic sync may
# try again even at/above the degrade threshold (a manual Test Connection
# is always allowed regardless — see P62).
AUTO_RECOVERY_COOLDOWN_MINUTES = 15


class ConnectorTransientError(RuntimeError):
    """All retries exhausted for a transient condition."""


class ConnectorAuthError(RuntimeError):
    """A non-retryable 401/403 — never retried."""


def _sleep_backoff(attempt: int, retry_after: float | None) -> None:
    if retry_after is not None:
        time.sleep(min(retry_after, MAX_RETRY_AFTER_SECONDS))
        return
    backoff = min(BASE_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)
    jitter = random.uniform(0, backoff * 0.25)
    time.sleep(backoff + jitter)


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        seconds = float(raw)
        return max(0.0, seconds)
    except ValueError:
        return None  # HTTP-date form — not worth the parsing complexity for a bounded internal retry


def request_with_retry(
    method: str,
    url: str,
    *,
    allow_private_network: bool,
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
    max_retries: int = MAX_RETRIES,
    _sleep=_sleep_backoff,  # test seam — real callers never override this
) -> requests.Response:
    """SSRF-guarded request with bounded retry/backoff for transient
    conditions. Raises ConnectorAuthError immediately on 401/403 (never
    retried) and ConnectorTransientError if retries are exhausted."""
    last_exc: Exception | None = None
    last_response: requests.Response | None = None

    for attempt in range(max_retries + 1):
        try:
            response = safe_request(method, url, allow_private_network=allow_private_network, headers=headers, json_body=json_body)
        except SSRFBlocked:
            raise  # never retried — a policy violation, not a transient condition
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            if attempt < max_retries:
                _sleep(attempt, None)
                continue
            raise ConnectorTransientError(f"Connection/timeout error after {max_retries + 1} attempts: {exc}") from exc

        if response.status_code in NON_RETRYABLE_AUTH_STATUS_CODES:
            raise ConnectorAuthError(f"Authentication rejected (HTTP {response.status_code})")

        if response.status_code in RETRYABLE_STATUS_CODES:
            last_response = response
            if attempt < max_retries:
                retry_after = _parse_retry_after(response)
                _sleep(attempt, retry_after)
                continue
            # Last attempt and still retryable — raise, don't silently
            # return the failed response (a real bug this exact test
            # caught: the old code fell through to `return response`
            # here, handing a 503 back to the caller as if it were a
            # normal response).
            raise ConnectorTransientError(
                f"Transient HTTP error persisted after {max_retries + 1} attempts (last status {response.status_code})"
            )

        return response

    # Unreachable in practice (every loop iteration above either
    # continues, returns, or raises) — kept only as a defensive fallback.
    raise ConnectorTransientError(
        f"Transient HTTP error persisted after {max_retries + 1} attempts "
        f"(last status {last_response.status_code if last_response else 'unknown'})"
    )


@dataclass
class CircuitState:
    consecutive_failures: int
    last_failure_at: str | None
    last_failure_reason: str | None


def record_failure(state: CircuitState, reason: str) -> CircuitState:
    return CircuitState(
        consecutive_failures=state.consecutive_failures + 1,
        last_failure_at=datetime.now(UTC).isoformat(),
        last_failure_reason=reason,
    )


def record_success(state: CircuitState) -> CircuitState:
    return CircuitState(consecutive_failures=0, last_failure_at=None, last_failure_reason=None)


def should_degrade(state: CircuitState) -> bool:
    return state.consecutive_failures >= DEGRADE_AFTER_CONSECUTIVE_FAILURES


def apply_failure(connection, reason: str) -> None:
    """Mutates a real InteropConnection ORM object directly — the thin
    integration point main.py's routes use, on top of the pure
    CircuitState functions above (kept separate and unit-testable without
    a DB-backed model)."""
    connection.consecutive_failures = (connection.consecutive_failures or 0) + 1
    connection.last_failure_at = datetime.now(UTC).isoformat()
    connection.last_failure_reason = reason


def apply_success(connection) -> None:
    connection.consecutive_failures = 0
    connection.last_failure_at = None
    connection.last_failure_reason = None


def connection_should_degrade(connection) -> bool:
    return (connection.consecutive_failures or 0) >= DEGRADE_AFTER_CONSECUTIVE_FAILURES


def is_within_auto_recovery_cooldown(state: CircuitState) -> bool:
    """True if an automatic (non-manual) sync attempt should be skipped
    because a failure happened too recently. A manual "Test Connection"
    is never gated by this — see P62."""
    if not state.last_failure_at:
        return False
    try:
        last_failure = datetime.fromisoformat(state.last_failure_at)
    except ValueError:
        return False
    elapsed_minutes = (datetime.now(UTC) - last_failure).total_seconds() / 60
    return elapsed_minutes < AUTO_RECOVERY_COOLDOWN_MINUTES
