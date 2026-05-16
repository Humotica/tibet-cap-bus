from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .adapters import Aligner, CausalPlacer, Distributor, EventSink, Executor, Injector, UsageEventProjector
from .models import Cap, CapReceipt, DistributedCap, ExecutionResult, LanePolicy, PhaseEvidence, UsageEvent, new_id


class LamportCausalPlacer:
    """In-memory stand-in for tibet-causal-time."""

    def __init__(self) -> None:
        self._clock = 0

    def place(self, cap: Cap) -> tuple[int, PhaseEvidence]:
        self._clock += 1
        rank = self._clock
        return rank, PhaseEvidence(
            phase="place",
            status="placed",
            details={
                "causal_rank": rank,
                "algorithm": "lamport-like",
                "parent_id": cap.parent_id,
            },
        )


class IntentMuxDistributor:
    """In-memory stand-in for tibet-mux."""

    def distribute(self, cap: Cap, causal_rank: int) -> tuple[str, LanePolicy, PhaseEvidence]:
        lane_id = cap.lane_hint or f"lane:{cap.intent}:{cap.executor_class}"
        policy = _derive_lane_policy(cap, lane_id)
        return lane_id, policy, PhaseEvidence(
            phase="distribute",
            status="lane-assigned",
            details={
                "lane_id": lane_id,
                "route_class": cap.route_class,
                "distribution_fabric": "tibet-mux-sketch",
                "causal_rank": causal_rank,
                "lane_policy": policy.to_dict(),
            },
        )


class MemorySlotInjector:
    """In-memory stand-in for spaceshuttle / tibet-store-mmu."""

    def __init__(self) -> None:
        self._slots: dict[str, dict[str, Any]] = {}

    def inject(self, cap: Cap, lane_id: str, causal_rank: int) -> tuple[str, PhaseEvidence]:
        slot_id = f"slot:{lane_id}:{causal_rank}"
        self._slots[slot_id] = {
            "cap_id": cap.cap_id,
            "actor_id": cap.actor_id,
            "intent": cap.intent,
            "encrypted_for": cap.executor_class,
        }
        return slot_id, PhaseEvidence(
            phase="inject",
            status="slot-populated",
            details={
                "memory_slot": slot_id,
                "executor_class": cap.executor_class,
                "memory_regime": "bifurcated-ram-sketch",
            },
        )


class NoopAligner:
    """Stand-in for tibet-dgx when there is no real cluster yet."""

    def align(self, cap: Cap, lane_id: str, memory_slot: str) -> tuple[str, PhaseEvidence]:
        group = f"align:{lane_id}"
        return group, PhaseEvidence(
            phase="align",
            status="aligned",
            details={
                "alignment_group": group,
                "cluster_mode": "single-node-sketch",
                "memory_slot": memory_slot,
            },
        )


class EchoExecutor:
    """Simple executor that emits a receipt cap-like outcome."""

    def execute(self, distributed: DistributedCap) -> tuple[CapReceipt, PhaseEvidence]:
        continuation_mode = _determine_continuation_mode(distributed.cap.payload)
        if continuation_mode == "resume":
            continuation_mode = _map_resume_mode(distributed.lane_policy.coffee_lane_policy)
        outcome = _determine_outcome(continuation_mode)
        payload = {
            "accepted": True,
            "executed_intent": distributed.cap.intent,
            "lane_id": distributed.lane_id,
            "memory_slot": distributed.memory_slot,
            "alignment_group": distributed.alignment_group,
            "continuation_mode": continuation_mode,
        }
        receipt = CapReceipt(
            receipt_id=new_id("receipt"),
            cap_id=distributed.cap.cap_id,
            actor_id=distributed.cap.actor_id,
            outcome=outcome,
            continuation_mode=continuation_mode,
            payload=payload,
        )
        return receipt, PhaseEvidence(
            phase="execute",
            status=outcome,
            details=payload,
        )


