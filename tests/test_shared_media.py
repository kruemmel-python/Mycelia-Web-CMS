from __future__ import annotations

import io
import json
import hmac
import hashlib

from PIL import Image

from cms.db import MyceliaDBError, Node
from cms.media import SecureMediaRepository


class FakeCrypto:
    def __init__(self) -> None:
        self.key = b"media-test-key"
    def encrypt_json(self, record_id: str, value: dict) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    def decrypt_json(self, record_id: str, token: str) -> dict:
        return json.loads(token)
    def blind_index(self, namespace: str, value: str) -> str:
        normalized = " ".join(value.casefold().split()).encode()
        return hmac.new(self.key, namespace.encode() + b"\0" + normalized, hashlib.sha256).hexdigest()


class FakeDB:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, str]] = {}
    def list_node_ids(self, prefix: str = "") -> list[str]:
        return [node_id for node_id in self.nodes if node_id.startswith(prefix)]
    def get_node(self, node_id: str) -> Node:
        if node_id not in self.nodes:
            raise MyceliaDBError("ERR missing node")
        return Node(node_id, dict(self.nodes[node_id]))
    def set_property(self, node_id: str, key: str, value: str) -> None:
        self.nodes.setdefault(node_id, {})[key] = value
    def delete_node(self, node_id: str) -> str:
        if node_id not in self.nodes:
            raise MyceliaDBError("ERR missing node")
        del self.nodes[node_id]
        return f"OK ERASED {node_id}"


class FakeBackups:
    def __init__(self) -> None:
        self.checkpoints = 0
    def save_checkpoint(self) -> str:
        self.checkpoints += 1
        return "OK"


class Upload:
    def __init__(self, data: bytes, filename: str = "image.png") -> None:
        self.filename = filename
        self._io = io.BytesIO(data)
    def read(self, size: int = -1) -> bytes:
        return self._io.read(size)


def png_upload() -> Upload:
    buf = io.BytesIO()
    Image.new("RGBA", (120, 80), (40, 180, 100, 180)).save(buf, format="PNG")
    return Upload(buf.getvalue())


def test_shared_media_roundtrip_and_hard_delete() -> None:
    db = FakeDB(); crypto = FakeCrypto(); backups = FakeBackups()
    repo = SecureMediaRepository(db, crypto, backups)
    clean = repo.sanitize_upload(png_upload())
    images = repo.add_uploads(
        owner_id="a" * 32,
        parent_kind="forum-reply",
        parent_id="b" * 32,
        uploads=[clean],
        max_count=3,
    )
    assert len(images) == 1
    image = images[0]
    assert repo.bytes(image).startswith(b"\xff\xd8")
    assert repo.list_for_parent("forum-reply", "b" * 32)[0].id == image.id
    export = repo.export_owner("a" * 32)
    assert export[0]["content_b64"]
    assert repo.delete_owner("a" * 32) == 1
    assert repo.get(image.id) is None


def test_shared_media_enforces_limits_and_parent_context() -> None:
    db = FakeDB(); crypto = FakeCrypto(); backups = FakeBackups()
    repo = SecureMediaRepository(db, crypto, backups)
    clean = repo.sanitize_upload(png_upload())
    try:
        repo.add_uploads(owner_id="a" * 32, parent_kind="not-allowed", parent_id="b" * 32, uploads=[clean])
        assert False, "unknown parent kind must fail"
    except ValueError:
        pass
    try:
        repo.add_uploads(owner_id="a" * 32, parent_kind="community-comment", parent_id="b" * 32, uploads=[clean, clean], max_count=1)
        assert False, "max count must fail"
    except ValueError:
        pass
