# Bragi Interoperability Plan

**Status: Phase 1 implemented, feature-flagged off (`INTEROP_FHIR_ENABLED`,
default false). Not deployed to production. Merging this code changes
nothing for any real user until explicitly activated.**

**Migration framework**: Bragi's schema is now managed by Alembic —
see `docs/database/MIGRATIONS.md`. This was a prerequisite done alongside
Phase 1 closure, before Phase 2 adds more schema (see that doc for the
full story; the short version: the old hand-written
`run_migrations()`/`create_all()` startup path is retired, Phase 1's
schema is `alembic/versions/0002_interop_phase1.py`).

## Why this exists / scope boundary

This is a deliberate, explicit addition to Bragi's scope, decided
2026-09-11: Bragi grows a standards-based **interoperability** capability
(FHIR/HL7/CDA/DICOMweb/IHE connectivity) without becoming an operational
hospital EHR. Scheduling, billing, order entry, bed management, and
practice-management functionality remain permanently out of scope — see
`docs/` and the product's own README for what Bragi *is* (a longitudinal
patient record / clinical data layer). The prior "no EHR scope" boundary
is superseded specifically for external health-data connectivity, not
generally.

CNAS integration remains explicitly out of scope until real CNAS
registration exists — shown in the admin UI as "Awaiting registration,"
never implemented speculatively.

## Design constraint

**Do not rewrite working Bragi systems.** Every phase below is additive:
new tables, a new `app/services/interop/` package, and a handful of new
`/admin/interop/*` routes. Nothing about the existing upload pipeline,
`document_pipeline.py`, `lab_resolver.py`, Timeline, Analize, Readers, or
Ask Bragi changes. The FHIR connector *reuses* `resolve_analyte()` (the
same canonical lab resolver every upload already goes through) and writes
into the same `LabResult`/`Document`/`SourceEvidence` tables an upload
writes into — additively tagged with `source_connection_id`/
`external_observation_id` — so existing queries see synced data exactly
like uploaded data, for free.

**Everything new stays disabled by default in production until
individually validated and activated** — a whole-feature kill switch
(`INTEROP_FHIR_ENABLED`) plus a per-connection lifecycle
(draft → discovered → validated → shadow → active → paused/degraded →
disabled) rather than a bare boolean.

## Phase 1 — FHIR R4 inbound connector foundation (IMPLEMENTED)

