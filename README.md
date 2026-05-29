# tibet-cap-bus

**Identity-bound causal command substrate from sealed caps.**

Implements `lane_collision_policy` and `coffee_lane_policy`
(frozen-continuity vs fork-on-hop-off resume semantics) for
AI continuity governance.

> `lane_collision_policy` decides what happens when actors meet.
> `coffee_lane_policy` decides what happens when they should not.

## Pipeline

```text
sender
  -> causal-time          (place: assign causal rank)
  -> mux                  (distribute: lane + policy)
  -> spaceshuttle         (inject: executor-bound memory slot)
  -> tibet-dgx            (align: cluster alignment)
  -> executor             (execute)
  -> receipt cap          (sealed audit record)
```

## What this package provides

- **Clean data model** — `Cap`, `LanePolicy`, `PhaseEvidence`, `UsageEvent`, `CapReceipt`
- **Protocol adapters** (`adapters.py`) — drop-in interface for `tibet-mux`, `tibet-causal-time`, `tibet-store-mmu`, `tibet-dgx`, `tibet-phantom`
- **In-memory default implementations** — runnable out-of-the-box for local development
- **Branching continuations** — `receipt` / `continue` / `fork` (alpha/beta) / `resync-needed` / `reject`
- **Lane policies** — `lane_collision_policy` (5 values) + `coffee_lane_policy` (7 values)
- **Resume semantics** — `freeze_resume` and `fork_on_hop_off` as first-class runtime modes
- **Gateway-compatible event export** — `tibet-cap-bus.gateway-event.v1` contract
- **Validator + fixture** — `validate-gateway-event` CLI + reference JSON fixture
- **First-class `.aint` actor binding** + JIS attestation fields
- **`airlock_runtime_verdict.v1` contract** *(0.1.3)* — runtime-posture signal layer for the immune-switch pipeline (see below)
- **`verdict_transitions`** *(0.1.3)* — posture-transition builder that emits `gateway-event.v1` records

In-memory adapters are placeholders. Real implementations land via Protocol replacement
(see `ROADMAP.md` for the 0.2.x release line).

## Immune-switch contracts (since 0.1.3)

The signal layer for the `tibet-pol → snaft → cap-bus → tibet-airlock` immune-switch
pipeline. tibet-cap-bus owns the wire-format; the producers and consumers live in
their own packages and do not depend on each other.

```python
from tibet_cap_bus import (
    VERDICT_KIND,                       # "airlock_runtime_verdict.v1"
    validate_verdict_record,            # contract validation
    check_mode_coherence,               # soft warn on misconfigured emitters
    make_posture_transition_event,      # gateway-event.v1 builder for transitions
    POSTURE_TRANSITION_INTENT,          # "posture.transition.v1"
)

verdict = {
    "kind": VERDICT_KIND,
    "verdict_id": "verdict_demo_001",
    "timestamp": "2026-05-29T14:00:00+00:00",
    "emitter": "jis:humotica:tibet-pol",
    "runtime_mode": "python_fallback",
    "rust_airlock": "offline",
    "trust_kernel": "online_without_airlock",
    "python_fallback": "enabled",
    "external_ai_inbound": "deny",                  # the invariant kicks in
    "execution_policy": "local_or_operator_approved_only",
    "snaft_posture": "quarantine_external_ai",
    "reason": "Bolle airlock runtime unavailable; Python fallback is not a production isolation boundary.",
}

assert validate_verdict_record(verdict) == []
assert check_mode_coherence(verdict) == []
```

The 4 runtime-modes — `embedded_online` / `kernel_online` / `python_fallback` / `offline` —
map deterministically to 3 snaft postures: `normal_zero_trust` / `quarantine_external_ai` /
`hard_quarantine`. Snaft consumers (see `snaft.posture.consume_verdict`) call
`make_posture_transition_event(...)` from this package to log transitions as
`gateway-event.v1` records. Reference: Codex policy 2026-05-29 §"Runtime Modes".

## Why this exists

The concept is bigger than messaging:

- `cmail` moves continuity
- `cap` carries a sealed instruction unit
- `cap-stream` moves causally ordered action
- `mux` distributes those actions across isolated lanes

This package is the first code sketch of that execution-oriented substrate.

## Commands

### Demo

```bash
tibet-cap-bus demo
```

Runs a small cap flow with:

- one sender
- lamport-style causal placement
- mux-style lane distribution
- executor-bound memory slot injection
- optional cluster alignment marker
- receipt cap emission

### Emit a single cap

```bash
tibet-cap-bus emit \
  --actor codex.aint \
  --intent agent.tool.high \
  --authority sam:tool \
  --payload '{\"tool\": \"search\", \"query\": \"cap-stream\"}' \
  --continuation-mode fork
```

### Trace view

```bash
tibet-cap-bus trace
```

### Continuation chain

```bash
tibet-cap-bus chain
tibet-cap-bus chain --hops 4
```

### Triage lanes

```bash
tibet-cap-bus triage
```

### Governance export

```bash
tibet-cap-bus governance-export
tibet-cap-bus governance-export --source chain
tibet-cap-bus governance-export --source triage
```

### CBOM export

```bash
tibet-cap-bus cbom-export
tibet-cap-bus cbom-export --source chain
tibet-cap-bus cbom-export --source triage
```

### Combined export

```bash
tibet-cap-bus export-all
tibet-cap-bus export-all --source chain
tibet-cap-bus export-all --source triage
```

### Gateway-compatible JSONL export

