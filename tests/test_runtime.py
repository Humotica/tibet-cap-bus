from datetime import UTC, datetime, timedelta

from tibet_cap_bus.event_contract import validate_gateway_event_record, validate_gateway_event_records
from tibet_cap_bus.models import Cap, new_id
from tibet_cap_bus.runtime import (
    build_cbom_export,
    build_default_runtime,
    build_demo_resume_caps,
    build_export_all,
    build_gateway_event_export,
    build_governance_export,
)


def test_runtime_assigns_causal_rank_and_lane():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="codex.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "search"},
        executor_class="agent-tool",
    )

    result = runtime.run_cap(cap)

    assert result.distributed.causal_rank == 1
    assert result.distributed.lane_id == "lane:agent.tool.high:agent-tool"
    assert result.distributed.lane_policy.lane_class == "agent-high"
    assert result.distributed.lane_policy.priority == 7
    assert result.distributed.lane_policy.lane_collision_policy == "graceful_yield"
    assert result.distributed.lane_policy.coffee_lane_policy == "sip_anyway"
    assert result.receipt.outcome == "executed"
    assert result.receipt.continuation_mode == "receipt"
    assert len(result.usage_events) == 2
    assert result.usage_events[0].event_type == "cap-dispatched"
    assert result.usage_events[0].actor_aint == "codex.aint"
    assert result.usage_events[1].attestation_layer == "jis"


def test_runtime_increments_causal_rank():
    runtime = build_default_runtime()

    cap_a = Cap(
        cap_id=new_id("cap"),
        actor_id="a.aint",
        intent="service.rpc.standard",
        authority_ref="sam:service",
        payload={"id": 1},
    )
    cap_b = Cap(
        cap_id=new_id("cap"),
        actor_id="b.aint",
        intent="service.rpc.standard",
        authority_ref="sam:service",
        payload={"id": 2},
    )

    result_a = runtime.run_cap(cap_a)
    result_b = runtime.run_cap(cap_b)

    assert result_a.distributed.causal_rank == 1
    assert result_b.distributed.causal_rank == 2


def test_runtime_preserves_fork_continuation_mode():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="planner.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "plan", "continuation_mode": "fork"},
    )

    result = runtime.run_cap(cap)

    assert result.receipt.continuation_mode == "fork"
    assert result.receipt.outcome == "executed"
    assert result.usage_events[1].continuation_mode == "fork"


def test_runtime_builds_followup_caps_for_continue():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="planner.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "plan", "continuation_mode": "continue"},
    )

    result = runtime.run_cap(cap)
    followups = runtime.build_followup_caps(result)

    assert len(followups) == 1
    followup = followups[0]
    assert followup.parent_id == cap.cap_id
    assert followup.intent == cap.intent
    assert followup.payload["continued"] is True


def test_runtime_runs_bounded_chain():
    runtime = build_default_runtime()
    sealed_at = (datetime.now(UTC) - timedelta(seconds=300)).isoformat()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="planner.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "plan", "continuation_mode": "fork", "sealed_at": sealed_at},
    )

    results = runtime.run_chain(cap, max_hops=3)

    assert len(results) == 3
    assert results[0].distributed.cap.parent_id is None
    assert len(results[0].spawned_caps) == 2
    assert results[1].distributed.cap.parent_id == results[0].distributed.cap.cap_id
    assert results[2].distributed.cap.parent_id == results[0].distributed.cap.cap_id
    assert results[1].distributed.lane_policy.lane_class == "fork-alpha"
    assert results[2].distributed.lane_policy.lane_class == "fork-beta"
    assert results[1].distributed.lane_policy.priority > results[2].distributed.lane_policy.priority
    assert results[0].distributed.lane_policy.coffee_lane_policy == "fork_on_hop_off"
    assert results[0].receipt.continuation_mode == "fork"
    assert results[1].receipt.continuation_mode == "receipt"
    assert results[2].receipt.continuation_mode == "receipt"


def test_runtime_routes_resync_needed_into_triage_lane():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="syncer.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "sync", "continuation_mode": "resync-needed", "recent_failures": 4},
    )

    result = runtime.run_cap(cap)
    followups = runtime.build_followup_caps(result)

    assert len(followups) == 1
    followup = followups[0]
    assert followup.intent.endswith(".triage.resync")
    assert followup.lane_hint == "lane:triage.resync:default"

    chain = runtime.run_chain(cap, max_hops=2)
    assert len(chain) == 2
    assert chain[0].distributed.lane_policy.coffee_lane_policy == "rebuild"
    assert chain[1].distributed.lane_policy.lane_class == "triage-resync"
    assert chain[1].distributed.lane_policy.priority == 9


