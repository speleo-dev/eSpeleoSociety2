import base64

import pytest

from ess.security.crypto import (
    BlindIndex,
    CryptoError,
    FieldCipher,
    generate_key,
    normalize_for_index,
    parse_keyring,
)


def test_roundtrip():
    cipher = FieldCipher.from_spec(f"k1:{generate_key()}")
    blob = cipher.encrypt("Bohuslava Podhradská", "members.full_name")
    assert "Podhradsk".encode() not in blob
    assert cipher.decrypt(blob, "members.full_name") == "Bohuslava Podhradská"


def test_same_value_encrypts_differently():
    cipher = FieldCipher.from_spec(f"k1:{generate_key()}")
    assert cipher.encrypt("x", "c") != cipher.encrypt("x", "c")


def test_wrong_context_fails():
    cipher = FieldCipher.from_spec(f"k1:{generate_key()}")
    blob = cipher.encrypt("secret", "members.email")
    with pytest.raises(CryptoError):
        cipher.decrypt(blob, "members.last_name")


def test_tampered_value_fails():
    cipher = FieldCipher.from_spec(f"k1:{generate_key()}")
    blob = bytearray(cipher.encrypt("secret", "c"))
    blob[-1] ^= 0x01
    with pytest.raises(CryptoError):
        cipher.decrypt(bytes(blob), "c")


def test_key_rotation_keeps_old_values_readable():
    old_key, new_key = generate_key(), generate_key()
    old_cipher = FieldCipher.from_spec(f"k1:{old_key}")
    blob = old_cipher.encrypt("value", "c")

    rotated = FieldCipher.from_spec(f"k2:{new_key},k1:{old_key}")
    assert rotated.decrypt(blob, "c") == "value"
    assert rotated.needs_reencryption(blob)
    assert not rotated.needs_reencryption(rotated.encrypt("value", "c"))


def test_missing_key_fails():
    blob = FieldCipher.from_spec(f"k1:{generate_key()}").encrypt("value", "c")
    with pytest.raises(CryptoError):
        FieldCipher.from_spec(f"k2:{generate_key()}").decrypt(blob, "c")


@pytest.mark.parametrize(
    "spec",
    ["", "k1", f"k1:{base64.b64encode(b'short').decode()}", f"k1:{generate_key()},k1:{generate_key()}"],
)
def test_invalid_keyring(spec):
    with pytest.raises(CryptoError):
        parse_keyring(spec)


def test_normalization():
    assert normalize_for_index("  Podhradská  PhD. ") == "podhradska phd."
    assert normalize_for_index("ŠTEFAN") == normalize_for_index("stefan")


def test_blind_index_matches_normalized_input():
    index = BlindIndex.from_spec(generate_key())
    a = index.compute("members.lookup", "Štefan", "Kováč", "1970")
    b = index.compute("members.lookup", " stefan ", "KOVAC", "1970")
    assert a == b
    assert len(a) == 32


def test_blind_index_differs_by_context_key_and_value():
    key = generate_key()
    index = BlindIndex.from_spec(key)
    base = index.compute("members.lookup", "Jan", "Novak", "1980")
    assert index.compute("members.email", "Jan", "Novak", "1980") != base
    assert index.compute("members.lookup", "Jan", "Novak", "1981") != base
    assert BlindIndex.from_spec(generate_key()).compute("members.lookup", "Jan", "Novak", "1980") != base


def test_blind_index_value_boundaries():
    index = BlindIndex.from_spec(generate_key())
    assert index.compute("c", "ab", "c") != index.compute("c", "a", "bc")