@dataclass
class InMemoryEventSink:
    events: list[ExecutionResult] = field(default_factory=list)

    def record(self, result: ExecutionResult) -> None:
        self.events.append(result)


class RuntimeUsageProjector:
    """Projects canonical usage events from cap bus execution."""

    def project(self, distributed: DistributedCap, receipt: CapReceipt) -> list[UsageEvent]:
        cap = distributed.cap
        provider = _infer_provider(cap)
        model = _infer_model(cap)
        lane_policy = distributed.lane_policy
        common = {
            "cap_id": cap.cap_id,
            "actor_id": cap.actor_id,
            "actor_aint": cap.actor_aint,
            "actor_jis_pubkey": cap.actor_jis_pubkey,
            "intent": cap.intent,
            "provider": provider,
            "model": model,
            "route_class": cap.route_class,
            "lane_id": distributed.lane_id,
            "surface": _infer_surface(distributed),
            "target_url": _infer_target_url(cap),
            "transport": _infer_transport(cap),
            "lane_class": lane_policy.lane_class,
            "lane_collision_policy": lane_policy.lane_collision_policy,
            "coffee_lane_policy": lane_policy.coffee_lane_policy,
            "coffee_reason": lane_policy.coffee_reason,
            "time_diff_seconds": lane_policy.time_diff_seconds,
            "diff_threshold_seconds": lane_policy.diff_threshold_seconds,
            "preemptible": lane_policy.preemptible,
            "lane_priority": lane_policy.priority,
            "executor_class": cap.executor_class,
            "trust_basis": cap.trust_basis,
            "attestation_layer": cap.attestation_layer,
            "attestation_ref": cap.attestation_ref,
            "verified": cap.attestation_layer == "jis",
        }
        return [
            UsageEvent(
                event_id=new_id("evt"),
                observation_layer="cap-bus",
                event_type="cap-dispatched",
                status="queued",
                latency_ms=0.0,
                emitter="cap-bus-runtime",
                details={
                    "parent_id": cap.parent_id,
                    "causal_rank": distributed.causal_rank,
                    "memory_slot": distributed.memory_slot,
                    "alignment_group": distributed.alignment_group,
                    "lane_policy": distributed.lane_policy.to_dict(),
                    "payload": cap.payload,
                    "method": "POST",
                    "coffee_reason": lane_policy.coffee_reason,
                },
                **common,
            ),
            UsageEvent(
                event_id=new_id("evt"),
                observation_layer="executor",
                event_type="cap-executed",
                status=receipt.outcome,
                latency_ms=_infer_latency_ms(cap),
                emitter="cap-bus-runtime",
                continuation_mode=receipt.continuation_mode,
                details={
                    "parent_id": cap.parent_id,
                    "receipt_id": receipt.receipt_id,
                    "outcome": receipt.outcome,
                    "lane_policy": distributed.lane_policy.to_dict(),
                    "payload": cap.payload,
                    "method": "POST",
                    "coffee_reason": lane_policy.coffee_reason,
                },
                **common,
            ),
        ]


