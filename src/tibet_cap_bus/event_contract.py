from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_GATEWAY_FIELDS = (
    "event_id",
    "observation_layer",
    "timestamp",
    "operation_id",
    "agent_id",
    "intent",
    "provider",
    "model",
    "route_class",
    "surface",
    "transport",
    "status",
    "latency_ms",
    "lane_class",
    "lane_collision_policy",
    "coffee_lane_policy",
    "attestation_layer",
    "_emitter",
)

OPTIONAL_NUMERIC_FIELDS = (
    "latency_ms",
    "lane_priority",
    "time_diff_seconds",
    "diff_threshold_seconds",
)

ALLOWED_OBSERVATION_LAYERS = {"tibet-gateway"}
ALLOWED_ROUTE_CLASSES = {"direct", "relay", "triage", "local", "cluster"}
ALLOWED_LANE_COLLISION_POLICIES = {
    "graceful_yield",
    "assert_root",
    "override_all",
    "queue",
    "reject",
}
ALLOWED_COFFEE_LANE_POLICIES = {
    "sip_anyway",
    "polite_avoid",
    "hard_avoid",
    "rebuild",
    "offline_fallback",
    "freeze_resume",
    "fork_on_hop_off",
}
ALLOWED_ATTESTATION_LAYERS = {"jis", "self-signed", "none"}


def validate_gateway_event_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for field in REQUIRED_GATEWAY_FIELDS:
        if field not in record:
            errors.append(f"missing required field: {field}")
        elif record[field] in (None, ""):
            errors.append(f"required field is empty: {field}")

    if errors:
        return errors

    if record["observation_layer"] not in ALLOWED_OBSERVATION_LAYERS:
        errors.append(
            f"invalid observation_layer: {record['observation_layer']} "
            f"(expected one of {sorted(ALLOWED_OBSERVATION_LAYERS)})"
        )

    if record["route_class"] not in ALLOWED_ROUTE_CLASSES:
        errors.append(
            f"invalid route_class: {record['route_class']} "
            f"(expected one of {sorted(ALLOWED_ROUTE_CLASSES)})"
        )

    if record["lane_collision_policy"] not in ALLOWED_LANE_COLLISION_POLICIES:
        errors.append(
            f"invalid lane_collision_policy: {record['lane_collision_policy']} "
            f"(expected one of {sorted(ALLOWED_LANE_COLLISION_POLICIES)})"
        )

    if record["coffee_lane_policy"] not in ALLOWED_COFFEE_LANE_POLICIES:
        errors.append(
            f"invalid coffee_lane_policy: {record['coffee_lane_policy']} "
            f"(expected one of {sorted(ALLOWED_COFFEE_LANE_POLICIES)})"
        )

    if record["attestation_layer"] not in ALLOWED_ATTESTATION_LAYERS:
        errors.append(
            f"invalid attestation_layer: {record['attestation_layer']} "
            f"(expected one of {sorted(ALLOWED_ATTESTATION_LAYERS)})"
        )

    for field in OPTIONAL_NUMERIC_FIELDS:
        value = record.get(field)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            errors.append(f"{field} must be numeric when present")

    if "verified" in record and not isinstance(record.get("verified"), bool):
        errors.append("verified must be boolean when present")

    if record.get("agent_id") and not isinstance(record["agent_id"], str):
        errors.append("agent_id must be a string")

    if record.get("actor_aint") is not None and not isinstance(record["actor_aint"], str):
        errors.append("actor_aint must be a string when present")

    if record.get("payload") is not None and not isinstance(record["payload"], dict):
        errors.append("payload must be an object when present")

    return errors


def validate_gateway_event_records(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for index, record in enumerate(records):
        record_errors = validate_gateway_event_record(record)
        for error in record_errors:
            errors.append(f"record[{index}]: {error}")
    return errors


def load_event_records(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if file_path.suffix == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "gateway_events" in data and isinstance(data["gateway_events"], list):
            return data["gateway_events"]
        raise ValueError("JSON input must be a list of records or an object with gateway_events")

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records