def test_runtime_routes_reject_into_triage_lane():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="gateway.aint",
        intent="service.rpc.standard",
        authority_ref="sam:service",
        payload={"service": "billing", "continuation_mode": "reject", "endpoint_status": "down", "consecutive_errors": 3},
        executor_class="microservice",
    )

    result = runtime.run_cap(cap)
    followups = runtime.build_followup_caps(result)

    assert len(followups) == 1
    followup = followups[0]
    assert followup.intent.endswith(".triage.reject")
    assert followup.lane_hint == "lane:triage.reject:microservice"

    chain = runtime.run_chain(cap, max_hops=2)
    assert len(chain) == 2
    assert chain[0].distributed.lane_policy.coffee_lane_policy == "offline_fallback"
    assert chain[1].distributed.lane_policy.lane_class == "triage-reject"
    assert chain[1].distributed.lane_policy.priority == 10


def test_runtime_marks_freeze_resume_for_small_time_diff():
    runtime = build_default_runtime()
    sealed_at = (datetime.now(UTC) - timedelta(seconds=15)).isoformat()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="resume.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "resume", "continuation_mode": "resume", "sealed_at": sealed_at},
        executor_class="agent-tool",
    )

    result = runtime.run_cap(cap)

    assert result.distributed.lane_policy.coffee_lane_policy == "freeze_resume"
    assert result.receipt.continuation_mode == "freeze_resume"
    assert result.distributed.lane_policy.time_diff_seconds is not None
    assert result.distributed.lane_policy.diff_threshold_seconds == 3600

    followups = runtime.build_followup_caps(result)
    assert len(followups) == 1
    assert followups[0].intent.endswith(".resume.frozen")


def test_runtime_resume_can_fork_on_hop_off():
    runtime = build_default_runtime()
    sealed_at = (datetime.now(UTC) - timedelta(seconds=300)).isoformat()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="resume.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "resume", "continuation_mode": "resume", "sealed_at": sealed_at},
        executor_class="agent-tool",
        route_class="relay",
    )

    result = runtime.run_cap(cap)
    assert result.distributed.lane_policy.coffee_lane_policy == "fork_on_hop_off"
    assert result.receipt.continuation_mode == "fork_on_hop_off"

    followups = runtime.build_followup_caps(result)
    assert len(followups) == 2
    assert followups[0].intent.endswith(".resume.catchup")
    assert followups[1].intent.endswith(".resume.live")


def test_governance_export_has_ai_sbom_like_shape():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="codex.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "search"},
        executor_class="agent-tool",
    )
    results = runtime.run_chain(cap, max_hops=1)
    exported = build_governance_export(results)

    governance = exported["governance"]
    assert governance["questions"]["what"] == "ai-sbom"
    assert governance["trust_foundation"]["primary"] == "jis"
    assert isinstance(governance["usage_events"], list)
    assert len(governance["usage_events"]) == 2

    event = governance["usage_events"][0]
    assert event["actor"]["identity"] == "codex.aint"
    assert event["actor"]["ains_domain"] == "codex.aint"
    assert event["inference"]["surface"].startswith("lane:")
    assert event["trust"]["basis"] == "jis"
    assert event["trust"]["signature_ref"].startswith("attest:")
    assert event["route"]["lane_class"] == "agent-high"
    assert event["route"]["lane_collision_policy"] == "graceful_yield"
    assert event["route"]["coffee_lane_policy"] == "sip_anyway"
    assert event["route"]["lane_priority"] == 7
    assert event["evidence"]["emitter"] == "cap-bus-runtime"


def test_governance_export_exposes_continuation_graph():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="planner.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "plan", "continuation_mode": "fork"},
    )
    results = runtime.run_chain(cap, max_hops=3)
    exported = build_governance_export(results)

    governance = exported["governance"]
    graph = governance["continuation_graph"]
    assert len(graph) == 3
    root = graph[0]
    assert root["parent_id"] is None
    assert len(root["child_cap_ids"]) == 2

    links = governance["actor_model_provider_links"]
    assert links[0]["cap_id"] == root["cap_id"]
    assert len(links[0]["child_cap_ids"]) == 2

    child_event = governance["usage_events"][2]
    assert child_event["parent_id"] == root["cap_id"]