class CapBusRuntime:
    """Canonical draft runtime for sender -> place -> distribute -> inject -> align -> execute."""

    def __init__(
        self,
        placer: CausalPlacer,
        distributor: Distributor,
        injector: Injector,
        aligner: Aligner,
        executor: Executor,
        projector: UsageEventProjector,
        sink: EventSink | None = None,
    ) -> None:
        self.placer = placer
        self.distributor = distributor
        self.injector = injector
        self.aligner = aligner
        self.executor = executor
        self.projector = projector
        self.sink = sink

    def run_cap(self, cap: Cap) -> ExecutionResult:
        causal_rank, place_ev = self.placer.place(cap)
        lane_id, lane_policy, dist_ev = self.distributor.distribute(cap, causal_rank)
        memory_slot, inject_ev = self.injector.inject(cap, lane_id, causal_rank)
        alignment_group, align_ev = self.aligner.align(cap, lane_id, memory_slot)

        distributed = DistributedCap(
            cap=cap,
            causal_rank=causal_rank,
            lane_id=lane_id,
            lane_policy=lane_policy,
            memory_slot=memory_slot,
            alignment_group=alignment_group,
            evidence=[place_ev, dist_ev, inject_ev, align_ev],
        )

        receipt, execute_ev = self.executor.execute(distributed)
        distributed.evidence.append(execute_ev)
        usage_events = self.projector.project(distributed, receipt)
        result = ExecutionResult(distributed=distributed, receipt=receipt, usage_events=usage_events)

        if self.sink:
            self.sink.record(result)

        return result

    def run_many(self, caps: list[Cap]) -> list[ExecutionResult]:
        return [self.run_cap(cap) for cap in caps]

    def build_followup_caps(self, result: ExecutionResult) -> list[Cap]:
        """Translate a receipt into the next cap(s) in the chain when appropriate."""
        mode = result.receipt.continuation_mode
        if mode in {"receipt", "polite_avoid", "hard_avoid"}:
            return []

        source = result.distributed.cap
        if mode == "freeze_resume":
            return [
                self._make_followup_cap(
                    source=source,
                    followup_intent=f"{source.intent}.resume.frozen",
                    payload_extra={"resume_mode": "freeze_resume", "frozen_restore": True},
                    route_class=source.route_class,
                    lane_hint=source.lane_hint,
                )
            ]
        if mode == "fork_on_hop_off":
            return [
                self._make_followup_cap(
                    source=source,
                    followup_intent=f"{source.intent}.resume.catchup",
                    payload_extra={"resume_mode": "fork_on_hop_off", "branch": "catchup", "catchup_required": True},
                    route_class="relay",
                    lane_hint=None,
                ),
                self._make_followup_cap(
                    source=source,
                    followup_intent=f"{source.intent}.resume.live",
                    payload_extra={"resume_mode": "fork_on_hop_off", "branch": "live", "live_reentry": True},
                    route_class=source.route_class,
                    lane_hint=None,
                ),
            ]
        if mode == "offline_fallback":
            return [
                self._make_followup_cap(
                    source=source,
                    followup_intent=f"{source.intent}.resume.offline",
                    payload_extra={"resume_mode": "offline_fallback", "offline_fallback": True},
                    route_class="relay",
                    lane_hint=f"lane:offline.fallback:{source.executor_class}",
                )
            ]
        if mode == "rebuild":
            return [
                self._make_followup_cap(
                    source=source,
                    followup_intent=f"{source.intent}.resume.rebuild",
                    payload_extra={"resume_mode": "rebuild", "rebuild_pipeline": True},
                    route_class="relay",
                    lane_hint=f"lane:rebuild:{source.executor_class}",
                )
            ]
        if mode == "reject":
            return [
                self._make_followup_cap(
                    source=source,
                    followup_intent=f"{source.intent}.triage.reject",
                    payload_extra={"triage_reason": "executor-reject", "rejected": True},
                    route_class="relay",
                    lane_hint=f"lane:triage.reject:{source.executor_class}",
                )
            ]
        if mode == "resync-needed":
            return [
                self._make_followup_cap(
                    source=source,
                    followup_intent=f"{source.intent}.triage.resync",
                    payload_extra={"triage_reason": "resync-needed", "resync_requested": True},
                    route_class="relay",
                    lane_hint=f"lane:triage.resync:{source.executor_class}",
                )
            ]
        if mode == "continue":
            return [
                self._make_followup_cap(
                    source=source,
                    followup_intent=source.intent,
                    payload_extra={"continued": True},
                    route_class=source.route_class,
                    lane_hint=source.lane_hint,
                )
            ]
        if mode == "fork":
            return [
                self._make_followup_cap(
                    source=source,
                    followup_intent=f"{source.intent}.fork.alpha",
                    payload_extra={"fork_branch": "alpha", "forked": True},
                    route_class=source.route_class,
                    lane_hint=None,
                ),
                self._make_followup_cap(
                    source=source,
                    followup_intent=f"{source.intent}.fork.beta",
                    payload_extra={"fork_branch": "beta", "forked": True},
                    route_class="relay" if source.route_class == "direct" else source.route_class,
                    lane_hint=None,
                ),
            ]
        return []

    def run_chain(self, root_cap: Cap, max_hops: int = 3) -> list[ExecutionResult]:
        """Run a cap and automatically continue follow-up caps for bounded hops."""
        results: list[ExecutionResult] = []
        queue: list[tuple[Cap, int]] = [(root_cap, 0)]

        while queue:
            current, depth = queue.pop(0)
            result = self.run_cap(current)
            results.append(result)
            if depth + 1 >= max_hops:
                continue
            followups = self.build_followup_caps(result)
            result.spawned_caps.extend(followups)
            for followup in followups:
                queue.append((followup, depth + 1))

        return results

    def _make_followup_cap(
        self,
        *,
        source: Cap,
        followup_intent: str,
        payload_extra: dict[str, Any],
        route_class: str,
        lane_hint: str | None,
    ) -> Cap:
        followup_payload = {
            "source_receipt_id": new_id("source-receipt-ref"),
            "source_cap_id": source.cap_id,
            "continuation_from": source.intent,
            "continuation_mode": "receipt",
            **payload_extra,
        }
        return Cap(
            cap_id=new_id("cap"),
            actor_id=source.actor_id,
            intent=followup_intent,
            authority_ref=source.authority_ref,
            payload=followup_payload,
            parent_id=source.cap_id,
            trust_basis=source.trust_basis,
            route_class=route_class,
            executor_class=source.executor_class,
            lane_hint=lane_hint,
            object_ref=source.object_ref,
        )


