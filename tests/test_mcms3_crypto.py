from __future__ import annotations

import base64
from pathlib import Path

import pytest

from cms.security import MyceliaCryptoError, MyceliaSecuritySDK


MASTER = bytes(range(32))


def make_crypto() -> MyceliaSecuritySDK:
    return MyceliaSecuritySDK(Path("does-not-need-to-exist-for-mcms3.dll"), MASTER, initialize_native=False)


def test_mcms3_roundtrip_is_cpu_only() -> None:
    crypto = make_crypto()
    value = {"title": "ÄÖÜ Mycelia", "price": 19.95, "active": True, "items": [1, 2, 3]}
    token = crypto.encrypt_json("shop:alpha", value)
    assert MyceliaSecuritySDK.token_version(token) == b"MCMS3"
    assert crypto.decrypt_json("shop:alpha", token) == value


def test_mcms3_tamper_is_rejected_before_plaintext() -> None:
    crypto = make_crypto()
    token = crypto.encrypt_json("shop:alpha", {"x": 1})
    packet = bytearray(base64.urlsafe_b64decode(token.encode("ascii")))
    packet[25] ^= 0x01
    tampered = base64.urlsafe_b64encode(packet).decode("ascii")
    with pytest.raises(MyceliaCryptoError, match="verändert|anderen Datensatz"):
        crypto.decrypt_json("shop:alpha", tampered)


def test_mcms3_is_bound_to_record_id() -> None:
    crypto = make_crypto()
    token = crypto.encrypt_json("shop:alpha", {"x": 1})
    with pytest.raises(MyceliaCryptoError, match="verändert|anderen Datensatz"):
        crypto.decrypt_json("shop:beta", token)


def test_mcms3_stream_is_stable_for_same_key_data_and_offset() -> None:
    data = bytes(range(255)) * 3
    key = bytes(reversed(range(32)))
    a = MyceliaSecuritySDK._crypt_cpu_hmac_stream(data, key, 17)
    b = MyceliaSecuritySDK._crypt_cpu_hmac_stream(data, key, 17)
    assert a == b
    assert MyceliaSecuritySDK._crypt_cpu_hmac_stream(a, key, 17) == data


def test_mcms3_stream_keeps_persisted_compatibility_vector() -> None:
    key = bytes(range(32))
    data = bytes(range(100))
    expected = bytes.fromhex(
        "a088f2af14215ea7e20a23e48f7438436890f2f12531f052f696a948c628be87"
        "8f0a4a627591f0e72e88405f7f432192262bc7158989a26bdea1b9efc8e63077"
        "2d07a015b2da29512732381d2cb16f3973a52df24e2f17d90d5c1a0a80d0dd77"
        "881dfc93"
    )
    assert MyceliaSecuritySDK._crypt_cpu_hmac_stream(data, key, 17) == expected
