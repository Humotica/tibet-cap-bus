"""
airlock_runtime_verdict.v1 — runtime posture contract.

Emitted by `tibet-pol`, consumed by `snaft` (rule-bundle activation), and used by
`tibet-airlock` (Python operator) to refuse external execution when the bolle
runtime is unavailable. Every transition is logged as a `gateway-event.v1` on
cap-bus.

Core invariant (Jasper, 2026-05-29):
    "Als de bolle airlock-runtime wegvalt, mag extern AI-verkeer niet meer binnen."

Reference spec: sandbox/ai/codex/airlock-runtime-policy-immune-switch-2026-05-29.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VERDICT_KIND = "airlock_runtime_verdict.v1"

REQUIRED_VERDICT_FIELDS = (
    "kind",
    "verdict_id",
    "timestamp",
    "emitter",
    "runtime_mode",
    "rust_airlock",
    "trust_kernel",
    "python_fallback",
    "external_ai_inbound",
    "execution_policy",
    "snaft_posture",
    "reason",
)

ALLOWED_RUNTIME_MODES = {
    "embedded_online",          # trust-kerneld embeds airlock-kernel — best
    "kernel_online",            # standalone tibet-airlock-kernel — also good
    "python_fallback",          # Rust bolle offline — local/operator rescue only
    "offline",                  # nothing online — hard fail-closed
}

ALLOWED_RUST_AIRLOCK_STATES = {
    "embedded",                 # provided via trust-kerneld --features airlock
    "online",                   # standalone tibet-airlock-kernel running
    "offline",                  # not running
    "unknown",                  # detector did not resolve
}

ALLOWED_TRUST_KERNEL_STATES = {
    "online_with_airlock",      # trust-kerneld + embedded airlock
    "online_without_airlock",   # trust-kerneld without airlock feature
    "online",                   # generic "up" when sub-state not resolved
    "offline",
    "unknown",
}

ALLOWED_PYTHON_FALLBACK_STATES = {
    "disabled",                 # not in use (hardened mode active)
    "enabled",                  # in use (degraded mode)
    "available",                # could be enabled but currently not active
    "unavailable",              # not installed / not reachable
    "denied_unless_soft_bootstrap_dev",  # offline-mode soft-open allowance
}

ALLOWED_EXTERNAL_AI_INBOUND = {
    "allow_if_identity_bound",  # hardened mode: TIBET/JIS-bound traffic allowed
    "deny",                     # degraded/offline: no external AI inbound
}

ALLOWED_EXECUTION_POLICIES = {
    "allow_through_trust_kerneld",          # embedded_online preferred path
    "allow_through_airlock",                # kernel_online via airlock-kernel
    "local_or_operator_approved_only",      # python_fallback path
    "deny",                                 # offline / hard quarantine
}

ALLOWED_SNAFT_POSTURES = {
    "normal_zero_trust",        # hardened modes: standard rules
    "quarantine_external_ai",   # python_fallback: deny external AI + remote tool
    "hard_quarantine",          # offline: drop external, isolate, evidence only
}

# Posture coherence: per runtime_mode the *expected* values for downstream
# fields. tibet-pol may emit transitional verdicts, so this is a warn, not
# block; snaft uses it to detect misconfigured emitters.
_MODE_EXPECTATIONS: dict[str, dict[str, set[str]]] = {
    "embedded_online": {
        "trust_kernel": {"online_with_airlock"},
        "python_fallback": {"disabled"},
        "external_ai_inbound": {"allow_if_identity_bound"},
        "execution_policy": {"allow_through_trust_kerneld"},
        "snaft_posture": {"normal_zero_trust"},
    },
    "kernel_online": {
        "rust_airlock": {"online"},
        "python_fallback": {"disabled"},
        "external_ai_inbound": {"allow_if_identity_bound"},
        "execution_policy": {"allow_through_airlock"},
        "snaft_posture": {"normal_zero_trust"},
    },
    "python_fallback": {
        "rust_airlock": {"offline"},
        "python_fallback": {"enabled", "available"},
        "external_ai_inbound": {"deny"},
        "execution_policy": {"local_or_operator_approved_only"},
        "snaft_posture": {"quarantine_external_ai"},
    },
    "offline": {
        "rust_airlock": {"offline"},
        "trust_kernel": {"offline"},
        "external_ai_inbound": {"deny"},
        "execution_policy": {"deny"},
        "snaft_posture": {"hard_quarantine"},
    },
}


def validate_verdict_record(record: dict[str, Any]) -> list[str]:
    """Validate a single airlock_runtime_verdict.v1 record. Returns errors list (empty = ok)."""
    errors: list[str] = []

    for field in REQUIRED_VERDICT_FIELDS:
        if field not in record:
            errors.append(f"missing required field: {field}")
        elif record[field] in (None, ""):
            errors.append(f"required field is empty: {field}")

    if errors:
        return errors

    if record["kind"] != VERDICT_KIND:
        errors.append(f"kind must be '{VERDICT_KIND}', got: {record['kind']!r}")

    enum_checks = (
        ("runtime_mode", ALLOWED_RUNTIME_MODES),
        ("rust_airlock", ALLOWED_RUST_AIRLOCK_STATES),
        ("trust_kernel", ALLOWED_TRUST_KERNEL_STATES),
        ("python_fallback", ALLOWED_PYTHON_FALLBACK_STATES),
        ("external_ai_inbound", ALLOWED_EXTERNAL_AI_INBOUND),
        ("execution_policy", ALLOWED_EXECUTION_POLICIES),
        ("snaft_posture", ALLOWED_SNAFT_POSTURES),
    )
    for field, allowed in enum_checks:
        if record[field] not in allowed:
            errors.append(
                f"invalid {field}: {record[field]!r} "
                f"(expected one of {sorted(allowed)})"
            )

    if not isinstance(record["reason"], str):
        errors.append("reason must be a string")

    if not isinstance(record["verdict_id"], str):
        errors.append("verdict_id must be a string")

    if record.get("emitter") and not isinstance(record["emitter"], str):
        errors.append("emitter must be a string")

    # Optional fields with type checks
    if "previous_runtime_mode" in record:
        prev = record["previous_runtime_mode"]
        if prev is not None and prev not in ALLOWED_RUNTIME_MODES:
            errors.append(
                f"invalid previous_runtime_mode: {prev!r} "
                f"(expected one of {sorted(ALLOWED_RUNTIME_MODES)} or null)"
            )

    if "expires_at" in record and record["expires_at"] is not None:
        if not isinstance(record["expires_at"], str):
            errors.append("expires_at must be ISO8601 string when present")

    if "attestation_ref" in record and record["attestation_ref"] is not None:
        if not isinstance(record["attestation_ref"], str):
            errors.append("attestation_ref must be a string when present")

    return errors


def check_mode_coherence(record: dict[str, Any]) -> list[str]:
    """Soft-check: warn if downstream fields don't match runtime_mode expectations.

    Returns warning strings. snaft uses this to detect misconfigured emitters
    without rejecting transitional verdicts.
    """
    warnings: list[str] = []
    mode = record.get("runtime_mode")
    if mode not in _MODE_EXPECTATIONS:
        return warnings
    for field, expected in _MODE_EXPECTATIONS[mode].items():
        value = record.get(field)
        if value not in expected:
            warnings.append(
                f"{field}={value!r} is unusual for runtime_mode={mode!r} "
                f"(expected one of {sorted(expected)})"
            )
    return warnings


def validate_verdict_records(records: list[dict[str, Any]]) -> list[str]:
    """Validate a list of verdict records. Returns indexed error list."""
    errors: list[str] = []
    for index, record in enumerate(records):
        record_errors = validate_verdict_record(record)
        for error in record_errors:
            errors.append(f"record[{index}]: {error}")
    return errors


def load_verdict_records(path: str | Path) -> list[dict[str, Any]]:
    """Load verdict records from JSON (array or {verdicts:[...]}) or JSONL."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if file_path.suffix == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "verdicts" in data and isinstance(data["verdicts"], list):
            return data["verdicts"]
        raise ValueError("JSON input must be a list of records or an object with 'verdicts'")

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records
