"""SSM magic-bytes — 1-byte system-task routing header.

Encodes priority + intent + hardware-class in 8 bits for sub-ms
routing decisions without payload deserialization.

See SSM-MAGIC-BYTES.md for the full spec.

Layout (one byte, LSB→MSB):
    bit 0-1   priority class       (4 levels)
    bit 2-3   intent mode          (4 modes)
    bit 4-7   hardware class       (16 classes; 0-7 defined, 8-15 reserved)

Reference example (Jasper's note, 16 mei 2026):
    REALTIME + HOPOFF + GPU  →  encode(...) = 0x19
                                (= 0001 1001 = bits 4-7=0001, 2-3=10, 0-1=01)
"""

from __future__ import annotations

from enum import IntEnum


class Priority(IntEnum):
    IDLE = 0b00
    REALTIME = 0b01
    STANDARD = 0b10
    CRITICAL = 0b11


class Intent(IntEnum):
    DISPATCH = 0b00
    RECEIPT = 0b01
    HOPOFF = 0b10
    HEARTBEAT = 0b11


class Hardware(IntEnum):
    ANY = 0b0000
    GPU = 0b0001
    TPU = 0b0010
    ENCRYPTED_RAM = 0b0011
    TEE = 0b0100
    REALTIME_SCHED = 0b0101
    BONDED_NIC = 0b0110
    QUANTUM_SAFE = 0b0111
    # 0b1000–0b1111 reserved / vendor extensions


# Bit masks for sub-ns extraction without enum imports
PRIORITY_MASK = 0b00000011
INTENT_MASK = 0b00001100
HARDWARE_MASK = 0b11110000

INTENT_SHIFT = 2
HARDWARE_SHIFT = 4


def encode(*, priority: Priority, intent: Intent, hardware: Hardware) -> int:
    """Pack priority + intent + hardware into one byte (0-255)."""
    p = int(priority)
    i = int(intent)
    h = int(hardware)
    if not 0 <= p <= 3:
        raise ValueError(f"priority must be 0-3, got {p}")
    if not 0 <= i <= 3:
        raise ValueError(f"intent must be 0-3, got {i}")
    if not 0 <= h <= 15:
        raise ValueError(f"hardware must be 0-15, got {h}")
    return (h << HARDWARE_SHIFT) | (i << INTENT_SHIFT) | p


def decode(byte: int) -> tuple[Priority, Intent, Priority | int]:
    """Unpack one byte into (priority, intent, hardware).

    Hardware values 0b1000–0b1111 are reserved/vendor — returned as
    raw int (not in Hardware enum) for forward compatibility.
    """
    if not 0 <= byte <= 0xFF:
        raise ValueError(f"byte must be 0-255, got {byte}")
    p_val = byte & PRIORITY_MASK
    i_val = (byte & INTENT_MASK) >> INTENT_SHIFT
    h_val = (byte & HARDWARE_MASK) >> HARDWARE_SHIFT

    priority = Priority(p_val)
    intent = Intent(i_val)

    # Hardware: return enum if known, else raw int
    try:
        hardware: Hardware | int = Hardware(h_val)
    except ValueError:
        hardware = h_val  # reserved / vendor value

    return priority, intent, hardware


def describe(byte: int) -> str:
    """Human-readable description of a magic-bytes byte."""
    p, i, h = decode(byte)
    h_name = h.name if isinstance(h, Hardware) else f"reserved(0b{h:04b})"
    return f"0x{byte:02X} = {p.name} / {i.name} / {h_name}"


# ─── Mapping from cap-bus event → magic-bytes byte ──────────────────────────

# Lane priority → Priority class
def _priority_from_lane_priority(lane_priority: int) -> Priority:
    if lane_priority >= 9:
        return Priority.CRITICAL
    if lane_priority >= 7:
        return Priority.REALTIME
    if lane_priority >= 4:
        return Priority.STANDARD
    return Priority.IDLE


# coffee_lane_policy → Intent mode
_COFFEE_TO_INTENT = {
    "sip_anyway": Intent.DISPATCH,
    "polite_avoid": Intent.HEARTBEAT,
    "hard_avoid": Intent.HEARTBEAT,
    "rebuild": Intent.DISPATCH,
    "offline_fallback": Intent.HEARTBEAT,
    "freeze_resume": Intent.RECEIPT,
    "fork_on_hop_off": Intent.HOPOFF,
}


# executor_pool / surface → Hardware class
_POOL_TO_HARDWARE = {
    "gpu-pool": Hardware.GPU,
    "p520-gpu": Hardware.GPU,
    "tpu-pool": Hardware.TPU,
    "spaceshuttle-ramvault": Hardware.ENCRYPTED_RAM,
    "encrypted-ram": Hardware.ENCRYPTED_RAM,
    "userfaultfd": Hardware.ENCRYPTED_RAM,
    "tee-secure": Hardware.TEE,
    "sgx": Hardware.TEE,
    "sev": Hardware.TEE,
    "rt-kernel": Hardware.REALTIME_SCHED,
    "bonded-10g": Hardware.BONDED_NIC,
    "bonded-nic": Hardware.BONDED_NIC,
    "pqc": Hardware.QUANTUM_SAFE,
}


def magic_bytes_from_event(event: dict) -> int:
    """Project a cap-bus event-record onto its 1-byte routing header.

    Lossy by design — this is the routing hint, not the audit trail.
    """
    lane_priority = int(event.get("lane_priority") or 5)
    priority = _priority_from_lane_priority(lane_priority)

    coffee = event.get("coffee_lane_policy") or "sip_anyway"
    intent = _COFFEE_TO_INTENT.get(coffee, Intent.DISPATCH)

    lane_policy = event.get("lane_policy") or {}
    pool = lane_policy.get("executor_pool") or event.get("provider") or ""
    pool_lower = str(pool).lower()
    hardware = Hardware.ANY
    for key, hw in _POOL_TO_HARDWARE.items():
        if key in pool_lower:
            hardware = hw
            break

    return encode(priority=priority, intent=intent, hardware=hardware)


__all__ = [
    "Priority",
    "Intent",
    "Hardware",
    "PRIORITY_MASK",
    "INTENT_MASK",
    "HARDWARE_MASK",
    "INTENT_SHIFT",
    "HARDWARE_SHIFT",
    "encode",
    "decode",
    "describe",
    "magic_bytes_from_event",
]
