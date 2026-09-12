"""Connection lifecycle state-machine tests (BRAGI_INTEROP_PLAN.md Phase 3
§3.1). No DB, no network — pure state-transition logic."""

import pytest

from app.services.interop.lifecycle import (
    ACTIVE,
    DEGRADED,
    DISABLED,
    DISCOVERED,
    DRAFT,
    PAUSED,
    SHADOW,
    VALIDATED,
    LifecycleError,
    can_activate,
    can_discover,
    can_run_preview,
    validate_transition,
)


@pytest.mark.parametrize(
    "current,next_",
    [
        (DRAFT, DISCOVERED),
        (DISCOVERED, VALIDATED),
        (VALIDATED, SHADOW),
        (SHADOW, ACTIVE),
        (ACTIVE, PAUSED),
        (ACTIVE, DEGRADED),
        (PAUSED, ACTIVE),
        (DEGRADED, ACTIVE),
        (DEGRADED, PAUSED),
        (ACTIVE, DISABLED),
        (PAUSED, DISABLED),
        (DEGRADED, DISABLED),
        (DRAFT, DISABLED),
    ],
)
def test_legal_transitions_allowed(current, next_):
    validate_transition(current, next_)  # must not raise


@pytest.mark.parametrize(
    "current,next_",
    [
        (DRAFT, ACTIVE),  # can't skip straight to active
        (DRAFT, SHADOW),
        (DISCOVERED, ACTIVE),
        (VALIDATED, ACTIVE),  # must shadow-preview first
        (PAUSED, SHADOW),  # paused can only resume to active or disable
        (DEGRADED, SHADOW),
        (DISABLED, ACTIVE),  # terminal — no way back except a fresh flow
        (DISABLED, DRAFT),
        (ACTIVE, DRAFT),  # never regresses to draft
    ],
)
def test_illegal_transitions_rejected(current, next_):
    with pytest.raises(LifecycleError):
        validate_transition(current, next_)


def test_unknown_current_status_rejected():
    with pytest.raises(LifecycleError):
        validate_transition("not-a-real-status", ACTIVE)


def test_can_discover_blocked_only_for_disabled():
    for status in (DRAFT, DISCOVERED, VALIDATED, SHADOW, ACTIVE, PAUSED, DEGRADED):
        assert can_discover(status) is True
    assert can_discover(DISABLED) is False


def test_can_run_preview_only_validated_or_shadow():
    assert can_run_preview(VALIDATED) is True
    assert can_run_preview(SHADOW) is True
    for status in (DRAFT, DISCOVERED, ACTIVE, PAUSED, DEGRADED, DISABLED):
        assert can_run_preview(status) is False


def test_can_activate_excludes_degraded():
    assert can_activate(SHADOW) is True
    assert can_activate(ACTIVE) is True
    assert can_activate(PAUSED) is True
    # DEGRADED must recover via a passing /test call first, never a
    # direct real commit sync while compatibility is in question.
    assert can_activate(DEGRADED) is False
    assert can_activate(DRAFT) is False
