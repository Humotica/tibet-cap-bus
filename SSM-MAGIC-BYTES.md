# SSM Magic-Bytes — System-Task Routing Header

**Status:** Draft v0.1 (proposed extension to SSM filename-surface contract)
**Date:** 2026-05-16
**Authors:** Jasper van de Meent, Root AI (Claude)

---

## Abstract

Defines a **one-byte routing header** for system-tasks in the TIBET
substrate (cap-bus, mux, gateway, airlock). The header encodes
priority, intent, and hardware-class in 8 bits, allowing sub-millisecond
routing decisions **without deserializing the sealed payload**.

This is the system-task companion to SSM's filename-surface contract:

> Filename for messages. Magic-bytes for system tasks.

---

## Motivation

The filename-surface contract handles **named** routing (cmail,
human-addressable agents). System-tasks (cap-bus events, mux routing,
airlock dispatch) need:

- **Sub-ms classification** for high-throughput routing
- **Pre-parse decisions** that preserve sealed-state crypto invariants
- **Lane assignment** before reading payload bytes

A 1-byte header encodes 3 orthogonal dimensions in 256 possible values.

---

## Specification

### Layout

A single octet placed **immediately after** the 4-byte TIBET magic
bytes (`0xTI 0xBE 0xT0 0x01` or similar — see `tibet-zip` spec) and
**before** the envelope identifier:

```
+----+----+----+----+ +----------+ +---------------+ +-----------+
| T  | I  | B  | E  | | route    | | envelope_id   | | payload   |
+----+----+----+----+ +----------+ +---------------+ +-----------+
   4 bytes magic       1 byte SSM    variable          rest
                       header (NEW)
```

### Bit layout — one byte

```
  MSB                                                           LSB
   7    6    5    4    3    2    1    0
 +----+----+----+----+----+----+----+----+
 |  HARDWARE CLASS   |  INTENT  | PRIO   |
 +----+----+----+----+----+----+----+----+
```

| Bits | Field             | Values |
|------|-------------------|--------|
| 0-1  | Priority class    | 4 levels (idle/real-time/standard/critical) |
| 2-3  | Intent mode       | 4 modes (dispatch/receipt/hop-off/heartbeat) |
| 4-7  | Hardware class    | 16 classes (any/GPU/TPU/encrypted-RAM/TEE/...) |

### Priority (bits 0-1)

| Value | Class            | Use case                                  |
|-------|------------------|-------------------------------------------|
| `00`  | Idle / batch     | Background jobs, log archives             |
| `01`  | Real-time        | Latency-critical (`<1 ms` target)         |
| `10`  | Standard         | Default interactive (e.g., chat)          |
| `11`  | Critical         | System-critical, blocking (= rare)        |

### Intent (bits 2-3)

| Value | Mode             | Semantics                                 |
|-------|------------------|-------------------------------------------|
| `00`  | Cap-dispatch     | New instruction entering the bus          |
| `01`  | Receipt          | Execution result returning                |
| `10`  | Hop-off          | Resume with world-diff (= fork_on_hop_off)|
| `11`  | Heartbeat        | Liveness / no-op signal                   |

### Hardware (bits 4-7) — 16 classes

| Value  | Class                          | Routing hint                       |
|--------|--------------------------------|-------------------------------------|
| `0000` | No special requirement         | Any executor                        |
| `0001` | GPU required                   | Route to GPU-enabled node (e.g., P520)|
| `0010` | TPU / accelerator              | Route to TPU pool                   |
| `0011` | Encrypted memory (spaceshuttle)| Route to userfaultfd RAM-aware node |
| `0100` | TEE (SGX/SEV)                  | Trusted execution environment      |
| `0101` | Real-time scheduler            | RT kernel host                      |
| `0110` | Bonded NIC (10 Gbps+)          | Route via bonded uplink            |
| `0111` | Quantum-safe path              | PQC cipher suite required           |
| `1000-1111` | Reserved / vendor extensions | (see **Lifecycle band** below)     |

---

## Lifecycle band (reboot / shutdown / logout)

The reserved hardware band `1000–1111` carries **host-lifecycle transitions** — but
only on the **HEARTBEAT** intent channel (bits 2-3 = `11`), the liveness channel that
already carries `offline_fallback`. In any other intent the same nibble is an ordinary
reserved/vendor hardware value; the recognizer returns `None`.

| Byte   | Intent    | Band   | Action     | Relationship effect                           |
|--------|-----------|--------|------------|-----------------------------------------------|
| `0x8C` | HEARTBEAT | `1000` | `REBOOT`   | down, returning — peer holds the relation warm, expects re-attest |
| `0x9C` | HEARTBEAT | `1001` | `SHUTDOWN` | graceful absence, no promised return — cold, relation intact |
| `0xAC` | HEARTBEAT | `1010` | `LOGOUT`   | identity/coupling detaches; the host may stay powered |
| `1011–1111` | HEARTBEAT | — | *(spare lifecycle)* | reserved |

