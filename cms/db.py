from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import select
import socket
import threading
from typing import BinaryIO


class MyceliaDBError(RuntimeError):
    pass


_FORBIDDEN_PROTOCOL_CHARS = ("\r", "\n", "\x00")
_MAX_PROTOCOL_LINE_BYTES = 1024 * 1024
_SOCKET_BUFFER_BYTES = 64 * 1024


def _reject_protocol_controls(value: str, *, label: str = "Protokollparameter") -> None:
    if not isinstance(value, str):
        raise MyceliaDBError(f"{label} muss Text sein")
    if any(ch in value for ch in _FORBIDDEN_PROTOCOL_CHARS):
        raise MyceliaDBError(f"{label} enthält verbotene CR/LF/NUL-Steuerzeichen")


def _quote(value: str) -> str:
    """Quote one MyceliaDB protocol atom, fail-closed on line controls."""
    _reject_protocol_controls(value)
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


@dataclass(slots=True)
class Node:
    node_id: str
    properties: dict[str, str]


@dataclass(slots=True)
class _PooledConnection:
    sock: socket.socket
    file: BinaryIO

    def close(self) -> None:
        try:
            self.file.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class MyceliaDBClient:
    """Thread-safe pooled client for the native MyceliaDB control protocol.

    Connections are authenticated once and then reused. A connection is leased
    to exactly one caller at a time, so command/response framing cannot cross
    threads. Broken/stale connections are discarded, never silently retried
    after a command may already have reached the server.
    """

    REQUIRED_PING_MARKER = "snapshot=V2 manual_nodes=1 erase_node=1"
    SECURE_BANNER = "MYCELIADB ENTERPRISE SECURE AUTH_REQUIRED"

    def __init__(
        self,
        host: str,
        port: int,
        auth_token: str,
        timeout: float = 5.0,
        pool_size: int = 4,
    ) -> None:
        if len(auth_token) < 48 or any(ch.isspace() for ch in auth_token):
            raise MyceliaDBError("Ungültiges MyceliaDB-Authentifizierungstoken")
        if not 1 <= pool_size <= 16:
            raise MyceliaDBError("MyceliaDB-Poolgröße muss zwischen 1 und 16 liegen")
        self.host = host
        self.port = port
        self.auth_token = auth_token
        self.timeout = timeout
        self.pool_size = pool_size
        self._pool: queue.LifoQueue[_PooledConnection] = queue.LifoQueue(maxsize=pool_size)
        self._state_lock = threading.Lock()
        self._created = 0
        self._closed = False

    def _reserve_slot(self) -> bool:
        with self._state_lock:
            if self._closed:
                raise MyceliaDBError("MyceliaDB-Client ist geschlossen")
            if self._created >= self.pool_size:
                return False
            self._created += 1
            return True

    def _drop_slot(self) -> None:
        with self._state_lock:
            self._created = max(0, self._created - 1)

    def _connect(self, timeout: float) -> _PooledConnection:
        sock: socket.socket | None = None
        file: BinaryIO | None = None
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
            sock.settimeout(timeout)
            # Large encrypted media records are transported as one protocol
            # line. An unbuffered SocketIO readline performs excessive tiny
            # reads; a bounded buffer keeps the authenticated protocol exactly
            # the same while avoiding that latency.
            file = sock.makefile("rwb", buffering=_SOCKET_BUFFER_BYTES)
            banner = file.readline().decode("utf-8", "replace").rstrip("\r\n")
            if banner != self.SECURE_BANNER:
                raise MyceliaDBError("Unerwartete oder unsichere MyceliaDB-Protokollkennung")
            file.write(f"AUTH {self.auth_token}\n".encode("ascii"))
            file.flush()
            auth_response = file.readline().decode("utf-8", "replace").rstrip("\r\n")
            if auth_response != "OK AUTH":
                raise MyceliaDBError("MyceliaDB-Authentifizierung fehlgeschlagen")
            return _PooledConnection(sock, file)
        except Exception:
            if file is not None:
                try:
                    file.close()
                except OSError:
                    pass
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            raise

    @staticmethod
    def _stale(conn: _PooledConnection) -> bool:
        try:
            readable, _, exceptional = select.select([conn.sock], [], [conn.sock], 0)
            # The protocol has no unsolicited server messages. Readability while
            # idle therefore means EOF/close or an out-of-sync connection.
            return bool(readable or exceptional)
        except (OSError, ValueError):
            return True

    def _acquire(self, timeout: float) -> _PooledConnection:
        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                if self._reserve_slot():
                    try:
                        return self._connect(timeout)
                    except Exception:
                        self._drop_slot()
                        raise
                try:
                    conn = self._pool.get(timeout=timeout)
                except queue.Empty as exc:
                    raise MyceliaDBError("MyceliaDB-Verbindungspool ausgelastet") from exc
            if self._stale(conn):
                conn.close()
                self._drop_slot()
                continue
            return conn

    def _release(self, conn: _PooledConnection) -> None:
        with self._state_lock:
            closed = self._closed
        if closed or self._stale(conn):
            conn.close()
            self._drop_slot()
            return
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            conn.close()
            self._drop_slot()

    def _discard(self, conn: _PooledConnection) -> None:
        conn.close()
        self._drop_slot()

    def request(self, command: str, *, timeout: float | None = None) -> str:
        _reject_protocol_controls(command, label="MyceliaDB-Befehl")
        if not command.strip():
            raise MyceliaDBError("Leerer MyceliaDB-Befehl")
        encoded = command.encode("utf-8")
        if len(encoded) + 1 > _MAX_PROTOCOL_LINE_BYTES:
            raise MyceliaDBError("MyceliaDB-Befehl überschreitet das Protokolllimit")

        effective_timeout = self.timeout if timeout is None else timeout
        verb = command.split(maxsplit=1)[0]
        conn: _PooledConnection | None = None
        try:
            conn = self._acquire(effective_timeout)
            conn.sock.settimeout(effective_timeout)
            conn.file.write(encoded + b"\n")
            conn.file.flush()
            response = conn.file.readline().decode("utf-8", "replace").rstrip("\r\n")
            if not response:
                raise MyceliaDBError("MyceliaDB lieferte eine leere Antwort")
        except (TimeoutError, socket.timeout) as exc:
            if conn is not None:
                self._discard(conn)
                conn = None
            raise MyceliaDBError(f"MyceliaDB-Zeitüberschreitung bei {verb}") from exc
        except OSError as exc:
            if conn is not None:
                self._discard(conn)
                conn = None
            raise MyceliaDBError(f"MyceliaDB-Verbindungsfehler: {exc}") from exc
        except Exception:
            if conn is not None:
                self._discard(conn)
                conn = None
            raise
        else:
            self._release(conn)
            conn = None

        if response.startswith("ERR"):
            raise MyceliaDBError(response)
        return response

    def ping(self) -> str:
        return self.request("PING")

    def require_secure_snapshot_engine(self) -> str:
        response = self.ping()
        if self.REQUIRED_PING_MARKER not in response:
            raise MyceliaDBError(
                "Unsichere/alte MyceliaDB-Runtime erkannt. Erforderlich ist die native "
                "V2-Persistenz mit manuellen Nodes und ERASE_NODE. Bitte install.ps1 erneut ausführen."
            )
        return response

    def list_node_ids(self, prefix: str = "") -> list[str]:
        _reject_protocol_controls(prefix, label="Node-Präfix")
        response = self.request("LIST_NODES")
        ids = response.split()[1:] if response.startswith("NODES") else []
        return [node_id for node_id in ids if node_id.startswith(prefix)]

    def get_node(self, node_id: str) -> Node:
        response = self.request(f"GET {_quote(node_id)}")
        parts = response.split()
        if len(parts) < 2 or parts[0] != "NODE":
            raise MyceliaDBError("Ungültige NODE-Antwort")
        properties: dict[str, str] = {}
        for item in parts[3:]:
            if "=" in item:
                key, value = item.split("=", 1)
                properties[key] = value
        return Node(parts[1], properties)

    def ensure_node(self, node_id: str) -> None:
        try:
            self.get_node(node_id)
        except MyceliaDBError as exc:
            if "missing node" not in str(exc):
                raise
            self.request(f"SPAWN {_quote(node_id)}")

    def set_property(self, node_id: str, key: str, value: str) -> None:
        _reject_protocol_controls(key, label="Property-Key")
        _reject_protocol_controls(value, label="Property-Wert")
        if any(ch.isspace() for ch in key) or "=" in key:
            raise MyceliaDBError("Ungültiger Property-Key")
        self.ensure_node(node_id)
        self.request(f"MUTATE {_quote(node_id)} {_quote(key)} {_quote(value)}")

    def delete_node(self, node_id: str) -> str:
        response = self.request(f"ERASE_NODE {_quote(node_id)}")
        if not response.startswith("OK ERASED"):
            raise MyceliaDBError("MyceliaDB hat ERASE_NODE nicht bestätigt")
        return response

    def save_native(self, path: str | Path, *, timeout: float = 120.0) -> str:
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        response = self.request(f"SAVE_DB {_quote(str(target))}", timeout=timeout)
        if "format=V2" not in response:
            raise MyceliaDBError("MyceliaDB hat keinen V2-Snapshot bestätigt")
        return response

    def load_native(self, path: str | Path, *, timeout: float = 120.0) -> str:
        source = Path(path).resolve()
        if not source.is_file():
            raise MyceliaDBError("Backup-Datei existiert nicht")
        response = self.request(f"LOAD_DB {_quote(str(source))}", timeout=timeout)
        if "format=V2" not in response:
            raise MyceliaDBError("Geladener Snapshot ist nicht im V2-Format")
        return response

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                break
            conn.close()
            self._drop_slot()