def test_cbom_export_has_document_and_som_shape():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="planner.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "plan", "continuation_mode": "fork"},
    )
    results = runtime.run_chain(cap, max_hops=3)
    exported = build_cbom_export(results)

    docs = exported["cbom"]["documents"]
    assert len(docs) == 3
    root = docs[0]
    assert root["object_id"] == results[0].distributed.cap.cap_id
    assert root["surface_status"] == "FORKED"
    assert len(root["child_ids"]) == 2
    assert root["authority"]["trust_basis"] == "jis"
    assert root["authority"]["attestation_layer"] == "jis"
    assert root["material_facts"]["lane_policy"]["lane_class"] == "agent-high"
    assert root["material_facts"]["lane_policy"]["lane_collision_policy"] == "graceful_yield"
    assert isinstance(root["som_events"], list)
    assert root["som_events"][0]["action"] == "cap-dispatched"


def test_export_all_contains_governance_and_cbom():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="planner.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "plan", "continuation_mode": "fork"},
    )
    results = runtime.run_chain(cap, max_hops=3)
    exported = build_export_all(results)

    assert exported["cap_bus"]["result_count"] == 3
    assert len(exported["gateway_events"]) == 3
    assert "governance" in exported
    assert "cbom" in exported
    assert len(exported["governance"]["usage_events"]) == 6
    assert len(exported["cbom"]["documents"]) == 3
    assert "coffee_policies" in exported["governance"]["trust_foundation"]


def test_gateway_event_export_matches_tibet_gateway_shape():
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id="codex.aint",
        intent="agent.tool.high",
        authority_ref="sam:tool",
        payload={"tool": "search", "model": "qwen2.5:7b"},
        executor_class="agent-tool",
        actor_jis_pubkey="ed25519:abc123",
    )

    results = runtime.run_chain(cap, max_hops=1)
    exported = build_gateway_event_export(results)["gateway_events"]

    assert len(exported) == 1
    event = exported[0]
    assert event["observation_layer"] == "tibet-gateway"
    assert event["agent_id"] == "codex.aint"
    assert event["actor_aint"] == "codex.aint"
    assert event["actor_jis_pubkey"] == "ed25519:abc123"
    assert event["provider"] == "llm-runtime"
    assert event["model"] == "qwen2.5:7b"
    assert event["surface"] == "p520-ollama"
    assert event["route_class"] == "direct"
    assert event["transport"] == "mux-lane"
    assert event["lane_class"] == "agent-high"
    assert event["lane_collision_policy"] == "graceful_yield"
    assert event["coffee_lane_policy"] == "sip_anyway"
    assert event["preemptible"] is True
    assert event["lane_priority"] == 7
    assert event["attestation_layer"] == "jis"
    assert event["attestation_ref"].startswith("attest:")
    assert event["_emitter"] == "cap-bus-runtime"


def test_gateway_export_records_validate_against_contract():
    runtime = build_default_runtime()
    results = []
    for root in build_demo_resume_caps():
        results.extend(runtime.run_chain(root, max_hops=2))

    records = build_gateway_event_export(results)["gateway_events"]

    assert validate_gateway_event_records(records) == []


def test_gateway_contract_rejects_missing_required_field():
    record = {
        "event_id": "evt_1",
        "observation_layer": "tibet-gateway",
        "timestamp": "2026-05-15T16:00:00+00:00",
        "operation_id": "cap_1",
        "agent_id": "resume.aint",
        "intent": "agent.tool.high",
        "provider": "agent-runtime",
        "model": "runtime-command",
        "route_class": "relay",
        "surface": "lane:agent.tool.high:agent-tool",
        "transport": "mux-lane",
        "status": "cap-executed",
        "latency_ms": 12.5,
        "lane_class": "agent-high",
        "lane_collision_policy": "graceful_yield",
        "coffee_lane_policy": "fork_on_hop_off",
        "attestation_layer": "jis",
        "_emitter": "cap-bus-runtime",
        "verified": True,
    }

    broken = dict(record)
    del broken["provider"]

    errors = validate_gateway_event_record(broken)

    assert "missing required field: provider" in errors
