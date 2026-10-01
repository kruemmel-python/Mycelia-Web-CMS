from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_ROOT = ROOT / "third_party" / "MyceliaDB_Enterprise_Studio_v0_2_secure"


def test_python_client_requires_native_erase_capability() -> None:
    text = (ROOT / "cms" / "db.py").read_text(encoding="utf-8")
    assert 'snapshot=V2 manual_nodes=1 erase_node=1' in text
    assert 'ERASE_NODE' in text


def test_native_core_only_erases_manual_nodes() -> None:
    engine = (DB_ROOT / "src" / "server" / "MyceliaEngine.cpp").read_text(encoding="utf-8")
    protocol = (DB_ROOT / "src" / "common" / "Protocol.cpp").read_text(encoding="utf-8")
    assert 'tok=="ERASE_NODE"' in protocol
    assert 'manualNodes_.contains(id)' in engine
    assert 'OK ERASED' in engine
    assert 'erase_node=1' in engine
