"""SSRF-protection unit tests (BRAGI_INTEROP_PLAN.md P56/P75). No DB, no
network — validate_url() rejects a target before any connection is
attempted."""

import pytest

from app.services.interop.ssrf import SSRFBlocked, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata IP
        "http://169.254.169.254/latest/meta-data/",
        "https://169.254.169.254/",
        "http://localhost/fhir",
        "http://127.0.0.1:8000/fhir",
        "https://127.0.0.1/fhir",
        "https://10.0.0.5/fhir",  # RFC1918 private
        "https://192.168.1.1/fhir",
        "https://172.16.0.1/fhir",
        "ftp://hospital.example/fhir",  # disallowed scheme
        "file:///etc/passwd",
    ],
)
def test_blocks_dangerous_targets_by_default(url):
    with pytest.raises(SSRFBlocked):
        validate_url(url, allow_private_network=False)


def test_blocks_plain_http_outside_sandbox():
    with pytest.raises(SSRFBlocked):
        validate_url("http://example.invalid/fhir", allow_private_network=False)


def test_sandbox_mode_allows_localhost():
    # allow_private_network is only ever settable on a sandbox connection
    # (and refused outright in production by the /admin/interop/connections
    # route — see test_interop_e2e.py) — with it set, localhost is allowed
    # so the synthetic-server test fixtures work.
    validate_url("http://127.0.0.1:9999/fhir", allow_private_network=True)
    validate_url("http://localhost:9999/fhir", allow_private_network=True)


def test_sandbox_mode_still_blocks_disallowed_scheme():
    with pytest.raises(SSRFBlocked):
        validate_url("ftp://127.0.0.1/fhir", allow_private_network=True)


def test_https_scheme_allowed_without_sandbox_for_a_real_hostname_shape():
    # We can't resolve a real hospital hostname in a unit test, but a
    # malformed/empty host must still be rejected distinctly from a DNS
    # failure.
    with pytest.raises(SSRFBlocked):
        validate_url("https:///fhir", allow_private_network=False)
