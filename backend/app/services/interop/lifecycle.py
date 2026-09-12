"""Connection lifecycle state machine (BRAGI_INTEROP_PLAN.md Phase 3 §3.1).

`InteropConnection.status` was, through Phase 1, advanced ad hoc by
individual routes (each route just set the field it expected next). This
module makes the state machine explicit and enforces legal transitions
server-side — never a bare `enabled` boolean, and never a route silently
accepting an illegal jump (e.g. `draft` straight to `active`).

    DRAFT ──discover──> DISCOVERED ──test(pass)──> VALIDATED
                                                        │
                                                    preview
                                                        ▼
                                                     SHADOW
                                                        │
                                                     connect
                                                        ▼
                                                     ACTIVE ──pause──> PAUSED ──resume──> ACTIVE
                                                        │                  │
                                                     degrade            disable
                                                        ▼                  ▼
                                                    DEGRADED ──recover──> ACTIVE
                                                        │
                                                     disable
                                                        ▼
                                                    DISABLED

DISABLED is terminal in the sense that re-activating a disabled
connection must go through discovery/test/shadow again (not just
"resume") — a connection that was deliberately turned off warrants a
fresh compatibility check, not a silent resurrection.
"""

from __future__ import annotations

DRAFT = "draft"
DISCOVERED = "discovered"
VALIDATED = "validated"
SHADOW = "shadow"
ACTIVE = "active"
PAUSED = "paused"
DEGRADED = "degraded"
DISABLED = "disabled"

ALL_STATES = (DRAFT, DISCOVERED, VALIDATED, SHADOW, ACTIVE, PAUSED, DEGRADED, DISABLED)

# Legal (from_state -> {to_states}) transitions. Anything not listed here
# is illegal and LifecycleError-raising.
_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    DRAFT: {DISCOVERED, DISABLED},
    DISCOVERED: {VALIDATED, DISCOVERED, DISABLED},  # re-discovery is a legal no-op self-loop
    VALIDATED: {SHADOW, DISCOVERED, DISABLED},  # capabilities can be re-discovered from here too
    SHADOW: {ACTIVE, SHADOW, VALIDATED, DISABLED},  # re-preview is a legal self-loop
    ACTIVE: {PAUSED, DEGRADED, DISABLED, ACTIVE},  # a real sync run re-affirms ACTIVE (self-loop)
    PAUSED: {ACTIVE, DISABLED},
    DEGRADED: {ACTIVE, PAUSED, DISABLED},  # recovery (-> ACTIVE) requires a passing test, not a bare flag flip
    DISABLED: set(),  # terminal — reactivation is a NEW draft-like flow (P76), not a transition out of here
}


class LifecycleError(ValueError):
    """Raised when a caller attempts an illegal state transition."""


def validate_transition(current_status: str, next_status: str) -> None:
    """Raises LifecycleError if `current_status -> next_status` is not a
    legal transition. Never silently allows an unlisted jump."""
    if current_status not in _LEGAL_TRANSITIONS:
        raise LifecycleError(f"Unknown current status {current_status!r}")
    legal_targets = _LEGAL_TRANSITIONS[current_status]
    if next_status not in legal_targets:
        raise LifecycleError(
            f"Illegal transition: {current_status!r} -> {next_status!r}. "
            f"From {current_status!r}, only {sorted(legal_targets) or '(nothing — terminal state)'} "
            "are legal."
        )


def can_run_preview(status: str) -> bool:
    """Shadow sync (preview) is legal from VALIDATED (first preview) or
    SHADOW (repeat preview) — never from DRAFT/DISCOVERED (capabilities
    not yet validated) or DISABLED."""
    return status in (VALIDATED, SHADOW)


def can_discover(status: str) -> bool:
    """Re-discovery (P.6's "Re-discover capabilities") is legal from any
    non-terminal state — checking a partner's current capabilities is
    always safe and doesn't itself commit to anything. Only DISABLED
    blocks it (a disabled connection must be explicitly re-enabled via a
    fresh draft-like flow first — see DISABLED's docstring note)."""
    return status != DISABLED


def can_activate(status: str) -> bool:
    """Activation (the real commit-sync path) is legal only once a
    connection has been shadow-previewed at least once, or is already
    active/paused (a subsequent real sync run) — see P53's activation
    gate. DEGRADED is deliberately excluded: recovery from DEGRADED goes
    through a passing `/test` call first (see main.py's test route),
    never straight to a real commit sync while capability compatibility
    is still in question."""
    return status in (SHADOW, ACTIVE, PAUSED)
