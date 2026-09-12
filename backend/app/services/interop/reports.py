"""Sanitized, exportable reports: partner readiness (P21), profile export/
import (P3), and the diagnostic bundle (P74). Every function here is
built to make it structurally impossible to leak a secret: they read
from InteropConnection's own columns (which never contain secret
material — see InteropConnection.secret_ref) and never touch
InteropSecret.ciphertext.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app import models

SANITIZED_FIELDS = (
    "public_id",
    "name",
    "connector_type",
    "status",
    "base_url",
    "fhir_version",
    "auth_type",
    "version",
    "created_at",
    "updated_at",
)

# Shared with import_connection_profile's own check below. auth_config_json
# never carries secret material BY CONSTRUCTION (secrets only ever live in
# InteropSecret, referenced by secret_ref — see auth_providers.py), but this
# is a second, independent layer of defense: if an admin ever mis-set a
# secret-shaped value directly into non-secret config (a configuration
# mistake, not a code path this app offers), export still refuses to carry
# it out rather than trusting that mistake never happens.
SECRET_SHAPED_KEYS = frozenset(
    {"client_secret", "password", "private_key", "access_token", "refresh_token", "secret_ref", "api_key", "secret_plaintext"}
)


def _strip_secret_shaped_keys(data: dict[str, Any], *, context: str) -> dict[str, Any]:
    cleaned = {k: v for k, v in data.items() if k not in SECRET_SHAPED_KEYS}
    dropped = SECRET_SHAPED_KEYS & set(data.keys())
    if dropped:
        # Never raise/abort the export over this — silently dropping is
        # correct here (the caller already lost nothing they were entitled
        # to see back), but it's worth knowing about if it ever happens, so
        # a real admin misconfiguration doesn't go unnoticed. No secret
        # VALUE is ever included in this message, only the field name.
        print(f"INTEROP EXPORT WARNING: stripped secret-shaped field(s) {sorted(dropped)} from {context} before export")
    return cleaned


def export_connection_profile(connection: models.InteropConnection) -> dict[str, Any]:
    """P3 — sanitized export. No secret_ref, no ciphertext ever (both are
    structurally outside auth_config_json — see InteropConnection's own
    columns); auth_config_json is additionally passed through
    _strip_secret_shaped_keys as defense-in-depth against a misconfigured
    value ending up there by admin mistake rather than trusting that never
    happens."""
    auth_config = _strip_secret_shaped_keys(json.loads(connection.auth_config_json or "{}"), context="auth_config")
    return {
        "profile_version": 1,
        "name": connection.name,
        "connector": connection.connector_type,
        "base_url": connection.base_url,
        "fhir_version": connection.fhir_version,
        "auth": {"type": connection.auth_type, **auth_config},
        "patient_identity": json.loads(connection.patient_identity_json or "{}"),
        "capabilities": json.loads(connection.capabilities_json or "{}"),
        "terminology_overrides": json.loads(connection.terminology_overrides_json or "{}"),
        "sync": json.loads(connection.sync_config_json or "{}"),
    }


def import_connection_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validates a profile dict for re-use as a new draft connection (P3).
    Refuses (raises ValueError) if it finds anything that looks like a
    secret — an imported profile is expected to be the sanitized export
    above, never a live profile with credentials still attached."""
    auth = profile.get("auth", {})
    found = SECRET_SHAPED_KEYS & set(auth.keys())
    if found:
        raise ValueError(
            f"Refusing to import: profile contains secret-shaped field(s) {sorted(found)}. "
            "Only a sanitized export (from export_connection_profile) should ever be imported — "
            "secrets must be re-entered by the admin after import, never carried in the file."
        )
    return {
        "name": profile.get("name", "Imported connection"),
        "connector_type": profile.get("connector", "fhir"),
        "base_url": profile.get("base_url", ""),
        "fhir_version": profile.get("fhir_version"),
        "auth_type": auth.get("type", "none"),
        "auth_config_json": json.dumps({k: v for k, v in auth.items() if k != "type"}),
        "patient_identity_json": json.dumps(profile.get("patient_identity", {})),
        "terminology_overrides_json": json.dumps(profile.get("terminology_overrides", {})),
        "sync_config_json": json.dumps(profile.get("sync", {})),
    }


def build_partner_readiness_report(connection: models.InteropConnection, compatibility_report: dict[str, Any]) -> dict[str, Any]:
    """P21 — human/machine report suitable for sending to a hospital IT
    team. NO PHI, NO SECRETS — every field here comes from configuration
    and capability metadata only."""
    resources = compatibility_report.get("resources", {})

    def _status(name: str) -> str:
        return resources.get(name, {}).get("status", "UNSUPPORTED")

    configuration_still_required = []
    if connection.auth_type == "none":
        configuration_still_required.append("authentication method")
    if not json.loads(connection.patient_identity_json or "{}").get("primary_system"):
        configuration_still_required.append("patient identifier system")
    if not connection.secret_ref and connection.auth_type != "none":
        configuration_still_required.append("credential/secret configuration")

    return {
        "connection_name": connection.name,
        "fhir_version": compatibility_report.get("fhir_version"),
        "authentication": connection.auth_type,
        "patient_supported": _status("Patient"),
        "observation_supported": _status("Observation"),
        "diagnostic_report_supported": _status("DiagnosticReport"),
        "document_reference_supported": _status("DocumentReference"),
        "bulk_data_supported": compatibility_report.get("bulk_data_supported", False),
        "incremental_sync_supported": resources.get("Observation", {}).get("supports_last_updated", False),
        "compatibility_score_percent": compatibility_report.get("compatibility_score_percent"),
        "configuration_still_required": configuration_still_required,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def render_partner_readiness_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# BRAGI PARTNER CONNECTIVITY REPORT",
        "",
        f"**Connection:** {report['connection_name']}",
        f"**FHIR version:** {report.get('fhir_version') or 'unknown'}",
        f"**Authentication:** {report['authentication']}",
        f"**Compatibility score:** {report.get('compatibility_score_percent')}%",
        "",
        "| Capability | Status |",
        "|---|---|",
        f"| Patient | {report['patient_supported']} |",
        f"| Observation | {report['observation_supported']} |",
        f"| DiagnosticReport | {report['diagnostic_report_supported']} |",
        f"| DocumentReference | {report['document_reference_supported']} |",
        f"| Bulk Data | {'supported' if report['bulk_data_supported'] else 'unsupported'} |",
        f"| Incremental sync | {'supported' if report['incremental_sync_supported'] else 'unsupported'} |",
        "",
    ]
    if report["configuration_still_required"]:
        lines.append("**Configuration still required:**")
        lines.extend(f"- {item}" for item in report["configuration_still_required"])
    return "\n".join(lines)


def build_diagnostic_bundle(
    connection: models.InteropConnection, recent_runs: list[models.InteropSyncRun]
) -> dict[str, Any]:
    """P74 — sanitized troubleshooting bundle. NO PHI, NO AUTH HEADERS, NO
    TOKENS: only configuration (minus secret_ref), capability metadata, and
    run-level error/status information."""
    return {
        "connection": {k: getattr(connection, k) for k in SANITIZED_FIELDS},
        "capabilities": json.loads(connection.capabilities_json or "{}"),
        "capabilities_discovered_at": connection.capabilities_discovered_at,
        "recent_runs": [
            {
                "run_type": run.run_type,
                "status": run.status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "error_message": run.error_message,
                "summary": json.loads(run.summary_json) if run.summary_json else None,
            }
            for run in recent_runs
        ],
    }
