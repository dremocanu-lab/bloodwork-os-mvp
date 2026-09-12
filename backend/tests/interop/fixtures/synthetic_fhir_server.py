"""Real, in-process synthetic FHIR R4 servers for the interoperability test
suite (BRAGI_INTEROP_PLAN.md P50-P52/P61). These are genuine HTTP servers
(stdlib `http.server`, bound to 127.0.0.1 on a random free port, run in a
background thread) — the connector talks real HTTP to them exactly like it
would to a real hospital's FHIR endpoint, the same "verify for real, don't
just mock the client" philosophy the rest of this test suite already uses
elsewhere (real Playwright, real Reducto calls, etc.).

Three deliberately different servers, matching the plan's acceptance
scenarios:

- SERVER_A ("full-featured"): SMART security extension advertised,
  DiagnosticReport/DocumentReference/Encounter present, `_lastUpdated`
  supported, Observation results paginated across 2 pages to exercise
  `link.relation=next` following.
- SERVER_B ("minimal"): Observation + Encounter + MedicationRequest only —
  no SMART, no DiagnosticReport, no DocumentReference, no `_lastUpdated`,
  single-page results. Proves the SAME connector code adapts by capability
  rather than branching on server identity (P51).
- SERVER_C ("local profile"): a real LOINC-coded observation PLUS one
  observation using a made-up local coding system/local display text that
  `resolve_analyte()` cannot resolve on its own — requires a declarative
  terminology override, proving P15/P52 (mapping through configuration,
  not code).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# --- Fixed test identifiers -------------------------------------------------

PATIENT_IDENTIFIER_SYSTEM = "urn:oid:2.16.840.1.113883.3.9999.1"

SERVER_A_PATIENT = {
    "resourceType": "Patient",
    "id": "pt-a-1",
    "identifier": [{"system": PATIENT_IDENTIFIER_SYSTEM, "value": "MRN-A-1001"}],
    "name": [{"family": "Popescu", "given": ["Ana"]}],
}
SERVER_B_PATIENT = {
    "resourceType": "Patient",
    "id": "pt-b-1",
    "identifier": [{"system": PATIENT_IDENTIFIER_SYSTEM, "value": "MRN-B-2002"}],
    "name": [{"family": "Ionescu", "given": ["Mihai"]}],
}
SERVER_C_PATIENT = {
    "resourceType": "Patient",
    "id": "pt-c-1",
    "identifier": [{"system": PATIENT_IDENTIFIER_SYSTEM, "value": "MRN-C-3003"}],
    "name": [{"family": "Constantin", "given": ["Elena"]}],
}


def _observation(obs_id: str, *, system: str, code: str, display: str, value: float, unit: str, status: str = "final") -> dict:
    return {
        "resourceType": "Observation",
        "id": obs_id,
        "status": status,
        "code": {"coding": [{"system": system, "code": code, "display": display}], "text": display},
        "valueQuantity": {"value": value, "unit": unit},
        "effectiveDateTime": "2026-01-15T09:00:00+02:00",
    }


SERVER_A_OBSERVATIONS = [
    _observation("obs-a-1", system="http://loinc.org", code="718-7", display="Hemoglobin", value=13.8, unit="g/dL"),
    _observation("obs-a-2", system="http://loinc.org", code="2823-3", display="Potassium", value=4.2, unit="mmol/L"),
    _observation("obs-a-3", system="http://loinc.org", code="2951-2", display="Sodium", value=140, unit="mmol/L"),
]
SERVER_B_OBSERVATIONS = [
    _observation("obs-b-1", system="http://loinc.org", code="718-7", display="Hemoglobin", value=12.9, unit="g/dL"),
]
SERVER_C_OBSERVATIONS = [
    _observation("obs-c-1", system="http://loinc.org", code="718-7", display="Hemoglobin", value=14.1, unit="g/dL"),
    # A local, non-standard code resolve_analyte() genuinely cannot resolve
    # on its own (verified directly against the real resolver — "Hgb" and
    # similar clinical abbreviations are already real catalog aliases, so
    # this deliberately uses a display string with no resemblance to any
    # real analyte name/alias) — this is the one that needs a declarative
    # mapping override, not a code change.
    _observation(
        "obs-c-2",
        system="http://hospital.example.ro/local-lab-codes",
        code="HGB-LOCAL-X7",
        display="Local Marker Code QX9",
        value=14.3,
        unit="g/dL",
    ),
]


def _capability_statement(*, fhir_version: str, resources: list[dict], smart: bool) -> dict:
    rest_resource = {"security": {}}
    if smart:
        rest_resource["security"] = {
            "service": [{"coding": [{"code": "SMART-on-FHIR"}]}],
            "extension": [
                {
                    "url": "http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris",
                    "extension": [
                        {"url": "token", "valueUri": "https://example-token-endpoint.invalid/token"},
                    ],
                }
            ],
        }
    return {
        "resourceType": "CapabilityStatement",
        "fhirVersion": fhir_version,
        "software": {"name": "BragiSyntheticFhirServer", "version": "test"},
        "rest": [{"mode": "server", "security": rest_resource["security"], "resource": resources}],
    }


def _resource_entry(rtype: str, *, search_params: list[str], supports_last_updated: bool = False) -> dict:
    params = [{"name": p, "type": "string"} for p in search_params]
    if supports_last_updated and "_lastUpdated" not in search_params:
        params.append({"name": "_lastUpdated", "type": "date"})
    return {
        "type": rtype,
        "interaction": [{"code": "read"}, {"code": "search-type"}],
        "searchParam": params,
    }


SERVER_A_CAPABILITY = _capability_statement(
    fhir_version="4.0.1",
    smart=True,
    resources=[
        _resource_entry("Patient", search_params=["_id", "identifier"]),
        _resource_entry("Observation", search_params=["patient", "category", "code", "date"], supports_last_updated=True),
        _resource_entry("DiagnosticReport", search_params=["patient", "category", "date"]),
        _resource_entry("DocumentReference", search_params=["patient", "type", "date"]),
        _resource_entry("Encounter", search_params=["patient", "date"]),
    ],
)

SERVER_B_CAPABILITY = _capability_statement(
    fhir_version="4.0.1",
    smart=False,
    resources=[
        _resource_entry("Patient", search_params=["_id", "identifier"]),
        _resource_entry("Observation", search_params=["patient", "category", "code", "date"]),
        _resource_entry("Encounter", search_params=["patient", "date"]),
        _resource_entry("MedicationRequest", search_params=["patient"]),
    ],
)

SERVER_C_CAPABILITY = _capability_statement(
    fhir_version="4.0.1",
    smart=False,
    resources=[
        _resource_entry("Patient", search_params=["_id", "identifier"]),
        _resource_entry("Observation", search_params=["patient", "category", "code", "date"]),
    ],
)

_PROFILES = {
    "server_a": {"capability": SERVER_A_CAPABILITY, "patients": [SERVER_A_PATIENT], "observations": {"pt-a-1": SERVER_A_OBSERVATIONS}},
    "server_b": {"capability": SERVER_B_CAPABILITY, "patients": [SERVER_B_PATIENT], "observations": {"pt-b-1": SERVER_B_OBSERVATIONS}},
    "server_c": {"capability": SERVER_C_CAPABILITY, "patients": [SERVER_C_PATIENT], "observations": {"pt-c-1": SERVER_C_OBSERVATIONS}},
}


def _bundle(resources: list[dict], *, next_url: str | None = None) -> dict:
    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(resources),
        "entry": [{"resource": r} for r in resources],
        "link": [{"relation": "self", "url": "self"}],
    }
    if next_url:
        bundle["link"].append({"relation": "next", "url": next_url})
    return bundle


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 — silence per-request stderr logging in test runs
        pass

    def _profile(self) -> dict:
        return _PROFILES[self.server.profile]  # type: ignore[attr-defined]

    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 — required BaseHTTPRequestHandler method name
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        profile = self._profile()

        if parsed.path == "/metadata":
            self._send_json(profile["capability"])
            return

        if parsed.path == "/.well-known/smart-configuration":
            self.send_response(404)
            self.end_headers()
            return

        if parsed.path == "/Patient":
            self._send_json(_bundle(profile["patients"]))
            return

        if parsed.path == "/Observation":
            patient_id = (query.get("patient") or [None])[0]
            all_obs = profile["observations"].get(patient_id, [])

            # SERVER_A deliberately paginates 2-per-page to exercise
            # link.relation=next following in fhir_connector._fetch_bundle_pages.
            if self.server.profile == "server_a" and "page" not in query:  # type: ignore[attr-defined]
                page1 = all_obs[:2]
                next_url = f"http://{self.headers.get('Host')}/Observation?patient={patient_id}&page=2"
                self._send_json(_bundle(page1, next_url=next_url))
                return
            if self.server.profile == "server_a" and query.get("page") == ["2"]:  # type: ignore[attr-defined]
                self._send_json(_bundle(all_obs[2:]))
                return

            self._send_json(_bundle(all_obs))
            return

        self.send_response(404)
        self.end_headers()


class SyntheticFhirServer:
    """Usage: `with SyntheticFhirServer("server_a") as server: ...` —
    `server.base_url` is a real http://127.0.0.1:<port> URL."""

    def __init__(self, profile: str):
        if profile not in _PROFILES:
            raise ValueError(f"Unknown synthetic profile {profile!r}. Known: {sorted(_PROFILES)}")
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.profile = profile  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address
        return f"http://127.0.0.1:{port}"

    def __enter__(self) -> "SyntheticFhirServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
