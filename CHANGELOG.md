# Changelog — tibet-cap-bus

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.1] — 2026-05-16

### Added

#### SSM Magic-Bytes (1-byte system-task routing header)

New module `tibet_cap_bus.ssm_magic` implements the spec in
`SSM-MAGIC-BYTES.md`:

- **`Priority` enum** — 4 levels (IDLE/REALTIME/STANDARD/CRITICAL)
- **`Intent` enum** — 4 modes (DISPATCH/RECEIPT/HOPOFF/HEARTBEAT)
- **`Hardware` enum** — 16 classes (ANY/GPU/TPU/ENCRYPTED_RAM/TEE/...)
- **`encode(priority, intent, hardware)`** → byte (0-255)
- **`decode(byte)`** → (Priority, Intent, Hardware|int)
- **`describe(byte)`** → human-readable string
- **`magic_bytes_from_event(event)`** → lossy projection from cap-bus event

Allows **sub-ms routing decisions** without payload deserialization
via 1-byte bitwise extraction:

```python
priority = byte & 0b00000011
intent   = (byte >> 2) & 0b00000011
hardware = (byte >> 4) & 0b00001111
```

Poster:

> Filename for messages. Magic-bytes for system tasks.
> One byte, three dimensions, sub-ms routing.

#### Test coverage

- 21 new tests for `ssm_magic` (encode/decode roundtrip, spec examples,
  boundaries, event projection, bitwise routing)
- **Total package tests: 37 passing**

### Spec

- `SSM-MAGIC-BYTES.md` — full specification, candidate §X for
  IETF SSM-draft `tibet-semantic-surface-manifest-01`

---

## [0.1.0] — 2026-05-16

First production release. Migrated from sandbox sketch
(`sandbox/ai/codex/tibet-cap-bus-sketch/`) to packages tree.

### Added

#### Core runtime

- Six-phase pipeline: **sender → place → distribute → inject → align → execute**
- `Cap`, `LanePolicy`, `PhaseEvidence`, `UsageEvent`, `CapReceipt`, `DistributedCap`, `ExecutionResult` data models
- Branching continuations: `receipt` / `continue` / `fork` (alpha/beta) / `resync-needed` / `reject`
- In-memory stand-ins for causal-time / mux / spaceshuttle / dgx

#### Lane policies

- **`lane_collision_policy`** — conflict resolution when actors meet a lane:
  - `graceful_yield` / `assert_root` / `override_all` / `queue` / `reject`
- **`coffee_lane_policy`** — avoidance / degradation / resume policy:
  - `sip_anyway` / `polite_avoid` / `hard_avoid` / `rebuild` / `offline_fallback`
  - `freeze_resume` (= time-diff < 60s, frozen-continuity restore)
  - `fork_on_hop_off` (= 60s < diff < 3600s, world-aware catchup)

#### Resume semantics (paper #6 frame as runtime)

- `continuation_mode=resume` is now translated runtime-wise through `coffee_lane_policy`
- `freeze_resume` spawns one `.resume.frozen` follow-up (= "as if nothing changed")
- `fork_on_hop_off` spawns two follow-ups: `.resume.catchup` + `.resume.live`
- `rebuild` spawns `.resume.rebuild`
- `offline_fallback` spawns `.resume.offline`
- `polite_avoid` / `hard_avoid` terminate follow-up
- Each follow-up lives in its own sub-lane: `lane:<intent>.resume.<mode>:<class>`

#### Event contract

- `tibet-cap-bus.gateway-event.v1` contract specification
- 18 required fields per event-record
- Enum validation for `route_class`, `lane_collision_policy`, `coffee_lane_policy`, `attestation_layer`
- Numeric + type validation for optional fields
- Reference fixture: `fixtures/gateway-event.resume.example.json`

#### Adapters (Protocol layer)

- `CausalPlacer` — assigns causal rank
- `Distributor` — assigns lane / channel
- `Injector` — places cap into executor-bound memory slot
- `Aligner` — computes cluster alignment
- `Executor` — executes cap and returns receipt
- Drop-in interface for production replacements (tibet-mux, tibet-causal-time, tibet-store-mmu, tibet-dgx, tibet-phantom)

#### CLI

- `tibet-cap-bus demo` — basic end-to-end demo
- `tibet-cap-bus emit` — single cap through draft runtime
- `tibet-cap-bus trace` — compact trace + usage events
- `tibet-cap-bus chain` — bounded continuation chain
- `tibet-cap-bus triage` — reject / resync-needed into explicit triage lanes
- `tibet-cap-bus resume` — time-diff-aware resume semantics
- `tibet-cap-bus gateway-export --source <demo|chain|triage|resume> [--json]`
- `tibet-cap-bus governance-export --source <...>` (tibet-ai-sbom usage shape)
- `tibet-cap-bus cbom-export --source <...>` (CBOM/SoM shape)
- `tibet-cap-bus export-all --source <...>` (combined governance + CBOM)
- `tibet-cap-bus validate-gateway-event [--source ...] [--input <path>]`
- Alias: `cap-stream` (= same entry-point)

#### Integration

- `tibet-ai-sbom` gateway-ingest reads `coffee_lane_policy`, `coffee_reason`, `time_diff_seconds`, `diff_threshold_seconds`
- Actor/provider surface views retain **strongest** coffee policy across multiple events (= root `fork_on_hop_off` not overwritten by later `sip_anyway`)
- `tibet-audit` hook `evaluate_coffee_lane(...)` + `build_governance_conclusion(...)` returns `coffee_lane_recommendation`

### Tests

- 16 runtime tests
- 3 tibet-ai-sbom gateway-ingest tests
- 4 tibet-audit governance tests
- **23 tests total, all passing**

---

## Notes on positioning

This is a production release of what started as a sandbox sketch. The architecture is intentionally minimal and clean — in-memory stubs for causal-time, mux, spaceshuttle, and dgx are placeholders. Real implementations plug in via the `adapters.py` Protocol interface.

Sister packages in this release cycle:

- `tibet-ai-sbom 0.2.0` — gateway-ingest reads cap-bus event shape
- `tibet-gateway 0.4.0` — sovereign external API proxy aligned to event-contract
- `tibet-audit 0.24.1` — governance conclusion with `coffee_lane_recommendation`

### Poster lines

> `lane_collision_policy` decides what happens when actors meet.
> `coffee_lane_policy` decides what happens when they should not.

> Continuity is not a buzzword. It is a primitive with two semantics:
> frozen-resume and fork-on-hop-off, both verifiable, both auditable.
