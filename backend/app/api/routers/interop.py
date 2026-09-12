"""Interoperability admin routes (/admin/interop/*) — extracted verbatim
from app/main.py as part of the backend modularization refactor (Phase
4, docs/refactor/BACKEND_DECOMPOSITION_PLAN.md). Chosen as the FIRST
router extraction: contiguous in the original file, entirely self-
contained (its own app/services/interop/ package), and the newest, most
thoroughly tested code in the backend (BRAGI_INTEROP_PLAN.md Phases 1-3).

This is a pure relocation, not a redesign: every route, path, method,
request/response shape, and authorization requirement is unchanged from
before this move — see docs/refactor/AUTHORIZATION_MAP.md (captured
before this move) and the zero-diff route-inventory check performed
alongside this commit.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_db, require_role
from app.core.utils import generate_public_id, now_iso
from app.services.interop import (
    auth_providers as interop_auth_providers,
    capability as interop_capability,
    concurrency as interop_concurrency,
    fhir_connector,
    identity as interop_identity,
    jwks as interop_jwks,
    lifecycle as interop_lifecycle,
    reports as interop_reports,
    resilience as interop_resilience,
    templates as interop_templates,
)
from app.services.interop.crypto import encrypt_secret as interop_encrypt_secret
from app.services.interop.flags import INTEROP_FHIR_ENABLED, IS_PRODUCTION
from app.services.interop.mapping import MappingError, parse_mapping_rule

router = APIRouter()
# No prefix, no tags here deliberately — every route below keeps its
# exact original full path string (e.g. "/admin/interop/templates") and
# an empty tags list, unchanged from main.py, so this extraction is a
# pure mechanical move with verified zero OpenAPI contract drift (see
# docs/refactor/OPENAPI_EQUIVALENCE_REPORT.md). Adding a real "interop"
# tag for API-docs grouping is a reasonable follow-up, but a deliberate
# one — not a side effect of this move.




# ============================================================================
# Interoperability — /admin/interop/* (BRAGI_INTEROP_PLAN.md, Phase 1)
#
# Feature-flagged off by default (INTEROP_FHIR_ENABLED, same pattern as
# ASK_BRAGI_ENABLED above) — merging this code changes nothing for any real
# user until explicitly activated. Every route below is admin-only AND
# checks the flag first. Business logic lives in app/services/interop/;
# these routes are thin — resolve the connection, call the service, shape
# the response, same division of responsibility as the Ask Bragi routes.
# ============================================================================


def _require_interop_enabled():
    if not INTEROP_FHIR_ENABLED:
        raise HTTPException(status_code=404, detail="Interoperability is not enabled on this deployment.")


def _get_interop_connection_or_404(db: Session, connection_id: int) -> models.InteropConnection:
    connection = db.query(models.InteropConnection).filter(models.InteropConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


def _serialize_interop_connection(connection: models.InteropConnection) -> dict:
    """Never includes secret_ref's ciphertext (secret_ref itself is just an
    opaque pointer, not the secret) — safe to return to any admin caller."""
    return {
        "id": connection.id,
        "public_id": connection.public_id,
        "name": connection.name,
        "connector_type": connection.connector_type,
        "status": connection.status,
        "base_url": connection.base_url,
        "fhir_version": connection.fhir_version,
        "allow_private_network": connection.allow_private_network,
        "auth_type": connection.auth_type,
        "auth_config": json.loads(connection.auth_config_json or "{}"),
        "has_secret": bool(connection.secret_ref),
        "patient_identity": json.loads(connection.patient_identity_json or "{}"),
        "capabilities": json.loads(connection.capabilities_json or "{}"),
        "capabilities_discovered_at": connection.capabilities_discovered_at,
        "terminology_overrides": json.loads(connection.terminology_overrides_json or "{}"),
        "sync_config": json.loads(connection.sync_config_json or "{}"),
        "version": connection.version,
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
        # Phase 3 hardening state — all PHI-safe (counts/timestamps/short
        # classification strings only, never a secret or clinical value).
        "capability_fingerprint": connection.capability_fingerprint,
        "consecutive_failures": connection.consecutive_failures,
        "last_failure_at": connection.last_failure_at,
        "last_failure_reason": connection.last_failure_reason,
        "disabled_at": connection.disabled_at,
    }


class InteropConnectionCreateRequest(BaseModel):
    name: str
    base_url: str
    connector_type: str = "fhir"
    allow_private_network: bool = False
    patient_identity_primary_system: str | None = None


class InteropConnectionUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    auth_type: str | None = None
    auth_config: dict | None = None
    patient_identity: dict | None = None
    terminology_overrides: dict | None = None
    sync_config: dict | None = None
    change_reason: str | None = None


class InteropSecretSetRequest(BaseModel):
    secret_plaintext: str


class InteropIdentityLinkRequest(BaseModel):
    patient_id: int
    identifier_system: str
    identifier_value: str


class InteropTerminologyApproveRequest(BaseModel):
    target_canonical_name: str
    target_display_name: str
    target_category: str | None = None
    target_unit: str | None = None


class InteropProfileImportRequest(BaseModel):
    profile: dict


@router.get("/admin/interop/templates")
def list_interop_templates(current_user=Depends(require_role("admin"))):
    _require_interop_enabled()
    return {
        "templates": interop_templates.CONNECTOR_TEMPLATES,
        "unimplemented_connection_types": interop_templates.UNIMPLEMENTED_CONNECTION_TYPES,
    }


@router.post("/admin/interop/connections")
def create_interop_connection(
    payload: InteropConnectionCreateRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    _require_interop_enabled()
    if payload.allow_private_network and IS_PRODUCTION:
        raise HTTPException(
            status_code=400,
            detail="allow_private_network cannot be set in production — this is reserved for local sandbox/test connections.",
        )
    identity_json = json.dumps(
        {"primary_system": payload.patient_identity_primary_system} if payload.patient_identity_primary_system else {}
    )
    connection = models.InteropConnection(
        public_id=generate_public_id("interop"),
        name=payload.name,
        connector_type=payload.connector_type,
        status="draft",
        base_url=payload.base_url,
        allow_private_network=payload.allow_private_network,
        auth_type="none",
        patient_identity_json=identity_json,
        created_by_user_id=current_user.id,
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return _serialize_interop_connection(connection)


@router.get("/admin/interop/connections")
def list_interop_connections(current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    connections = db.query(models.InteropConnection).order_by(models.InteropConnection.id.desc()).all()
    return {"connections": [_serialize_interop_connection(c) for c in connections]}


@router.get("/admin/interop/connections/{connection_id}")
def get_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    return _serialize_interop_connection(_get_interop_connection_or_404(db, connection_id))


@router.patch("/admin/interop/connections/{connection_id}")
def update_interop_connection(
    connection_id: int,
    payload: InteropConnectionUpdateRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """P64 — configuration versioning: every update bumps `version` and can
    record a change_reason; nothing here mutates an ACTIVE connection's
    behavior mid-sync (a running sync reads its own connection row once at
    the start)."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)

    if payload.name is not None:
        connection.name = payload.name
    if payload.base_url is not None:
        connection.base_url = payload.base_url
    if payload.auth_type is not None:
        if payload.auth_type not in interop_auth_providers.SUPPORTED_AUTH_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown auth_type. Supported: {interop_auth_providers.SUPPORTED_AUTH_TYPES}")
        connection.auth_type = payload.auth_type
    if payload.auth_config is not None:
        connection.auth_config_json = json.dumps(payload.auth_config)
    if payload.patient_identity is not None:
        connection.patient_identity_json = json.dumps(payload.patient_identity)
    if payload.terminology_overrides is not None:
        # Validate every rule up front — a malformed/unknown-op rule is
        # refused here rather than failing silently mid-sync.
        for _key, rule in payload.terminology_overrides.items():
            try:
                parse_mapping_rule(rule)
            except MappingError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid mapping rule for {_key!r}: {exc}") from exc
        connection.terminology_overrides_json = json.dumps(payload.terminology_overrides)
    if payload.sync_config is not None:
        connection.sync_config_json = json.dumps(payload.sync_config)

    connection.version += 1
    connection.change_reason = payload.change_reason
    connection.updated_at = now_iso()
    db.commit()
    db.refresh(connection)
    return _serialize_interop_connection(connection)


