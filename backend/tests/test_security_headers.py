"""Regression tests for the security-headers middleware and CORS config in
`app/main.py` (see BRAGI_SECURITY_GDPR_PLAN.md).

Unlike the rest of this suite, importing `app.main` runs `run_migrations()`
at module load, which needs real DB connectivity (DATABASE_URL) — a real
departure from this repo's existing unit-only test convention (see
CLAUDE_HANDOFF.md: "no DB fixtures convention exists yet"). Skipped
gracefully rather than failing the whole suite when no DATABASE_URL is
configured (e.g. in a CI job that hasn't been given DB credentials yet —
see docs/security/PRODUCTION_ACCESS_POLICY.md's CI section for what a
future job running this file needs).
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip(
        "DATABASE_URL not configured — this file needs real DB connectivity "
        "to import app.main (run_migrations() runs at import time).",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_security_headers_present_on_every_response():
    response = client.get("/docs")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "geolocation=()" in response.headers.get("permissions-policy", "")
    assert response.headers.get("x-frame-options") == "DENY"
    assert "default-src 'none'" in response.headers.get("content-security-policy", "")


def test_hsts_present_outside_development():
    # Whatever ENVIRONMENT this test process actually has (dev machines
    # normally run with ENVIRONMENT=development, per backend/.env) —
    # assert the header's presence tracks that setting exactly, rather
    # than assuming one value.
    response = client.get("/docs")
    is_dev = os.environ.get("ENVIRONMENT", "production").lower() == "development"
    has_hsts = "strict-transport-security" in response.headers
    assert has_hsts != is_dev


def test_cors_allows_configured_frontend_origin_only():
    # A real preflight request from the production frontend origin must be
    # allowed...
    response = client.options(
        "/auth/login",
        headers={
            "Origin": "https://app.bragi.health",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "https://app.bragi.health"

    # ...but an arbitrary, unrelated origin must not be reflected back.
    response = client.options(
        "/auth/login",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "https://evil.example.com"


def test_cors_never_wildcards_with_credentials():
    response = client.options(
        "/auth/login",
        headers={
            "Origin": "https://app.bragi.health",
            "Access-Control-Request-Method": "POST",
        },
    )
    # allow_credentials=True makes a bare "*" here an actual vulnerability
    # (it would let any origin's authenticated requests succeed) — this
    # must always be a specific origin, never a wildcard.
    assert response.headers.get("access-control-allow-origin") != "*"
