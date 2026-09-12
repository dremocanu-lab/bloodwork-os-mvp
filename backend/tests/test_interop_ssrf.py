"""SSRF-protection unit tests (BRAGI_INTEROP_PLAN.md P56/P75). No DB, no
real network — validate_url() rejects a target before any connection is
attempted. DNS resolution and outbound HTTP are mocked where a test needs
to simulate a platform/attacker-controlled answer (e.g. a libc that
accepts legacy numeric IP forms, or a DNS answer that changes between
requests) rather than depend on this machine's real resolver behavior."""

from unittest.mock import patch

import pytest

from app.services.interop.ssrf import SSRFBlocked, safe_request, validate_url


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


def test_userinfo_in_url_does_not_bypass_ip_literal_check():
    with pytest.raises(SSRFBlocked):
        validate_url("https://admin:hunter2@127.0.0.1/fhir", allow_private_network=False)


def test_unusual_port_does_not_bypass_ip_literal_check():
    with pytest.raises(SSRFBlocked):
        validate_url("https://127.0.0.1:65432/fhir", allow_private_network=False)


def test_ipv6_loopback_and_link_local_blocked():
    for url in ("https://[::1]/fhir", "https://[fe80::1]/fhir"):
        with pytest.raises(SSRFBlocked):
            validate_url(url, allow_private_network=False)


def test_ipv4_mapped_ipv6_loopback_blocked():
    with pytest.raises(SSRFBlocked):
        validate_url("https://[::ffff:127.0.0.1]/fhir", allow_private_network=False)


@pytest.mark.parametrize(
    "legacy_form",
    [
        "127.1",  # short-form IPv4 (some libc getaddrinfo implementations accept this as 127.0.0.1)
        "0177.0.0.1",  # octal-looking
        "0x7f.0x0.0x0.0x1",  # hex-looking
        "2130706433",  # decimal-integer form of 127.0.0.1
    ],
)
def test_legacy_numeric_ip_forms_blocked_even_if_a_libc_would_resolve_them(legacy_form):
    """This machine's real resolver rejects these outright (see
    test_blocks_dangerous_targets_by_default's sibling assertions), but
    production runs on a different OS/libc, and some do accept these as
    valid loopback spellings. Prove the block doesn't depend on THIS
    platform's resolver being strict: mock getaddrinfo to answer the way a
    permissive libc would (resolving straight to 127.0.0.1), and confirm
    the guard still blocks it — the check runs against the RESOLVED
    address, never trusts the literal spelling."""
    fake_addrinfo = [(2, 1, 6, "", ("127.0.0.1", 0))]
    with patch("socket.getaddrinfo", return_value=fake_addrinfo):
        with pytest.raises(SSRFBlocked):
            validate_url(f"https://{legacy_form}/fhir", allow_private_network=False)


def test_dns_rebinding_style_answer_is_still_blocked():
    """A hostname that resolves to a private address on ANY answer must be
    blocked, regardless of what a first-glance "looks public" hostname
    string suggests."""
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.99", 0))]):
        with pytest.raises(SSRFBlocked):
            validate_url("https://partner-fhir.example/fhir", allow_private_network=False)


class _FakeResponse:
    def __init__(self, status_code, headers=None, content=b"{}"):
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content
        self.closed = False

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308) and "Location" in self.headers

    is_permanent_redirect = False

    def iter_content(self, chunk_size=65536):
        yield self._content

    def close(self):
        self.closed = True


def test_redirect_from_allowed_public_host_to_private_ip_is_blocked():
    """P75's exact named scenario: an initially-approved public-looking
    endpoint issues a redirect to a private address (e.g. a compromised or
    misconfigured partner server, or an attacker who controls one hop).
    safe_request must re-validate the Location header before following
    it, not just the original URL."""
    # "partner-fhir.example" resolves to a public-looking address (DNS is
    # mocked — no real network I/O happens; the HTTP layer is mocked too).
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 0))]):
        with patch(
            "requests.request",
            return_value=_FakeResponse(302, headers={"Location": "https://169.254.169.254/latest/meta-data/"}),
        ):
            with pytest.raises(SSRFBlocked):
                safe_request("GET", "https://partner-fhir.example/fhir", allow_private_network=False)


def test_redirect_chain_is_bounded():
    """An unbounded redirect chain (even one that never actually reaches a
    blocked address) must not be followed forever."""
    call_count = {"n": 0}

    def _next_hop_response(method, url, **kwargs):
        call_count["n"] += 1
        return _FakeResponse(302, headers={"Location": f"https://partner-fhir.example/hop{call_count['n']}"})

    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 0))]):
        with patch("requests.request", side_effect=_next_hop_response):
            with pytest.raises(SSRFBlocked, match="redirect"):
                safe_request("GET", "https://partner-fhir.example/fhir", allow_private_network=False)
