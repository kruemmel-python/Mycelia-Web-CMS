from __future__ import annotations

import base64
import hashlib

from cms.security import MyceliaSecuritySDK


def _fake_sdk() -> MyceliaSecuritySDK:
    sdk = object.__new__(MyceliaSecuritySDK)
    sdk._master_key = bytearray(bytes(range(32)))
    # Deterministic reversible stand-ins isolate packet/version/KDF behavior
    # from the native GPU runtime for this unit test.
    sdk._crypt_key256 = lambda data, key: bytes(b ^ hashlib.sha256(key).digest()[i % 32] for i, b in enumerate(data))
    sdk._crypt_legacy = lambda data, seed: bytes(b ^ ((seed >> ((i % 8) * 8)) & 0xFF) for i, b in enumerate(data))
    return sdk


def test_new_records_use_mcms3_and_roundtrip() -> None:
    sdk = _fake_sdk()
    token = sdk.encrypt_json("record-1", {"hello": "world"})
    packet = base64.urlsafe_b64decode(token.encode("ascii"))
    assert packet.startswith(b"MCMS3")
    assert sdk.decrypt_json("record-1", token) == {"hello": "world"}


def test_record_binding_rejects_wrong_record_id() -> None:
    sdk = _fake_sdk()
    token = sdk.encrypt_json("record-1", {"x": 1})
    try:
        sdk.decrypt_json("record-2", token)
    except Exception as exc:
        assert "verändert" in str(exc) or "Datensatz" in str(exc)
    else:
        raise AssertionError("record binding did not reject wrong id")
