"""Access to the configured field cipher and blind index (keys come from ESS_PII_KEYS / ESS_BLIND_INDEX_KEY)."""

from datetime import date
from functools import lru_cache

from ess.config import get_settings
from ess.security.crypto import BlindIndex, FieldCipher


@lru_cache
def get_cipher() -> FieldCipher:
    spec = get_settings().pii_keys
    if not spec:
        raise RuntimeError("ESS_PII_KEYS is not set")
    return FieldCipher.from_spec(spec)


@lru_cache
def get_blind_index() -> BlindIndex:
    spec = get_settings().blind_index_key
    if not spec:
        raise RuntimeError("ESS_BLIND_INDEX_KEY is not set")
    return BlindIndex.from_spec(spec)


def encrypt(value: str | None, context: str) -> bytes | None:
    if value is None or value == "":
        return None
    return get_cipher().encrypt(value, context)


def decrypt(blob: bytes | None, context: str) -> str | None:
    if blob is None:
        return None
    return get_cipher().decrypt(blob, context)


def encrypt_date(value: date | None, context: str) -> bytes | None:
    return encrypt(value.isoformat(), context) if value else None


def decrypt_date(blob: bytes | None, context: str) -> date | None:
    text = decrypt(blob, context)
    return date.fromisoformat(text) if text else None


def blind_index(context: str, *values: str | None) -> bytes | None:
    """Blind index over all values; None if any value is missing."""
    if any(v is None or v == "" for v in values):
        return None
    return get_blind_index().compute(context, *values)  # type: ignore[arg-type]