@router.post("/admin/interop/connections/{connection_id}/secret")
def set_interop_connection_secret(
    connection_id: int,
    payload: InteropSecretSetRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Stores the secret encrypted (see app/services/interop/crypto.py) and
    points the connection at it by opaque reference. The plaintext is never
    echoed back, never logged, and never included in any export."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)

    ref = connection.secret_ref or f"interop-secret-{connection.public_id}"
    ciphertext = interop_encrypt_secret(payload.secret_plaintext)
    existing = db.query(models.InteropSecret).filter_by(ref=ref).first()
    if existing:
        existing.ciphertext = ciphertext
        existing.rotated_at = now_iso()
    else:
        db.add(
            models.InteropSecret(
                ref=ref,
                ciphertext=ciphertext,
                created_at=now_iso(),
                created_by_user_id=current_user.id,
            )
        )
    # SessionLocal is autoflush=False (see app/db.py) — without an explicit
    # flush here, the new InteropSecret row and the InteropConnection
    # UPDATE that references it by FK (secret_ref) are both only pending in
    # memory, and nothing guarantees the INSERT is sent before the UPDATE
    # when db.commit() flushes everything together (reproduced for real
    # against Neon: a fresh secret_ref FK violation on first secret-set).
    # Flushing the new secret row first makes the ordering explicit rather
    # than relying on SQLAlchemy's flush-ordering heuristics across two
    # mapped classes with no declared relationship() between them.
    db.flush()
    connection.secret_ref = ref
    connection.updated_at = now_iso()
    db.commit()
    interop_auth_providers.clear_token_cache(connection.id)
    return {"ok": True, "has_secret": True}


@router.post("/admin/interop/connections/{connection_id}/generate-signing-key")
def generate_interop_signing_key(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """For smart_backend_services: generates an RSA keypair, stores the
    private key as this connection's secret, and returns the PUBLIC JWK for
    the admin to register with the partner (or host at a JWKS URL) — see
    app/services/interop/jwks.py."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)

    private_pem, public_jwk = interop_jwks.generate_keypair()
    ref = connection.secret_ref or f"interop-secret-{connection.public_id}"
    ciphertext = interop_encrypt_secret(private_pem)
    existing = db.query(models.InteropSecret).filter_by(ref=ref).first()
    if existing:
        existing.ciphertext = ciphertext
        existing.rotated_at = now_iso()
    else:
        db.add(models.InteropSecret(ref=ref, ciphertext=ciphertext, created_at=now_iso(), created_by_user_id=current_user.id))
    db.flush()  # see set_interop_connection_secret's comment — same FK-ordering hazard
    connection.secret_ref = ref
    auth_config = json.loads(connection.auth_config_json or "{}")
    auth_config["jwks"] = {"keys": [public_jwk]}
    connection.auth_config_json = json.dumps(auth_config)
    connection.updated_at = now_iso()
    db.commit()
    interop_auth_providers.clear_token_cache(connection.id)
    return {"public_jwk": public_jwk}


def _record_sync_run(db: Session, connection: models.InteropConnection, run_type: str, current_user) -> models.InteropSyncRun:
    run = models.InteropSyncRun(
        connection_id=connection.id,
        run_type=run_type,
        status="running",
        started_at=now_iso(),
        started_by_user_id=current_user.id if current_user else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finish_sync_run(db: Session, run: models.InteropSyncRun, *, status: str, summary: dict | None = None, error: str | None = None):
    run.status = status
    run.finished_at = now_iso()
    if summary is not None:
        run.summary_json = json.dumps(summary)
    if error is not None:
        run.error_message = error
    db.commit()


def _log_interop_metric(name: str, connection_id: int, **fields):
    """PHI-safe operational metrics (Phase 3 §3.13) — connection_id (an
    internal integer, not a patient identifier) plus counts/durations
    only. Never a patient id, clinical value, or free-text field. Same
    print-based pattern the rest of this codebase already uses for
    operational logging (see the ASK BRAGI metric line elsewhere in this
    file) rather than introducing a new logging framework for this alone.
    """
    safe_fields = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"INTEROP METRIC: {name} connection_id={connection_id} {safe_fields}")


@router.post("/admin/interop/connections/{connection_id}/discover")
def discover_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    if not interop_lifecycle.can_discover(connection.status):
        raise HTTPException(status_code=400, detail=f"Cannot discover a {connection.status} connection.")

    try:
        with interop_concurrency.connection_sync_lock(db, connection.id):
            run = _record_sync_run(db, connection, "discover", current_user)
            try:
                result = fhir_connector.run_discovery(connection)
            except fhir_connector.ConnectorError as exc:
                interop_resilience.apply_failure(connection, "discovery_error")
                db.commit()
                _finish_sync_run(db, run, status="failed", error=str(exc))
                _log_interop_metric("interop_connection_tests_total", connection.id, outcome="discover_failed")
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            drift_result = fhir_connector.compute_discovery_drift(connection, result)

            interop_resilience.apply_success(connection)
            connection.capabilities_json = json.dumps(result)
            connection.capabilities_discovered_at = result["discovered_at"]
            connection.capability_fingerprint = drift_result["fingerprint"]
            connection.fhir_version = result["capability"].get("fhir_version")
            if connection.status == "draft":
                connection.status = "discovered"
            elif drift_result["breaking"] and connection.status == "active":
                # Phase 3 §3.2 — a breaking capability change on an ACTIVE
                # connection stops automatic sync rather than silently
                # continuing as if nothing changed. Re-validate (test +
                # preview) to clear DEGRADED — see lifecycle.py.
                connection.status = "degraded"
            if result.get("recommended_auth_type") and connection.auth_type == "none":
                # Recommend only — never silently activate real auth (P8). The
                # admin still has to call PATCH .../secret to supply credentials.
                auth_config = json.loads(connection.auth_config_json or "{}")
                auth_config.setdefault("_recommended_auth_type", result["recommended_auth_type"])
                connection.auth_config_json = json.dumps(auth_config)
            connection.updated_at = now_iso()
            db.commit()

            _finish_sync_run(
                db,
                run,
                status="succeeded",
                summary={"resources_found": len(result["capability"].get("resources", {})), "drift": drift_result},
            )
    except interop_concurrency.ConnectionSyncInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _log_interop_metric("interop_connection_tests_total", connection.id, outcome="discover_succeeded")
    return {"capability": result, "compatibility_report": result["compatibility_report"], "drift": drift_result}


@router.post("/admin/interop/connections/{connection_id}/test")
def test_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)

    try:
        with interop_concurrency.connection_sync_lock(db, connection.id):
            run = _record_sync_run(db, connection, "test", current_user)
            stages = fhir_connector.run_connection_test(connection)
            all_passed = all(s.passed for s in stages)
            if all_passed:
                interop_resilience.apply_success(connection)
                if connection.status == "discovered":
                    interop_lifecycle.validate_transition(connection.status, "validated")
                    connection.status = "validated"
                    connection.updated_at = now_iso()
                elif connection.status == "degraded":
                    # A passing manual test is how a DEGRADED connection
                    # recovers — see P62/lifecycle.py's DEGRADED docstring.
                    interop_lifecycle.validate_transition(connection.status, "active")
                    connection.status = "active"
                    connection.updated_at = now_iso()
                db.commit()
            else:
                interop_resilience.apply_failure(connection, "test_failed")
                db.commit()
            _finish_sync_run(
                db,
                run,
                status="succeeded" if all_passed else "failed",
                summary={"stages": [{"stage": s.stage, "passed": s.passed, "message": s.message} for s in stages]},
            )
    except interop_concurrency.ConnectionSyncInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _log_interop_metric("interop_connection_tests_total", connection.id, outcome="passed" if all_passed else "failed")
    return {"passed": all_passed, "stages": [{"stage": s.stage, "passed": s.passed, "message": s.message} for s in stages]}


@router.post("/admin/interop/connections/{connection_id}/preview")
def preview_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """P66/P67 — shadow sync. Commits no clinical data — see
    fhir_connector.preview_sync's own docstring for exactly what it does
    persist (terminology-review bookkeeping only)."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    if not interop_lifecycle.can_run_preview(connection.status):
        raise HTTPException(status_code=400, detail=f"Cannot preview a {connection.status} connection — discover and test it first.")

    try:
        with interop_concurrency.connection_sync_lock(db, connection.id):
            run = _record_sync_run(db, connection, "preview", current_user)
            try:
                result = fhir_connector.preview_sync(db, connection)
            except fhir_connector.ConnectorError as exc:
                interop_resilience.apply_failure(connection, "preview_failed")
                db.commit()
                _finish_sync_run(db, run, status="failed", error=str(exc))
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            interop_resilience.apply_success(connection)
            if connection.status == "validated":
                interop_lifecycle.validate_transition(connection.status, "shadow")
                connection.status = "shadow"
                connection.updated_at = now_iso()
            db.commit()
            _finish_sync_run(db, run, status="succeeded", summary=result["summary"])
    except interop_concurrency.ConnectionSyncInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _log_interop_metric(
        "interop_sync_runs_total",
        connection.id,
        run_type="preview",
        would_create=result["summary"].get("would_create"),
        would_update=result["summary"].get("would_update"),
    )
    return result


@router.post("/admin/interop/connections/{connection_id}/connect")
def connect_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """The real activation step (spec STEP 8) — only reachable after a
    connection has been discovered, tested, and shadow-previewed at least
    once. Runs one real, idempotent commit sync."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    if not interop_lifecycle.can_activate(connection.status):
        raise HTTPException(
            status_code=400,
            detail=f"Connection must be shadow-previewed before connecting (current status: {connection.status}).",
        )

    try:
        with interop_concurrency.connection_sync_lock(db, connection.id):
            run = _record_sync_run(db, connection, "sync", current_user)
            try:
                result = fhir_connector.run_sync(db, connection, user_id=current_user.id)
            except fhir_connector.ConnectorError as exc:
                interop_resilience.apply_failure(connection, "sync_failed")
                db.commit()
                _finish_sync_run(db, run, status="failed", error=str(exc))
                _log_interop_metric("interop_sync_failures_total", connection.id)
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            interop_resilience.apply_success(connection)
            if connection.status != "active":
                interop_lifecycle.validate_transition(connection.status, "active")
            connection.status = "active"
            connection.updated_at = now_iso()
            db.commit()
            _finish_sync_run(db, run, status="succeeded", summary=result["summary"])
    except interop_concurrency.ConnectionSyncInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _log_interop_metric(
        "interop_sync_runs_total",
        connection.id,
        run_type="sync",
        created=result["summary"].get("created"),
        updated=result["summary"].get("updated"),
    )
    return result


@router.post("/admin/interop/connections/{connection_id}/pause")
def pause_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """P69/P70 — stops future sync/token use immediately; never deletes
    already-imported clinical history. Reversible via a subsequent
    real sync/test call, which moves the connection back to ACTIVE."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    try:
        interop_lifecycle.validate_transition(connection.status, "paused")
    except interop_lifecycle.LifecycleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    connection.status = "paused"
    connection.updated_at = now_iso()
    db.commit()
    interop_auth_providers.clear_token_cache(connection.id)
    return _serialize_interop_connection(connection)


@router.post("/admin/interop/connections/{connection_id}/disable")
def disable_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """P67/§3.12 — distinct from pause: disabling is a more deliberate,
    longer-term "stop using this connection" action. Re-enabling a
    disabled connection is NOT a status flip back — it requires a fresh
    discover/test/shadow pass (see lifecycle.py's DISABLED docstring),
    since a connection someone deliberately turned off deserves a real
    compatibility re-check, not a silent resurrection. Never deletes
    already-imported clinical history — same guarantee as pause."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    try:
        interop_lifecycle.validate_transition(connection.status, "disabled")
    except interop_lifecycle.LifecycleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    connection.status = "disabled"
    connection.disabled_at = now_iso()
    connection.updated_at = now_iso()
    db.commit()
    interop_auth_providers.clear_token_cache(connection.id)
    return _serialize_interop_connection(connection)


@router.get("/admin/interop/connections/{connection_id}/export")
def export_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    return interop_reports.export_connection_profile(connection)


@router.post("/admin/interop/connections/import")
def import_interop_connection(
    payload: InteropProfileImportRequest, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)
):
    _require_interop_enabled()
    try:
        draft_fields = interop_reports.import_connection_profile(payload.profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    connection = models.InteropConnection(
        public_id=generate_public_id("interop"),
        status="draft",
        created_by_user_id=current_user.id,
        created_at=now_iso(),
        updated_at=now_iso(),
        **draft_fields,
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return _serialize_interop_connection(connection)


@router.get("/admin/interop/connections/{connection_id}/report")
def get_interop_partner_report(
    connection_id: int, format: str = "json", current_user=Depends(require_role("admin")), db: Session = Depends(get_db)
):
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    cached = json.loads(connection.capabilities_json or "{}")
    compatibility_report = cached.get("compatibility_report")
    if not compatibility_report:
        raise HTTPException(status_code=400, detail="Run discovery before requesting a partner readiness report.")
    report = interop_reports.build_partner_readiness_report(connection, compatibility_report)
    if format == "markdown":
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(interop_reports.render_partner_readiness_markdown(report))
    return report


@router.get("/admin/interop/connections/{connection_id}/diagnostic-bundle")
def get_interop_diagnostic_bundle(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """P74 — sanitized, PHI-free, secret-free troubleshooting bundle."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    recent_runs = (
        db.query(models.InteropSyncRun)
        .filter(models.InteropSyncRun.connection_id == connection_id)
        .order_by(models.InteropSyncRun.id.desc())
        .limit(20)
        .all()
    )
    return interop_reports.build_diagnostic_bundle(connection, recent_runs)


@router.get("/admin/interop/connections/{connection_id}/identity/conflicts")
def list_interop_identity_conflicts(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    _get_interop_connection_or_404(db, connection_id)
    conflicts = (
        db.query(models.InteropIdentityConflict)
        .filter(models.InteropIdentityConflict.connection_id == connection_id, models.InteropIdentityConflict.resolved.is_(False))
        .all()
    )
    return {
        "conflicts": [
            {
                "id": c.id,
                "identifier_system": c.identifier_system,
                "identifier_value": c.identifier_value,
                "existing_link_id": c.existing_link_id,
                "attempted_patient_id": c.attempted_patient_id,
                "detected_at": c.detected_at,
            }
            for c in conflicts
        ]
    }


@router.post("/admin/interop/connections/{connection_id}/identity/links")
def create_interop_identity_link(
    connection_id: int,
    payload: InteropIdentityLinkRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """P32/P33 — the only way an identity link is ever created: an explicit
    admin action naming both sides. Refuses (400, with an IDENTITY CONFLICT
    recorded for review) rather than silently overwriting a link that
    already points at a different patient."""
    _require_interop_enabled()
    _get_interop_connection_or_404(db, connection_id)
    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    try:
        link = interop_identity.create_identity_link(
            db,
            connection_id=connection_id,
            patient_id=payload.patient_id,
            identifier_system=payload.identifier_system,
            identifier_value=payload.identifier_value,
            verified_by_user_id=current_user.id,
        )
    except ValueError as exc:
        db.commit()  # persist the conflict row create_identity_link recorded before raising
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"id": link.id, "patient_id": link.patient_id, "status": link.status}


@router.get("/admin/interop/connections/{connection_id}/terminology")
def list_interop_terminology_mappings(
    connection_id: int, status: str = "pending", current_user=Depends(require_role("admin")), db: Session = Depends(get_db)
):
    _require_interop_enabled()
    _get_interop_connection_or_404(db, connection_id)
    mappings = (
        db.query(models.InteropTerminologyMapping)
        .filter(models.InteropTerminologyMapping.connection_id == connection_id, models.InteropTerminologyMapping.status == status)
        .order_by(models.InteropTerminologyMapping.frequency_seen.desc())
        .all()
    )
    return {
        "mappings": [
            {
                "id": m.id,
                "source_system": m.source_system,
                "source_code": m.source_code,
                "source_display": m.source_display,
                "frequency_seen": m.frequency_seen,
                "status": m.status,
                "example": json.loads(m.example_json) if m.example_json else None,
            }
            for m in mappings
        ]
    }


@router.post("/admin/interop/connections/{connection_id}/terminology/{mapping_id}/approve")
def approve_interop_terminology_mapping(
    connection_id: int,
    mapping_id: int,
    payload: InteropTerminologyApproveRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """P15/P19/P73 — a human-approved local-code override, reused
    automatically by every future sync from this connection (never
    re-guessed per import)."""
    _require_interop_enabled()
    _get_interop_connection_or_404(db, connection_id)
    mapping = (
        db.query(models.InteropTerminologyMapping)
        .filter(models.InteropTerminologyMapping.id == mapping_id, models.InteropTerminologyMapping.connection_id == connection_id)
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    mapping.target_canonical_name = payload.target_canonical_name
    mapping.target_display_name = payload.target_display_name
    mapping.target_category = payload.target_category
    mapping.target_unit = payload.target_unit
    mapping.mapping_type = "local_override"
    mapping.status = "approved"
    mapping.approved_at = now_iso()
    mapping.approved_by_user_id = current_user.id
    db.commit()
    return {"ok": True}
