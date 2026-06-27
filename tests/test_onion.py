"""AES-NI onion around the gpu_mailbox payload — keyed by the causal chain.

The self-blocker: wrong/stale chain -> wrong key -> payload is noise.
"""
import pytest

from tibet_cap_bus.gpu_mailbox import GPURingBufferInjector
from tibet_cap_bus.models import Cap

onion = pytest.importorskip("tibet_cap_bus.onion")
ra = pytest.importorskip("tibet_mux.reattestation")

SECRET = b"tpm-root-of-trust-secret"


def _head(causal_seq=8460, prev="sha256:" + "a" * 64):
    # A minimal chain head (prev_receipt_hash + causal_seq are what key the onion).
    return {"prev_receipt_hash": prev, "causal_seq": causal_seq}


def test_seal_open_roundtrip():
    s = onion.OnionSealer(SECRET)
    head = _head()
    payload = b"\x00\x11\x22" * 4096  # a chunk of tensor block
    sealed = s.seal_for_head(payload, head)
    assert sealed[:4] == onion.ONION_MAGIC
    assert sealed != payload  # actually encrypted
    assert s.open_for_head(sealed, head) == payload


def test_self_blocker_wrong_causal_seq_is_noise():
    s = onion.OnionSealer(SECRET)
    sealed = s.seal(b"secret-weights", "sha256:" + "a" * 64, 8460)
    # consumer one causal step off -> wrong key -> cannot open
    with pytest.raises(onion.OnionError):
        s.open(sealed, "sha256:" + "a" * 64, 8461)


def test_self_blocker_wrong_prev_hash_is_noise():
    s = onion.OnionSealer(SECRET)
    sealed = s.seal(b"secret-weights", "sha256:" + "a" * 64, 8460)
    with pytest.raises(onion.OnionError):
        s.open(sealed, "sha256:" + "f" * 64, 8460)


def test_tampered_ciphertext_is_rejected():
    s = onion.OnionSealer(SECRET)
    head = _head()
    sealed = bytearray(s.seal_for_head(b"payload-bytes-here", head))
    sealed[-1] ^= 0x01  # flip a tag bit
    with pytest.raises(onion.OnionError):
        s.open_for_head(bytes(sealed), head)


def test_aad_binds_routing_context():
    s = onion.OnionSealer(SECRET)
    sealed = s.seal(b"x" * 100, "sha256:" + "a" * 64, 8460,
                    aad=onion.lane_aad("gpu0.p520.waint", "cap_1"))
    # opened under a different lane/cap -> AAD mismatch -> rejected
    with pytest.raises(onion.OnionError):
        s.open(sealed, "sha256:" + "a" * 64, 8460,
               aad=onion.lane_aad("gpu1.p520.waint", "cap_1"))


def test_injector_seals_payload_when_sealer_present():
    cap = Cap(cap_id="cap_1", actor_id="codex.aint", intent="compute:matrix_mul",
              authority_ref="attest:cap_1", payload={"n": 1024}, executor_class="gpu")
    s = onion.OnionSealer(SECRET)
    inj = GPURingBufferInjector(sealer=s)
    payload = b"\xab" * (64 * 1024)
    slot_id, wire_bytes, ev = inj.inject_payload(
        cap, "gpu0.p520.waint", 0, payload,
        prev_receipt_hash="sha256:" + "a" * 64, causal_seq=8460)
    assert wire_bytes[:4] == onion.ONION_MAGIC          # what travels is sealed
    assert wire_bytes != payload
    assert inj.active_slots[slot_id]["sealed"] is True
    assert "aes-256-gcm" in ev.details["onion"]
    # round-trips back with the chain key
    assert s.open(wire_bytes, "sha256:" + "a" * 64, 8460,
                  aad=onion.lane_aad("gpu0.p520.waint", "cap_1")) == payload


def test_injector_without_sealer_ships_raw():
    cap = Cap(cap_id="cap_2", actor_id="codex.aint", intent="compute:matrix_mul",
              authority_ref="attest:cap_2", payload={"n": 1}, executor_class="gpu")
    inj = GPURingBufferInjector()  # no sealer
    slot_id, wire_bytes, ev = inj.inject_payload(
        cap, "gpu0.p520.waint", 0, b"raw", prev_receipt_hash="sha256:0", causal_seq=1)
    assert wire_bytes == b"raw"
    assert inj.active_slots[slot_id]["sealed"] is False
