from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from cms.backup import BackupIntegrityError, NativeBackupManager


class FakeNativeDB:
    def __init__(self) -> None:
        self.payload = b"MYCELIADB_SNAPSHOT_V2\nMANUAL_NODE_COUNT\t1\n"
        self.loaded: bytes | None = None

    def save_native(self, path: Path) -> str:
        Path(path).write_bytes(self.payload)
        return "OK SAVE_DB format=V2"

    def load_native(self, path: Path) -> str:
        self.loaded = Path(path).read_bytes()
        return "OK LOAD_DB format=V2"


class NativeBackupTests(unittest.TestCase):
    def test_backup_is_authenticated_and_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = NativeBackupManager(FakeNativeDB(), Path(tmp), b"k" * 32)
            info, _ = manager.create()
            path = Path(tmp) / info.name
            self.assertTrue(manager.verify(path))
            path.write_bytes(path.read_bytes() + b"tamper")
            self.assertFalse(manager.verify(path))
            with self.assertRaises(BackupIntegrityError):
                manager.restore(info.name)


if __name__ == "__main__":
    unittest.main()
