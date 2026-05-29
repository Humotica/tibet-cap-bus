"""Tests for verdict_transitions.py — posture-transition gateway-event.v1 builder."""

from __future__ import annotations

import pytest

from tibet_cap_bus.event_contract import validate_gateway_event_record
from tibet_cap_bus.verdict_transitions import (
    POSTURE_TRANSITION_INTENT,
    diff_switches,
    make_posture_transition_event,
)


def _kwargs(**overrides):
    base = {
        "verdict_id": "verdict_demo_001",
        "emitter": "jis:humotica:snaft",
        "current_posture": "quarantine_external_ai",
        "current_runtime_mode": "python_fallback",
        "previous_posture": "normal_zero_trust",
        "previous_runtime_mode": "kernel_online",
        "switches_changed": ["deny_external_ai_inbound", "deny_remote_tool_invocation"],
        "reason": "Bolle airlock runtime unavailable; Python fallback degraded.",
        "timestamp": "2026-05-29T14:10:00+00:00",
        "event_id": "posture_test_001",
    }
    base.update(overrides)
    return base


def test_builder_produces_valid_gateway_event():
    event = make_posture_transition_event(**_kwargs())
    errors = validate_gateway_event_record(event)
    assert errors == [], f"validation errors: {errors}"


def test_intent_is_posture_transition():
    event = make_posture_transition_event(**_kwargs())
    assert event["intent"] == POSTURE_TRANSITION_INTENT


def test_payload_has_posture_diff():
    event = make_posture_transition_event(**_kwargs())
    p = event["payload"]
    assert p["kind"] == "posture_transition.v1"
    assert p["previous"]["posture"] == "normal_zero_trust"
    assert p["current"]["posture"] == "quarantine_external_ai"
    assert p["previous"]["runtime_mode"] == "kernel_online"
    assert p["current"]["runtime_mode"] == "python_fallback"
    assert "deny_external_ai_inbound" in p["switches_changed"]
    assert p["cold_start"] is False


def test_cold_start_flag_when_no_previous_posture():
    event = make_posture_transition_event(
        **_kwargs(previous_posture=None, previous_runtime_mode=None)
    )
    assert event["payload"]["cold_start"] is True
    assert event["payload"]["previous"]["posture"] is None
    # Still passes gateway-event validation
    assert validate_gateway_event_record(event) == []


def test_operation_id_defaults_to_verdict_id():
    event = make_posture_transition_event(**_kwargs(operation_id=None))
    assert event["operation_id"] == "verdict_demo_001"


def test_explicit_operation_id_honored():
    event = make_posture_transition_event(**_kwargs(operation_id="op-42"))
    assert event["operation_id"] == "op-42"


def test_event_id_unique_when_unset():
    a = make_posture_transition_event(**_kwargs(event_id=None))
    b = make_posture_transition_event(**_kwargs(event_id=None))
    assert a["event_id"] != b["event_id"]
    assert a["event_id"].startswith("posture_")


def test_surface_carries_current_posture():
    event = make_posture_transition_event(**_kwargs(current_posture="hard_quarantine"))
    assert "hard_quarantine" in event["surface"]


def test_agent_id_is_emitter():
    event = make_posture_transition_event(**_kwargs(emitter="jis:humotica:test"))
    assert event["agent_id"] == "jis:humotica:test"
    assert event["actor_aint"] == "jis:humotica:test"


def test_switches_changed_empty_when_unset():
    event = make_posture_transition_event(**_kwargs(switches_changed=None))
    assert event["payload"]["switches_changed"] == []


def test_diff_switches_empty_for_identical():
    a = {"x": True, "y": False, "z": True}
    b = {"x": True, "y": False, "z": True}
    assert diff_switches(a, b, ["x", "y", "z"]) == []


def test_diff_switches_returns_flipped():
    a = {"deny_external_ai_inbound": False, "isolate_session": False}
    b = {"deny_external_ai_inbound": True, "isolate_session": False}
    changed = diff_switches(a, b, ["deny_external_ai_inbound", "isolate_session"])
    assert changed == ["deny_external_ai_inbound"]


def test_diff_switches_only_inspects_given_keys():
    a = {"x": True, "y": False, "z": True}
    b = {"x": False, "y": False, "z": True}
    assert diff_switches(a, b, ["y", "z"]) == []  # x flipped but not asked


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
