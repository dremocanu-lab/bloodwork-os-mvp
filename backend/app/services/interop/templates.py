"""ConnectorTemplate library (P4) — known interoperability patterns,
separate from a live InteropConnection. Never claims compatibility with a
named commercial vendor unless it's actually been tested against that
vendor's real system — every entry below is "Generic", not a vendor name.
"""

from __future__ import annotations

CONNECTOR_TEMPLATES = [
    {
        "id": "generic-fhir-r4",
        "name": "Generic FHIR R4",
        "connector_type": "fhir",
        "description": "A standards-compliant FHIR R4 server with public /metadata. Works with any conformant server via capability discovery — no vendor-specific code.",
        "default_auth_type": "none",
    },
    {
        "id": "generic-smart-backend-services",
        "name": "Generic SMART Backend Services",
        "connector_type": "fhir",
        "description": "FHIR R4 + SMART Backend Services (asymmetric client-credentials) for unattended server-to-server sync.",
        "default_auth_type": "smart_backend_services",
    },
    {
        "id": "one-click-sandbox",
        "name": "Synthetic FHIR Sandbox (development only)",
        "connector_type": "fhir",
        "description": "A local/mock synthetic FHIR server for development — sets allow_private_network so it can target localhost. Never usable in production (ENVIRONMENT=production refuses this template).",
        "default_auth_type": "none",
        "development_only": True,
    },
]

# Deliberately NOT implemented yet — shown to an admin as "Awaiting
# registration" per BRAGI_INTEROP_PLAN.md P1, never as a working option.
UNIMPLEMENTED_CONNECTION_TYPES = ["cnas"]