def build_default_runtime() -> CapBusRuntime:
    return CapBusRuntime(
        placer=LamportCausalPlacer(),
        distributor=IntentMuxDistributor(),
        injector=MemorySlotInjector(),
        aligner=NoopAligner(),
        executor=EchoExecutor(),
        projector=RuntimeUsageProjector(),
        sink=InMemoryEventSink(),
    )


def build_demo_caps() -> list[Cap]:
    return [
        Cap(
            cap_id=new_id("cap"),
            actor_id="codex.aint",
            intent="agent.tool.high",
            authority_ref="sam:tool",
            payload={"tool": "search", "query": "cap-stream substrate"},
            executor_class="agent-tool",
        ),
        Cap(
            cap_id=new_id("cap"),
            actor_id="jasper.aint",
            intent="factory.motion.control",
            authority_ref="sam:control",
            payload={"command": "move-axis", "axis": "x", "distance_mm": 3.5},
            executor_class="motion-controller",
        ),
        Cap(
            cap_id=new_id("cap"),
            actor_id="service_api.gateway",
            intent="service.rpc.standard",
            authority_ref="sam:service",
            payload={"service": "orders", "action": "reserve", "id": "ord_123"},
            executor_class="microservice",
        ),
        Cap(
            cap_id=new_id("cap"),
            actor_id="scheduler.aint",
            intent="agent.tool.high",
            authority_ref="sam:tool",
            payload={"tool": "plan", "goal": "fork-check", "continuation_mode": "fork", "sealed_at": _seconds_ago_iso(300)},
            executor_class="agent-tool",
            route_class="relay",
        ),
    ]


def build_demo_chain_cap() -> Cap:
    return Cap(
        cap_id=new_id("cap"),
        actor_id="scheduler.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "plan", "goal": "branch-check", "continuation_mode": "fork", "sealed_at": _seconds_ago_iso(300)},
        executor_class="agent-tool",
        route_class="relay",
    )


