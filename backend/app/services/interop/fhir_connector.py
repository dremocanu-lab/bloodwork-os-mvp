"""The FHIR R4 inbound connector: discover -> test -> preview (shadow sync,
commits nothing) -> sync (idempotent commit). See BRAGI_INTEROP_PLAN.md
for the full phased plan this implements (P1-P22 core-FHIR sections).

Design constraint from the product decision that authorized this feature:
"do not rewrite working Bragi systems." This connector never touches the
upload pipeline, document_pipeline.py, or any existing route — it reuses
`app.services.lab_resolver.resolve_analyte` (the same canonical resolver
every upload already goes through) and writes into the SAME LabResult/
Document/SourceEvidence tables an upload writes into, additively tagged
with `source_connection_id`/`external_observation_id` so existing queries
(Analize, Timeline, Ask Bragi) see synced data exactly like uploaded data,
for free, without themselves changing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app import models
from app.services.interop import capability as capability_module
from app.services.interop import drift as drift_module
from app.services.interop import identity as identity_module
from app.services.interop import resilience
from app.services.interop import smart_discovery
from app.services.interop.auth_providers import AuthConfigError, get_auth_provider
from app.services.interop.crypto import decrypt_secret
from app.services.interop.ssrf import SSRFBlocked, safe_request
from app.services.lab_resolver import resolve_analyte

PREVIEW_MAX_PATIENTS = 50
MAX_OBSERVATIONS_PER_PATIENT = 500
MAX_PAGES = 20

# Phase 3 §3.4/§3.8 — independent bounds on top of MAX_PAGES, so a
# malicious/misbehaving server can't exhaust memory, time, or bandwidth
# even within the page-count budget (e.g. very large pages, or distinct-
# looking but non-terminating next links).
MAX_SYNC_RESOURCES = 20_000
MAX_SYNC_BYTES = 200 * 1024 * 1024  # 200MB
MAX_SYNC_DURATION_SECONDS = 300  # 5 minutes, bounded total pagination time

# Observation statuses safe to import as a real clinical value. Anything
# else is counted and skipped, never silently dropped from the summary —
# see the "status-filtered lookup silently hid a conflict" class of bug
# this codebase has already fixed once (git history) for a different table.
IMPORTABLE_OBSERVATION_STATUSES = {"final", "amended", "corrected", "preliminary"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ConnectorError(RuntimeError):
    """Human-readable connector failure — always includes which stage
    failed (P57), never a bare protocol exception."""


@dataclass
class MappedObservation:
    external_id: str
    patient_external_identifier: tuple[str, str] | None  # (system, value)
    raw_test_name: str
    canonical_name: str | None
    display_name: str | None
    category: str | None
    value: str | None
    unit: str | None
    reference_range: str | None
    flag: str | None
    observation_datetime: str | None
    normalization_method: str
    mapping_source: str  # "terminology_override" | "resolver" | "unresolved"
    skipped_reason: str | None = None


@dataclass
class SyncSummary:
    patients_discovered: int = 0
    observations_seen: int = 0
    documents: int = 0
    encounters: int = 0
    medications: int = 0
    mapped_automatically: int = 0
    requires_mapping_review: int = 0
    unmapped_terminology: int = 0
    identity_conflicts: int = 0
    duplicates_detected: int = 0
    would_create: int = 0
    would_update: int = 0
    created: int = 0
    updated: int = 0
    skipped_status: int = 0
    quarantined_identity: int = 0

    def to_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


def _auth_headers(connection: models.InteropConnection) -> dict[str, str]:
    auth_config = json.loads(connection.auth_config_json or "{}")
    auth_config["_allow_private_network"] = connection.allow_private_network
    secret_plaintext = None
    if connection.secret_ref:
        secret_row = None
        # Lazily imported to avoid a hard dependency loop; secret lookup is a
        # tiny read the caller's session already has open.
        from app.db import SessionLocal

        own_session = SessionLocal()
        try:
            secret_row = own_session.query(models.InteropSecret).filter_by(ref=connection.secret_ref).first()
        finally:
            own_session.close()
        if secret_row:
            secret_plaintext = decrypt_secret(secret_row.ciphertext)
    provider = get_auth_provider(connection.auth_type)
    try:
        return provider.get_headers(connection.id, auth_config, secret_plaintext)
    except AuthConfigError as exc:
        raise ConnectorError(f"Authentication configuration error: {exc}") from exc


def run_discovery(connection: models.InteropConnection) -> dict[str, Any]:
    """P5/P6 — capability + SMART discovery. Raises ConnectorError on
    failure; returns the combined, cacheable discovery dict on success."""
    try:
        headers = _auth_headers(connection)
    except ConnectorError:
        # Discovery of PUBLIC capability metadata should work even before
        # auth is fully configured (most FHIR servers publish /metadata
        # unauthenticated) — fall back to no auth headers rather than
        # failing discovery outright.
        headers = {}

    try:
        discovered = capability_module.discover_capabilities(
            connection.base_url, allow_private_network=connection.allow_private_network, headers=headers
        )
    except capability_module.CapabilityDiscoveryError as exc:
        raise ConnectorError(f"Capability discovery failed: {exc}") from exc
    except SSRFBlocked as exc:
        raise ConnectorError(f"Endpoint rejected by connectivity policy: {exc}") from exc

    smart_config = smart_discovery.discover_smart_configuration(
        connection.base_url, allow_private_network=connection.allow_private_network
    )
    recommended_auth = smart_discovery.recommend_auth_type(smart_config, discovered)

    result = {
        "discovered_at": _now_iso(),
        "capability": discovered,
        "compatibility_report": capability_module.build_compatibility_report(discovered),
        "smart_configuration": smart_config,
        "recommended_auth_type": recommended_auth,
    }
    return result


def compute_discovery_drift(connection: models.InteropConnection, discovery_result: dict[str, Any]) -> dict[str, Any]:
    """Phase 3 §3.2 — compares this discovery against the PREVIOUSLY
    cached one (connection.capabilities_json/capability_fingerprint) and
    reports what changed. The caller decides what to do with a breaking
    result (mark DEGRADED rather than silently continuing) — this
    function only computes the diff."""
    new_normalized = drift_module.normalize_discovery(discovery_result["capability"])
    new_fingerprint = drift_module.compute_fingerprint(discovery_result["capability"])

    previous_normalized = None
    if connection.capabilities_json:
        try:
            previous_capability = json.loads(connection.capabilities_json).get("capability")
            if previous_capability:
                previous_normalized = drift_module.normalize_discovery(previous_capability)
        except (json.JSONDecodeError, AttributeError, TypeError):
            previous_normalized = None

    report = drift_module.diff_fingerprints(previous_normalized, new_normalized)
    return {"fingerprint": new_fingerprint, **report.to_dict()}


@dataclass
class TestStageResult:
    stage: str
    passed: bool
    message: str


def run_connection_test(connection: models.InteropConnection) -> list[TestStageResult]:
    """P20 — non-mutating diagnostic, exact failure stage reported (P57)."""
    stages: list[TestStageResult] = []

    try:
        headers = _auth_headers(connection)
        stages.append(TestStageResult("authentication", True, "Authentication configuration resolved successfully."))
    except ConnectorError as exc:
        stages.append(TestStageResult("authentication", False, str(exc)))
        return stages

    try:
        discovered = capability_module.discover_capabilities(
            connection.base_url, allow_private_network=connection.allow_private_network, headers=headers
        )
        stages.append(
            TestStageResult(
                "capability_statement",
                True,
                f"FHIR {discovered.get('fhir_version', 'unknown version')} CapabilityStatement retrieved.",
            )
        )
    except SSRFBlocked as exc:
        stages.append(TestStageResult("capability_statement", False, f"Endpoint rejected by connectivity policy: {exc}"))
        return stages
    except capability_module.CapabilityDiscoveryError as exc:
        stages.append(TestStageResult("capability_statement", False, str(exc)))
        return stages

    for resource_name in ("Patient", "Observation"):
        resource = discovered.get("resources", {}).get(resource_name)
        if not resource:
            stages.append(TestStageResult(f"resource_{resource_name.lower()}", False, f"Server does not advertise {resource_name}."))
            continue
        required = capability_module.REQUIRED_SEARCH_PARAMS.get(resource_name, [])
        missing = [p for p in required if p not in resource.get("search_params", [])]
        if missing:
            stages.append(
                TestStageResult(
                    f"resource_{resource_name.lower()}",
                    False,
                    f"{resource_name} search failed: server does not support required search parameter(s) {', '.join(missing)}.",
                )
            )
        else:
            stages.append(TestStageResult(f"resource_{resource_name.lower()}", True, f"{resource_name} search parameters supported."))

    # One bounded, real, read-only query — Patient search with _count=1 —
    # if the server allows patient search at all.
    if discovered.get("resources", {}).get("Patient", {}).get("searchable"):
        try:
            response = safe_request(
                "GET",
                connection.base_url.rstrip("/") + "/Patient?_count=1",
                allow_private_network=connection.allow_private_network,
                headers={**headers, "Accept": "application/fhir+json"},
            )
            if response.status_code == 200:
                stages.append(TestStageResult("bounded_query", True, "A bounded Patient search (_count=1) succeeded."))
            else:
                stages.append(
                    TestStageResult("bounded_query", False, f"Bounded Patient search returned HTTP {response.status_code}.")
                )
        except SSRFBlocked as exc:
            stages.append(TestStageResult("bounded_query", False, f"Endpoint rejected by connectivity policy: {exc}"))
        except Exception as exc:  # noqa: BLE001 — surfaced as a diagnostic, not raised
            stages.append(TestStageResult("bounded_query", False, f"Bounded Patient search failed: {exc}"))

    return stages


def _fetch_bundle_pages(url: str, connection: models.InteropConnection, headers: dict[str, str]) -> list[dict[str, Any]]:
    """P42/Phase-3 §3.4 — every page (including every `next` link) goes
    through the same SSRF-guarded, retrying request path. Bounded on four
    independent axes (pages, resources, bytes, wall-clock duration) and
    detects a repeated `next` link (a malicious or buggy server serving
    the same page forever) rather than trusting MAX_PAGES alone to save
    us — a server could otherwise return distinct-looking but
    non-progressing URLs indefinitely within that page budget."""
    resources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    total_bytes = 0
    start_time = time.monotonic()
    next_url: str | None = url

    for _ in range(MAX_PAGES):
        if not next_url:
            break
        if next_url in seen_urls:
            raise ConnectorError(f"Pagination loop detected — {next_url} was already fetched this sync")
        seen_urls.add(next_url)

        if time.monotonic() - start_time > MAX_SYNC_DURATION_SECONDS:
            raise ConnectorError(f"Sync exceeded the maximum bounded duration ({MAX_SYNC_DURATION_SECONDS}s) while paginating")

        try:
            response = resilience.request_with_retry(
                "GET", next_url, allow_private_network=connection.allow_private_network, headers={**headers, "Accept": "application/fhir+json"}
            )
        except resilience.ConnectorAuthError as exc:
            raise ConnectorError(f"Authentication was rejected by the partner server: {exc}") from exc
        except resilience.ConnectorTransientError as exc:
            raise ConnectorError(f"Search request to {next_url} failed after retries: {exc}") from exc

        if response.status_code != 200:
            raise ConnectorError(f"Search request to {next_url} returned HTTP {response.status_code}")

        total_bytes += len(response.content)
        if total_bytes > MAX_SYNC_BYTES:
            raise ConnectorError(f"Sync exceeded the maximum bounded response size ({MAX_SYNC_BYTES} bytes) while paginating")

        bundle = response.json()
        if bundle.get("resourceType") != "Bundle":
            raise ConnectorError("Search response was not a FHIR Bundle")

        for entry in bundle.get("entry", []):
            resource = entry.get("resource")
            if resource:
                resources.append(resource)
                if len(resources) > MAX_SYNC_RESOURCES:
                    raise ConnectorError(f"Sync exceeded the maximum bounded resource count ({MAX_SYNC_RESOURCES}) while paginating")

        next_url = None
        for link in bundle.get("link", []):
            if link.get("relation") == "next":
                next_url = link.get("url")
    return resources


def _extract_patient_identifier(patient_resource: dict[str, Any], system: str) -> str | None:
    for identifier in patient_resource.get("identifier", []):
        if identifier.get("system") == system and identifier.get("value"):
            return identifier["value"]
    return None


def _extract_observation_fields(observation: dict[str, Any]) -> dict[str, Any]:
    coding = (observation.get("code", {}).get("coding") or [{}])[0]
    raw_test_name = observation.get("code", {}).get("text") or coding.get("display") or coding.get("code") or "Unknown"
    quantity = observation.get("valueQuantity") or {}
    value = str(quantity.get("value")) if quantity.get("value") is not None else None
    unit = quantity.get("unit") or quantity.get("code")
    ref_range = observation.get("referenceRange") or []
    reference_range = None
    if ref_range:
        low = ref_range[0].get("low", {}).get("value")
        high = ref_range[0].get("high", {}).get("value")
        if low is not None and high is not None:
            reference_range = f"{low} - {high}"
    flag = None
    interpretation = observation.get("interpretation") or []
    if interpretation:
        flag_coding = (interpretation[0].get("coding") or [{}])[0]
        flag = flag_coding.get("code")
    return {
        "system": coding.get("system"),
        "code": coding.get("code"),
        "raw_test_name": raw_test_name,
        "value": value,
        "unit": unit,
        "reference_range": reference_range,
        "flag": flag,
        "observation_datetime": observation.get("effectiveDateTime"),
        "status": observation.get("status"),
    }


def _resolve_terminology(
    db: Session, connection_id: int, system: str | None, code: str | None
) -> models.InteropTerminologyMapping | None:
    if not code:
        return None
    return (
        db.query(models.InteropTerminologyMapping)
        .filter(
            models.InteropTerminologyMapping.connection_id == connection_id,
            models.InteropTerminologyMapping.source_system == system,
            models.InteropTerminologyMapping.source_code == code,
            models.InteropTerminologyMapping.status == "approved",
        )
        .first()
    )


def _map_observation(
    db: Session, connection: models.InteropConnection, observation: dict[str, Any], patient_identity: tuple[str, str] | None
) -> MappedObservation:
    fields = _extract_observation_fields(observation)

    if fields["status"] not in IMPORTABLE_OBSERVATION_STATUSES:
        return MappedObservation(
            external_id=observation.get("id", ""),
            patient_external_identifier=patient_identity,
            raw_test_name=fields["raw_test_name"],
            canonical_name=None,
            display_name=None,
            category=None,
            value=fields["value"],
            unit=fields["unit"],
            reference_range=fields["reference_range"],
            flag=fields["flag"],
            observation_datetime=fields["observation_datetime"],
            normalization_method="skipped",
            mapping_source="skipped",
            skipped_reason=f"status={fields['status']!r} is not imported (cancelled/entered-in-error/unknown)",
        )

    override = _resolve_terminology(db, connection.id, fields["system"], fields["code"])
    if override:
        return MappedObservation(
            external_id=observation.get("id", ""),
            patient_external_identifier=patient_identity,
            raw_test_name=fields["raw_test_name"],
            canonical_name=override.target_canonical_name,
            display_name=override.target_display_name,
            category=override.target_category,
            value=fields["value"],
            unit=fields["unit"] or override.target_unit,
            reference_range=fields["reference_range"],
            flag=fields["flag"],
            observation_datetime=fields["observation_datetime"],
            normalization_method="local_override",
            mapping_source="terminology_override",
        )

    resolved = resolve_analyte(fields["raw_test_name"], unit=fields["unit"])
    if resolved.resolved:
        return MappedObservation(
            external_id=observation.get("id", ""),
            patient_external_identifier=patient_identity,
            raw_test_name=fields["raw_test_name"],
            canonical_name=resolved.canonical_name,
            display_name=resolved.display_name,
            category=resolved.category,
            value=fields["value"],
            unit=fields["unit"],
            reference_range=fields["reference_range"],
            flag=fields["flag"],
            observation_datetime=fields["observation_datetime"],
            normalization_method=resolved.normalization_method,
            mapping_source="resolver",
        )

    # Unresolved — surfaced for review (P73), never guessed.
    _record_unmapped_terminology(db, connection.id, fields)
    return MappedObservation(
        external_id=observation.get("id", ""),
        patient_external_identifier=patient_identity,
        raw_test_name=fields["raw_test_name"],
        canonical_name=None,
        display_name=fields["raw_test_name"],
        category=None,
        value=fields["value"],
        unit=fields["unit"],
        reference_range=fields["reference_range"],
        flag=fields["flag"],
        observation_datetime=fields["observation_datetime"],
        normalization_method="unresolved",
        mapping_source="unresolved",
    )


def _record_unmapped_terminology(db: Session, connection_id: int, fields: dict[str, Any]) -> None:
    existing = (
        db.query(models.InteropTerminologyMapping)
        .filter(
            models.InteropTerminologyMapping.connection_id == connection_id,
            models.InteropTerminologyMapping.source_system == fields["system"],
            models.InteropTerminologyMapping.source_code == fields["code"],
        )
        .first()
    )
    if existing:
        existing.frequency_seen += 1
        return
    db.add(
        models.InteropTerminologyMapping(
            connection_id=connection_id,
            source_system=fields["system"],
            source_code=fields["code"],
            source_display=fields["raw_test_name"],
            mapping_type="pending_review",
            status="pending",
            frequency_seen=1,
            example_json=json.dumps(fields),
            created_at=_now_iso(),
        )
    )


def _supports_incremental_sync(connection: models.InteropConnection, resource_type: str) -> bool:
    """Phase 3 §3.3 — only ever use `_lastUpdated` when the connection's
    OWN cached discovery says the partner actually advertised it for this
    resource. Never assumed."""
    if not connection.capabilities_json:
        return False
    try:
        resources = json.loads(connection.capabilities_json).get("capability", {}).get("resources", {})
        return bool(resources.get(resource_type, {}).get("supports_last_updated"))
    except (json.JSONDecodeError, AttributeError, TypeError):
        return False


def _get_sync_cursor(connection: models.InteropConnection, resource_type: str) -> str | None:
    if not connection.sync_cursor_json:
        return None
    try:
        return json.loads(connection.sync_cursor_json).get(resource_type)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None


def _collect_mapped_observations(
    db: Session, connection: models.InteropConnection, headers: dict[str, str], primary_system: str
) -> tuple[list[dict[str, Any]], list[MappedObservation], SyncSummary, str]:
    """Shared by preview and sync — fetches Patients (bounded), resolves
    identity per patient, fetches that patient's Observations (bounded —
    incrementally via `_lastUpdated` where the partner supports it and a
    prior cursor exists, otherwise a full bounded fetch), and maps each
    one. Returns (patients, mapped_observations, summary, sync_started_at).

    `sync_started_at` is captured BEFORE any request — the safe watermark
    for the NEXT sync's cursor if this one commits (see run_sync): using
    the pre-fetch timestamp rather than the max `meta.lastUpdated` seen in
    results guarantees overlap with anything updated during this sync's
    own execution window, and existing external_observation_id-keyed
    idempotency makes that overlap safe (re-processed, never duplicated)
    rather than something that needs its own dedup logic.
    """
    sync_started_at = _now_iso()
    summary = SyncSummary()

    patients = _fetch_bundle_pages(
        connection.base_url.rstrip("/") + f"/Patient?_count={PREVIEW_MAX_PATIENTS}", connection, headers
    )[:PREVIEW_MAX_PATIENTS]
    summary.patients_discovered = len(patients)

    incremental = _supports_incremental_sync(connection, "Observation")
    cursor = _get_sync_cursor(connection, "Observation") if incremental else None

    mapped: list[MappedObservation] = []
    for patient in patients:
        identifier_value = _extract_patient_identifier(patient, primary_system)
        if not identifier_value:
            continue  # no configured identifier present on this resource — nothing to link, not an error

        resolution = identity_module.resolve_external_identity(
            db, connection_id=connection.id, identifier_system=primary_system, identifier_value=identifier_value
        )
        if resolution.outcome == "requires_review":
            continue  # not yet linked — no data fetched for an unlinked identity (P33)

        patient_fhir_id = patient.get("id")
        observation_url = connection.base_url.rstrip("/") + f"/Observation?patient={patient_fhir_id}&_count={MAX_OBSERVATIONS_PER_PATIENT}"
        if cursor:
            observation_url += f"&_lastUpdated=gt{cursor}"
        observations = _fetch_bundle_pages(observation_url, connection, headers)[:MAX_OBSERVATIONS_PER_PATIENT]
        summary.observations_seen += len(observations)

        for observation in observations:
            mapped_observation = _map_observation(db, connection, observation, (primary_system, identifier_value))
            mapped.append(mapped_observation)
            if mapped_observation.mapping_source == "skipped":
                summary.skipped_status += 1
            elif mapped_observation.mapping_source == "unresolved":
                summary.unmapped_terminology += 1
                summary.requires_mapping_review += 1
            else:
                summary.mapped_automatically += 1

    return patients, mapped, summary, sync_started_at


def preview_sync(db: Session, connection: models.InteropConnection) -> dict[str, Any]:
    """P66/P67 — shadow sync. Real retrieve + map + identity + dedup
    computation against the real partner, COMMITS NOTHING. This is always
    the first thing run for a new connection."""
    headers = _auth_headers(connection)
    identity_config = json.loads(connection.patient_identity_json or "{}")
    primary_system = identity_config.get("primary_system")
    if not primary_system:
        raise ConnectorError("patient_identity.primary_system is not configured — cannot resolve any identity safely.")

    patients, mapped, summary, _sync_started_at = _collect_mapped_observations(db, connection, headers, primary_system)

    unresolved_identities = 0
    for patient in patients:
        identifier_value = _extract_patient_identifier(patient, primary_system)
        if identifier_value:
            resolution = identity_module.resolve_external_identity(
                db, connection_id=connection.id, identifier_system=primary_system, identifier_value=identifier_value
            )
            if resolution.outcome == "requires_review":
                unresolved_identities += 1

    for observation in mapped:
        if observation.mapping_source == "skipped":
            continue
        existing = (
            db.query(models.LabResult)
            .filter(models.LabResult.external_observation_id == observation.external_id, models.LabResult.source_connection_id == connection.id)
            .first()
        )
        if existing:
            summary.duplicates_detected += 1
            summary.would_update += 1
        else:
            summary.would_create += 1

    # Preview never creates/updates a Document or LabResult (those blocks
    # only exist in run_sync below) — nothing clinical is committed here.
    # The one thing preview DOES persist is the terminology-review queue
    # (InteropTerminologyMapping "pending" rows written by _map_observation
    # via _record_unmapped_terminology): that's non-clinical bookkeeping
    # metadata, and persisting it is what lets an admin review/approve
    # unmapped codes (P73) before ever running a real sync.
    db.commit()

    return {
        "run_type": "preview",
        "identity": {"requires_review": unresolved_identities, "linked": summary.patients_discovered - unresolved_identities},
        "summary": summary.to_dict(),
    }


def run_sync(db: Session, connection: models.InteropConnection, *, user_id: int | None) -> dict[str, Any]:
    """The real, idempotent commit path (P50). Only patients with a
    VERIFIED ExternalPatientIdentityLink ever get data written; everything
    else is quarantined for review, never guessed at."""
    headers = _auth_headers(connection)
    identity_config = json.loads(connection.patient_identity_json or "{}")
    primary_system = identity_config.get("primary_system")
    if not primary_system:
        raise ConnectorError("patient_identity.primary_system is not configured — cannot sync safely.")

    patients, mapped, summary, sync_started_at = _collect_mapped_observations(db, connection, headers, primary_system)

    # Group mapped observations by the Bragi patient they resolved to.
    by_patient: dict[int, list[MappedObservation]] = {}
    linked_patient_count = 0
    for patient in patients:
        identifier_value = _extract_patient_identifier(patient, primary_system)
        if not identifier_value:
            continue
        resolution = identity_module.resolve_external_identity(
            db, connection_id=connection.id, identifier_system=primary_system, identifier_value=identifier_value
        )
        if resolution.outcome != "linked" or resolution.patient_id is None:
            continue
        linked_patient_count += 1
        patient_observations = [
            m for m in mapped if m.patient_external_identifier == (primary_system, identifier_value) and m.mapping_source != "skipped"
        ]
        by_patient.setdefault(resolution.patient_id, []).extend(patient_observations)

    for bragi_patient_id, observations in by_patient.items():
        if not observations:
            continue
        sync_document = models.Document(
            patient_id=bragi_patient_id,
            uploaded_by_user_id=None,
            section="bloodwork",
            filename=f"FHIR sync — {connection.name} — {_now_iso()}",
            content_type="application/fhir+json",
            document_type="lab_results",
            classification_status="auto",
            classification_source="interop_fhir",
            source_connection_id=connection.id,
            is_verified=False,
            created_at=_now_iso(),
        )
        db.add(sync_document)
        db.flush()

        for observation in observations:
            existing = (
                db.query(models.LabResult)
                .filter(
                    models.LabResult.external_observation_id == observation.external_id,
                    models.LabResult.source_connection_id == connection.id,
                )
                .first()
            )
            if existing:
                existing.value = observation.value
                existing.unit = observation.unit
                existing.flag = observation.flag
                existing.reference_range = observation.reference_range
                existing.observation_datetime = observation.observation_datetime
                summary.updated += 1
                continue

            lab_result = models.LabResult(
                document_id=sync_document.id,
                raw_test_name=observation.raw_test_name,
                canonical_name=observation.canonical_name,
                display_name=observation.display_name,
                category=observation.category,
                value=observation.value,
                unit=observation.unit,
                flag=observation.flag,
                reference_range=observation.reference_range,
                observation_datetime=observation.observation_datetime,
                normalization_method=observation.normalization_method,
                verification_state="unverified",
                source_connection_id=connection.id,
                external_observation_id=observation.external_id,
            )
            db.add(lab_result)
            db.flush()

            db.add(
                models.SourceEvidence(
                    document_id=sync_document.id,
                    lab_result_id=lab_result.id,
                    source_text=(
                        f"External FHIR observation — connection={connection.name}, "
                        f"observation_id={observation.external_id}"
                    ),
                    provider="interop_fhir",
                    created_at=_now_iso(),
                )
            )
            summary.created += 1

    summary.quarantined_identity = summary.patients_discovered - linked_patient_count

    # Phase 3 §3.3 — advance the incremental-sync watermark only on a
    # real committed sync (never during preview — see preview_sync's own
    # docstring), and only to this sync's OWN start time (captured before
    # any request), not the max lastUpdated seen in results — see
    # _collect_mapped_observations' docstring for why that ordering
    # matters for safe overlap.
    if _supports_incremental_sync(connection, "Observation"):
        cursor_state = json.loads(connection.sync_cursor_json or "{}")
        cursor_state["Observation"] = sync_started_at
        connection.sync_cursor_json = json.dumps(cursor_state)

    db.commit()

    return {"run_type": "sync", "summary": summary.to_dict()}