```bash
tibet-cap-bus gateway-export
tibet-cap-bus gateway-export --source chain
tibet-cap-bus gateway-export --json
```

### Validate common event lane records

```bash
tibet-cap-bus validate-gateway-event
tibet-cap-bus validate-gateway-event --source chain
tibet-cap-bus validate-gateway-event --input fixtures/gateway-event.resume.example.json
```

This validates the shared event lane used by:

- `tibet-cap-bus`
- `tibet-gateway`
- `tibet-ai-sbom`
- future live emitters such as `brain_api`, `service_api`, or `telecom_api`

The current contract is `tibet-cap-bus.gateway-event.v1`.

## Package structure

- `models.py`
  - canonical records
- `adapters.py`
  - phase protocols
- `runtime.py`
  - in-memory default implementation
- `cli.py`
  - operator surface

## Current phases

1. emit
2. place
3. distribute
4. inject
5. align
6. execute

Each phase returns explicit evidence so a future CBOM / audit / usage-event layer can attach cleanly.

The current runtime also projects:

- `cap-dispatched`
- `cap-executed`

events as a first bridge toward:

- AI-SBOM usage events
- CBOM / continuity walkability
- governance/audit conclusions

It can now also translate receipts back into follow-up caps for bounded
chain execution, so the sketch behaves more like a real continuity
substrate instead of a single-hop runner.

Fork mode now spawns multiple follow-up caps from one parent, making the
chain runner branch rather than only continue linearly.

Each distributed cap now also carries a lane policy so branch children can
be treated differently by a future real `tibet-mux` integration.

Lane policy also now carries an explicit `lane_collision_policy`:

- `graceful_yield`
- `assert_root`
- `override_all`
- `queue`
- `reject`

Naast conflict-policy heeft de sketch nu ook een tweede primitive:
`coffee_lane_policy`, voor avoidance en graceful degradation.

Waarden die nu in de sandbox voorkomen:

- `sip_anyway`
- `polite_avoid`
- `hard_avoid`
- `rebuild`
- `offline_fallback`
- `freeze_resume`
- `fork_on_hop_off`

Daarmee kunnen trust-, outage- en time-diff signalen per event zichtbaar
worden zonder meteen hard in runtimegedrag vast te lopen.

De sandbox vertaalt `resume` nu ook echt naar verschillend vervolggedrag:

- `freeze_resume` -> één `.resume.frozen` follow-up
- `fork_on_hop_off` -> `.resume.catchup` + `.resume.live`
- `rebuild` -> `.resume.rebuild`
- `offline_fallback` -> `.resume.offline`

`resync-needed` and `reject` now route into explicit triage lanes, so
failure and recovery paths are modeled as first-class continuation flows
instead of dead ends.

The sketch can now also export a governance-shaped document that mirrors
the structure used by `tibet-ai-sbom`:

- `governance.questions`
- `governance.trust_foundation`
- `governance.actor_model_provider_links`
- `governance.continuation_graph`
- `governance.usage_events`

And a small CBOM/SoM-shaped document with:

- `cbom.documents`
- `canonical_surface`
- `surface_status`
- `authority`
- `material_facts`
- `continuity`
- `som_events`

`export-all` combines both dialects from the same run so governance and
continuity/object views stay aligned.

The sketch can also emit a `tibet-gateway`-compatible JSONL shape so the
sandbox can act as a direct fixture/data generator for `tibet-ai-sbom`
ingest without adapter glue.

That same lane can now also be validated directly, so future emitters can
test their records before wiring them into `tibet-ai-sbom` or `tibet-audit`.

That event shape now also carries lane-level operational semantics per
record, including:

- `lane_class`
- `lane_collision_policy`
- `preemptible`
- `lane_priority`
- `_emitter`

And the sandbox now ships a first fixture file:

- `fixtures/gateway-event.resume.example.json`

The cap and usage-event models now carry:

- `actor_aint`
- `actor_jis_pubkey`
- `attestation_layer`
- `attestation_ref`

So the runtime can express not only execution and continuation, but also:

- who the actor is in `.aint` terms
- what trust lane the event claims
- where later real JIS attestations can attach

## Future replacement plan

### place

Replace `LamportCausalPlacer` with real `tibet-causal-time`.

### distribute

Replace `IntentMuxDistributor` with real `tibet-mux`.

### inject

Replace `MemorySlotInjector` with real `tibet-store-mmu` / spaceshuttle hooks.

### align

Replace `NoopAligner` with real `tibet-dgx`.

### execute

Replace `EchoExecutor` with:

- agent tools
- service calls
- model invocation
- industrial control adapters

## Short framing

This sketch is not the product. It is the **attachment point** for the product.


## Enterprise

For private hub hosting, SLA support, custom integrations, or compliance guidance:

| | |
|---|---|
| **Enterprise** | enterprise@humotica.com |
| **Support** | support@humotica.com |
| **Security** | security@humotica.com |

## License

MIT

## Credits

Designed by [Jasper van de Meent](https://github.com/jaspertvdm). Built by Jasper and [Root AI](https://humotica.com) as part of [HumoticaOS](https://humotica.com).

---

**Stack-positie:** Groep `agentic` · Bootstrap = OSAPI-handshake naar [`tibet`](https://pypi.org/project/tibet-core/) + [`jis`](https://pypi.org/project/jis-core/) (fail → snaft-rule + tibet-pol-rapport) · ← [`ainternet`](https://pypi.org/project/ainternet/) · [`tibet-triage`](https://pypi.org/project/tibet-triage/) → · See `STACK.md` · See `demo/golden-path/` for the spine end-to-end.
