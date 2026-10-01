from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import threading
from typing import Any


class AuditLog:
    """Append-only HMAC hash chain for privileged CMS actions."""

    def __init__(self, path: Path, master_key: bytes) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key = hmac.new(master_key, b"mycelia-cms/audit-chain/v1", hashlib.sha256).digest()
        self._lock = threading.RLock()
        self._last = self._read_last_hash()

    def _read_last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = ""
        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    last = line
        if not last:
            return "0" * 64
        try:
            obj = json.loads(last)
            return str(obj.get("chain", "0" * 64))
        except Exception:
            return "0" * 64

    def record(self, event: str, *, actor: str, remote: str, detail: dict[str, Any] | None = None) -> None:
        with self._lock:
            payload = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "event": event,
                "actor": actor,
                "remote": remote,
                "detail": detail or {},
                "prev": self._last,
            }
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            chain = hmac.new(self._key, canonical, hashlib.sha256).hexdigest()
            payload["chain"] = chain
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
            self._last = chain
