from __future__ import annotations

import json
from pathlib import Path

import typer

from .event_contract import load_event_records, validate_gateway_event_records
from .models import Cap, new_id
from .runtime import (
    build_export_all,
    build_cbom_export,
    build_default_runtime,
    build_demo_caps,
    build_demo_chain_cap,
    build_demo_resume_caps,
    build_demo_triage_caps,
    build_gateway_event_export,
    build_governance_export,
    format_result_json,
)

app = typer.Typer(add_completion=False, help="tibet-cap-bus sandbox sketch")


@app.command()
def demo(json_output: bool = typer.Option(False, "--json", help="Emit full JSON results")) -> None:
    """Run a small end-to-end cap bus demo."""
    runtime = build_default_runtime()
    results = runtime.run_many(build_demo_caps())

    if json_output:
        print(json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True))
        return

    print("tibet-cap-bus demo")
    print()
    for result in results:
        cap = result.distributed.cap
        print(f"- cap: {cap.cap_id}")
        print(f"  actor: {cap.actor_id}")
        print(f"  intent: {cap.intent}")
        print(f"  causal-rank: {result.distributed.causal_rank}")
        print(f"  lane: {result.distributed.lane_id}")
        policy = result.distributed.lane_policy
        print(
            f"  policy: class={policy.lane_class} priority={policy.priority} "
            f"burst={policy.burst_limit} preemptible={policy.preemptible}"
        )
        print(f"  slot: {result.distributed.memory_slot}")
        print(f"  align: {result.distributed.alignment_group}")
        print(
            f"  receipt: {result.receipt.receipt_id} "
            f"({result.receipt.outcome}, mode={result.receipt.continuation_mode})"
        )
        print(f"  usage-events: {len(result.usage_events)}")
        print()


@app.command()
def emit(
    actor: str = typer.Option(..., "--actor", help="Actor identity, usually .aint or service actor"),
    actor_aint: str | None = typer.Option(None, "--actor-aint", help="Explicit .aint binding for WHO-layer alignment"),
    actor_jis_pubkey: str | None = typer.Option(None, "--actor-jis-pubkey", help="Optional JIS pubkey placeholder"),
    intent: str = typer.Option(..., "--intent", help="Intent or command lane"),
    authority: str = typer.Option(..., "--authority", help="Authority reference, e.g. SAM lane"),
    payload: str = typer.Option("{}", "--payload", help="JSON payload"),
    executor_class: str = typer.Option("default", "--executor-class", help="Executor class"),
    route_class: str = typer.Option("direct", "--route-class", help="Route class"),
    lane_hint: str | None = typer.Option(None, "--lane-hint", help="Optional explicit lane override"),
    parent_id: str | None = typer.Option(None, "--parent-id", help="Optional causal parent cap id"),
    continuation_mode: str = typer.Option("receipt", "--continuation-mode", help="receipt, continue, fork, resync-needed, reject"),
    attestation_layer: str = typer.Option("jis", "--attestation-layer", help="jis, self-signed, or none"),
    attestation_ref: str | None = typer.Option(None, "--attestation-ref", help="Optional attestation reference"),
) -> None:
    """Emit a single cap through the draft runtime."""
    runtime = build_default_runtime()
    cap = Cap(
        cap_id=new_id("cap"),
        actor_id=actor,
        intent=intent,
        authority_ref=authority,
        payload={**json.loads(payload), "continuation_mode": continuation_mode},
        executor_class=executor_class,
        route_class=route_class,
        lane_hint=lane_hint,
        parent_id=parent_id,
        actor_aint=actor_aint,
        actor_jis_pubkey=actor_jis_pubkey,
        attestation_layer=attestation_layer,
        attestation_ref=attestation_ref,
    )
    result = runtime.run_cap(cap)
    print(format_result_json(result))


@app.command()
def trace() -> None:
    """Show a compact trace view with usage events from the demo flow."""
    runtime = build_default_runtime()
    results = runtime.run_many(build_demo_caps())

    print("tibet-cap-bus trace")
    print()
    for result in results:
        cap = result.distributed.cap
        print(f"- {cap.actor_id} -> {cap.intent} -> {result.distributed.lane_id}")
        for event in result.usage_events:
            provider = event.provider or "-"
            model = event.model or "-"
            print(
                f"  [{event.observation_layer}] {event.event_type} "
                f"provider={provider} model={model} route={event.route_class} "
                f"mode={event.continuation_mode or '-'}"
            )
        print()


