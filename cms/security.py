from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any


class MyceliaCryptoError(RuntimeError):
    pass


class MyceliaSecuritySDK:
    """CMS record crypto with legacy GPU compatibility and CPU-stable MCMS3.

    MCMS1/MCMS2 remain readable for migration. New writes use MCMS3, whose
    keystream is derived entirely from HMAC-SHA256 and therefore does not depend
    on GPU model, OpenCL driver, compiler flags or floating-point behaviour.
    """

    VERSION_V1 = b"MCMS1"
    VERSION_V2 = b"MCMS2"
    VERSION_V3 = b"MCMS3"
    VERSION = VERSION_V3
    _V3_DOMAIN = b"MYCELIA-MCMS3-STREAM\0"

    def __init__(
        self,
        dll_path: Path,
        master_key: bytes,
        gpu_index: int = 0,
        *,
        initialize_native: bool = True,
    ) -> None:
        if len(master_key) != 32:
            raise MyceliaCryptoError("MYCELIA_CMS_MASTER_KEY muss exakt 32 Byte besitzen")
        self._dll_path = dll_path.resolve()
        self._master_key = bytearray(master_key)
        self._gpu_index = gpu_index
        self._lock = threading.RLock()
        self._dll_dir_handle = None
        self._lib = None
        self._ctx = ctypes.c_void_p()
        if initialize_native:
            self._initialize_native()

    def _initialize_native(self) -> None:
        if self._lib is not None:
            return
        if not self._dll_path.exists():
            raise MyceliaCryptoError(f"Security SDK DLL fehlt: {self._dll_path}")
        if os.name == "nt" and hasattr(os, "add_dll_directory") and self._dll_dir_handle is None:
            self._dll_dir_handle = os.add_dll_directory(str(self._dll_path.parent.resolve()))
        lib = ctypes.WinDLL(str(self._dll_path)) if hasattr(ctypes, "WinDLL") else ctypes.CDLL(str(self._dll_path))
        self._bind(lib)
        self._check_lib(lib, lib.myc_init(), "myc_init")
        if lib.myc_get_device_count() <= self._gpu_index:
            raise MyceliaCryptoError(f"GPU {self._gpu_index} ist für Mycelia Security nicht verfügbar")
        ctx = ctypes.c_void_p()
        self._check_lib(lib, lib.myc_create_context(self._gpu_index, ctypes.byref(ctx)), "myc_create_context")
        self._lib = lib
        self._ctx = ctx

    @staticmethod
    def _bind(lib: Any) -> None:
        lib.myc_init.restype = ctypes.c_int
        lib.myc_get_device_count.restype = ctypes.c_int
        lib.myc_get_last_error.restype = ctypes.c_char_p
        lib.myc_create_context.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        lib.myc_create_context.restype = ctypes.c_int
        lib.myc_destroy_context.argtypes = [ctypes.c_void_p]
        lib.myc_set_seed.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        lib.myc_set_seed.restype = ctypes.c_int
        try:
            lib.myc_set_key_256.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
            lib.myc_set_key_256.restype = ctypes.c_int
            lib.myc_get_security_capabilities.restype = ctypes.c_char_p
        except AttributeError as exc:
            raise MyceliaCryptoError(
                "Unsichere/alte Mycelia Security SDK Runtime: 256-Bit-Key-ABI fehlt."
            ) from exc
        caps_raw = lib.myc_get_security_capabilities()
        caps = caps_raw.decode("ascii", "replace") if caps_raw else ""
        if "key256=1" not in caps or "hmac_sha256_stream=1" not in caps:
            raise MyceliaCryptoError("Mycelia Security SDK meldet nicht die erforderliche 256-Bit-Sicherheits-Capability")
        lib.myc_process_buffer.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_size_t]
        lib.myc_process_buffer.restype = ctypes.c_int

    @staticmethod
    def _check_lib(lib: Any, result: int, operation: str) -> None:
        if result == 0:
            return
        raw = lib.myc_get_last_error()
        detail = raw.decode("utf-8", "replace") if raw else "unbekannter SDK-Fehler"
        raise MyceliaCryptoError(f"{operation} fehlgeschlagen ({result}): {detail}")

    def _check(self, result: int, operation: str) -> None:
        if self._lib is None:
            raise MyceliaCryptoError("Legacy Security SDK ist nicht initialisiert")
        self._check_lib(self._lib, result, operation)

    def _derive(self, purpose: bytes, nonce: bytes, record_id: str) -> bytes:
        return hmac.new(
            self._master_key,
            purpose + b"\0" + nonce + b"\0" + record_id.encode("utf-8"),
            hashlib.sha256,
        ).digest()

    @classmethod
    def _crypt_cpu_hmac_stream(cls, data: bytes, key: bytes, stream_offset: int = 0) -> bytes:
        if not data:
            return b""
        if len(key) != 32:
            raise MyceliaCryptoError("Interner Mycelia-MCMS3-Key muss 32 Byte besitzen")
        if stream_offset < 0:
            raise MyceliaCryptoError("MCMS3-Streamoffset darf nicht negativ sein")

        out = bytearray(len(data))
        counter = stream_offset // 32
        skip = stream_offset % 32
        src_pos = 0
        while src_pos < len(data):
            msg = cls._V3_DOMAIN + counter.to_bytes(8, "big", signed=False)
            block = hmac.new(key, msg, hashlib.sha256).digest()
            usable = block[skip:]
            take = min(len(usable), len(data) - src_pos)
            # XOR one HMAC block as a single integer operation. This is
            # bit-identical to the byte loop but avoids Python work per byte,
            # which matters for encrypted image payloads.
            plain_block = int.from_bytes(data[src_pos:src_pos + take], "big")
            stream_block = int.from_bytes(usable[:take], "big")
            out[src_pos:src_pos + take] = (plain_block ^ stream_block).to_bytes(take, "big")
            src_pos += take
            counter += 1
            skip = 0
        return bytes(out)

    def _crypt_legacy(self, data: bytes, seed: int) -> bytes:
        """MCMS1 compatibility path. Never used for new encryption."""
        if not data:
            return b""
        self._initialize_native()
        assert self._lib is not None
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        try:
            with self._lock:
                self._check(self._lib.myc_set_seed(self._ctx, seed), "myc_set_seed")
                self._check(self._lib.myc_process_buffer(self._ctx, buffer, len(data), 0), "myc_process_buffer")
            return bytes(buffer)
        finally:
            ctypes.memset(ctypes.addressof(buffer), 0, len(data))

    def _crypt_key256(self, data: bytes, key: bytes) -> bytes:
        if not data:
            return b""
        if len(key) != 32:
            raise MyceliaCryptoError("Interner Mycelia-Record-Key muss 32 Byte besitzen")
        self._initialize_native()
        assert self._lib is not None
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        key_buffer = (ctypes.c_uint8 * 32).from_buffer_copy(key)
        try:
            with self._lock:
                self._check(self._lib.myc_set_key_256(self._ctx, key_buffer, 32), "myc_set_key_256")
                self._check(self._lib.myc_process_buffer(self._ctx, buffer, len(data), 0), "myc_process_buffer")
            return bytes(buffer)
        finally:
            ctypes.memset(ctypes.addressof(buffer), 0, len(data))
            ctypes.memset(ctypes.addressof(key_buffer), 0, 32)

    @staticmethod
    def token_version(token: str) -> bytes:
        try:
            packet = base64.urlsafe_b64decode(token.encode("ascii"))
        except Exception as exc:
            raise MyceliaCryptoError("Ungültiger CMS-Ciphertext") from exc
        if len(packet) < 5:
            raise MyceliaCryptoError("Unbekanntes CMS-Ciphertext-Format")
        return packet[:5]

    def _decode_and_authenticate(self, record_id: str, token: str) -> tuple[bytes, bytes, bytes]:
        try:
            packet = base64.urlsafe_b64decode(token.encode("ascii"))
        except Exception as exc:
            raise MyceliaCryptoError("Ungültiger CMS-Ciphertext") from exc
        if len(packet) < 5 + 16 + 32:
            raise MyceliaCryptoError("Unbekanntes CMS-Ciphertext-Format")

        version = packet[:5]
        if version not in {self.VERSION_V1, self.VERSION_V2, self.VERSION_V3}:
            raise MyceliaCryptoError("Unbekanntes CMS-Ciphertext-Format")
        nonce = packet[5:21]
        cipher = packet[21:-32]
        supplied_tag = packet[-32:]

        match version:
            case self.VERSION_V3:
                tag_key = self._derive(b"auth3", nonce, record_id)
            case self.VERSION_V2:
                tag_key = self._derive(b"auth2", nonce, record_id)
            case _:
                tag_key = self._derive(b"auth", nonce, record_id)
        expected_tag = hmac.new(tag_key, packet[:-32] + record_id.encode("utf-8"), hashlib.sha256).digest()
        if not hmac.compare_digest(supplied_tag, expected_tag):
            raise MyceliaCryptoError("CMS-Ciphertext wurde verändert oder gehört zu einem anderen Datensatz")
        return version, nonce, cipher

    def verify_token_auth(self, record_id: str, token: str) -> bytes:
        version, _, _ = self._decode_and_authenticate(record_id, token)
        return version

    def encrypt_json(self, record_id: str, value: dict[str, Any]) -> str:
        """Encrypt one record using CPU-only MCMS3."""
        plain = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        nonce = secrets.token_bytes(16)
        record_key = self._derive(b"enc3", nonce, record_id)
        cipher = self._crypt_cpu_hmac_stream(plain, record_key)
        header = self.VERSION_V3 + nonce
        tag_key = self._derive(b"auth3", nonce, record_id)
        tag = hmac.new(tag_key, header + cipher + record_id.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(header + cipher + tag).decode("ascii")

    def decrypt_json(self, record_id: str, token: str) -> dict[str, Any]:
        version, nonce, cipher = self._decode_and_authenticate(record_id, token)

        match version:
            case self.VERSION_V3:
                record_key = self._derive(b"enc3", nonce, record_id)
                plain = self._crypt_cpu_hmac_stream(cipher, record_key)
            case self.VERSION_V2:
                record_key = self._derive(b"enc2", nonce, record_id)
                plain = self._crypt_key256(cipher, record_key)
            case _:
                seed = int.from_bytes(self._derive(b"seed", nonce, record_id)[:8], "little", signed=False)
                plain = self._crypt_legacy(cipher, seed)

        try:
            obj = json.loads(plain.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MyceliaCryptoError("Entschlüsselter CMS-Datensatz ist ungültig") from exc
        if not isinstance(obj, dict):
            raise MyceliaCryptoError("CMS-Datensatz muss ein JSON-Objekt sein")
        return obj

    def blind_index(self, namespace: str, value: str) -> str:
        normalized = " ".join(value.casefold().split()).encode("utf-8")
        digest = hmac.new(
            self._master_key,
            b"idx\0" + namespace.encode("utf-8") + b"\0" + normalized,
            hashlib.sha256,
        ).hexdigest()
        return digest

    def close(self) -> None:
        ctx = getattr(self, "_ctx", None)
        lib = getattr(self, "_lib", None)
        if ctx and lib is not None:
            lib.myc_destroy_context(ctx)
            self._ctx = ctypes.c_void_p()
        self._lib = None
        if self._dll_dir_handle is not None:
            self._dll_dir_handle.close()
            self._dll_dir_handle = None
        key = getattr(self, "_master_key", None)
        if isinstance(key, bytearray):
            for index in range(len(key)):
                key[index] = 0
