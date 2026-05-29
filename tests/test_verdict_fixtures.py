"""Tests for airlock_runtime_verdict.v1 contract + 4-modes fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from tibet_cap_bus.verdict_contract import (
    ALLOWED_RUNTIME_MODES,
    VERDICT_KIND,
    check_mode_coherence,
    load_verdict_records,
    validate_verdict_record,
    validate_verdict_records,
)

FIXTURE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "airlock-runtime-verdict.v1.example.json"
)


def test_fixture_loads():
    records = load_verdict_records(FIXTURE_PATH)
    assert len(records) == 4, "expected one verdict per runtime mode"


def test_fixture_covers_all_modes():
    records = load_verdict_records(FIXTURE_PATH)
    modes = {r["runtime_mode"] for r in records}
    assert modes == ALLOWED_RUNTIME_MODES, (
        f"fixtures must cover all runtime modes; missing: "
        f"{ALLOWED_RUNTIME_MODES - modes}"
    )


def test_all_fixtures_validate():
    records = load_verdict_records(FIXTURE_PATH)
    errors = validate_verdict_records(records)
    assert errors == [], f"unexpected validation errors: {errors}"


def test_all_fixtures_coherent():
    """Soft-check: each fixture's downstream fields should match its runtime_mode."""
    records = load_verdict_records(FIXTURE_PATH)
    for i, record in enumerate(records):
        warnings = check_mode_coherence(record)
        assert warnings == [], (
            f"fixture[{i}] runtime_mode={record['runtime_mode']!r} has "
            f"coherence warnings: {warnings}"
        )


def test_kind_must_be_verdict_v1():
    bad = {
        "kind": "gateway-event.v1",
        "verdict_id": "v1",
        "timestamp": "2026-05-29T14:00:00+00:00",
        "emitter": "tibet-pol",
        "runtime_mode": "embedded_online",
        "rust_airlock": "embedded",
        "trust_kernel": "online_with_airlock",
        "python_fallback": "disabled",
        "external_ai_inbound": "allow_if_identity_bound",
        "execution_policy": "allow_through_trust_kerneld",
        "snaft_posture": "normal_zero_trust",
        "reason": "x",
    }
    errors = validate_verdict_record(bad)
    assert any("kind must be" in e for e in errors)


def test_missing_field_caught():
    bad = {
        "kind": VERDICT_KIND,
        "verdict_id": "v1",
        "timestamp": "2026-05-29T14:00:00+00:00",
        # missing emitter onwards
    }
    errors = validate_verdict_record(bad)
    assert any("missing required field: emitter" in e for e in errors)


def test_invalid_enum_caught():
    bad = {
        "kind": VERDICT_KIND,
        "verdict_id": "v1",
        "timestamp": "2026-05-29T14:00:00+00:00",
        "emitter": "tibet-pol",
        "runtime_mode": "vibes_only",  # not in enum
        "rust_airlock": "embedded",
        "trust_kernel": "online_with_airlock",
        "python_fallback": "disabled",
        "external_ai_inbound": "allow_if_identity_bound",
        "execution_policy": "allow_through_trust_kerneld",
        "snaft_posture": "normal_zero_trust",
        "reason": "x",
    }
    errors = validate_verdict_record(bad)
    assert any("invalid runtime_mode" in e for e in errors)


def test_coherence_warns_on_mismatch():
    """python_fallback mode with allow_if_identity_bound should warn."""
    mismatched = {
        "kind": VERDICT_KIND,
        "verdict_id": "v1",
        "timestamp": "2026-05-29T14:00:00+00:00",
        "emitter": "tibet-pol",
        "runtime_mode": "python_fallback",
        "rust_airlock": "offline",
        "trust_kernel": "online_without_airlock",
        "python_fallback": "enabled",
        # The invariant violation:
        "external_ai_inbound": "allow_if_identity_bound",
        "execution_policy": "local_or_operator_approved_only",
        "snaft_posture": "quarantine_external_ai",
        "reason": "test invariant violation",
    }
    # Strict validation passes (each field is in its allowed enum)
    assert validate_verdict_record(mismatched) == []
    # But coherence warns
    warnings = check_mode_coherence(mismatched)
    assert any("external_ai_inbound" in w for w in warnings)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