def build_demo_triage_caps() -> list[Cap]:
    return [
        Cap(
            cap_id=new_id("cap"),
            actor_id="scheduler.aint",
            intent="agent.tool.high",
            authority_ref="sam:tool",
            payload={"tool": "sync", "goal": "resync-branch", "continuation_mode": "resync-needed", "recent_failures": 4},
            executor_class="agent-tool",
            route_class="relay",
        ),
        Cap(
            cap_id=new_id("cap"),
            actor_id="gateway.aint",
            intent="service.rpc.standard",
            authority_ref="sam:service",
            payload={"service": "billing", "action": "charge", "continuation_mode": "reject", "endpoint_status": "down", "consecutive_errors": 3},
            executor_class="microservice",
            route_class="direct",
        ),
    ]


def build_demo_resume_caps() -> list[Cap]:
    return [
        Cap(
            cap_id=new_id("cap"),
            actor_id="resume.aint",
            intent="agent.tool.high",
            authority_ref="sam:tool",
            payload={"tool": "resume", "continuation_mode": "resume", "sealed_at": _seconds_ago_iso(15)},
            executor_class="agent-tool",
            route_class="relay",
        ),
        Cap(
            cap_id=new_id("cap"),
            actor_id="resume.aint",
            intent="agent.tool.high",
            authority_ref="sam:tool",
            payload={"tool": "resume", "continuation_mode": "resume", "sealed_at": _seconds_ago_iso(300)},
            executor_class="agent-tool",
            route_class="relay",
        ),
    ]


def format_result_json(result: ExecutionResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)


def build_governance_export(results: list[ExecutionResult]) -> dict[str, Any]:
    usage_events = [event.to_governance_dict() for result in results for event in result.usage_events]
    actor_links: list[dict[str, Any]] = []
    continuation_graph: list[dict[str, Any]] = []

    for result in results:
        cap = result.distributed.cap
        child_ids = [spawned.cap_id for spawned in result.spawned_caps]
        actor_links.append(
            {
                "cap_id": cap.cap_id,
                "parent_id": cap.parent_id,
                "actor": cap.actor_id,
                "provider": _infer_provider(cap),
                "model": _infer_model(cap),
                "actor_aint": cap.actor_aint,
                "actor_jis_pubkey": cap.actor_jis_pubkey,
                "route_class": cap.route_class,
                "lane_id": result.distributed.lane_id,
                "lane_policy": result.distributed.lane_policy.to_dict(),
                "trust_basis": cap.trust_basis,
                "attestation_layer": cap.attestation_layer,
                "attestation_ref": cap.attestation_ref,
                "continuation_mode": result.receipt.continuation_mode,
                "coffee_lane_policy": result.distributed.lane_policy.coffee_lane_policy,
                "coffee_reason": result.distributed.lane_policy.coffee_reason,
                "time_diff_seconds": result.distributed.lane_policy.time_diff_seconds,
                "diff_threshold_seconds": result.distributed.lane_policy.diff_threshold_seconds,
                "child_cap_ids": child_ids,
            }
        )
        continuation_graph.append(
            {
                "cap_id": cap.cap_id,
                "parent_id": cap.parent_id,
                "child_cap_ids": child_ids,
                "intent": cap.intent,
                "lane_id": result.distributed.lane_id,
                "continuation_mode": result.receipt.continuation_mode,
            }
        )

    return {
        "governance": {
            "questions": {
                "what": "ai-sbom",
                "how": "cbom",
                "who": "ains",
                "why": "jis",
            },
            "trust_foundation": {
                "primary": "jis",
                "jis_present": True,
                "cap_bus_present": True,
                "attestation_layers": sorted({result.distributed.cap.attestation_layer for result in results}),
                "coffee_policies": sorted({result.distributed.lane_policy.coffee_lane_policy for result in results}),
            },
            "claims": {
                "usage_event_truth": bool(usage_events),
                "lane_policy_truth": True,
                "continuation_truth": any(result.receipt.continuation_mode != "receipt" for result in results),
            },
            "governance_links": {
                "what_path": "governance.actor_model_provider_links",
                "how_path": "governance.usage_events",
                "who_path": "governance.actor_model_provider_links",
                "why_path": "governance.trust_foundation",
                "continuation_graph_path": "governance.continuation_graph",
            },
            "actor_model_provider_links": actor_links,
            "continuation_graph": continuation_graph,
            "usage_events": usage_events,
        }
    }


