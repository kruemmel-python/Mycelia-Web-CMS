from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import re

from .db import MyceliaDBClient, MyceliaDBError

BACKUP_NAME_RE = re.compile(r"^mycelia-cms-[0-9]{8}T[0-9]{6}Z\.mycdb$")


class BackupIntegrityError(MyceliaDBError):
    pass


@dataclass(frozen=True, slots=True)
class BackupInfo:
    name: str
    size: int
    created_at: str
    authenticated: bool


class NativeBackupManager:
    """Native MyceliaDB V2 backup/restore with a keyed integrity sidecar.

    The snapshot itself is produced and consumed only by MyceliaDB.  The CMS
    sidecar does not replace database persistence; it merely authenticates the
    backup file before a restore is allowed.
    """

    def __init__(self, db: MyceliaDBClient, backup_dir: Path, master_key: bytes) -> None:
        self.db = db
        self.backup_dir = backup_dir.resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.backup_dir / "cms-live.mycdb"
        self._auth_key = hmac.new(master_key, b"mycelia-cms/native-backup-auth/v1", hashlib.sha256).digest()

    def _safe_path(self, name: str) -> Path:
        if not BACKUP_NAME_RE.fullmatch(name):
            raise BackupIntegrityError("Ungültiger Backup-Dateiname")
        candidate = (self.backup_dir / name).resolve()
        if candidate.parent != self.backup_dir:
            raise BackupIntegrityError("Backup-Pfad verlässt das erlaubte Verzeichnis")
        return candidate

    @staticmethod
    def _tag_path(path: Path) -> Path:
        return path.with_suffix(path.suffix + ".hmac")

    def _file_hmac(self, path: Path) -> str:
        mac = hmac.new(self._auth_key, digestmod=hashlib.sha256)
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                mac.update(chunk)
        mac.update(path.name.encode("utf-8"))
        return mac.hexdigest()


    def save_checkpoint(self) -> str:
        message = self.db.save_native(self.checkpoint_path)
        if not self.checkpoint_path.is_file() or self.checkpoint_path.stat().st_size == 0:
            raise BackupIntegrityError("Native Live-Persistenz wurde nicht geschrieben")
        tag = self._file_hmac(self.checkpoint_path)
        self._tag_path(self.checkpoint_path).write_text(tag + "\n", encoding="ascii")
        return message

    def restore_checkpoint_if_present(self) -> str:
        if not self.checkpoint_path.exists():
            return "OK LIVE_RESTORE_SKIPPED reason=missing"
        if not self.verify(self.checkpoint_path):
            raise BackupIntegrityError("Native Live-Persistenz ist verändert oder beschädigt; Start verweigert")
        return self.db.load_native(self.checkpoint_path)

    def create(self) -> tuple[BackupInfo, str]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"mycelia-cms-{stamp}.mycdb"
        target = self._safe_path(name)
        message = self.db.save_native(target)
        if not target.is_file() or target.stat().st_size == 0:
            raise BackupIntegrityError("MyceliaDB meldete Erfolg, aber die Backup-Datei fehlt oder ist leer")
        tag = self._file_hmac(target)
        self._tag_path(target).write_text(tag + "\n", encoding="ascii")
        return self.describe(target), message

    def verify(self, path: Path) -> bool:
        tag_path = self._tag_path(path)
        if not path.is_file() or not tag_path.is_file():
            return False
        supplied = tag_path.read_text(encoding="ascii").strip()
        expected = self._file_hmac(path)
        return hmac.compare_digest(supplied, expected)

    def purge_historical_backups(self) -> int:
        """Delete historical manual backups after a privacy hard-delete.

        The canonical live checkpoint is overwritten separately after the
        deletion. Historical snapshots are removed so erased personal data is
        not silently retained in ordinary CMS backups.
        """
        removed = 0
        for path in self.backup_dir.glob("mycelia-cms-*.mycdb"):
            if not BACKUP_NAME_RE.fullmatch(path.name) or not path.is_file():
                continue
            tag = self._tag_path(path)
            path.unlink(missing_ok=True)
            tag.unlink(missing_ok=True)
            removed += 1
        return removed

    def restore(self, name: str) -> str:
        source = self._safe_path(name)
        if not self.verify(source):
            raise BackupIntegrityError("Backup-Integritätsprüfung fehlgeschlagen; Restore wurde verweigert")
        return self.db.load_native(source)

    def describe(self, path: Path) -> BackupInfo:
        stat = path.stat()
        dt = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        return BackupInfo(path.name, stat.st_size, dt, self.verify(path))

    def list(self) -> list[BackupInfo]:
        items: list[BackupInfo] = []
        for path in sorted(self.backup_dir.glob("mycelia-cms-*.mycdb"), reverse=True):
            if BACKUP_NAME_RE.fullmatch(path.name) and path.is_file():
                items.append(self.describe(path))
        return items
