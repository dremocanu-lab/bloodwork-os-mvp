"""Bragi interoperability — standards-based inbound connectivity.

See `BRAGI_INTEROP_PLAN.md` at the repo root for the full phased plan and
`app/main.py`'s `/admin/interop/*` routes for the API surface. Everything
here is additive and stays inert until INTEROP_FHIR_ENABLED=true and an
admin explicitly creates and activates a connection — no existing route,
query, or upload path changes because this package exists.

Phase 1 scope (this package): FHIR R4 only, inbound (Bragi reads from a
partner), read-only from the partner's point of view. SMART Backend
Services auth, capability discovery, declarative mapping overrides,
explicit (never fuzzy) patient identity linking, non-mutating test/
preview, and an idempotent commit-sync path. HL7v2, CDA, DICOMweb, IHE
MHD/PIXm/PDQm, Bulk Data, and outbound FHIR exposure are later phases —
see the plan doc's "Deferred" section.
"""

from app.services.interop.flags import INTEROP_FHIR_ENABLED

__all__ = ["INTEROP_FHIR_ENABLED"]
