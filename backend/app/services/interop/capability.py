"""FHIR capability discovery + the FhirCompatibilityReport (P5/P11/P12/P13/P49).

`discover_capabilities()` fetches and parses `GET {base}/metadata` into a
plain, JSON-serializable dict — this is what gets cached in
InteropConnection.capabilities_json and shown to the admin in the wizard
(P5, spec STEP 3/4). `build_compatibility_report()` turns that same parse
into the per-resource SUPPORTED/PARTIAL/UNSUPPORTED report (P11) plus the
deterministic compatibility score (P49).

Only resources Bragi's Phase 1 pipeline actually knows how to turn into
canonical data (Patient, Observation) are ever marked with real Bragi
import support — everything else is reported honestly as "advertised by
the server, not yet consumed by Bragi" rather than claimed.
"""

from __future__ import annotations

from typing import Any

from app.services.interop.ssrf import safe_request

# Resources this compatibility report evaluates, matching P11's list.
TRACKED_RESOURCES = [
    "Patient",
    "Observation",
    "DiagnosticReport",
    "DocumentReference",
    "Encounter",
    "MedicationStatement",
    "MedicationRequest",
    "Provenance",
    "Composition",
    "ImagingStudy",
]

# Resources Bragi's Phase 1 connector actually maps into canonical data.
# Keep this honest and narrow — expand only as real mapping code ships.
BRAGI_IMPORT_SUPPORTED_RESOURCES = {"Patient", "Observation"}

REQUIRED_SEARCH_PARAMS = {
    "Patient": ["_id", "identifier"],
    "Observation": ["patient", "category", "code", "date"],
    "DiagnosticReport": ["patient", "category", "date"],
    "DocumentReference": ["patient", "type", "date"],
    "Encounter": ["patient", "date"],
    "MedicationStatement": ["patient"],
    "MedicationRequest": ["patient"],
}


class CapabilityDiscoveryError(RuntimeError):
    pass


