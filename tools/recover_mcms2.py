from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cms.backup import NativeBackupManager
from cms.config import Settings
from cms.db import MyceliaDBClient
from cms.security import MyceliaCryptoError, MyceliaSecuritySDK


@dataclass(slots=True)
class Candidate:
    path: Path
    sha256: str
    gpu_index: int
    crypto: MyceliaSecuritySDK


@dataclass(slots=True)
class RecordResult:
    node_id: str
    version: str
    authenticated: bool
    recovered: bool
    candidate: str | None = None
    candidate_sha256: str | None = None
    gpu_index: int | None = None
    error: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def native_device_count(path: Path) -> int:
    dll_dir_handle = None
    try:
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            dll_dir_handle = os.add_dll_directory(str(path.parent.resolve()))
        lib = ctypes.WinDLL(str(path.resolve())) if hasattr(ctypes, "WinDLL") else ctypes.CDLL(str(path.resolve()))
        lib.myc_init.restype = ctypes.c_int
        lib.myc_get_device_count.restype = ctypes.c_int
        if lib.myc_init() != 0:
            return 0
        return max(0, int(lib.myc_get_device_count()))
    except (OSError, AttributeError):
        return 0
    finally:
        if dll_dir_handle is not None:
            dll_dir_handle.close()


def discover_runtime_paths(cfg: Settings, explicit: list[Path]) -> list[Path]:
    candidates: list[Path] = [
        cfg.sdk_dll,
        ROOT / "third_party" / "prebuilt" / "CC_OpenCl.dll",
        ROOT / "third_party" / "Mycelia-Security-SDK_v2_secure" / "bin" / "CC_OpenCl.dll",
    ]
    candidates.extend(sorted((ROOT / "recovery_runtimes").glob("**/CC_OpenCl.dll")))
    candidates.extend(explicit)

    unique: list[Path] = []
    seen: set[tuple[str, str]] = set()
    for path in candidates:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            continue
        try:
            digest = sha256_file(resolved)
        except OSError:
            continue
        # Same bytes on a different path are the same runtime candidate.
        key = (digest, resolved.name.casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def build_candidates(paths: list[Path], master_key: bytes) -> tuple[list[Candidate], list[str]]:
    ready: list[Candidate] = []
    warnings: list[str] = []
    for path in paths:
        digest = sha256_file(path)
        count = native_device_count(path)
        if count <= 0:
            warnings.append(f"{path}: keine kompatible GPU/ABI erkannt")
            continue
        for gpu_index in range(count):
            try:
                crypto = MyceliaSecuritySDK(path, master_key, gpu_index=gpu_index)
            except Exception as exc:  # recovery must continue with other candidates
                warnings.append(f"{path} GPU {gpu_index}: {exc}")
                continue
            ready.append(Candidate(path, digest, gpu_index, crypto))
    return ready, warnings


def is_ciphertext_token(value: str) -> bool:
    if not value or len(value) < 16:
        return False
    try:
        version = MyceliaSecuritySDK.token_version(value)
    except MyceliaCryptoError:
        return False
    return version in {
        MyceliaSecuritySDK.VERSION_V1,
        MyceliaSecuritySDK.VERSION_V2,
        MyceliaSecuritySDK.VERSION_V3,
    }


def recover_record(
    node_id: str,
    token: str,
    verifier: MyceliaSecuritySDK,
    candidates: list[Candidate],
) -> tuple[RecordResult, dict[str, Any] | None]:
    try:
        version = verifier.verify_token_auth(node_id, token)
    except MyceliaCryptoError as exc:
        return RecordResult(node_id, "unknown", False, False, error=str(exc)), None

    version_text = version.decode("ascii", "replace")
    if version == MyceliaSecuritySDK.VERSION_V3:
        try:
            value = verifier.decrypt_json(node_id, token)
            return RecordResult(node_id, version_text, True, True, candidate="MCMS3-CPU", candidate_sha256=None), value
        except MyceliaCryptoError as exc:
            return RecordResult(node_id, version_text, True, False, error=str(exc)), None

    errors: list[str] = []
    for candidate in candidates:
        try:
            value = candidate.crypto.decrypt_json(node_id, token)
        except Exception as exc:
            errors.append(f"{candidate.path.name}@GPU{candidate.gpu_index}: {exc}")
            continue
        return (
            RecordResult(
                node_id=node_id,
                version=version_text,
                authenticated=True,
                recovered=True,
                candidate=str(candidate.path.relative_to(ROOT) if candidate.path.is_relative_to(ROOT) else candidate.path),
                candidate_sha256=candidate.sha256,
                gpu_index=candidate.gpu_index,
            ),
            value,
        )

    return RecordResult(
        node_id=node_id,
        version=version_text,
        authenticated=True,
        recovered=False,
        error=" | ".join(errors[-8:]) if errors else "Kein Legacy-Runtime-Kandidat verfügbar",
    ), None


def write_report(results: list[RecordResult], warnings: list[str], mode: str) -> Path:
    out_dir = ROOT / "data" / "recovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"mcms2-recovery-{stamp}.json"
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "records": [asdict(item) for item in results],
        "warnings": warnings,
        "plaintext_in_report": False,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only probe or fail-closed migration of legacy MCMS1/MCMS2 records to CPU-stable MCMS3."
    )
    parser.add_argument("--migrate", action="store_true", help="Migrate only if every authenticated legacy record can be recovered.")
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        type=Path,
        help="Additional CC_OpenCl.dll recovery runtime. May be specified multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Settings.load()
    db = MyceliaDBClient(cfg.db_host, cfg.db_port, cfg.db_auth_token, pool_size=1)
    backups = NativeBackupManager(db, cfg.backup_dir, cfg.master_key)
    verifier = MyceliaSecuritySDK(cfg.sdk_dll, cfg.master_key, initialize_native=False)
    candidates: list[Candidate] = []

    try:
        db.require_secure_snapshot_engine()
        restore_message = backups.restore_checkpoint_if_present()
        print(f"[RECOVERY] Live-Checkpoint geladen: {restore_message}")

        runtime_paths = discover_runtime_paths(cfg, args.candidate)
        candidates, warnings = build_candidates(runtime_paths, cfg.master_key)
        print(f"[RECOVERY] Legacy-Runtime-Kandidaten: {len(candidates)}")
        for candidate in candidates:
            rel = candidate.path.relative_to(ROOT) if candidate.path.is_relative_to(ROOT) else candidate.path
            print(f"  - {rel} | GPU {candidate.gpu_index} | SHA256 {candidate.sha256}")
        for warning in warnings:
            print(f"[WARN] {warning}")

        results: list[RecordResult] = []
        recovered_plaintext: dict[str, dict[str, Any]] = {}
        encrypted_nodes = 0
        for node_id in db.list_node_ids():
            node = db.get_node(node_id)
            token = node.properties.get("data", "")
            if not is_ciphertext_token(token):
                continue
            encrypted_nodes += 1
            result, value = recover_record(node_id, token, verifier, candidates)
            results.append(result)
            state = "OK" if result.recovered else "FAIL"
            print(f"[{state}] {node_id} {result.version}" + (f" via {result.candidate} GPU {result.gpu_index}" if result.candidate else ""))
            if value is not None and result.version != "MCMS3":
                recovered_plaintext[node_id] = value

        failed = [item for item in results if item.authenticated and not item.recovered]
        unauthenticated = [item for item in results if not item.authenticated]
        legacy = [item for item in results if item.version in {"MCMS1", "MCMS2"}]
        report = write_report(results, warnings, "migrate" if args.migrate else "probe")

        print("\n=== Recovery-Zusammenfassung ===")
        print(f"Verschlüsselte Datensätze: {encrypted_nodes}")
        print(f"Legacy MCMS1/MCMS2:       {len(legacy)}")
        print(f"Erfolgreich lesbar:       {sum(1 for x in results if x.recovered)}")
        print(f"Authenticated, aber FAIL: {len(failed)}")
        print(f"Auth/Format FAIL:         {len(unauthenticated)}")
        print(f"Report:                   {report}")

        if not args.migrate:
            print("\nREAD-ONLY Probe abgeschlossen. Es wurde kein Datenbankwert verändert.")
            return 0 if not failed and not unauthenticated else 2

        if failed or unauthenticated:
            print("\nABBRUCH: Migration bleibt fail-closed. Kein Datensatz wird verändert, solange nicht alle Legacy-Datensätze lesbar sind.")
            return 3

        if not recovered_plaintext:
            print("\nKeine Legacy-Datensätze zu migrieren. Die Datenbank ist bereits MCMS3 oder enthält keine CMS-Ciphertexte.")
            return 0

        backup_info, backup_message = backups.create()
        print(f"\n[SAFETY] Unveränderter Pre-Migration-Backup erzeugt: {backup_info.name}")
        print(f"[SAFETY] {backup_message}")

        for node_id, value in recovered_plaintext.items():
            token_v3 = verifier.encrypt_json(node_id, value)
            if MyceliaSecuritySDK.token_version(token_v3) != MyceliaSecuritySDK.VERSION_V3:
                raise RuntimeError(f"Interner Fehler: MCMS3-Erzeugung für {node_id} fehlgeschlagen")
            db.set_property(node_id, "data", token_v3)
            # Immediate read-back using CPU-only crypto before proceeding.
            roundtrip = db.get_node(node_id).properties.get("data", "")
            if verifier.decrypt_json(node_id, roundtrip) != value:
                raise RuntimeError(f"MCMS3-Readback für {node_id} fehlgeschlagen")
            print(f"[MIGRATE] {node_id} -> MCMS3")

        checkpoint_message = backups.save_checkpoint()
        print(f"\n[OK] MCMS3-Migration vollständig. Live-Checkpoint geschrieben: {checkpoint_message}")
        print("[OK] Ab jetzt hängen neue und migrierte Datensätze nicht mehr vom GPU/OpenCL-Keystream ab.")
        return 0
    finally:
        for candidate in candidates:
            candidate.crypto.close()
        verifier.close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