@app.command()
def chain(
    json_output: bool = typer.Option(False, "--json", help="Emit full JSON chain results"),
    hops: int = typer.Option(3, "--hops", min=1, help="Maximum continuation hops"),
) -> None:
    """Run a bounded continuation chain starting from one root cap."""
    runtime = build_default_runtime()
    results = runtime.run_chain(build_demo_chain_cap(), max_hops=hops)

    if json_output:
        print(json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True))
        return

    print("tibet-cap-bus chain")
    print()
    for index, result in enumerate(results, start=1):
        cap = result.distributed.cap
        print(
            f"{index}. cap={cap.cap_id} parent={cap.parent_id or '-'} "
            f"intent={cap.intent} rank={result.distributed.causal_rank}"
        )
        print(
            f"   receipt={result.receipt.receipt_id} "
            f"outcome={result.receipt.outcome} mode={result.receipt.continuation_mode}"
        )
        print(f"   lane={result.distributed.lane_id}")
        policy = result.distributed.lane_policy
        print(
            f"   policy=class:{policy.lane_class} priority:{policy.priority} "
            f"burst:{policy.burst_limit} preemptible:{policy.preemptible}"
        )
        if result.spawned_caps:
            print("   spawned:")
            for spawned in result.spawned_caps:
                print(
                    f"     - {spawned.cap_id} parent={spawned.parent_id} "
                    f"intent={spawned.intent} route={spawned.route_class}"
                )
        print()


@app.command()
def triage() -> None:
    """Show reject/resync-needed continuation into explicit triage lanes."""
    runtime = build_default_runtime()
    roots = build_demo_triage_caps()

    print("tibet-cap-bus triage")
    print()
    for root in roots:
        results = runtime.run_chain(root, max_hops=2)
        for index, result in enumerate(results, start=1):
            cap = result.distributed.cap
            policy = result.distributed.lane_policy
            print(
                f"{index}. cap={cap.cap_id} parent={cap.parent_id or '-'} "
                f"intent={cap.intent} mode={result.receipt.continuation_mode}"
            )
            print(
                f"   lane={result.distributed.lane_id} "
                f"class={policy.lane_class} priority={policy.priority} "
                f"burst={policy.burst_limit} preemptible={policy.preemptible}"
            )
            if result.spawned_caps:
                print("   spawned:")
                for spawned in result.spawned_caps:
                    print(
                        f"     - {spawned.cap_id} parent={spawned.parent_id} "
                        f"intent={spawned.intent} lane_hint={spawned.lane_hint}"
                    )
        print()


@app.command()
def resume() -> None:
    """Show time-diff-aware resume semantics: freeze vs fork-on-hop-off."""
    runtime = build_default_runtime()
    roots = build_demo_resume_caps()

    print("tibet-cap-bus resume")
    print()
    for root in roots:
        results = runtime.run_chain(root, max_hops=2)
        for index, result in enumerate(results, start=1):
            cap = result.distributed.cap
            policy = result.distributed.lane_policy
            print(
                f"{index}. cap={cap.cap_id} parent={cap.parent_id or '-'} "
                f"intent={cap.intent} mode={result.receipt.continuation_mode}"
            )
            print(
                f"   coffee={policy.coffee_lane_policy} "
                f"reason={policy.coffee_reason} diff={policy.time_diff_seconds}"
            )
            print(
                f"   lane={result.distributed.lane_id} "
                f"class={policy.lane_class} priority={policy.priority}"
            )
            if result.spawned_caps:
                print("   spawned:")
                for spawned in result.spawned_caps:
                    print(
                        f"     - {spawned.cap_id} parent={spawned.parent_id} "
                        f"intent={spawned.intent} route={spawned.route_class}"
                    )
        print()


@app.command("governance-export")
def governance_export(
    source: str = typer.Option("demo", "--source", help="demo, chain, or triage"),
) -> None:
    """Export a governance-shaped document aligned to tibet-ai-sbom usage semantics."""
    runtime = build_default_runtime()
    if source == "demo":
        results = runtime.run_many(build_demo_caps())
    elif source == "chain":
        results = runtime.run_chain(build_demo_chain_cap(), max_hops=3)
    elif source == "resume":
        results = []
        for root in build_demo_resume_caps():
            results.extend(runtime.run_chain(root, max_hops=2))
    elif source == "triage":
        results = []
        for root in build_demo_triage_caps():
            results.extend(runtime.run_chain(root, max_hops=2))
    else:
        raise typer.BadParameter("source must be demo, chain, resume, or triage")

    print(json.dumps(build_governance_export(results), indent=2, sort_keys=True))


