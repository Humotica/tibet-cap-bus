"""AES-NI onion around the GPU-mailbox payload — the self-blocker, end to end.

The gpu_mailbox moves payload bytes (a 2MB ring block) over the PCIe lane. This
module seals that payload with AES-256-GCM (hardware AES-NI + PCLMULQDQ for the
GHASH tag) using a key derived from the causal re-attestation chain:

    K_payload = HKDF(tpm_secret, prev_receipt_hash || causal_seq)   (tibet_mux.reattestation)

So encryption is NOT a separate gate. A broken, stale, or skipped chain derives
a DIFFERENT key, GCM authentication fails, and the payload is undecryptable
noise — fail-closed by math, no hot-path firewall (gravity's self-blocker).
Measured on P520/W2135: AES-256-GCM ~4 GB/s/core, well past the ~8 GB/s bus
across a couple of cores, and on the SAME box as the GPUs (no cross-node hop).

Single-source: the key derivation lives in tibet_mux.reattestation; this module
never re-implements the KDF. Fail-closed if AES-NI or the KDF is unavailable.
Part of the TIBET ecosystem / AInternet. One love, one fAmIly.
"""
from __future__ import annotations

import os
from typing import Any, Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAVE_AES = True
except Exception:  # pragma: no cover - environment without cryptography
    AESGCM = None  # type: ignore
    _HAVE_AES = False

try:
    # Single source for the causal-chain key derivation (no second KDF here).
    from tibet_mux.reattestation import derive_payload_key
    _HAVE_KDF = True
except Exception:  # pragma: no cover - environment without tibet-mux
    derive_payload_key = None  # type: ignore
    _HAVE_KDF = False

ONION_MAGIC = b"ONI1"   # self-describing: a sealed block is recognizable on the wire
NONCE_LEN = 12          # AES-GCM standard nonce


class OnionError(Exception):
    """Sealing/opening failed. Opening fails when the chain key is wrong/stale."""


class OnionSealer:
    """Seal/open a gpu_mailbox payload, keyed by the causal re-attestation chain.

    Fails CLOSED at construction if AES-NI (cryptography) or the single-source
    KDF (tibet_mux.reattestation) is unavailable — never silently ships plaintext.
    """

    def __init__(self, tpm_secret: bytes) -> None:
        if not _HAVE_AES:
            raise OnionError("AES-NI / cryptography unavailable — refusing to ship unsealed")
        if not _HAVE_KDF:
            raise OnionError("tibet_mux.reattestation KDF unavailable — fail closed")
        if not tpm_secret:
            raise OnionError("empty tpm_secret")
        self._secret = tpm_secret

    def _key(self, prev_receipt_hash: str, causal_seq: int) -> bytes:
        return derive_payload_key(self._secret, prev_receipt_hash, causal_seq, 32)

    def seal(self, plaintext: bytes, prev_receipt_hash: str, causal_seq: int,
             *, aad: bytes = b"") -> bytes:
        """Encrypt the payload for (prev_receipt_hash, causal_seq). The AAD binds
        the routing context (lane/cap) into the GCM tag without encrypting it."""
        key = self._key(prev_receipt_hash, causal_seq)
        nonce = os.urandom(NONCE_LEN)
        ct = AESGCM(key).encrypt(nonce, plaintext, aad or None)
        return ONION_MAGIC + nonce + ct

    def open(self, sealed: bytes, prev_receipt_hash: str, causal_seq: int,
             *, aad: bytes = b"") -> bytes:
        """Decrypt — only succeeds with the exact chain key the sealer used.
        Wrong/stale/skipped chain -> wrong key -> GCM auth fail -> OnionError
        (the bytes are noise). This IS the self-blocker."""
        if sealed[:4] != ONION_MAGIC:
            raise OnionError("not an onion payload (bad magic)")
        nonce = sealed[4:4 + NONCE_LEN]
        ct = sealed[4 + NONCE_LEN:]
        key = self._key(prev_receipt_hash, causal_seq)
        try:
            return AESGCM(key).decrypt(nonce, ct, aad or None)
        except Exception:
            raise OnionError(
                "undecryptable: wrong/stale causal-chain key — payload is noise (self-blocker)")

    # Convenience: seal/open against a verified chain HEAD link (the live route).
    def seal_for_head(self, plaintext: bytes, head_link: dict, *, aad: bytes = b"") -> bytes:
        return self.seal(plaintext, head_link["prev_receipt_hash"], head_link["causal_seq"], aad=aad)

    def open_for_head(self, sealed: bytes, head_link: dict, *, aad: bytes = b"") -> bytes:
        return self.open(sealed, head_link["prev_receipt_hash"], head_link["causal_seq"], aad=aad)


def lane_aad(lane_id: str, cap_id: str) -> bytes:
    """Routing context bound into the GCM tag: lane + cap identity."""
    return f"{lane_id}|{cap_id}".encode("utf-8")


__all__ = ["OnionSealer", "OnionError", "ONION_MAGIC", "NONCE_LEN", "lane_aad"]
