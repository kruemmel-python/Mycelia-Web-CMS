from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import uuid

from .backup import NativeBackupManager
from .db import MyceliaDBClient, MyceliaDBError
from .validation import normalize_slug, validate_page_id, validate_title
from .richtext import validate_richtext
from .security import MyceliaSecuritySDK


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class Page:
    id: str
    title: str
    slug: str
    body: str
    status: str
    created_at: str
    updated_at: str
    deleted: bool = False


class CMSRepository:
    PREFIX = "cms:page:"

    def __init__(self, db: MyceliaDBClient, crypto: MyceliaSecuritySDK, backups: NativeBackupManager) -> None:
        self.db = db
        self.crypto = crypto
        self.backups = backups

    def _node_id(self, page_id: str) -> str:
        return f"{self.PREFIX}{validate_page_id(page_id)}"

    def _decode_page(self, node_id: str, token: str) -> Page:
        data = self.crypto.decrypt_json(node_id, token)
        page = Page(**data)
        validate_page_id(page.id)
        page.title = validate_title(page.title)
        page.slug = normalize_slug(page.slug)
        page.body = validate_richtext(page.body, "document", max_chars=524_288, required=False)
        if page.status not in {"draft", "published"}:
            raise ValueError("Ungültiger Seitenstatus im verschlüsselten Datensatz")
        return page

    def list_pages(self, include_deleted: bool = False) -> list[Page]:
        pages: list[Page] = []
        for node_id in self.db.list_node_ids(self.PREFIX):
            node = self.db.get_node(node_id)
            token = node.properties.get("data")
            if not token:
                continue
            page = self._decode_page(node_id, token)
            if include_deleted or not page.deleted:
                pages.append(page)
        pages.sort(key=lambda page: page.updated_at, reverse=True)
        return pages

    def get_page(self, page_id: str) -> Page | None:
        node_id = self._node_id(page_id)
        try:
            node = self.db.get_node(node_id)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise
        token = node.properties.get("data")
        if not token:
            return None
        page = self._decode_page(node_id, token)
        return None if page.deleted else page

    def find_by_slug(self, slug: str, published_only: bool = True) -> Page | None:
        normalized = normalize_slug(slug)
        target = self.crypto.blind_index("page-slug", normalized)
        for node_id in self.db.list_node_ids(self.PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("slug_idx") != target:
                continue
            token = node.properties.get("data")
            if not token:
                continue
            page = self._decode_page(node_id, token)
            if page.deleted or (published_only and page.status != "published"):
                return None
            return page
        return None

    def _assert_slug_available(self, slug: str, page_id: str | None) -> None:
        existing = self.find_by_slug(slug, published_only=False)
        if existing is not None and existing.id != page_id:
            raise ValueError("Dieser Slug wird bereits von einer anderen Seite verwendet.")

    def save_page(self, *, page_id: str | None, title: str, slug: str, body: str, status: str) -> Page:
        title = validate_title(title)
        slug = normalize_slug(slug)
        body = validate_richtext(body, "document", max_chars=524_288, required=False)
        if status not in {"draft", "published"}:
            raise ValueError("Ungültiger Status")
        if page_id is not None:
            validate_page_id(page_id)
        self._assert_slug_available(slug, page_id)

        now = utc_now()
        existing = self.get_page(page_id) if page_id else None
        page = Page(
            id=page_id or uuid.uuid4().hex,
            title=title,
            slug=slug,
            body=body,
            status=status,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        node_id = self._node_id(page.id)

        # The public metadata is deliberately minimal. The actual page object is
        # encrypted by the original Mycelia Security SDK before it reaches MyceliaDB.
        self.db.set_property(node_id, "kind", "page")
        self.db.set_property(node_id, "slug_idx", self.crypto.blind_index("page-slug", page.slug))
        self.db.set_property(node_id, "data", self.crypto.encrypt_json(node_id, asdict(page)))

        # Durability is native MyceliaDB V2, not a parallel CMS JSON format.
        self.backups.save_checkpoint()
        return page

    def delete_page(self, page_id: str) -> bool:
        validate_page_id(page_id)
        page = self.get_page(page_id)
        if not page:
            return False
        page.deleted = True
        page.updated_at = utc_now()
        node_id = self._node_id(page.id)
        self.db.set_property(node_id, "data", self.crypto.encrypt_json(node_id, asdict(page)))
        self.backups.save_checkpoint()
        return True
