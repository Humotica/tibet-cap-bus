"""GPU mailbox — the cap-bus Injector + content-addressed dedup for the .caint GPU lane.

Lifted from gravity.aint's reviewed sandbox reference (gpu_mailbox_engine.py) into core,
after a 3-round review (build -> possession-receipt signature-verify -> mandatory-pubkey
hardening). The crypto is single-source: signatures verify through tibet_mux.verify
(verify_canonical / sign_canonical) — no second serializer, no local verifier.

Components:
  - resolve_waint_block_offset : address gpu0/gpu1.p520.waint -> block offset in the 100MB ring
  - GPURingBufferInjector       : cap-bus Injector protocol (pinned-host-DMA ring slots)
  - TTLEnforcer                 : cmail capsule expiry (task #42)
  - PossessionReceipt + ContentAddressedVRAM : zero-transfer dedup, gated on a *verified* receipt
  - JISPrefetcher               : intent-driven pre-staging (physical-staged != pre-authorized)

Design & authorship: gravity.aint (reference) + Root AI (core lift + fail-closed hardening).
Part of the TIBET ecosystem / AInternet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .models import Cap, PhaseEvidence

# Single source for canonical bytes + Ed25519 verify. If tibet-mux is unavailable the GPU
# mailbox stays importable, but the dedup fast-path FAILS CLOSED (never skips a transfer it
# cannot cryptographically verify).
try:
    from tibet_mux.verify import sign_canonical, verify_canonical
    _HAVE_VERIFIER = True
except Exception:  # pragma: no cover - environment without tibet-mux installed
    sign_canonical = None  # type: ignore
    verify_canonical = None  # type: ignore
    _HAVE_VERIFIER = False


# ─────────────────────────────────────────────────────────────────
# 1. Address-to-offset mapping (100MB ring = 50 x 2MB blocks)
# ─────────────────────────────────────────────────────────────────

RING_SIZE_MIB = 100
BLOCK_SIZE_MIB = 2
MAX_BLOCKS = RING_SIZE_MIB // BLOCK_SIZE_MIB  # 50 blocks

WAINT_TO_OFFSET = {
    "gpu0.p520.waint": 0,               # block index 0..24 (first 50MB)
    "gpu1.p520.waint": MAX_BLOCKS // 2,  # block index 25..49 (second 50MB)
}


def resolve_waint_block_offset(waint_actor: str, causal_rank: int) -> int:
    """Resolve a waint address to a byte offset inside the ring-buffer."""
    base_offset = WAINT_TO_OFFSET.get(waint_actor)
    if base_offset is None:
        raise ValueError(f"Unknown waint actor: {waint_actor}")
    actor_segment_size = MAX_BLOCKS // 2
    block_index = base_offset + (causal_rank % actor_segment_size)
    return block_index * BLOCK_SIZE_MIB * 1024 * 1024


# ─────────────────────────────────────────────────────────────────
# 2. GPURingBufferInjector — cap-bus Injector protocol
# ─────────────────────────────────────────────────────────────────

class GPURingBufferInjector:
    """Inject a cap into the pinned-host-DMA GPU ring buffer (Injector protocol)."""

    def __init__(self, ring_size_mib: int = RING_SIZE_MIB, sealer: Any = None) -> None:
        self.ring_size_mib = ring_size_mib
        self.active_slots: dict[str, dict[str, Any]] = {}
        # Optional AES-NI onion sealer (tibet_cap_bus.onion.OnionSealer). When set,
        # inject_payload seals the block with a causal-chain-derived key before it
        # enters the ring — a stale/broken chain yields an undecryptable payload.
        self.sealer = sealer

    def inject(self, cap: Cap, lane_id: str, causal_rank: int) -> tuple[str, PhaseEvidence]:
        """Place the cap into the executor-bound GPU ring memory offset."""
        try:
            byte_offset = resolve_waint_block_offset(lane_id, causal_rank)
        except ValueError:
            byte_offset = (causal_rank % MAX_BLOCKS) * BLOCK_SIZE_MIB * 1024 * 1024

        slot_id = f"gpu_ring_offset:{lane_id}:{byte_offset}"
        self.active_slots[slot_id] = {
            "cap_id": cap.cap_id,
            "actor_id": cap.actor_id,
            "intent": cap.intent,
            "byte_offset": byte_offset,
            "allocated_size_mib": BLOCK_SIZE_MIB,
        }
        return slot_id, PhaseEvidence(
            phase="inject",
            status="slot-populated",
            details={
                "memory_slot": slot_id,
                "executor_class": cap.executor_class,
                "memory_regime": "pinned-host-dma-ring",
                "byte_offset": byte_offset,
                "skips": ["cpu-copy"],
                "does_not_skip": ["host-ram"],
            },
        )

    def inject_payload(
        self,
        cap: Cap,
        lane_id: str,
        causal_rank: int,
        payload: bytes,
        *,
        prev_receipt_hash: str,
        causal_seq: int,
    ) -> tuple[str, bytes, PhaseEvidence]:
        """Inject a cap AND its payload bytes. If a sealer is configured, the
        payload is sealed with an AES-NI onion keyed by the causal chain
        (prev_receipt_hash || causal_seq) before it enters the ring. The bytes
        returned are what actually travels: sealed when a sealer is present, raw
        otherwise. A stale/broken chain -> wrong key -> the consumer cannot open
        it (the self-blocker)."""
        slot_id, evidence = self.inject(cap, lane_id, causal_rank)
        if self.sealer is None:
            self.active_slots[slot_id]["sealed"] = False
            evidence.details["onion"] = "none (no sealer configured)"
            return slot_id, payload, evidence
        from .onion import lane_aad  # local import: onion is optional
        aad = lane_aad(lane_id, cap.cap_id)
        sealed = self.sealer.seal(payload, prev_receipt_hash, causal_seq, aad=aad)
        self.active_slots[slot_id]["sealed"] = True
        self.active_slots[slot_id]["onion_bytes"] = len(sealed)
        self.active_slots[slot_id]["causal_seq"] = causal_seq
        evidence.details["onion"] = "aes-256-gcm (aes-ni), causal-chain-keyed"
        evidence.details["onion_bytes"] = len(sealed)
        return slot_id, sealed, evidence


# ─────────────────────────────────────────────────────────────────
# 3. CMail TTL enforcement (task #42)
# ─────────────────────────────────────────────────────────────────

def datetime_to_unix(iso_str: str) -> float:
    """Convert an ISO-8601 time string to a unix timestamp (offset-naive parse)."""
    cleaned = iso_str.split("+")[0].split("Z")[0]
    return time.mktime(time.strptime(cleaned, "%Y-%m-%dT%H:%M:%S"))


@dataclass
class TTLEnforcer:
    """Reject expired capsules based on `expires_at` or `sent_at` + `ttl_seconds`."""

    default_ttl_seconds: int = 3600

    def verify_ttl(self, envelope: dict[str, Any], *, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now

        expires_at_str = envelope.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime_to_unix(expires_at_str)
            except ValueError:
                return False, "invalid-expires-at-format"
            if now > expires_at:
                return False, f"capsule-expired: {now} > {expires_at}"

        sent_at_str = envelope.get("sent_at")
        ttl_seconds = envelope.get("ttl_seconds")
        if sent_at_str and ttl_seconds is not None:
            try:
                expires_at = datetime_to_unix(sent_at_str) + int(ttl_seconds)
            except (ValueError, TypeError):
                return False, "invalid-sent-at-or-ttl"
            if now > expires_at:
                return False, f"capsule-expired: {now} > {expires_at}"

        return True, "ttl-valid"


# ─────────────────────────────────────────────────────────────────
# 4. Content-addressed VRAM dedup + possession receipts
# ─────────────────────────────────────────────────────────────────

POSSESSION_RECEIPT_KIND = "org.ainternet.tibet-dgx.possession-receipt.v1"


@dataclass
class PossessionReceipt:
    """A signed claim that an actor already holds a content hash in its local VRAM."""

    content_hash: str
    actor: str
    timestamp: float
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": POSSESSION_RECEIPT_KIND,
            "content_hash": self.content_hash,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "signature": self.signature,
        }


class ContentAddressedVRAM:
    """Zero-transfer dedup: swap a full 2MB block for a 32B hash pointer — but ONLY when the
    target actor proves possession with a *verified* signed receipt. 'I have it' is never trusted.
    """

    def __init__(self, freshness_window_s: int = 60) -> None:
        self.freshness_window_s = freshness_window_s
        self._vram_cache: dict[str, set[str]] = {
            "gpu0.p520.waint": set(),
            "gpu1.p520.waint": set(),
        }

    def register_block(self, actor: str, content_hash: str) -> None:
        self._vram_cache.setdefault(actor, set()).add(content_hash)

    def verify_and_route(
        self,
        content_hash: str,
        target_actor: str,
        possession_receipt: dict[str, Any] | None,
        block_data: bytes,
        target_pubkey: str | None = None,
        *,
        now: float | None = None,
    ) -> tuple[str, bytes]:
        """Decide transfer-full-block vs zero-transfer-dedup. Fails CLOSED (full transfer) on
        any missing/invalid proof — a skip is only granted on a fresh, verified possession receipt.
        """
        if not possession_receipt:
            return "transfer-full-block", block_data
        if possession_receipt.get("kind") != POSSESSION_RECEIPT_KIND:
            return "transfer-full-block-invalid-receipt-kind", block_data

        # pubkey is MANDATORY for the zero-transfer bypass (no pubkey -> no skip, no bypass path)
        if not target_pubkey:
            return "transfer-full-block-missing-pubkey", block_data
        # cannot verify without the single-source verifier -> fail closed
        if not _HAVE_VERIFIER:
            return "transfer-full-block-verify-unavailable", block_data
        if not verify_canonical(possession_receipt, target_pubkey,
                                sig_field="signature", excluded=("signature",)):
            return "transfer-full-block-invalid-signature", block_data

        if possession_receipt.get("content_hash") != content_hash:
            return "transfer-full-block-hash-mismatch", block_data
        if possession_receipt.get("actor") != target_actor:
            return "transfer-full-block-actor-mismatch", block_data

        now = time.time() if now is None else now
        if abs(now - possession_receipt.get("timestamp", 0)) > self.freshness_window_s:
            return "transfer-full-block-expired-receipt", block_data

        if content_hash in self._vram_cache.get(target_actor, set()):
            return "zero-transfer-dedup", f"hash-ptr:{content_hash}".encode("utf-8")
        return "transfer-full-block-not-cached", block_data


# ─────────────────────────────────────────────────────────────────
# 5. JIS-driven prefetch (physical-staged != pre-authorized)
# ─────────────────────────────────────────────────────────────────

class JISPrefetcher:
    """Pre-stage ring blocks from a declared compute intent. Staging only moves BYTES early;
    the .caint gate still fires at consume time (this class never authorizes — it warms the ring).
    """

    def __init__(self, ring: GPURingBufferInjector) -> None:
        self.ring = ring
        self.prefetch_queue: list[dict[str, Any]] = []

    def queue_prefetch_from_intent(self, intent: str, blocks: list[str]) -> None:
        if intent.startswith("compute:inference"):
            for i, block_hash in enumerate(blocks):
                self.prefetch_queue.append({
                    "block_hash": block_hash,
                    "target_offset": (i % MAX_BLOCKS) * BLOCK_SIZE_MIB * 1024 * 1024,
                    "status": "staged-dma",
                })

    def run_prefetch(self) -> int:
        count = 0
        for item in self.prefetch_queue:
            if item["status"] == "staged-dma":
                item["status"] = "loaded-in-ring"
                count += 1
        return count


__all__ = [
    "RING_SIZE_MIB", "BLOCK_SIZE_MIB", "MAX_BLOCKS", "WAINT_TO_OFFSET",
    "resolve_waint_block_offset", "GPURingBufferInjector", "datetime_to_unix",
    "TTLEnforcer", "POSSESSION_RECEIPT_KIND", "PossessionReceipt",
    "ContentAddressedVRAM", "JISPrefetcher",
]