def build_cbom_export(results: list[ExecutionResult]) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []

    for result in results:
        cap = result.distributed.cap
        receipt = result.receipt
        lane_policy = result.distributed.lane_policy.to_dict()
        events = [
            {
                "timestamp": event.timestamp,
                "action": event.event_type,
                "actor": event.actor_id,
                "action_id": event.event_id,
                "phase": event.observation_layer,
                "continuation_mode": event.continuation_mode,
                "notes": event.details,
            }
            for event in result.usage_events
        ]
        documents.append(
            {
                "object_id": cap.cap_id,
                "parent_id": cap.parent_id,
                "child_ids": [spawned.cap_id for spawned in result.spawned_caps],
                "human_name": cap.intent,
                "canonical_surface": result.distributed.lane_id,
                "surface_status": _surface_status_for_result(result),
                "authority": {
                    "actor_id": cap.actor_id,
                    "actor_aint": cap.actor_aint,
                    "actor_jis_pubkey": cap.actor_jis_pubkey,
                    "authority_ref": cap.authority_ref,
                    "trust_basis": cap.trust_basis,
                    "attestation_layer": cap.attestation_layer,
                    "attestation_ref": cap.attestation_ref,
                },
                "material_facts": {
                    "intent": cap.intent,
                    "executor_class": cap.executor_class,
                    "route_class": cap.route_class,
                    "lane_policy": lane_policy,
                    "causal_rank": result.distributed.causal_rank,
                    "alignment_group": result.distributed.alignment_group,
                    "memory_slot": result.distributed.memory_slot,
                },
                "continuity": {
                    "continuation_mode": receipt.continuation_mode,
                    "outcome": receipt.outcome,
                    "receipt_id": receipt.receipt_id,
                    "child_count": len(result.spawned_caps),
                },
                "som_events": events,
            }
        )

    return {
        "cbom": {
            "document_type": "cap-bus-cbom-sketch",
            "documents": documents,
        }
    }


def build_export_all(results: list[ExecutionResult]) -> dict[str, Any]:
    return {
        "cap_bus": {
            "version": "0.1.0",
            "result_count": len(results),
        },
        "gateway_events": build_gateway_event_export(results)["gateway_events"],
        **build_governance_export(results),
        **build_cbom_export(results),
    }


def build_gateway_event_export(results: list[ExecutionResult]) -> dict[str, Any]:
    records = [
        event.to_gateway_event_dict()
        for result in results
        for event in result.usage_events
        if event.event_type == "cap-executed"
    ]
    return {"gateway_events": records}


def _determine_continuation_mode(payload: dict[str, Any]) -> str:
    value = str(payload.get("continuation_mode", "receipt")).strip().lower()
    allowed = {
        "receipt",
        "continue",
        "fork",
        "resume",
        "freeze_resume",
        "fork_on_hop_off",
        "resync-needed",
        "reject",
        "rebuild",
        "offline_fallback",
        "polite_avoid",
        "hard_avoid",
    }
    return value if value in allowed else "receipt"


def _determine_outcome(continuation_mode: str) -> str:
    if continuation_mode == "reject":
        return "rejected"
    if continuation_mode == "resync-needed":
        return "resync-needed"
    return "executed"


def _map_resume_mode(coffee_lane_policy: str) -> str:
    mapping = {
        "freeze_resume": "freeze_resume",
        "fork_on_hop_off": "fork_on_hop_off",
        "rebuild": "rebuild",
        "offline_fallback": "offline_fallback",
        "hard_avoid": "hard_avoid",
        "polite_avoid": "polite_avoid",
    }
    return mapping.get(coffee_lane_policy, "freeze_resume")


def _infer_provider(cap: Cap) -> str | None:
    if "model" in cap.payload:
        return "llm-runtime"
    if cap.intent.startswith("service.rpc"):
        return "internal-service"
    if cap.intent.startswith("factory."):
        return "industrial-controller"
    if cap.intent.startswith("agent."):
        return "agent-runtime"
    return None


