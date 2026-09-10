import os

# The rate limiter (app/rate_limit.py) keys by client IP by default.
# Starlette's TestClient reports the same fake IP for every request, so
# every test file in a pytest session would otherwise share ONE global
# counter across the whole run — an account-creation-heavy regression
# suite (test_idor_regression.py, test_upload_validation.py, and this
# round's deletion/DSAR/malware tests) would trip production rate limits
# from test volume alone, not abuse. Disable rate limiting for the test
# session by default; app/rate_limit.py's own unit tests
# (test_rate_limit.py) explicitly re-enable it via monkeypatch per-test
# since they need to exercise real enforcement.
#
# This must be set before `app.rate_limit` (imported by `app.main`) is
# first imported, since RATE_LIMIT_DISABLED is read once at module load —
# conftest.py is collected before any test module, so this always runs
# first.
os.environ.setdefault("RATE_LIMIT_DISABLED", "true")
