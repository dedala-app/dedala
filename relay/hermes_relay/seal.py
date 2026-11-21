# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Sealing as docs/relay.md describes it, for the plugin and for tests: X25519
between the agent's and the device's keys, HKDF-SHA256 to one key per
direction, ChaCha20-Poly1305 with the sequence number authenticated. The relay
itself never opens anything."""

import base64
import hashlib
import hmac
import json
import os
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def public(key: X25519PrivateKey) -> str:
    return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def keys(own: X25519PrivateKey, other: str, pairing: str) -> tuple[bytes, bytes]:
    """The keys (to the app, to the agent), the same on both sides."""
    shared = own.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(other)))

    def derive(info: str) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=pairing.encode(), info=info.encode()).derive(shared)

    return derive("hermes-app v1 to-app"), derive("hermes-app v1 to-agent")


def seal_bytes(key: bytes, seq: int, plain: bytes) -> dict:
    nonce = os.urandom(12)
    box = ChaCha20Poly1305(key).encrypt(nonce, plain, str(seq).encode())
    return {"seq": seq, "nonce": base64.b64encode(nonce).decode(), "box": base64.b64encode(box).decode()}


def unseal_bytes(key: bytes, message: dict) -> bytes:
    return ChaCha20Poly1305(key).decrypt(base64.b64decode(message["nonce"]), base64.b64decode(message["box"]), str(message["seq"]).encode())


def seal(key: bytes, seq: int, value) -> dict:
    return seal_bytes(key, seq, json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def unseal(key: bytes, message: dict):
    return json.loads(unseal_bytes(key, message))


def seal_design(key: bytes, design) -> str:
    """A Live Activity design for the start push: raw-deflated, sealed with
    sequence 0, as a JSON string (attributes.design)."""
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = packer.compress(json.dumps(design, separators=(",", ":"), ensure_ascii=False).encode()) + packer.flush()
    return json.dumps(seal_bytes(key, 0, packed), separators=(",", ":"))


def seal_state(key: bytes, data) -> str:
    """A Live Activity's data, sealed with sequence 0, as a JSON string (content-state.data)."""
    return json.dumps(seal(key, 0, data), separators=(",", ":"))


def proof_mac(proof: str, device_key: str) -> str:
    return base64.b64encode(hmac.new(proof.encode(), device_key.encode(), hashlib.sha256).digest()).decode()


def claim_hash(claim: str) -> str:
    return hashlib.sha256(claim.encode()).hexdigest()
