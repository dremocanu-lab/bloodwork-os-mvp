"""Pluggable connector authentication (BRAGI_INTEROP_PLAN.md P7/P8).

One shared abstraction (`ConnectorAuthProvider`) instead of auth logic
duplicated per connector. Phase 1 implements the auth types the FHIR
connector actually needs; the interface is written so later connectors
(HL7 gateway, DICOMweb) can reuse the same providers without change.

Every provider's `get_headers()` is called fresh per request (providers
that fetch/cache a token do so internally, keyed by connection id) so a
connector never has to know whether auth involves a static value or a
live token exchange.

Auth types NOT implemented yet (raise NotImplementedError with a clear
message rather than silently no-op'ing): SMART authorization-code/PKCE
(interactive — not applicable to a server-to-server sync), mTLS (network-
level, needs the certificate-reference architecture in a later phase),
custom-header-secret (trivial extension of api_key_header, deferred until
a real partner needs it to avoid speculative surface).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from jose import jwt as jose_jwt

from app.services.interop.ssrf import safe_request

SUPPORTED_AUTH_TYPES = (
    "none",
    "static_bearer",
    "api_key_header",
    "basic_auth_legacy",
    "oauth2_client_credentials",
    "smart_backend_services",
)


class AuthConfigError(ValueError):
    """Raised when auth_config_json is missing a field a given auth_type requires."""


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # epoch seconds


# Process-local token cache keyed by connection id. Phase 1 doesn't persist
# tokens (P47: never persist raw access tokens longer than necessary) — a
# restart simply re-acquires one on next use. Multi-instance deployments
# each acquire independently, which is safe (no shared secret) if slightly
# redundant; a shared cache is a later optimization, not a correctness gap.
_token_cache: dict[int, _CachedToken] = {}

CLOCK_SKEW_TOLERANCE_SECONDS = 60  # P48 — small, fixed tolerance; exp/nbf are never disabled


class ConnectorAuthProvider:
    def get_headers(self, connection_id: int, auth_config: dict[str, Any], secret_plaintext: str | None) -> dict[str, str]:
        raise NotImplementedError


class NoneAuthProvider(ConnectorAuthProvider):
    def get_headers(self, connection_id, auth_config, secret_plaintext):
        return {}


class StaticBearerAuthProvider(ConnectorAuthProvider):
    """A fixed, admin-configured bearer token — legitimate for a sandbox or
    a partner that issues a long-lived static token out of band. The token
    is the secret; never logged, never returned by any API response."""

    def get_headers(self, connection_id, auth_config, secret_plaintext):
        if not secret_plaintext:
            raise AuthConfigError("static_bearer requires a configured secret (bearer token)")
        return {"Authorization": f"Bearer {secret_plaintext}"}


class ApiKeyHeaderAuthProvider(ConnectorAuthProvider):
    def get_headers(self, connection_id, auth_config, secret_plaintext):
        header_name = auth_config.get("header_name")
        if not header_name:
            raise AuthConfigError("api_key_header requires auth_config.header_name")
        if not secret_plaintext:
            raise AuthConfigError("api_key_header requires a configured secret (the API key value)")
        return {header_name: secret_plaintext}


class BasicAuthLegacyAuthProvider(ConnectorAuthProvider):
    """Basic Auth is only offered for explicitly configured legacy endpoints
    (P7) — the admin UI must label this as a legacy option, not a default
    recommendation. `secret_plaintext` is "username:password"."""

    def get_headers(self, connection_id, auth_config, secret_plaintext):
        import base64

        if not secret_plaintext or ":" not in secret_plaintext:
            raise AuthConfigError("basic_auth_legacy requires a secret formatted as \"username:password\"")
        encoded = base64.b64encode(secret_plaintext.encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}


def _fetch_token(
    connection_id: int,
    token_url: str,
    body: dict[str, str],
    *,
    allow_private_network: bool,
) -> _CachedToken:
    cached = _token_cache.get(connection_id)
    now = time.time()
    if cached and cached.expires_at - CLOCK_SKEW_TOLERANCE_SECONDS > now:
        return cached

    response = safe_request(
        "POST",
        token_url,
        allow_private_network=allow_private_network,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        data="&".join(f"{k}={v}" for k, v in body.items()),
    )
    if response.status_code != 200:
        raise AuthConfigError(f"Token endpoint {token_url} returned HTTP {response.status_code}: {response.text[:500]}")

    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise AuthConfigError("Token response did not include access_token")
    expires_in = int(payload.get("expires_in", 300))
    token = _CachedToken(access_token=access_token, expires_at=now + expires_in)
    _token_cache[connection_id] = token
    return token


class OAuth2ClientCredentialsAuthProvider(ConnectorAuthProvider):
    def get_headers(self, connection_id, auth_config, secret_plaintext):
        token_url = auth_config.get("token_url")
        client_id = auth_config.get("client_id")
        scope = auth_config.get("scope", "")
        if not token_url or not client_id:
            raise AuthConfigError("oauth2_client_credentials requires auth_config.token_url and client_id")
        if not secret_plaintext:
            raise AuthConfigError("oauth2_client_credentials requires a configured secret (client_secret)")

        body = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret_plaintext,
        }
        if scope:
            body["scope"] = scope

        token = _fetch_token(
            connection_id,
            token_url,
            body,
            allow_private_network=bool(auth_config.get("_allow_private_network")),
        )
        return {"Authorization": f"Bearer {token.access_token}"}


class SmartBackendServicesAuthProvider(ConnectorAuthProvider):
    """SMART App Launch Backend Services (P6/P7/P8/P24). Bragi is the
    client: it signs a JWT client assertion with its OWN private key
    (`secret_plaintext`, an RSA private key PEM the partner has been given
    the matching public JWKS for out of band or via /interop/jwks.json —
    see jwks.py) and exchanges it at the partner's token_endpoint for an
    access token. This is standard asymmetric SMART Backend Services —
    Bragi never needs the partner's secret, only the partner needs Bragi's
    public key.
    """

    def get_headers(self, connection_id, auth_config, secret_plaintext):
        token_url = auth_config.get("token_url")
        issuer = auth_config.get("issuer")  # Bragi's client_id as registered with the partner
        audience = auth_config.get("audience", token_url)
        scope = auth_config.get("scope", "system/*.read")
        key_id = auth_config.get("key_id", "bragi-interop-1")
        if not token_url or not issuer:
            raise AuthConfigError("smart_backend_services requires auth_config.token_url and issuer")
        if not secret_plaintext:
            raise AuthConfigError("smart_backend_services requires a configured secret (RSA private key PEM)")

        now = int(time.time())
        claims = {
            "iss": issuer,
            "sub": issuer,
            "aud": audience,
            "jti": f"{connection_id}-{now}-{time.time_ns()}",
            "exp": now + 300,
            "iat": now,
        }
        assertion = jose_jwt.encode(claims, secret_plaintext, algorithm="RS384", headers={"kid": key_id})

        body = {
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
            "scope": scope,
        }
        token = _fetch_token(
            connection_id,
            token_url,
            body,
            allow_private_network=bool(auth_config.get("_allow_private_network")),
        )
        return {"Authorization": f"Bearer {token.access_token}"}


_PROVIDERS: dict[str, ConnectorAuthProvider] = {
    "none": NoneAuthProvider(),
    "static_bearer": StaticBearerAuthProvider(),
    "api_key_header": ApiKeyHeaderAuthProvider(),
    "basic_auth_legacy": BasicAuthLegacyAuthProvider(),
    "oauth2_client_credentials": OAuth2ClientCredentialsAuthProvider(),
    "smart_backend_services": SmartBackendServicesAuthProvider(),
}


def get_auth_provider(auth_type: str) -> ConnectorAuthProvider:
    provider = _PROVIDERS.get(auth_type)
    if provider is None:
        raise AuthConfigError(
            f"Unknown or not-yet-implemented auth_type {auth_type!r}. Supported: {', '.join(SUPPORTED_AUTH_TYPES)}"
        )
    return provider


def clear_token_cache(connection_id: int) -> None:
    """Called on pause/disconnect/secret-rotation so a revoked credential's
    cached token stops being reused (P70 — pause must actually stop token use)."""
    _token_cache.pop(connection_id, None)
