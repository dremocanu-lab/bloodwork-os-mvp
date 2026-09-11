"""SSRF protection for outbound interop connector traffic.

Every network call this feature makes (capability discovery, SMART
discovery, token requests, FHIR search) MUST go through `safe_request()`
below rather than calling `requests` directly. See BRAGI_INTEROP_PLAN.md
P56/P75 — plug-and-play convenience must never weaken this.

What this blocks:
- non-http(s) schemes
- an IP-literal host in a private/loopback/link-local/multicast/reserved
  range, including the cloud-metadata address 169.254.169.254
- a hostname that RESOLVES to any such address (checked via a real DNS
  resolution before connecting)
- automatic redirect-following: redirects are disabled at the HTTP layer
  and re-validated one hop at a time (bounded), so a 302 from an approved
  endpoint to a private address is blocked rather than silently followed

Honest limitation: this validates the resolved address immediately before
each request, which closes the obvious SSRF cases (metadata IP, localhost,
private ranges, redirect-to-private) but is not a full defense against a
sub-second DNS-rebinding attack that changes the answer between this
check and the TCP connect a few milliseconds later. Closing that
completely needs a connection-level IP pin (a custom transport adapter);
not implemented in Phase 1 — tracked in BRAGI_INTEROP_PLAN.md's deferred
list. `allow_private_network` (sandbox connections only, never settable
in production — see InteropConnection.allow_private_network) bypasses the
private-range block for local development/test fixtures only.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import requests

MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = (5, 20)  # (connect, read) seconds
MAX_RESPONSE_BYTES = 25 * 1024 * 1024  # 25MB — generous for a CapabilityStatement/Bundle page


class SSRFBlocked(Exception):
    """Raised whenever a target URL/redirect fails the SSRF policy."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        # is_link_local covers 169.254.0.0/16, including the cloud metadata IP.
        return True
    # An IPv6 address that's really an IPv4-mapped/embedded private address
    # (e.g. ::ffff:169.254.169.254) — unwrap and re-check.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None and _is_blocked_ip(mapped):
        return True
    return False


def _validate_host(hostname: str, *, allow_private_network: bool) -> None:
    if not hostname:
        raise SSRFBlocked("URL has no hostname")

    # IP literal in the hostname itself.
    try:
        literal = ipaddress.ip_address(hostname.strip("[]"))
        if not allow_private_network and _is_blocked_ip(literal):
            raise SSRFBlocked(f"Target IP address {hostname} is in a blocked (private/loopback/link-local) range")
        return
    except ValueError:
        pass  # not an IP literal — resolve it below

    if not allow_private_network and hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise SSRFBlocked("Target host resolves to localhost, which is blocked")

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFBlocked(f"Could not resolve hostname {hostname}: {exc}") from exc

    if not addrinfo:
        raise SSRFBlocked(f"Hostname {hostname} did not resolve to any address")

    if allow_private_network:
        return

    for family, _, _, _, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if _is_blocked_ip(ip):
            raise SSRFBlocked(
                f"Hostname {hostname} resolves to {ip_str}, which is in a blocked "
                "(private/loopback/link-local/metadata) range"
            )


def validate_url(url: str, *, allow_private_network: bool = False) -> None:
    """Raise SSRFBlocked if `url` fails the outbound-connectivity policy.
    Call this before every connector network operation, including on each
    redirect hop."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlocked(f"Scheme {parsed.scheme!r} is not allowed — only http/https")
    if not allow_private_network and parsed.scheme == "http":
        raise SSRFBlocked("Plain http is only allowed for sandbox connections (allow_private_network)")
    _validate_host(parsed.hostname or "", allow_private_network=allow_private_network)


def safe_request(
    method: str,
    url: str,
    *,
    allow_private_network: bool = False,
    headers: dict | None = None,
    json_body: dict | None = None,
    data: bytes | str | None = None,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    _hop: int = 0,
) -> requests.Response:
    """SSRF-guarded HTTP request. Validates the target, disables automatic
    redirect-following, and re-validates + re-issues manually on each
    redirect hop (bounded by MAX_REDIRECTS)."""
    validate_url(url, allow_private_network=allow_private_network)

    response = requests.request(
        method,
        url,
        headers=headers,
        json=json_body,
        data=data,
        timeout=timeout,
        allow_redirects=False,
        stream=True,
    )

    if response.is_redirect or response.is_permanent_redirect:
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise SSRFBlocked("Redirect response had no Location header")
        if _hop >= MAX_REDIRECTS:
            raise SSRFBlocked(f"Too many redirects (> {MAX_REDIRECTS})")
        next_url = requests.compat.urljoin(url, location)
        return safe_request(
            method,
            next_url,
            allow_private_network=allow_private_network,
            headers=headers,
            json_body=json_body,
            data=data,
            timeout=timeout,
            _hop=_hop + 1,
        )

    # Bound response size even though we validated the target — a
    # compromised/misbehaving partner endpoint shouldn't be able to exhaust
    # memory on a capability/search fetch.
    total = 0
    chunks = []
    for chunk in response.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            response.close()
            raise SSRFBlocked(f"Response exceeded {MAX_RESPONSE_BYTES} bytes")
        chunks.append(chunk)
    response._content = b"".join(chunks)  # noqa: SLF001 — populate .content/.json() from bounded read
    response._content_consumed = True
    return response
