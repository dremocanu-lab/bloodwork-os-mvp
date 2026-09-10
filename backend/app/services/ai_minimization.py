"""Reusable data-minimization boundary for every call to an external AI
provider (OpenAI today; any future provider, including "Ask Bragi").

Why this file exists
---------------------
`docs/ai/AI_GOVERNANCE.md` and `BRAGI_SECURITY_GDPR_PLAN.md` §21 require a
permanent boundary between "what this app knows about a patient" and "what
an external model actually needs for one specific task" — even before
Ask Bragi (an AI chat feature) exists. This module is that boundary: one
place to strip/allowlist identifiers, instead of ad hoc string edits
scattered across call sites, so every future provider call goes through
the same discipline:

    user
      -> server-side authorization (existing require_role()/can_access_patient())
      -> minimum-necessary retrieval (caller decides what data the task needs)
      -> identity stripping/minimization (this module)
      -> provider call (OpenAI, or any future one)

Audit of the three existing OpenAI call sites this round (`ai_extract.py`,
`services/openai_discharge_service.py`, `services/discharge_summary_pipeline.py`):
each sends ONLY the raw uploaded document (page image / native PDF bytes)
plus a fixed extraction-schema prompt. None of them separately constructs
or injects a patient/user context object (no email, phone, or address is
ever attached — the `Patient` model doesn't even have those columns; only
`User.email` exists, and it is never read by any of these three call
sites). The patient's name/CNP/DOB that these calls return are the
INTENDED OUTPUT of an identity-extraction task (matching an uploaded
document to the right patient — see `services/patient_identity.py`), not
incidental leakage, so this module does not (and must not) try to strip
those out of the document image itself — that would just break the
extraction it exists to perform. What this module DOES apply to: any
future code path that assembles a text/JSON context ABOUT a patient
(beyond the document's own bytes) before sending it to a provider — which
is exactly the shape a future Ask Bragi retrieval step will have, and
exactly the shape defensive-in-depth calls to this module should guard
even for existing structured data if it's ever reused for a new prompt.
"""

from __future__ import annotations

import re

# Direct/near-direct identifiers that must never ride along in a prompt's
# free-text context unless the task is EXPLICITLY the extraction of that
# exact field from a document image (see module docstring).
_CNP_RE = re.compile(r"\b\d{13}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Romanian mobile/landline-shaped sequences: an optional +40/0040/0 prefix
# then 9 digits, allowing common separators. Deliberately conservative
# (fewer false positives) over exhaustive telecom-format coverage.
_PHONE_RE = re.compile(r"\b(?:\+?40|0)[\s.-]?\d{2,3}(?:[\s.-]?\d{3}){2}\b")

# Patient-record fields that are identity/contact metadata, not clinical
# content — the default allowlist for any minimized patient context is
# everything EXCEPT these, unless a caller explicitly opts a field back in
# via `keep_fields`.
DEFAULT_STRIPPED_FIELDS = frozenset(
    {
        "cnp",
        "email",
        "phone",
        "phone_number",
        "address",
        "patient_identifier",
        "linked_user_id",
        "user_id",
        "care_partner_code",
    }
)


def redact_direct_identifiers(text: str | None) -> str:
    """Strip CNP-shaped numbers, email addresses, and phone numbers out of
    a free-text string before it can be combined into a provider prompt.

    Deliberately NOT applied to raw document OCR/vision extraction input —
    those calls need to actually read the identifiers off the page (that
    is the task). This is for any text assembled FROM ALREADY-STRUCTURED
    data (e.g. a future Ask Bragi context paragraph built from multiple
    records), where an identifier being present would be incidental, not
    the point of the call.
    """
    if not text:
        return text or ""
    redacted = _CNP_RE.sub("[REDACTED-ID]", text)
    redacted = _EMAIL_RE.sub("[REDACTED-EMAIL]", redacted)
    redacted = _PHONE_RE.sub("[REDACTED-PHONE]", redacted)
    return redacted


def minimize_patient_context(
    patient: dict,
    keep_fields: set[str] | None = None,
) -> dict:
    """Return a copy of a patient-like dict with identity/contact fields
    removed by default. `keep_fields` is an explicit, per-call opt-in
    allowlist for the rare case a field is genuinely required (e.g. a
    task that legitimately needs CNP re-attached) — callers must name the
    field, minimization never happens by silently trusting whatever keys
    happen to be present on the dict.
    """
    keep_fields = keep_fields or set()
    return {
        key: value
        for key, value in patient.items()
        if key not in DEFAULT_STRIPPED_FIELDS or key in keep_fields
    }


def minimize_patient_record_for_provider(
    patient: dict,
    *,
    purpose_requires_cnp: bool = False,
) -> dict:
    """Convenience wrapper for the common case: a task needs clinical/
    demographic context about a patient but not their identifiers. Only
    `purpose_requires_cnp=True` (a real, explicit, per-call decision —
    e.g. a document identity-match confirmation step) re-admits CNP.
    """
    keep = {"cnp"} if purpose_requires_cnp else set()
    return minimize_patient_context(patient, keep_fields=keep)