def discover_capabilities(base_url: str, *, allow_private_network: bool, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """GET {base}/metadata and parse it into a compact, cacheable dict.
    Raises CapabilityDiscoveryError with a human-readable stage on failure
    (P57 — no bare protocol errors)."""
    url = base_url.rstrip("/") + "/metadata"
    try:
        response = safe_request(
            "GET",
            url,
            allow_private_network=allow_private_network,
            headers={**(headers or {}), "Accept": "application/fhir+json"},
        )
    except Exception as exc:  # SSRFBlocked, connection errors, timeouts
        raise CapabilityDiscoveryError(f"Could not reach {url}: {exc}") from exc

    if response.status_code != 200:
        raise CapabilityDiscoveryError(
            f"The server rejected the capability request (HTTP {response.status_code}) at {url}"
        )

    try:
        statement = response.json()
    except ValueError as exc:
        raise CapabilityDiscoveryError("The server response was not valid JSON — expected a FHIR CapabilityStatement") from exc

    if statement.get("resourceType") != "CapabilityStatement":
        raise CapabilityDiscoveryError(
            "The server response was valid JSON but not a FHIR CapabilityStatement "
            f"(resourceType={statement.get('resourceType')!r})"
        )

    return _parse_capability_statement(statement)


def _parse_capability_statement(statement: dict[str, Any]) -> dict[str, Any]:
    fhir_version = statement.get("fhirVersion")
    software = statement.get("software") or {}
    implementation = statement.get("implementation") or {}

    rest_entries = statement.get("rest") or []
    rest = rest_entries[0] if rest_entries else {}
    security = rest.get("security") or {}

    resources: dict[str, Any] = {}
    for resource in rest.get("resource", []):
        rtype = resource.get("type")
        if not rtype:
            continue
        interactions = {i.get("code") for i in resource.get("interaction", []) if i.get("code")}
        search_params = {p.get("name") for p in resource.get("searchParam", []) if p.get("name")}
        profiles = [p for p in [resource.get("profile")] if p]
        profiles.extend(resource.get("supportedProfile", []) or [])
        resources[rtype] = {
            "interactions": sorted(interactions),
            "searchable": "search-type" in interactions,
            "search_params": sorted(search_params),
            "profiles": profiles,
            "supports_last_updated": "_lastUpdated" in search_params,
        }

    server_operations = [op.get("name") for op in rest.get("operation", []) if op.get("name")]
    resource_operations = [
        op.get("name")
        for r in rest.get("resource", [])
        for op in r.get("operation", [])
        if op.get("name")
    ]
    bulk_data_supported = "export" in server_operations or "export" in resource_operations

    smart_supported = False
    smart_uris: dict[str, str] = {}
    for ext in security.get("extension", []):
        if ext.get("url") == "http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris" or ext.get(
            "url"
        ) == "http://fhir.org/guides/argonaut/StructureDefinition/oauth-uris":
            smart_supported = True
            for sub in ext.get("extension", []):
                if sub.get("url") and sub.get("valueUri"):
                    smart_uris[sub["url"]] = sub["valueUri"]
    security_services = [
        coding.get("code")
        for svc in security.get("service", [])
        for coding in svc.get("coding", [])
    ]
    if any("smart" in (s or "").lower() for s in security_services):
        smart_supported = True

    return {
        "fhir_version": fhir_version,
        "software": {"name": software.get("name"), "version": software.get("version")},
        "implementation": {"description": implementation.get("description")},
        "resources": resources,
        "bulk_data_supported": bulk_data_supported,
        "smart_supported": smart_supported,
        "smart_uris": smart_uris,
        "server_operations": server_operations,
    }


def _resource_status(name: str, discovered: dict[str, Any]) -> str:
    resource = discovered.get("resources", {}).get(name)
    if resource is None:
        return "UNSUPPORTED"
    required = REQUIRED_SEARCH_PARAMS.get(name, [])
    has_all_required = all(p in resource.get("search_params", []) for p in required)
    if resource.get("searchable") and (not required or has_all_required):
        return "SUPPORTED"
    if resource.get("interactions"):
        return "PARTIALLY SUPPORTED"
    return "UNSUPPORTED"


def build_compatibility_report(discovered: dict[str, Any]) -> dict[str, Any]:
    """The FhirCompatibilityReport (P11) — one row per tracked resource plus
    a deterministic compatibility score (P49). Never presents an optional,
    unsupported capability (e.g. Bulk Data) as an "error" — see `notes`."""
    resource_reports = {}
    for name in TRACKED_RESOURCES:
        status = _resource_status(name, discovered)
        resource = discovered.get("resources", {}).get(name, {})
        resource_reports[name] = {
            "status": status,
            "available": name in discovered.get("resources", {}),
            "searchable": resource.get("searchable", False),
            "profiles": resource.get("profiles", []),
            "required_search_params": REQUIRED_SEARCH_PARAMS.get(name, []),
            "missing_search_params": [
                p for p in REQUIRED_SEARCH_PARAMS.get(name, []) if p not in resource.get("search_params", [])
            ],
            "bragi_import_support": name in BRAGI_IMPORT_SUPPORTED_RESOURCES,
        }

    checks = {
        "Core patient retrieval": resource_reports["Patient"]["status"] == "SUPPORTED",
        "Laboratory observations": resource_reports["Observation"]["status"] == "SUPPORTED",
        "Documents": resource_reports["DocumentReference"]["status"] in ("SUPPORTED", "PARTIALLY SUPPORTED"),
        "Medication": resource_reports["MedicationRequest"]["status"] in ("SUPPORTED", "PARTIALLY SUPPORTED")
        or resource_reports["MedicationStatement"]["status"] in ("SUPPORTED", "PARTIALLY SUPPORTED"),
        "Incremental synchronization": discovered.get("resources", {}).get("Observation", {}).get("supports_last_updated", False),
        "SMART authentication": discovered.get("smart_supported", False),
        "Bulk Data": discovered.get("bulk_data_supported", False),
    }
    # Score = fraction of checks that pass, weighted equally. Core patient
    # retrieval and lab observations are the two Bragi actually depends on
    # in Phase 1; everything else is informative, never blocking.
    passed = sum(1 for v in checks.values() if v)
    score_percent = round(100 * passed / len(checks))

    # Optional/informative checks (Bulk Data) are reported as UNSUPPORTED
    # rather than FAIL when absent — a missing optional capability is never
    # presented as an error (P49).
    optional_checks = {"Bulk Data"}
    check_statuses = {
        name: "PASS" if v else ("UNSUPPORTED" if name in optional_checks else "FAIL")
        for name, v in checks.items()
    }

    return {
        "fhir_version": discovered.get("fhir_version"),
        "resources": resource_reports,
        "checks": check_statuses,
        "compatibility_score_percent": score_percent,
        "smart_supported": discovered.get("smart_supported", False),
        "bulk_data_supported": discovered.get("bulk_data_supported", False),
    }
