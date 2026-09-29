"""A minimal software passkey (ES256, "none" attestation) for tests – no browser or device needed."""

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url


class SoftAuthenticator:
    def __init__(self, origin: str, rp_id: str):
        self.origin, self.rp_id = origin, rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.counter = 0
        self.user_handle = None

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin}).encode()

    def _auth_data(self, flags: int, extra: bytes = b"") -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", self.counter) + extra

    def create(self, options_json: str) -> dict:
        options = json.loads(options_json)
        self.user_handle = options["user"]["id"]
        numbers = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + cose
        auth_data = self._auth_data(0x45, attested)  # user present, user verified, attested credential
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        raw_id = bytes_to_base64url(self.credential_id)
        return {"id": raw_id, "rawId": raw_id, "type": "public-key",
                "response": {"clientDataJSON": bytes_to_base64url(self._client_data("webauthn.create", options["challenge"])),
                             "attestationObject": bytes_to_base64url(attestation)}}

    def get(self, options_json: str) -> dict:
        options = json.loads(options_json)
        allowed = [base64url_to_bytes(c["id"]) for c in options.get("allowCredentials", [])]
        assert not allowed or self.credential_id in allowed
        self.counter += 1
        auth_data = self._auth_data(0x05)  # user present, user verified
        client = self._client_data("webauthn.get", options["challenge"])
        signature = self.key.sign(auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        raw_id = bytes_to_base64url(self.credential_id)
        return {"id": raw_id, "rawId": raw_id, "type": "public-key",
                "response": {"clientDataJSON": bytes_to_base64url(client), "authenticatorData": bytes_to_base64url(auth_data),
                             "signature": bytes_to_base64url(signature), "userHandle": self.user_handle}}
