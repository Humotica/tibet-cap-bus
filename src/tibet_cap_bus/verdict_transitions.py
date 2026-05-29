"""
Posture-transition event builder.

When a snaft consumer observes a new PostureDecision that differs from the
previous one (via `snaft.posture.is_transition`), the change must land on
cap-bus as a `gateway-event.v1` record. This module builds that record.

Dependency discipline: this builder takes *primitive* fields only (strings,
lists). It does not import from snaft. snaft.posture is the package that holds
the glue function and calls this builder.

Reference: sandbox/ai/codex/airlock-runtime-policy-immune-switch-2026-05-29.md
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from .event_contract import validate_gateway_event_record


POSTURE_TRANSITION_INTENT = "posture.transition.v1"


def make_posture_transition_event(
    *,
    verdict_id: str,
    emitter: str,
    current_posture: str,
    current_runtime_mode: str,
    previous_posture: Optional[str] = None,
    previous_runtime_mode: Optional[str] = None,
    switches_changed: Optional[list[str]] = None,
    reason: Optional[str] = None,
    timestamp: Optional[str] = None,
    event_id: Optional[str] = None,
    operation_id: Optional[str] = None,
) -> dict:
    """Build a `gateway-event.v1`-shaped record for a posture transition.

    Validates against `validate_gateway_event_record` before returning, so a
    successful call guarantees the event will pass cap-bus ingestion.

    Args:
        verdict_id: id of the verdict.v1 record that triggered this transition.
        emitter: jis: URI of the snaft instance (or other consumer) that
            observed the transition. Used as agent_id.
        current_posture: snaft_posture string of the new PostureDecision.
        current_runtime_mode: runtime_mode of the new verdict.
        previous_posture: snaft_posture of the prior PostureDecision, or None
            if this is the first verdict (cold-start).
        previous_runtime_mode: runtime_mode of the prior verdict, or None.
        switches_changed: optional list of switch-names that flipped value
            across the transition. Helps auditors understand impact at a glance.
        reason: optional human-readable reason (typically the verdict's reason).
        timestamp: optional ISO8601 timestamp (defaults to now UTC).
        event_id: optional explicit event_id (defaults to posture_<uuid>).
        operation_id: optional operation_id; defaults to verdict_id (links the
            chain end-to-end).

    Returns:
        A dict matching `gateway-event.v1` REQUIRED_GATEWAY_FIELDS.

    Raises:
        ValueError: if the constructed record fails contract validation.
    """
    record = {
        # REQUIRED_GATEWAY_FIELDS
        "event_id": event_id or f"posture_{uuid.uuid4().hex[:16]}",
        "observation_layer": "tibet-gateway",
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "operation_id": operation_id or verdict_id,
        "agent_id": emitter,
        "intent": POSTURE_TRANSITION_INTENT,
        "provider": "snaft-posture",
        "model": "airlock_runtime_verdict.v1",
        "route_class": "local",
        "surface": f"posture-transition:{current_posture}",
        "transport": "memory",
        "status": "posture-transitioned",
        "latency_ms": 0,
        "lane_class": "system-event",
        "lane_collision_policy": "graceful_yield",
        "coffee_lane_policy": "sip_anyway",
        "attestation_layer": "jis",
        "_emitter": "snaft-posture-transition",
        # Useful optional fields
        "actor_aint": emitter,
        "verified": True,
        "payload": {
            "kind": "posture_transition.v1",
            "verdict_id": verdict_id,
            "previous": {
                "posture": previous_posture,
                "runtime_mode": previous_runtime_mode,
            },
            "current": {
                "posture": current_posture,
                "runtime_mode": current_runtime_mode,
            },
            "switches_changed": list(switches_changed or ()),
            "reason": reason,
            "cold_start": previous_posture is None,
        },
    }

    errors = validate_gateway_event_record(record)
    if errors:
        raise ValueError(
            f"posture-transition event failed gateway-event.v1 validation: {errors}"
        )
    return record


def diff_switches(previous: dict, current: dict, switch_keys: list[str]) -> list[str]:
    """Return the subset of switch_keys whose bool value differs between two dicts.

    Helper for callers that want to populate the `switches_changed` field
    cleanly. Pass two dicts of switch_name -> bool (e.g. asdict of a
    PostureDecision filtered to its boolean fields).
    """
    changed: list[str] = []
    for key in switch_keys:
        if previous.get(key) != current.get(key):
            changed.append(key)
    return changed
