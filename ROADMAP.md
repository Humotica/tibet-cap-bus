# Roadmap — tibet-cap-bus

This roadmap is a living document. Order ≠ commitment; priorities shift as the substrate matures.

---

## 0.1.x — stabilization

- Documentation polish for production framing
- Additional fixture variants (chain, triage, fork-on-hop-off, freeze-resume)
- Integration tests against `tibet-ai-sbom` and `tibet-audit` releases
- Performance baseline measurements (cap throughput, lane-policy decision latency)

## 0.2.x — Protocol-adapter realizations

Drop-in real-world implementations behind the `adapters.py` Protocol contracts:

- `CausalPlacer` → real `tibet-causal-time` integration (Lamport-grounded)
- `Distributor` → real `tibet-mux` integration (intent-based lane fan-out)
- `Injector` → real `tibet-store-mmu` integration (encrypted RAM slots, spaceshuttle)
- `Aligner` → real `tibet-dgx` integration (cluster alignment)
- `Executor` → pluggable real executors (tibet-phantom, brain-api, factory-AI, etc.)

## 0.3.x — Real emitters

Live emitter integration for production services:

- `brain_api` cap emission for `/api/ipoll`, `/api/phantom`, BYOK provider dispatch
- `service_api` cap emission for tool-routing decisions
- `telecom_api` cap emission for cmail handoffs
- `tibet-gateway` cap emission for external API proxy events

## 0.4.x — Observability + audit

- Cap-stream visualization tools (TUI + web)
- CBOM walk-back for cap chains (continuity bill of materials)
- Audit-trail export to W3C Verifiable Credentials
- Long-term retention + compression strategies for cap-stream storage

## 0.5.x — Multi-tenant + federation

- Tenant-isolated cap-stream channels with `coffee_lane_policy` per tenant
- Federation across AInternet nodes (cap-stream over `tibet-mux:443`)
- Cross-organization cap signing + JIS-DID attestation chains

## Looking further

- Spec-level IETF draft (`tibet-cap-bus-00.md` — already drafted, push to datatracker after 0.2.x)
- W3C alignment for cap-as-verifiable-credential interoperability
- Conformance vectors package (`tibet-conformance-vectors`) extensions for cap-bus
- Real-time cap-stream introspection for `tibet-twin` digital-twin drift detection

---

## Companion packages

- `tibet-ai-sbom` reads cap-bus events for governance projection
- `tibet-audit` reads cap-bus events for compliance conclusion
- `tibet-gateway` emits cap-bus events for external API observation
- `tibet-phantom` will emit cap-bus events for session seal / materialize / launch / evaporate (= post-Marco work, task #121)

## Reference frame

The paper-grade frame behind this work:

> **"Two Resume Semantics for Sealed Causal Sessions:**
> **Frozen-Continuity vs Fork-On-Hop-Off in Distributed AI Systems"**

This roadmap operationalizes that frame into a working substrate.
