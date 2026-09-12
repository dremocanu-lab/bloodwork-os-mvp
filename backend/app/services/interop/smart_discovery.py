"""SMART on FHIR discovery (P6). Determines configuration OPTIONS only —
never infers or activates credentials. An admin still explicitly
configures/authorizes auth after seeing what discovery found (P8)."""

from __future__ import annotations

from typing import Any

from app.services.interop.ssrf import safe_request

SMART_CONFIGURATION_PATH = "/.well-known/smart-configuration"


def discover_smart_configuration(base_url: str, *, allow_private_network: bool) -> dict[str, Any] | None:
    """Fetch {base}/.well-known/smart-configuration per the SMART App Launch
    spec. Returns None (not an error) if the endpoint doesn't exist — many
    real FHIR servers don't advertise SMART at all, which is a normal,
    reportable outcome, not a failure."""
    url = base_url.rstrip("/") + SMART_CONFIGURATION_PATH
    try:
        response = safe_request(
            "GET",
            url,
            allow_private_network=allow_private_network,
            headers={"Accept": "application/json"},
        )
    except Exception:
        return None

    if response.status_code != 200:
        return None

    try:
        config = response.json()
    except ValueError:
        return None

    return {
        "authorization_endpoint": config.get("authorization_endpoint"),
        "token_endpoint": config.get("token_endpoint"),
        "jwks_uri": config.get("jwks_uri"),
        "capabilities": config.get("capabilities", []),
        "scopes_supported": config.get("scopes_supported", []),
        "token_endpoint_auth_methods_supported": config.get("token_endpoint_auth_methods_supported", []),
    }


def recommend_auth_type(smart_config: dict[str, Any] | None, capability_report: dict[str, Any] | None) -> str | None:
    """P8 — recommend, never silently activate. Returns an auth_type string
    or None when nothing is unambiguous enough to recommend."""
    smart_advertised = bool(smart_config and smart_config.get("token_endpoint")) or bool(
        capability_report and capability_report.get("smart_supported")
    )
    if not smart_advertised:
        return None

    backend_capable = bool(
        smart_config
        and (
            "client-confidential-asymmetric" in (smart_config.get("capabilities") or [])
            or "backend-services" in " ".join(smart_config.get("capabilities") or []).lower()
        )
    )
    if backend_capable or (smart_config is None and capability_report and capability_report.get("smart_supported")):
        return "smart_backend_services"
    return None
