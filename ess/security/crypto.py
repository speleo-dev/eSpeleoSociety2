"""Application-level encryption of personal data (GDPR) and blind indexes for searching.

Encrypted value layout (bytes):
    b"\\x01" | len(key_id) (1 byte) | key_id (ascii) | nonce (12 bytes) | AES-256-GCM ciphertext+tag

Each value is bound to a *context* (e.g. "members.last_name") used as associated data, so a value
copied into another column or table fails to decrypt.

Blind index: HMAC-SHA256 over a normalized value and its context. It allows exact-match lookups
(e.g. first name + last name + birth year) without storing readable data.
"""

import base64
import hashlib
import hmac
import os
import unicodedata

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_FORMAT_VERSION = 1
_NONCE_SIZE = 12
_KEY_SIZE = 32


class CryptoError(Exception):
    """Raised when a value cannot be encrypted or decrypted."""


def generate_key() -> str:
    """Return a new random 256-bit key encoded as base64."""
    return base64.b64encode(os.urandom(_KEY_SIZE)).decode()


def _decode_key(encoded: str) -> bytes:
    key = base64.b64decode(encoded, validate=True)
    if len(key) != _KEY_SIZE:
        raise CryptoError("Key must be 32 bytes (base64-encoded)")
    return key


def parse_keyring(spec: str) -> list[tuple[str, bytes]]:
    """Parse "key_id:base64key,key_id2:base64key" into an ordered list; first entry is active."""
    keys: list[tuple[str, bytes]] = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        key_id, sep, encoded = part.partition(":")
        if not sep or not key_id or not key_id.isascii() or len(key_id) > 32:
            raise CryptoError("Invalid keyring entry; expected key_id:base64key")
        keys.append((key_id, _decode_key(encoded)))
    if not keys:
        raise CryptoError("Keyring is empty")
    if len({k for k, _ in keys}) != len(keys):
        raise CryptoError("Duplicate key id in keyring")
    return keys


class FieldCipher:
    """Encrypts and decrypts single field values with AES-256-GCM and key rotation support."""

    def __init__(self, keyring: list[tuple[str, bytes]]):
        if not keyring:
            raise CryptoError("Keyring is empty")
        self._active_id, active_key = keyring[0]
        self._active = AESGCM(active_key)
        self._by_id = {key_id: AESGCM(key) for key_id, key in keyring}

    @classmethod
    def from_spec(cls, spec: str) -> "FieldCipher":
        return cls(parse_keyring(spec))

    def encrypt(self, plaintext: str, context: str) -> bytes:
        key_id = self._active_id.encode("ascii")
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext = self._active.encrypt(nonce, plaintext.encode("utf-8"), context.encode("utf-8"))
        return bytes([_FORMAT_VERSION, len(key_id)]) + key_id + nonce + ciphertext

    def decrypt(self, blob: bytes, context: str) -> str:
        try:
            if blob[0] != _FORMAT_VERSION:
                raise CryptoError("Unknown encrypted value format")
            id_len = blob[1]
            key_id = blob[2 : 2 + id_len].decode("ascii")
            nonce = blob[2 + id_len : 2 + id_len + _NONCE_SIZE]
            ciphertext = blob[2 + id_len + _NONCE_SIZE :]
            aead = self._by_id[key_id]
            return aead.decrypt(nonce, ciphertext, context.encode("utf-8")).decode("utf-8")
        except CryptoError:
            raise
        except KeyError:
            raise CryptoError("Encryption key for this value is not available") from None
        except Exception:
            # Never include the value itself in the error.
            raise CryptoError("Value cannot be decrypted") from None

    def needs_reencryption(self, blob: bytes) -> bool:
        """True if the value was encrypted with an older (non-active) key."""
        id_len = blob[1]
        return blob[2 : 2 + id_len].decode("ascii") != self._active_id


def normalize_for_index(value: str) -> str:
    """Normalize text for matching: Unicode NFKD, no diacritics, case-folded, single spaces.

    "  Podhradská " and "podhradska" produce the same index.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_marks.casefold().split())


class BlindIndex:
    """Deterministic keyed hash (HMAC-SHA256) for exact-match lookups of encrypted values."""

    def __init__(self, key: bytes):
        if len(key) != _KEY_SIZE:
            raise CryptoError("Blind index key must be 32 bytes")
        self._key = key

    @classmethod
    def from_spec(cls, encoded: str) -> "BlindIndex":
        return cls(_decode_key(encoded))

    def compute(self, context: str, *values: str) -> bytes:
        """Index over one or more values (e.g. first name, last name, birth year)."""
        message = "\x1f".join([context, *(normalize_for_index(v) for v in values)])
        return hmac.new(self._key, message.encode("utf-8"), hashlib.sha256).digest()
