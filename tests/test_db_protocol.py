from __future__ import annotations

import socket
import threading
import unittest

from cms.db import MyceliaDBClient, MyceliaDBError, _quote


class _TestServer:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.accepts = 0
        self.commands: list[str] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                self.sock.settimeout(0.1)
                c, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.accepts += 1
            threading.Thread(target=self._client, args=(c,), daemon=True).start()

    def _client(self, c: socket.socket) -> None:
        with c:
            f = c.makefile("rwb", buffering=0)
            f.write(b"MYCELIADB ENTERPRISE SECURE AUTH_REQUIRED\n")
            f.flush()
            auth = f.readline().decode().rstrip("\r\n")
            if not auth.startswith("AUTH "):
                return
            f.write(b"OK AUTH\n")
            f.flush()
            while True:
                raw = f.readline()
                if not raw:
                    break
                cmd = raw.decode().rstrip("\r\n")
                self.commands.append(cmd)
                if cmd == "PING":
                    f.write(b"OK PONG snapshot=V2 manual_nodes=1 erase_node=1\n")
                else:
                    f.write(b"OK\n")
                f.flush()

    def close(self) -> None:
        self.stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self.thread.join(timeout=1)


class DBProtocolTests(unittest.TestCase):
    def test_quote(self) -> None:
        self.assertEqual(_quote('a"b\\c'), '"a\\"b\\\\c"')

    def test_quote_rejects_line_controls(self) -> None:
        for value in ("a\nb", "a\rb", "a\x00b"):
            with self.assertRaises(MyceliaDBError):
                _quote(value)

    def test_request_rejects_protocol_injection_before_socket(self) -> None:
        client = MyceliaDBClient("127.0.0.1", 1, "a" * 64)
        with self.assertRaises(MyceliaDBError):
            client.request("GET \"x\"\nERASE_NODE \"acct:user:admin\"")

    def test_auth_token_is_mandatory(self) -> None:
        with self.assertRaises(MyceliaDBError):
            MyceliaDBClient("127.0.0.1", 4555, "short")

    def test_persistent_connection_is_reused(self) -> None:
        server = _TestServer()
        try:
            client = MyceliaDBClient("127.0.0.1", server.port, "x" * 64, pool_size=2)
            self.assertIn("snapshot=V2", client.ping())
            self.assertIn("snapshot=V2", client.ping())
            self.assertIn("snapshot=V2", client.ping())
            self.assertEqual(server.accepts, 1)
            client.close()
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
