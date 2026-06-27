"""Conformance for the GPU mailbox core lift (from gravity.aint's reviewed reference).

Covers: waint->offset mapping, Injector protocol, TTL (#42), content-addressed dedup with a
VERIFIED possession receipt, the mandatory-pubkey bypass guard, and JIS prefetch.

    python3 -m pytest packages/tibet-cap-bus/tests/test_gpu_mailbox.py
"""

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tibet_mux.verify import sign_canonical

from tibet_cap_bus.models import Cap
from tibet_cap_bus.gpu_mailbox import (
    ContentAddressedVRAM,
    GPURingBufferInjector,
    JISPrefetcher,
    POSSESSION_RECEIPT_KIND,
    TTLEnforcer,
    datetime_to_unix,
    resolve_waint_block_offset,
)


def test_waint_offset_mapping():
    assert resolve_waint_block_offset("gpu0.p520.waint", 0) == 0
    assert resolve_waint_block_offset("gpu1.p520.waint", 0) == 25 * 2 * 1024 * 1024


def test_injector_protocol_populates_pinned_dma_slot():
    cap = Cap(cap_id="cap_1", actor_id="codex.aint", intent="compute:matrix_mul",
              authority_ref="attest:cap_1", payload={"n": 1024}, executor_class="gpu")
    slot_id, evidence = GPURingBufferInjector().inject(cap, "gpu0.p520.waint", 0)
    assert evidence.status == "slot-populated"
    assert evidence.details["memory_regime"] == "pinned-host-dma-ring"
    assert evidence.details["skips"] == ["cpu-copy"]
    assert slot_id.startswith("gpu_ring_offset:gpu0.p520.waint:")


def test_ttl_enforcer_valid_and_expired():
    ttl = TTLEnforcer()
    now = datetime_to_unix("2026-06-27T10:15:00Z")  # 900s after sent
    ok, _ = ttl.verify_ttl({"sent_at": "2026-06-27T10:00:00Z", "ttl_seconds": 3600}, now=now)
    bad, _ = ttl.verify_ttl({"sent_at": "2026-06-27T10:00:00Z", "ttl_seconds": 10}, now=now)
    assert ok is True and bad is False


def _signed_receipt(content_hash, actor, ts):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes_raw().hex()
    receipt = sign_canonical(
        {"kind": POSSESSION_RECEIPT_KIND, "content_hash": content_hash, "actor": actor, "timestamp": ts},
        priv, sig_field="signature", excluded=("signature",))
    return receipt, pub


def test_dedup_zero_transfer_on_verified_receipt():
    cav = ContentAddressedVRAM()
    block = b"LLM_LAYER_WEIGHTS"
    h = hashlib.sha256(block).hexdigest()
    cav.register_block("gpu1.p520.waint", h)
    now = 1782000000.0
    receipt, pub = _signed_receipt(h, "gpu1.p520.waint", now)
    action, data = cav.verify_and_route(h, "gpu1.p520.waint", receipt, block, target_pubkey=pub, now=now)
    assert action == "zero-transfer-dedup" and data.startswith(b"hash-ptr:")


def test_dedup_missing_pubkey_is_blocked():
    cav = ContentAddressedVRAM()
    block = b"X"; h = hashlib.sha256(block).hexdigest()
    cav.register_block("gpu1.p520.waint", h)
    now = 1782000000.0
    receipt, _ = _signed_receipt(h, "gpu1.p520.waint", now)
    action, data = cav.verify_and_route(h, "gpu1.p520.waint", receipt, block, target_pubkey=None, now=now)
    assert action == "transfer-full-block-missing-pubkey" and data == block  # no bypass path


def test_dedup_forged_signature_is_blocked():
    cav = ContentAddressedVRAM()
    block = b"Y"; h = hashlib.sha256(block).hexdigest()
    cav.register_block("gpu1.p520.waint", h)
    now = 1782000000.0
    receipt, pub = _signed_receipt(h, "gpu1.p520.waint", now)
    receipt["signature"] = "ed25519:" + "00" * 64  # forged
    action, _ = cav.verify_and_route(h, "gpu1.p520.waint", receipt, block, target_pubkey=pub, now=now)
    assert action == "transfer-full-block-invalid-signature"


def test_jis_prefetch_stages_blocks():
    p = JISPrefetcher(GPURingBufferInjector())
    p.queue_prefetch_from_intent("compute:inference:qwen-7b", ["h1", "h2"])
    assert p.run_prefetch() == 2