def _infer_model(cap: Cap) -> str | None:
    model = cap.payload.get("model")
    if isinstance(model, str):
        return model
    tool = cap.payload.get("tool")
    if isinstance(tool, str):
        return tool
    if cap.intent.startswith("service.rpc"):
        service = cap.payload.get("service")
        if isinstance(service, str):
            return service
        return "service-call"
    if cap.intent.startswith("factory."):
        return "control-command"
    if cap.intent.startswith("agent."):
        return "continuation-runtime"
    return None


def _infer_target_url(cap: Cap) -> str | None:
    if "target_url" in cap.payload and isinstance(cap.payload["target_url"], str):
        return cap.payload["target_url"]
    if "model" in cap.payload:
        return "http://10.100.0.2:11434/api/chat"
    if cap.intent.startswith("service.rpc"):
        service = str(cap.payload.get("service", "service"))
        return f"https://{service}.internal/api"
    if cap.intent.startswith("factory."):
        return "opcua://factory-bus.local/line/a"
    if cap.intent.startswith("agent."):
        return "cap://agent-runtime/execute"
    return None


def _infer_transport(cap: Cap) -> str:
    if cap.route_class == "relay":
        return "http-relay"
    if cap.intent.startswith("factory."):
        return "mux-opcua"
    if cap.intent.startswith("service.rpc"):
        return "http-mesh"
    return "mux-lane"


def _infer_surface(distributed: DistributedCap) -> str:
    cap = distributed.cap
    if cap.intent.startswith("factory."):
        return "factory-control-plane"
    if cap.intent.startswith("service.rpc"):
        service = str(cap.payload.get("service", "service"))
        return f"{service}-service-lane"
    if cap.payload.get("model"):
        return "p520-ollama"
    return distributed.lane_id


def _infer_latency_ms(cap: Cap) -> float:
    if cap.intent.startswith("factory."):
        return 3.2
    if cap.intent.startswith("service.rpc"):
        return 22.5
    if cap.payload.get("model"):
        return 118.4
    return 8.0


