"""Conservative patient identity matching.

Compares identity fields extracted from an uploaded document against the
patient record it was uploaded for, to catch "wrong patient" documents
before their clinical contents (or even their extracted identity fields)
are merged into someone else's record.

This is a rule-based, deliberately conservative comparator — no LLM is
used to decide a mismatch is okay (see BRAGI_REDUCTO_PLAN.md — that
requirement is a hard line). When in doubt, it prefers
`needs_confirmation` (a human decides) over `matched` (silently trust
it) or `mismatch` (silently discard it).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.synonyms import normalize_text

MATCHED = "matched"
NEEDS_CONFIRMATION = "needs_confirmation"
MISMATCH = "mismatch"
INSUFFICIENT_IDENTITY = "insufficient_identity"


@dataclass
class IdentityCheckResult:
    status: str
    reasons: list[str] = field(default_factory=list)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _name_tokens(value: str | None) -> set[str] | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    normalized = normalize_text(cleaned)
    tokens = {token for token in normalized.split() if len(token) > 1}
    return tokens or None


def _compare_names(patient_name: str | None, extracted_name: str | None) -> str | None:
    """Returns "match" | "different" | "partial" | None (nothing to compare)."""
    patient_tokens = _name_tokens(patient_name)
    extracted_tokens = _name_tokens(extracted_name)

    if not patient_tokens or not extracted_tokens:
        return None

    overlap = patient_tokens & extracted_tokens
    smaller = min(len(patient_tokens), len(extracted_tokens))

    if smaller == 0:
        return None

    ratio = len(overlap) / smaller

    if ratio >= 0.75:
        return "match"
    if ratio == 0:
        return "different"
    return "partial"


def _compare_exact(a: str | None, b: str | None) -> bool | None:
    """Returns True/False if both present, None if either is missing."""
    a_clean = _clean(a)
    b_clean = _clean(b)

    if a_clean is None or b_clean is None:
        return None

    return normalize_text(a_clean) == normalize_text(b_clean)


def check_patient_identity(
    *,
    patient_full_name: str | None,
    patient_dob: str | None,
    patient_cnp: str | None,
    patient_identifier: str | None,
    extracted_full_name: str | None,
    extracted_dob: str | None,
    extracted_cnp: str | None,
    extracted_patient_identifier: str | None,
) -> IdentityCheckResult:
    cnp_match = _compare_exact(patient_cnp, extracted_cnp)
    identifier_match = _compare_exact(patient_identifier, extracted_patient_identifier)
    dob_match = _compare_exact(patient_dob, extracted_dob)
    name_comparison = _compare_names(patient_full_name, extracted_full_name)

    nothing_extracted = (
        extracted_full_name is None
        and extracted_dob is None
        and extracted_cnp is None
        and extracted_patient_identifier is None
    )

    if nothing_extracted:
        return IdentityCheckResult(
            status=INSUFFICIENT_IDENTITY,
            reasons=["No identity fields were extracted from this document."],
        )

    # A strong identifier that is present on both sides and disagrees is
    # the clearest possible signal of a wrong-patient document — nothing
    # else can override this.
    if cnp_match is False:
        return IdentityCheckResult(status=MISMATCH, reasons=["CNP on the document does not match this patient's CNP."])

    if identifier_match is False:
        return IdentityCheckResult(
            status=MISMATCH,
            reasons=["Patient identifier on the document does not match this patient's identifier."],
        )

    if name_comparison == "different":
        # A clearly different name is only safe to treat as a mismatch if
        # nothing else confirms it's actually the same person.
        if dob_match is True or cnp_match is True or identifier_match is True:
            return IdentityCheckResult(
                status=NEEDS_CONFIRMATION,
                reasons=["Document name differs from patient record, but another identifier matches."],
            )
        return IdentityCheckResult(
            status=MISMATCH,
            reasons=["Document name does not match this patient's name, and no identifier confirms a match."],
        )

    if dob_match is False and name_comparison != "match":
        return IdentityCheckResult(
            status=NEEDS_CONFIRMATION,
            reasons=["Date of birth on the document does not match this patient's date of birth."],
        )

    strong_match = cnp_match is True or identifier_match is True or name_comparison == "match"

    if strong_match:
        return IdentityCheckResult(status=MATCHED, reasons=["Identity fields are consistent with this patient."])

    if name_comparison == "partial":
        return IdentityCheckResult(
            status=NEEDS_CONFIRMATION,
            reasons=["Document name partially matches this patient's name — please confirm."],
        )

    # Nothing contradicted, but nothing strongly confirmed either (e.g. only
    # a DOB match with no name/ID at all extracted). Conservative default.
    if dob_match is True:
        return IdentityCheckResult(
            status=NEEDS_CONFIRMATION,
            reasons=["Only date of birth matched; no name or ID was extracted to confirm identity."],
        )

    return IdentityCheckResult(
        status=INSUFFICIENT_IDENTITY,
        reasons=["Extracted identity fields were not sufficient to confirm or reject a match."],
    )