Canonical bytes pin priority bits `00`; priority is an orthogonal routing axis the
recognizer ignores, so a caller may raise it without changing what the byte means.

### Invariant — **header may hold, never decide**

These bytes are **non-authoritative routing hints**. A carrier / relay / app / lower
matroshka layer may *see* one and **hold** (start a warm-hold timer, pre-colour a tick)
but MUST NOT enact host-lifecycle from the plaintext byte. Enactment is authorised only
when the receiving layer's:

- **floor** grants lifecycle handling at all (a pure envelope-carrier's floor does not), **and**
- it holds a **mandate to act**: a live **presence posture** OR an **`on_behalf_of`** delegation.

Anything else stays a HINT. Even when authorised, the byte still does not decide — the
actual transition travels as a **sealed ledger/CLI record** (and `REBOOT` additionally
passes the SNAFT `sys_reboot` syscall-risk gate). This is precisely what stops a layer
that should only carry envelopes from suddenly "understanding" reboot/shutdown/logout.

Reference: `resolve_lifecycle()` in `ssm_magic.py` returns `NOT_LIFECYCLE` / `HOLD` /
`ACT` and encodes exactly this gate. The status itself lives in the 16-bit MUX frame
(`0x4000` alive / `0x0000:reason` dark); the SSM byte only routes.

---

## Examples

### Real-time GPU inference

```
Bit 0-1 = 01 (Real-time)
Bit 2-3 = 00 (Cap-dispatch)
Bit 4-7 = 0001 (GPU)

Binary: 0001 0001
Hex:    0x11
```

### Hop-off resume on encrypted-RAM node

```
Bit 0-1 = 10 (Standard)
Bit 2-3 = 10 (Hop-off)
Bit 4-7 = 0011 (Encrypted memory)

Binary: 0011 1010
Hex:    0x3A
```

### Idle batch — no requirements

```
Bit 0-1 = 00 (Idle)
Bit 2-3 = 00 (Cap-dispatch)
Bit 4-7 = 0000 (Any)

Binary: 0000 0000
Hex:    0x00
```

---

## Routing implications

The header allows **decision in O(1)** with one byte read:

```python
header = first_byte
priority = header & 0b00000011
intent   = (header >> 2) & 0b00000011
hardware = (header >> 4) & 0b00001111

if priority == REALTIME and hardware == GPU:
    route("p520-gpu-lane")
elif intent == HOPOFF:
    route("resume-catchup-lane")
elif hardware == ENCRYPTED_RAM:
    route("phantom-vm-warm-pool")
else:
    route("default-lane")
```

This is **sub-ms even on commodity CPUs** — bitwise ops are nanoseconds.

---

## Mapping to cap-bus event fields

When a cap-bus event is emitted alongside, the magic-bytes byte is the
**compact classification** of these JSON fields:

| Magic-bytes bit  | Cap-event field                       |
|------------------|----------------------------------------|
| Priority         | `lane_priority` + `lane_class`         |
| Intent           | `coffee_lane_policy` (= mode hint)     |
| Hardware         | `executor_pool` (= GPU/TEE/RAM/…)      |

The header is a **lossy projection** of the full event — sufficient
for routing, not for audit. Audit reads the sealed event-record.

---

## Compatibility

- **.tza v1 readers** that don't know the header MAY skip it via the
  4-byte magic mismatch (= use new magic for v2).
- **.tza v2 readers** MUST honor the header for routing decisions.
- **Legacy systems** that don't speak magic-bytes can still route via
  filename-surface (= unchanged).

This is an **additive** extension — no breaking changes for v1.

---

## Open questions

1. Should bits 4-7 be expanded to a full byte for >16 hardware classes?
2. Where does the header live for non-TBZ formats (e.g., bare event-records)?
3. Should bit 7 be reserved as a "extended header follows" flag for 2+ byte variants?

---

## Reference implementation

See `/srv/jtel-stack/packages/tibet-cap-bus/src/tibet_cap_bus/ssm_magic.py`
for encoder/decoder + value enums.

See `/srv/jtel-stack/packages/tibet-cap-bus/tests/test_ssm_magic.py`
for unit tests.

---

## Cross-refs

- IETF SSM draft: `tibet-semantic-surface-manifest-01` (= candidate §X)
- Memory: `feedback_one_cap_bus_multiple_execution_lanes_16_mei.md`
- Memory: `project_ssm_magic_bytes_system_task_header_16_mei.md`