def _derive_lane_policy(cap: Cap, lane_id: str) -> LanePolicy:
    lane_class = "standard"
    priority = 5
    burst_limit = 8
    preemptible = False
    executor_pool = cap.executor_class
    lane_collision_policy = "queue"
    coffee_lane_policy, coffee_reason, time_diff_seconds, diff_threshold_seconds = _derive_coffee_lane_policy(cap)

    if cap.intent.startswith("factory."):
        lane_class = "industrial-control"
        priority = 9
        burst_limit = 2
        preemptible = False
        executor_pool = "motion-critical"
        lane_collision_policy = "assert_root"
    elif cap.intent.startswith("agent.tool.high"):
        lane_class = "agent-high"
        priority = 7
        burst_limit = 16
        preemptible = True
        executor_pool = "agent-burst"
        lane_collision_policy = "graceful_yield"
    elif cap.intent.startswith("service.rpc"):
        lane_class = "service-standard"
        priority = 6
        burst_limit = 32
        preemptible = True
        executor_pool = "service-mesh"
        lane_collision_policy = "queue"

    if ".triage.reject" in lane_id or "lane:triage.reject:" in lane_id:
        lane_class = "triage-reject"
        priority = 10
        burst_limit = 1
        preemptible = False
        executor_pool = "triage-human"
        lane_collision_policy = "reject"
    elif ".triage.resync" in lane_id or "lane:triage.resync:" in lane_id:
        lane_class = "triage-resync"
        priority = 9
        burst_limit = 2
        preemptible = False
        executor_pool = "triage-resync"
        lane_collision_policy = "queue"

    if ".fork.alpha" in lane_id:
        lane_class = "fork-alpha"
        priority = max(priority, 8)
        burst_limit = max(4, burst_limit // 2)
        preemptible = False
        executor_pool = f"{executor_pool}-alpha"
        lane_collision_policy = "override_all"
    elif ".fork.beta" in lane_id:
        lane_class = "fork-beta"
        priority = min(priority, 4)
        burst_limit = max(2, burst_limit // 2)
        preemptible = True
        executor_pool = f"{executor_pool}-beta"
        lane_collision_policy = "graceful_yield"

    if cap.route_class == "relay":
        burst_limit = max(1, burst_limit - 1)

    return LanePolicy(
        lane_class=lane_class,
        priority=priority,
        burst_limit=burst_limit,
        preemptible=preemptible,
        executor_pool=executor_pool,
        lane_collision_policy=lane_collision_policy,
        coffee_lane_policy=coffee_lane_policy,
        coffee_reason=coffee_reason,
        time_diff_seconds=time_diff_seconds,
        diff_threshold_seconds=diff_threshold_seconds,
    )


def _derive_coffee_lane_policy(cap: Cap) -> tuple[str, str | None, float | None, int | None]:
    diff_threshold_seconds = int(cap.payload.get("diff_threshold_seconds", 3600))
    sealed_at = cap.payload.get("sealed_at")
    time_diff_seconds = _time_diff_seconds(sealed_at) if isinstance(sealed_at, str) else None

    if time_diff_seconds is not None:
        if time_diff_seconds < 60:
            return "freeze_resume", f"time_diff_seconds={time_diff_seconds:.0f}<60", time_diff_seconds, diff_threshold_seconds
        if time_diff_seconds < diff_threshold_seconds:
            return "fork_on_hop_off", f"time_diff_seconds={time_diff_seconds:.0f}<{diff_threshold_seconds}", time_diff_seconds, diff_threshold_seconds
        if time_diff_seconds < 86400:
            return "rebuild", f"time_diff_seconds={time_diff_seconds:.0f}>=diff_threshold", time_diff_seconds, diff_threshold_seconds
        return "hard_avoid", f"time_diff_seconds={time_diff_seconds:.0f}>=86400", time_diff_seconds, diff_threshold_seconds

    if not cap.actor_aint and not any(token in cap.actor_id.lower() for token in ("gateway", "service", "controller")):
        return "polite_avoid", "actor_unknown", None, diff_threshold_seconds

    trust_score = cap.payload.get("trust_score")
    if isinstance(trust_score, (int, float)) and trust_score < 0.3:
        return "hard_avoid", f"actor_trust_score={trust_score:.2f}", None, diff_threshold_seconds

    recent_failures = cap.payload.get("recent_failures")
    if isinstance(recent_failures, int) and recent_failures > 3:
        return "rebuild", f"recent_failures={recent_failures}", None, diff_threshold_seconds

    endpoint_status = str(cap.payload.get("endpoint_status", "")).lower()
    http_status = cap.payload.get("http_status")
    consecutive_errors = cap.payload.get("consecutive_errors")
    if endpoint_status in {"offline", "down"} or (
        isinstance(http_status, int) and http_status >= 500
    ) or (
        isinstance(consecutive_errors, int) and consecutive_errors >= 3
    ):
        reason = endpoint_status or (f"http_status={http_status}" if isinstance(http_status, int) else f"consecutive_errors={consecutive_errors}")
        return "offline_fallback", reason, None, diff_threshold_seconds

    return "sip_anyway", "healthy_lane", None, diff_threshold_seconds


def _time_diff_seconds(sealed_at: str) -> float | None:
    try:
        dt = datetime.fromisoformat(sealed_at)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return max((datetime.now(UTC) - dt.astimezone(UTC)).total_seconds(), 0.0)


def _seconds_ago_iso(seconds: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def _surface_status_for_result(result: ExecutionResult) -> str:
    mode = result.receipt.continuation_mode
    if mode == "reject":
        return "TRIAGE"
    if mode == "resync-needed":
        return "PARTIAL"
    if mode == "fork":
        return "FORKED"
    return "MATCH"
