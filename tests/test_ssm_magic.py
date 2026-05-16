"""Tests for SSM magic-bytes header (= 1-byte system-task routing)."""

import pytest

from tibet_cap_bus.ssm_magic import (
    Priority,
    Intent,
    Hardware,
    encode,
    decode,
    describe,
    magic_bytes_from_event,
)


class TestEncodeDecodeRoundtrip:
    """encode → decode → encode invariant for every combination."""

    def test_all_combinations_roundtrip(self):
        for p in Priority:
            for i in Intent:
                for h in Hardware:
                    byte = encode(priority=p, intent=i, hardware=h)
                    p2, i2, h2 = decode(byte)
                    assert p2 == p
                    assert i2 == i
                    assert h2 == h

    def test_byte_in_valid_range(self):
        for p in Priority:
            for i in Intent:
                for h in Hardware:
                    byte = encode(priority=p, intent=i, hardware=h)
                    assert 0 <= byte <= 0xFF


class TestSpecExamples:
    """Examples from SSM-MAGIC-BYTES.md."""

    def test_realtime_gpu_dispatch(self):
        byte = encode(
            priority=Priority.REALTIME,
            intent=Intent.DISPATCH,
            hardware=Hardware.GPU,
        )
        assert byte == 0x11  # 0001 0001

    def test_hopoff_encrypted_ram_standard(self):
        byte = encode(
            priority=Priority.STANDARD,
            intent=Intent.HOPOFF,
            hardware=Hardware.ENCRYPTED_RAM,
        )
        assert byte == 0x3A  # 0011 1010

    def test_idle_batch_any(self):
        byte = encode(
            priority=Priority.IDLE,
            intent=Intent.DISPATCH,
            hardware=Hardware.ANY,
        )
        assert byte == 0x00

    def test_jasper_voorbeeld_realtime_hopoff_gpu(self):
        """Jasper's brainstorm 16 mei: real-time + hop-off + GPU.

        Note: Jasper's note said 0x61 but with the canonical
        LSB→MSB layout (priority in lowest 2 bits, hardware in
        highest 4 bits), this combination yields 0x19:
            0001 1001 = 0001 (GPU<<4) | 10 (HOPOFF<<2) | 01 (REALTIME)

        The 0x61 value would imply a different bit-ordering.
        We use the canonical LSB layout for clarity and tooling.
        """
        byte = encode(
            priority=Priority.REALTIME,
            intent=Intent.HOPOFF,
            hardware=Hardware.GPU,
        )
        assert byte == 0x19  # 0001 1001 (canonical LSB layout)


class TestBoundaries:

    def test_max_byte(self):
        byte = encode(
            priority=Priority.CRITICAL,
            intent=Intent.HEARTBEAT,
            hardware=Hardware.QUANTUM_SAFE,
        )
        assert byte == 0x7F  # 0111 1111

    def test_invalid_priority_raises(self):
        with pytest.raises(ValueError):
            encode(priority=4, intent=Intent.DISPATCH, hardware=Hardware.ANY)  # type: ignore[arg-type]

    def test_byte_out_of_range_raises(self):
        with pytest.raises(ValueError):
            decode(0x100)
        with pytest.raises(ValueError):
            decode(-1)


class TestDecodeReservedVendorBits:
    """Bits 4-7 values 8-15 are reserved; decode returns raw int."""

    def test_reserved_vendor_hardware_returns_int(self):
        # 0xF0 = hardware bits = 1111, priority=00, intent=00
        priority, intent, hardware = decode(0xF0)
        assert priority == Priority.IDLE
        assert intent == Intent.DISPATCH
        # Hardware enum doesn't define 0b1111, so we get raw int
        assert hardware == 15
        assert not isinstance(hardware, Hardware)


class TestDescribe:

    def test_describe_format(self):
        # 0x61 in canonical layout = REALTIME / DISPATCH / BONDED_NIC
        # (priority=01, intent=00, hardware=0110)
        text = describe(0x61)
        assert "0x61" in text
        assert "REALTIME" in text
        assert "DISPATCH" in text
        assert "BONDED_NIC" in text

    def test_describe_jasper_intended(self):
        # REALTIME+HOPOFF+GPU under canonical layout = 0x19
        text = describe(0x19)
        assert "0x19" in text
        assert "REALTIME" in text
        assert "HOPOFF" in text
        assert "GPU" in text


class TestEventProjection:

    def test_realtime_gpu_event(self):
        event = {
            "lane_priority": 8,
            "coffee_lane_policy": "sip_anyway",
            "lane_policy": {"executor_pool": "gpu-pool"},
        }
        byte = magic_bytes_from_event(event)
        # priority=8 → REALTIME, sip_anyway → DISPATCH, gpu-pool → GPU
        assert byte == 0x11

    def test_hopoff_event(self):
        event = {
            "lane_priority": 5,
            "coffee_lane_policy": "fork_on_hop_off",
            "lane_policy": {"executor_pool": "agent-burst"},
        }
        byte = magic_bytes_from_event(event)
        # priority=5 → STANDARD, fork_on_hop_off → HOPOFF, agent-burst → ANY
        priority, intent, hardware = decode(byte)
        assert priority == Priority.STANDARD
        assert intent == Intent.HOPOFF
        assert hardware == Hardware.ANY

    def test_critical_tee_event(self):
        event = {
            "lane_priority": 10,
            "coffee_lane_policy": "sip_anyway",
            "lane_policy": {"executor_pool": "tee-secure"},
        }
        byte = magic_bytes_from_event(event)
        priority, intent, hardware = decode(byte)
        assert priority == Priority.CRITICAL
        assert intent == Intent.DISPATCH
        assert hardware == Hardware.TEE

    def test_freeze_resume_maps_to_receipt(self):
        event = {
            "lane_priority": 5,
            "coffee_lane_policy": "freeze_resume",
            "lane_policy": {},
        }
        byte = magic_bytes_from_event(event)
        _, intent, _ = decode(byte)
        assert intent == Intent.RECEIPT

    def test_offline_fallback_maps_to_heartbeat(self):
        event = {
            "lane_priority": 3,
            "coffee_lane_policy": "offline_fallback",
            "lane_policy": {},
        }
        byte = magic_bytes_from_event(event)
        _, intent, _ = decode(byte)
        assert intent == Intent.HEARTBEAT

    def test_encrypted_ram_pool(self):
        event = {
            "lane_priority": 7,
            "coffee_lane_policy": "sip_anyway",
            "lane_policy": {"executor_pool": "spaceshuttle-ramvault"},
        }
        byte = magic_bytes_from_event(event)
        _, _, hardware = decode(byte)
        assert hardware == Hardware.ENCRYPTED_RAM


class TestBitwiseRouting:
    """Routing decisions can use bitwise ops without enum import."""

    def test_priority_extract_realtime(self):
        # encode(REALTIME, ANY, ANY) → 0x01
        byte = encode(priority=Priority.REALTIME, intent=Intent.DISPATCH, hardware=Hardware.ANY)
        assert byte == 0x01
        assert (byte & 0b00000011) == 0b01

    def test_intent_extract_hopoff(self):
        byte = encode(priority=Priority.IDLE, intent=Intent.HOPOFF, hardware=Hardware.ANY)
        assert ((byte & 0b00001100) >> 2) == Intent.HOPOFF.value

    def test_hardware_extract(self):
        byte = encode(
            priority=Priority.IDLE,
            intent=Intent.DISPATCH,
            hardware=Hardware.GPU,
        )
        assert ((byte & 0b11110000) >> 4) == Hardware.GPU.value