Everything below is real, working code — not stubs — verified against
three synthetic FHIR servers with materially different capabilities using
the same, unmodified connector code path (see "Zero-code compatibility
tests" below).

### What shipped

- **`app/services/interop/`** — the connector package:
  - `flags.py` — `INTEROP_FHIR_ENABLED` (whole-feature kill switch, default
    false), `INTEROP_SECRET_ENCRYPTION_KEY`, `IS_PRODUCTION`.
  - `ssrf.py` — SSRF guard every outbound call goes through: blocks
    non-http(s) schemes, IP-literal and DNS-resolved private/loopback/
    link-local/multicast/reserved targets (including the cloud metadata
    address `169.254.169.254`), and disables automatic redirect-following
    (re-validates each hop manually, bounded). `allow_private_network` is
    the one, explicit, non-production-only escape hatch for sandbox/dev
    connections. Honest documented limitation: not a full defense against
    sub-second DNS-rebinding (would need a connection-level IP pin) —
    tracked as deferred, not silently claimed as closed.
  - `crypto.py` — Fernet-based at-rest encryption for connector secrets
    (`InteropSecret.ciphertext`), keyed by `INTEROP_SECRET_ENCRYPTION_KEY`.
    Fails closed (raises) rather than storing plaintext if unset.
  - `auth_providers.py` — `ConnectorAuthProvider` abstraction: `none`,
    `static_bearer`, `api_key_header`, `basic_auth_legacy`,
    `oauth2_client_credentials`, `smart_backend_services` (asymmetric,
    JWT client-assertion — see `jwks.py`). Token caching/refresh with a
    fixed clock-skew tolerance; `exp`/`nbf` are never disabled.
  - `jwks.py` — RSA keypair generation + public JWK export for SMART
    Backend Services (Bragi is the client; partners need Bragi's public
    key, never a secret of theirs).
  - `capability.py` — `GET {base}/metadata` → parsed `CapabilityStatement`
    → `FhirCompatibilityReport` (per-resource SUPPORTED / PARTIALLY
    SUPPORTED / UNSUPPORTED, required search params, profiles, SMART/Bulk
    Data detection) with a deterministic compatibility score. An
    unsupported *optional* capability (Bulk Data) is reported as
    UNSUPPORTED, never as an error.
  - `smart_discovery.py` — `.well-known/smart-configuration` discovery +
    auth-type *recommendation* (never silent activation).
  - `mapping.py` — the declarative mapping DSL (see below).
  - `identity.py` — deterministic patient-identity resolution — see below.
  - `fhir_connector.py` — `run_discovery`, `run_connection_test`,
    `preview_sync` (shadow, commits nothing), `run_sync` (idempotent
    commit) — the actual connector.
  - `reports.py` — sanitized profile export/import, the partner-readiness
    report (JSON + Markdown), the diagnostic bundle.
  - `templates.py` — the `ConnectorTemplate` library (Generic FHIR R4,
    Generic SMART Backend Services, a development-only synthetic sandbox
    template). CNAS listed as `UNIMPLEMENTED_CONNECTION_TYPES` only.
- **New additive tables** (`app/models.py`, migrated in `run_migrations()`
  the same idempotent `CREATE TABLE IF NOT EXISTS`/`ALTER TABLE ... ADD
  COLUMN IF NOT EXISTS` way every other table in this codebase is):
  `InteropSecret`, `InteropConnection`, `InteropSyncRun`,
  `ExternalPatientIdentityLink`, `InteropIdentityConflict`,
  `InteropTerminologyMapping`; plus additive nullable
  `source_connection_id`/`external_observation_id` columns on `Document`/
  `LabResult`.
- **`/admin/interop/*` routes** in `app/main.py` (admin-only, each checks
  `INTEROP_FHIR_ENABLED` first): connection CRUD, secret/signing-key
  management, discover, test, preview, connect, pause, export/import,
  partner-readiness report, diagnostic bundle, identity links/conflicts,
  terminology mapping review/approval.
- **Patient-deletion fix**: `DELETE /my/account` broke with a
  `ForeignKeyViolation` for a patient with an `ExternalPatientIdentityLink`
  row — the exact same FK-cascade bug class this codebase has already hit
  and fixed for `AskBragiConversation` (see `CLAUDE_HANDOFF.md`). Fixed in
  the same commit as this feature, found by this feature's own test suite
  before merging.

### Patient identity (P31-P34) — no fuzzy linking, ever

`ExternalPatientIdentityLink` is created **only** by an explicit admin
action (`POST .../identity/links`) naming both the Bragi patient and the
external `(system, value)` pair. There is no code path that creates one
automatically from a name/demographic match. An identifier already
verified-linked to a *different* patient is refused (409) and recorded as
an `InteropIdentityConflict` for review — never silently overwritten,
never "the closer match." A sync never fetches or commits data for an
unlinked identity; it's counted as `requires_review`/`quarantined_identity`
in the summary instead.

### Mapping (P15-P19) — declarative, schema-validated, no eval

`app/services/interop/mapping.py` is a fixed, `Literal`-enumerated set of
operations (`constant`, `field_path`, `lookup_table`, `code_map`,
`unit_map`, `string_normalize`, `date_parse`) validated by Pydantic —
there is no `eval()`, no arbitrary Python/JS/shell, and no way to
construct an operation outside the allowlist (an unknown `op` fails
validation before a rule is ever stored or run — see
`tests/test_interop_mapping.py::test_unknown_op_is_rejected`).
`field_path` is a **restricted subset**, not full FHIRPath (P17's honest
caveat): dotted/indexed access plus one `[system=...]` filter for picking
a coding out of a CodeableConcept — enough for what Phase 1 actually
needs; swap in a real FHIRPath library later without changing the rule
schema if a future phase needs more.

An unresolved local code is written to `InteropTerminologyMapping` as
`pending` (never guessed) and surfaced via `GET .../terminology`; an
admin's explicit `POST .../terminology/{id}/approve` is the only way it
becomes an active mapping, and once approved it's reused automatically on
every future sync from that connection (P19) — never remapped by hand
per import.

### Shadow sync / sync diff (P66/P67)

`preview_sync()` performs a **real** retrieve + map + identity + dedup
computation against the real partner server and commits **no clinical
data** — the one thing it does persist is the terminology-review queue
(non-clinical bookkeeping metadata), which is what makes mapping review
possible before a real sync ever runs. `run_sync()` is the only path that
writes `Document`/`LabResult`/`SourceEvidence` rows, and only for patients
with a `verified` identity link.

### Idempotency

Re-syncing the same partner data twice updates existing `LabResult` rows
(keyed by `external_observation_id` + `source_connection_id`) instead of
duplicating them — verified in
`tests/test_interop_e2e.py::test_idempotent_resync_updates_instead_of_duplicating`.

## Zero-code compatibility tests (P50-P52)

`tests/interop/fixtures/synthetic_fhir_server.py` — three **real**
in-process HTTP servers (stdlib `http.server`, bound to `127.0.0.1` on a
random free port, run in a background thread — genuine HTTP, not a mocked
client):

- **Server A** (full-featured): SMART security extension advertised,
  DiagnosticReport/DocumentReference/Encounter present, `_lastUpdated`
  supported, Observation results paginated across 2 pages (exercises
  `link.relation=next` following).
- **Server B** (minimal): Observation/Encounter/MedicationRequest only —
  no SMART, no DiagnosticReport, no DocumentReference, no `_lastUpdated`,
  single-page results.
- **Server C** (local profile): one real LOINC-coded observation plus one
  using a made-up local coding system/display text that `resolve_analyte()`
  cannot resolve on its own.

`tests/test_interop_e2e.py` drives the full admin API against all three
through the **same, unmodified** `fhir_connector.py` — grep confirms there
is no `if server ==` / `if connector_type ==`-style branching anywhere in
that file. Server C's local code requires a declarative mapping override
(configuration), never a code change, to sync (P52).

## What Phase 1 deliberately does NOT include (next phases)

Per the phasing decision: SMART interactive (authorization-code/PKCE),
FHIR Bulk Data, IHE MHD/PIXm/PDQm, HL7v2 (+ Z-segment mapping), CDA
template detection, DICOMweb, generic REST declarative connector,
webhooks/subscriptions, background polling scheduler, mTLS network
implementation (architecture referenced in `auth_providers.py`/model
comments, not wired to a real TLS client), certificate-expiry monitoring,
connection wizard frontend UI, profile package registry, schema-drift
detection, data-quality dashboard UI. Each is a later phase in this same
doc, built on the same `ConnectorAuthProvider`/`ssrf.py`/`mapping.py`/
identity-linking foundation rather than duplicated per-connector.

## Answers to the acceptance questions (Phase 1 scope only)

1. Standards-compliant FHIR R4 server addable without code changes? **Yes**
   — proven against 3 materially different synthetic servers.
2. FHIR capability auto-discovery? **Yes** (`capability.py`).
3. SMART configuration auto-discovery? **Yes** (`smart_discovery.py`),
   recommendation only, never silent credential activation.
4. Adapts requests to advertised resources/search params? **Yes** — Server
   B (no DiagnosticReport/DocumentReference/SMART) never gets those
   requested; no per-server branching in the connector.
5. Local FHIR code mapped through configuration, not code? **Yes** (Server
   C test).
6/7. Connection profiles reusable / sanitized export-import without
   secrets? **Yes** (`reports.py`; `import_connection_profile` refuses a
   profile containing secret-shaped fields).
8/9. Partner tested without importing data / real shadow-sync without
   committing? **Yes** (`test`/`preview` routes).
10. Exact sync diff shown before activation? **Yes** (`preview`'s
   `would_create`/`would_update`/`duplicates_detected`).
11. Incremental FHIR sync where supported? Capability-detected
   (`supports_last_updated`); not yet wired into an actual incremental
   query strategy — **deferred to a later phase**.
12-15, 17-20. Bulk Data / MHD / PIXm / PDQm / HL7 / CDA / DICOMweb /
   generic-REST declarative mapping: **not in Phase 1** — see "deliberately
   NOT included" above.
16. Ambiguous identities quarantined? **Yes** — no link ⇒ no data,
   ever (`requires_review`/`quarantined_identity`).
22. Arbitrary/eval-based mappings prohibited? **Yes** — enumerated,
   schema-validated ops only.
23. Auth methods through one shared provider system? **Yes**
   (`ConnectorAuthProvider`).
24/25. mTLS/certificate references safely, expiry visible? **Architecture
   referenced, not implemented** — deferred.
26. Connection paused instantly? **Yes** (`/pause`, clears token cache).
27. Capability/schema drift detected? **Not yet** — deferred (Phase 1 has
   `capabilities_discovered_at` for a manual "re-discover" comparison, no
   automatic diff/alert yet).
28. Unknown terminology surfaced for review? **Yes**
   (`InteropTerminologyMapping`).
29. Partner IT checklist generator? **Not yet** — deferred; the partner
   readiness report (P21) is implemented, the pre-connection checklist
   generator (P58) is not.
30. Diagnostic bundle without PHI/secrets? **Yes** (`build_diagnostic_bundle`).
31/32. Three materially different synthetic FHIR servers through the same
   connector, with no per-server branching? **Yes** — verified.
33. Existing Bragi features unchanged with integrations disabled? **Yes**
   — `INTEROP_FHIR_ENABLED` defaults false; every new table is additive;
   no existing route/query/model was modified beyond adding nullable
   columns.
34. CNAS still completely excluded? **Yes** — `UNIMPLEMENTED_CONNECTION_TYPES`.
35. Configuration/onboarding exercise rather than new engineering, for a
   standard FHIR partner? **Yes**, within Phase 1's scope (FHIR only).

## Next phase (pick up here)

1. Wire `supports_last_updated` into an actual incremental `_lastUpdated`
   query strategy (currently detected but not used to narrow a re-sync).
2. Connection-wizard frontend (`Admin → Integrations → Add Connection`,
   spec P1/P55) — Phase 1 only shipped the backend API.
3. SMART Backend Services against a *real* (not synthetic) SMART sandbox,
   to verify the JWKS/client-assertion flow end to end against real SMART
   server validation, not just our own synthetic server's canned response.
4. Bulk Data (P23-P25), reusing the same `ConnectorAuthProvider` — do not
   duplicate secret logic.
5. IHE MHD (P26-P28) — read-only Find/Retrieve first; documents still go
   through the existing file-security/import boundary (P28), never a
   special "trusted because it's from an HIE" path.
6. PIXm/PDQm (P29-P30) — evidence for identity resolution, never
   automatic linking; same `ExternalPatientIdentityLink` table.
7. HL7 v2 configuration profile + Z-segment declarative mapping (P35-P37).
8. CDA template registry (P38).
9. DICOMweb (P39-P40).
10. Connection self-healing/token-refresh hardening (P46-P48) — the
    current token cache is process-local and per-connection; revisit once
    a background poller (P44) exists.
11. Schema-drift detection (P71) + data-quality dashboard (P72).
12. Partner-profile regression fixtures (P63) once a first real partner
    profile exists to freeze.
