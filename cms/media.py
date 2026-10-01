from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import uuid
from typing import Iterable

from .backup import NativeBackupManager
from .db import MyceliaDBClient, MyceliaDBError
from .security import MyceliaSecuritySDK
from .modules.webshop.media import SanitizedImage, sanitize_image


@dataclass(slots=True)
class MediaImage:
    id: str
    owner_id: str
    parent_kind: str
    parent_id: str
    shop_id: str | None
    slot: str
    original_name: str
    mime_type: str
    content_b64: str
    sha256: str
    width: int
    height: int
    position: int
    created_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SecureMediaRepository:
    """Shared encrypted image layer for CMS and platform content.

    All image bytes are decoded/re-encoded by the same sanitizer used for the
    product gallery, then stored inside the encrypted Mycelia payload.  No
    public upload directory or user supplied filesystem path exists.
    """

    PREFIX = "media:image:"
    ALLOWED_PARENT_KINDS = {
        "cms-page",
        "shop-logo",
        "shop-banner",
        "shop-blog",
        "creator-avatar",
        "creator-post",
        "forum-topic",
        "forum-reply",
        "knowledge",
        "community-post",
        "community-comment",
        "ticket-message",
        "document",
    }

    def __init__(self, db: MyceliaDBClient, crypto: MyceliaSecuritySDK, backups: NativeBackupManager) -> None:
        self.db = db
        self.crypto = crypto
        self.backups = backups

    @staticmethod
    def sanitize_upload(file_storage) -> SanitizedImage:
        return sanitize_image(file_storage)

    @staticmethod
    def _validate_parent_kind(parent_kind: str) -> str:
        if parent_kind not in SecureMediaRepository.ALLOWED_PARENT_KINDS:
            raise ValueError("Ungültiger Media-Kontext")
        return parent_kind

    def _node(self, image_id: str) -> str:
        if len(image_id) != 32 or any(ch not in "0123456789abcdef" for ch in image_id):
            raise ValueError("Ungültige Media-ID")
        return self.PREFIX + image_id

    def _parent_index(self, parent_kind: str, parent_id: str, slot: str) -> str:
        return self.crypto.blind_index(f"media-parent:{parent_kind}:{slot}", parent_id)

    def _owner_index(self, owner_id: str) -> str:
        return self.crypto.blind_index("media-owner", owner_id)

    def _write(self, image: MediaImage) -> None:
        node_id = self._node(image.id)
        self.db.set_property(node_id, "kind", "media_image")
        self.db.set_property(node_id, "parent_kind", image.parent_kind)
        self.db.set_property(node_id, "slot", image.slot)
        self.db.set_property(node_id, "parent_idx", self._parent_index(image.parent_kind, image.parent_id, image.slot))
        self.db.set_property(node_id, "owner_idx", self._owner_index(image.owner_id))
        if image.shop_id:
            self.db.set_property(node_id, "shop_idx", self.crypto.blind_index("media-shop", image.shop_id))
        self.db.set_property(node_id, "data", self.crypto.encrypt_json(node_id, asdict(image)))

    def get(self, image_id: str) -> MediaImage | None:
        node_id = self._node(image_id)
        try:
            node = self.db.get_node(node_id)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise
        token = node.properties.get("data")
        return MediaImage(**self.crypto.decrypt_json(node_id, token)) if token else None

    def list_for_parent(self, parent_kind: str, parent_id: str, *, slot: str = "gallery") -> list[MediaImage]:
        self._validate_parent_kind(parent_kind)
        target = self._parent_index(parent_kind, parent_id, slot)
        out: list[MediaImage] = []
        for node_id in self.db.list_node_ids(self.PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("parent_idx") != target:
                continue
            token = node.properties.get("data")
            if not token:
                continue
            image = MediaImage(**self.crypto.decrypt_json(node_id, token))
            if image.parent_kind == parent_kind and image.parent_id == parent_id and image.slot == slot:
                out.append(image)
        out.sort(key=lambda x: (x.position, x.created_at, x.id))
        return out

    def add_uploads(
        self,
        *,
        owner_id: str,
        parent_kind: str,
        parent_id: str,
        uploads: Iterable[SanitizedImage],
        max_count: int = 3,
        shop_id: str | None = None,
        slot: str = "gallery",
        remove_ids: set[str] | None = None,
        replace_slot: bool = False,
    ) -> list[MediaImage]:
        self._validate_parent_kind(parent_kind)
        if not 1 <= max_count <= 6:
            raise ValueError("Ungültiges Media-Limit")
        existing = self.list_for_parent(parent_kind, parent_id, slot=slot)
        existing_by_id = {x.id: x for x in existing}
        remove = set(existing_by_id) if replace_slot else set(remove_ids or set())
        if not remove.issubset(existing_by_id):
            raise ValueError("Ungültige Bildauswahl")
        retained = [x for x in existing if x.id not in remove]
        pending = list(uploads)
        if len(retained) + len(pending) > max_count:
            raise ValueError(f"Maximal {max_count} Bilder sind in diesem Bereich erlaubt")

        created: list[MediaImage] = []
        try:
            now = utc_now()
            for pos, upload in enumerate(pending, start=len(retained)):
                image = MediaImage(
                    id=uuid.uuid4().hex,
                    owner_id=owner_id,
                    parent_kind=parent_kind,
                    parent_id=parent_id,
                    shop_id=shop_id,
                    slot=slot,
                    original_name=upload.original_name,
                    mime_type=upload.mime_type,
                    content_b64=base64.b64encode(upload.content).decode("ascii"),
                    sha256=upload.sha256,
                    width=upload.width,
                    height=upload.height,
                    position=pos,
                    created_at=now,
                )
                self._write(image)
                created.append(image)

            final = retained + created
            for pos, image in enumerate(final):
                if image.position != pos:
                    image.position = pos
                    self._write(image)

            for image_id in remove:
                try:
                    self.db.delete_node(self._node(image_id))
                except MyceliaDBError as exc:
                    if "missing node" not in str(exc):
                        raise
            self.backups.save_checkpoint()
            return final
        except Exception:
            for image in created:
                try:
                    self.db.delete_node(self._node(image.id))
                except Exception:
                    pass
            raise

    def delete_parent(self, parent_kind: str, parent_id: str, *, slot: str | None = None, checkpoint: bool = True) -> int:
        self._validate_parent_kind(parent_kind)
        targets: list[MediaImage] = []
        if slot is not None:
            targets.extend(self.list_for_parent(parent_kind, parent_id, slot=slot))
        else:
            for candidate_slot in ("gallery", "avatar", "logo", "banner"):
                targets.extend(self.list_for_parent(parent_kind, parent_id, slot=candidate_slot))
        deleted = 0
        for image in {x.id: x for x in targets}.values():
            try:
                self.db.delete_node(self._node(image.id))
                deleted += 1
            except MyceliaDBError as exc:
                if "missing node" not in str(exc):
                    raise
        if deleted and checkpoint:
            self.backups.save_checkpoint()
        return deleted

    def list_for_owner(self, owner_id: str) -> list[MediaImage]:
        target = self._owner_index(owner_id)
        out: list[MediaImage] = []
        for node_id in self.db.list_node_ids(self.PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("owner_idx") != target:
                continue
            token = node.properties.get("data")
            if token:
                out.append(MediaImage(**self.crypto.decrypt_json(node_id, token)))
        out.sort(key=lambda x: x.created_at)
        return out

    def export_owner(self, owner_id: str) -> list[dict[str, object]]:
        return [asdict(image) for image in self.list_for_owner(owner_id)]

    def delete_owner(self, owner_id: str, *, checkpoint: bool = True) -> int:
        deleted = 0
        for image in self.list_for_owner(owner_id):
            try:
                self.db.delete_node(self._node(image.id))
                deleted += 1
            except MyceliaDBError as exc:
                if "missing node" not in str(exc):
                    raise
        if deleted and checkpoint:
            self.backups.save_checkpoint()
        return deleted

    def bytes(self, image: MediaImage) -> bytes:
        try:
            data = base64.b64decode(image.content_b64, validate=True)
        except Exception as exc:
            raise MyceliaDBError("Media-Payload ist beschädigt") from exc
        digest = hashlib.sha256(data).hexdigest()
        if not hmac.compare_digest(digest, image.sha256):
            raise MyceliaDBError("Media-Integritätsprüfung fehlgeschlagen")
        return data