@app.command("cbom-export")
def cbom_export(
    source: str = typer.Option("demo", "--source", help="demo, chain, or triage"),
) -> None:
    """Export a CBOM/SoM-shaped document from cap bus execution."""
    runtime = build_default_runtime()
    if source == "demo":
        results = runtime.run_many(build_demo_caps())
    elif source == "chain":
        results = runtime.run_chain(build_demo_chain_cap(), max_hops=3)
    elif source == "resume":
        results = []
        for root in build_demo_resume_caps():
            results.extend(runtime.run_chain(root, max_hops=2))
    elif source == "triage":
        results = []
        for root in build_demo_triage_caps():
            results.extend(runtime.run_chain(root, max_hops=2))
    else:
        raise typer.BadParameter("source must be demo, chain, resume, or triage")

    print(json.dumps(build_cbom_export(results), indent=2, sort_keys=True))


@app.command("export-all")
def export_all(
    source: str = typer.Option("demo", "--source", help="demo, chain, or triage"),
) -> None:
    """Export governance and CBOM views from the same cap bus run."""
    runtime = build_default_runtime()
    if source == "demo":
        results = runtime.run_many(build_demo_caps())
    elif source == "chain":
        results = runtime.run_chain(build_demo_chain_cap(), max_hops=3)
    elif source == "resume":
        results = []
        for root in build_demo_resume_caps():
            results.extend(runtime.run_chain(root, max_hops=2))
    elif source == "triage":
        results = []
        for root in build_demo_triage_caps():
            results.extend(runtime.run_chain(root, max_hops=2))
    else:
        raise typer.BadParameter("source must be demo, chain, resume, or triage")

    print(json.dumps(build_export_all(results), indent=2, sort_keys=True))


@app.command("gateway-export")
def gateway_export(
    source: str = typer.Option("demo", "--source", help="demo, chain, or triage"),
    json_output: bool = typer.Option(False, "--json", help="Emit as JSON array instead of JSONL"),
) -> None:
    """Export cap-bus execution as tibet-gateway-compatible event records."""
    runtime = build_default_runtime()
    if source == "demo":
        results = runtime.run_many(build_demo_caps())
    elif source == "chain":
        results = runtime.run_chain(build_demo_chain_cap(), max_hops=3)
    elif source == "resume":
        results = []
        for root in build_demo_resume_caps():
            results.extend(runtime.run_chain(root, max_hops=2))
    elif source == "triage":
        results = []
        for root in build_demo_triage_caps():
            results.extend(runtime.run_chain(root, max_hops=2))
    else:
        raise typer.BadParameter("source must be demo, chain, resume, or triage")

    records = build_gateway_event_export(results)["gateway_events"]
    if json_output:
        print(json.dumps(records, indent=2, sort_keys=True))
        return

    for record in records:
        print(json.dumps(record, sort_keys=True))


@app.command("validate-gateway-event")
def validate_gateway_event(
    input_path: str | None = typer.Option(None, "--input", help="Path to JSON or JSONL gateway-event records"),
    source: str = typer.Option("resume", "--source", help="demo, chain, resume, or triage"),
) -> None:
    """Validate gateway/common-lane event records against the shared sandbox contract."""
    if input_path:
        records = load_event_records(Path(input_path))
    else:
        runtime = build_default_runtime()
        if source == "demo":
            results = runtime.run_many(build_demo_caps())
        elif source == "chain":
            results = runtime.run_chain(build_demo_chain_cap(), max_hops=3)
        elif source == "resume":
            results = []
            for root in build_demo_resume_caps():
                results.extend(runtime.run_chain(root, max_hops=2))
        elif source == "triage":
            results = []
            for root in build_demo_triage_caps():
                results.extend(runtime.run_chain(root, max_hops=2))
        else:
            raise typer.BadParameter("source must be demo, chain, resume, or triage")
        records = build_gateway_event_export(results)["gateway_events"]

    errors = validate_gateway_event_records(records)
    if errors:
        print("INVALID")
        print()
        for error in errors:
            print(f"- {error}")
        raise typer.Exit(code=1)

    print("VALID")
    print()
    print(f"records: {len(records)}")
    print("contract: tibet-cap-bus.gateway-event.v1")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
