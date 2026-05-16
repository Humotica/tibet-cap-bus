from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


@dataclass(slots=True)
class Cap:
    cap_id: str
    actor_id: str
    intent: str
    authority_ref: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=utc_now)
    parent_id: str | None = None
    trust_basis: str = "jis"
    route_class: str = "direct"
    executor_class: str = "default"
    lane_hint: str | None = None
    object_ref: str | None = None
    actor_aint: str | None = None
    actor_jis_pubkey: str | None = None
    attestation_layer: str = "jis"
    attestation_ref: str | None = None

    def __post_init__(self) -> None:
        if self.actor_aint is None and self.actor_id.endswith(".aint"):
            self.actor_aint = self.actor_id
        if self.attestation_ref is None and self.attestation_layer == "jis":
            self.attestation_ref = f"attest:{self.cap_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PhaseEvidence:
    phase: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LanePolicy:
    lane_class: str
    priority: int
    burst_limit: int
    preemptible: bool
    executor_pool: str
    lane_collision_policy: str
    coffee_lane_policy: str
    coffee_reason: str | None = None
    time_diff_seconds: float | None = None
    diff_threshold_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DistributedCap:
    cap: Cap
    causal_rank: int
    lane_id: str
    lane_policy: LanePolicy
    memory_slot: str
    alignment_group: str
    evidence: list[PhaseEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cap": self.cap.to_dict(),
            "causal_rank": self.causal_rank,
            "lane_id": self.lane_id,
            "lane_policy": self.lane_policy.to_dict(),
            "memory_slot": self.memory_slot,
            "alignment_group": self.alignment_group,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(slots=True)
class CapReceipt:
    receipt_id: str
    cap_id: str
    actor_id: str
    outcome: str
    continuation_mode: str
    created_at: str = field(default_factory=utc_now)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class UsageEvent:
    event_id: str
    observation_layer: str
    event_type: str
    cap_id: str
    actor_id: str
    intent: str
    timestamp: str = field(default_factory=utc_now)
    provider: str | None = None
    model: str | None = None
    actor_aint: str | None = None
    actor_jis_pubkey: str | None = None
    route_class: str | None = None
    lane_id: str | None = None
    executor_class: str | None = None
    trust_basis: str | None = None
    attestation_layer: str | None = None
    attestation_ref: str | None = None
    target_url: str | None = None
    transport: str | None = None
    surface: str | None = None
    lane_class: str | None = None
    lane_collision_policy: str | None = None
    coffee_lane_policy: str | None = None
    coffee_reason: str | None = None
    time_diff_seconds: float | None = None
    diff_threshold_seconds: int | None = None
    preemptible: bool | None = None
    lane_priority: int | None = None
    status: str | None = None
    latency_ms: float | None = None
    verified: bool | None = None
    continuation_mode: str | None = None
    emitter: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_governance_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "observation_layer": self.observation_layer,
            "timestamp": self.timestamp,
            "operation_id": self.cap_id,
            "thread_id": self.cap_id,
            "request_id": None,
            "token_id": None,
            "object_id": self.cap_id,
            "parent_id": self.details.get("parent_id"),
            "actor": {
                "identity": self.actor_id,
                "agent_id": self.actor_id.split(".")[0] if "." in self.actor_id else self.actor_id,
                "entity_type": _infer_entity_type(self.actor_id),
                "ains_domain": self.actor_aint,
            },
            "inference": {
                "provider": self.provider,
                "model": self.model,
                "execution_mode": "local" if self.provider in {"agent-runtime", "industrial-controller", "internal-service"} else "remote",
                "surface": self.surface or self.lane_id,
            },
            "route": {
                "route_class": self.route_class,
                "transport": self.transport or "mux-lane",
                "overlay_hops": [],
                "egress_host": None,
                "lane_class": self.lane_class,
                "lane_collision_policy": self.lane_collision_policy,
                "coffee_lane_policy": self.coffee_lane_policy,
                "coffee_reason": self.coffee_reason,
                "time_diff_seconds": self.time_diff_seconds,
                "diff_threshold_seconds": self.diff_threshold_seconds,
                "preemptible": self.preemptible,
                "lane_priority": self.lane_priority,
            },
            "trust": {
                "basis": self.trust_basis,
                "attested": self.attestation_layer == "jis",
                "attester": self.actor_id if self.attestation_layer == "jis" else None,
                "signature_ref": self.attestation_ref,
                "bearer": self.actor_id,
            },
            "continuity": {
                "disposition": self.event_type,
                "verify_valid": self.details.get("outcome") != "rejected",
                "causal_status": self.continuation_mode or "observed",
            },
            "evidence": {
                "source": self.observation_layer,
                "raw_ref": self.event_id,
                "emitter": self.emitter,
                "details": self.details,
            },
        }

    def to_gateway_event_dict(self) -> dict[str, Any]:
        token_id = self.attestation_ref or self.event_id
        return {
            "event_id": self.event_id,
            "observation_layer": "tibet-gateway",
            "timestamp": self.timestamp,
            "operation_id": self.cap_id,
            "thread_id": self.cap_id,
            "request_id": self.cap_id,
            "token_id": token_id,
            "envelope_id": self.cap_id,
            "parent_id": self.details.get("parent_id"),
            "agent_id": self.actor_aint or self.actor_id,
            "actor_aint": self.actor_aint,
            "actor_jis_pubkey": self.actor_jis_pubkey,
            "intent": self.intent,
            "method": self.details.get("method", "POST"),
            "target_url": self.target_url,
            "provider": self.provider,
            "model": self.model,
            "payload": self.details.get("payload", {"intent": self.intent}),
            "route_class": self.route_class,
            "transport": self.transport or "mux-lane",
            "surface": self.surface or self.lane_id,
            "lane_class": self.lane_class,
            "lane_collision_policy": self.lane_collision_policy,
            "coffee_lane_policy": self.coffee_lane_policy,
            "coffee_reason": self.coffee_reason,
            "time_diff_seconds": self.time_diff_seconds,
            "diff_threshold_seconds": self.diff_threshold_seconds,
            "preemptible": self.preemptible,
            "lane_priority": self.lane_priority,
            "gateway_actor": "jis:tibet-cap-bus",
            "status": self.status or self.event_type,
            "verified": bool(self.verified if self.verified is not None else self.attestation_layer == "jis"),
            "latency_ms": self.latency_ms,
            "content_hash": self.details.get("content_hash"),
            "attestation_layer": self.attestation_layer,
            "attestation_ref": self.attestation_ref,
            "_emitter": self.emitter or "cap-bus-runtime",
        }


@dataclass(slots=True)
class ExecutionResult:
    distributed: DistributedCap
    receipt: CapReceipt
    usage_events: list[UsageEvent] = field(default_factory=list)
    spawned_caps: list[Cap] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "distributed": self.distributed.to_dict(),
            "receipt": self.receipt.to_dict(),
            "usage_events": [item.to_dict() for item in self.usage_events],
            "spawned_caps": [item.to_dict() for item in self.spawned_caps],
        }


def _infer_entity_type(actor_id: str) -> str:
    lowered = actor_id.lower()
    if lowered.endswith(".aint"):
        return "ai"
    if "gateway" in lowered or "service" in lowered:
        return "service"
    if "factory" in lowered or "controller" in lowered:
        return "device"
    return "agent"
