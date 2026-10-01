from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import datetime, timezone
import re
from typing import Any, Type, TypeVar
import uuid

from ...backup import NativeBackupManager
from ...db import MyceliaDBClient, MyceliaDBError
from ...security import MyceliaSecuritySDK
from ...validation import normalize_slug, validate_body, validate_title
from ...richtext import validate_richtext, plain_text as richtext_plain
from ..webshop.repository import WebshopRepository, validate_id
from .models import (
    CommunityComment,
    CommunityPost,
    CreatorPost,
    CreatorProfile,
    DocumentRecord,
    DownloadAsset,
    ForumReply,
    ForumTopic,
    KnowledgeArticle,
    ShopMembership,
    SupportTicket,
    TicketMessage,
)

T = TypeVar("T")
URL_RE = re.compile(r"^https://[^\s]{1,1900}$", re.IGNORECASE)
MAX_TEXT = 200_000
MAX_UPLOAD_BYTES = 700_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _plain(value: str, *, max_len: int = MAX_TEXT, required: bool = True) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\x00" in text:
        raise ValueError("NUL-Zeichen sind nicht erlaubt")
    if required and not text:
        raise ValueError("Das Feld darf nicht leer sein")
    if len(text) > max_len:
        raise ValueError(f"Text ist zu lang (maximal {max_len} Zeichen)")
    return text


class EcosystemRepository:
    CREATOR_PREFIX = "platform:creator:profile:"
    CREATOR_POST_PREFIX = "platform:creator:post:"
    MEMBER_PREFIX = "platform:member:"
    DOWNLOAD_PREFIX = "platform:download:"
    TICKET_PREFIX = "platform:ticket:"
    TICKET_MSG_PREFIX = "platform:ticketmsg:"
    KB_PREFIX = "platform:kb:"
    FORUM_TOPIC_PREFIX = "platform:forum:topic:"
    FORUM_REPLY_PREFIX = "platform:forum:reply:"
    DOC_PREFIX = "platform:doc:"
    COMMUNITY_POST_PREFIX = "platform:community:post:"
    COMMUNITY_COMMENT_PREFIX = "platform:community:comment:"

    def __init__(self, db: MyceliaDBClient, crypto: MyceliaSecuritySDK, backups: NativeBackupManager, webshop: WebshopRepository) -> None:
        self.db = db
        self.crypto = crypto
        self.backups = backups
        self.webshop = webshop

    @staticmethod
    def _node(prefix: str, record_id: str) -> str:
        return prefix + validate_id(record_id)

    def _write(self, prefix: str, record_id: str, kind: str, value: Any, props: dict[str, str]) -> None:
        node_id = self._node(prefix, record_id)
        self.db.set_property(node_id, "kind", kind)
        for key, val in props.items():
            self.db.set_property(node_id, key, val)
        self.db.set_property(node_id, "data", self.crypto.encrypt_json(node_id, asdict(value)))

    def _decode(self, prefix: str, record_id: str, model: Type[T]) -> T | None:
        node_id = self._node(prefix, record_id)
        try:
            node = self.db.get_node(node_id)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise
        token = node.properties.get("data")
        return model(**self.crypto.decrypt_json(node_id, token)) if token else None

    def _list(self, prefix: str, model: Type[T], prop: tuple[str, str] | None = None) -> list[T]:
        out: list[T] = []
        for node_id in self.db.list_node_ids(prefix):
            node = self.db.get_node(node_id)
            if prop and node.properties.get(prop[0]) != prop[1]:
                continue
            token = node.properties.get("data")
            if token:
                out.append(model(**self.crypto.decrypt_json(node_id, token)))
        return out

    def _delete(self, prefix: str, record_id: str) -> None:
        self.db.delete_node(self._node(prefix, record_id))

    def _checkpoint(self) -> None:
        self.backups.save_checkpoint()

    # Creator platform -------------------------------------------------
    def get_creator(self, user_id: str) -> CreatorProfile | None:
        validate_id(user_id)
        return self._decode(self.CREATOR_PREFIX, user_id, CreatorProfile)

    def save_creator(self, user_id: str, display_name: str, bio: str, website: str) -> CreatorProfile:
        user = self.webshop.get_user(user_id)
        if not user:
            raise ValueError("Benutzer nicht gefunden")
        display_name = validate_title(display_name)
        bio = validate_richtext(bio, "standard", max_chars=40_000, required=False)
        website = website.strip()
        if website and not URL_RE.fullmatch(website):
            raise ValueError("Website muss eine HTTPS-Adresse sein")
        old = self.get_creator(user_id)
        now = utc_now()
        profile = CreatorProfile(user_id, user_id, display_name, bio, website, old.created_at if old else now, now, True)
        self._write(self.CREATOR_PREFIX, user_id, "creator_profile", profile, {
            "user_idx": self.crypto.blind_index("creator-user", user_id)
        })
        self._checkpoint()
        return profile

    def list_creators(self) -> list[CreatorProfile]:
        items = [x for x in self._list(self.CREATOR_PREFIX, CreatorProfile) if x.active]
        items.sort(key=lambda x: x.display_name.casefold())
        return items

    def get_creator_post(self, post_id: str) -> CreatorPost | None:
        return self._decode(self.CREATOR_POST_PREFIX, post_id, CreatorPost)

    def list_creator_posts(self, creator_id: str, *, public_only: bool = False) -> list[CreatorPost]:
        idx = self.crypto.blind_index("creator-post-owner", creator_id)
        posts = self._list(self.CREATOR_POST_PREFIX, CreatorPost, ("creator_idx", idx))
        if public_only:
            posts = [x for x in posts if x.status == "published"]
        posts.sort(key=lambda x: x.created_at, reverse=True)
        return posts

    def save_creator_post(self, creator_id: str, post_id: str | None, title: str, slug: str, body: str, visibility: str, status: str) -> CreatorPost:
        if not self.get_creator(creator_id):
            raise ValueError("Creator-Profil zuerst anlegen")
        title = validate_title(title)
        slug = normalize_slug(slug)
        body = validate_richtext(body, "document", max_chars=200_000, required=True)
        if visibility not in {"public", "members"}:
            raise ValueError("Ungültige Sichtbarkeit")
        if status not in {"draft", "published"}:
            raise ValueError("Ungültiger Status")
        old = self.get_creator_post(post_id) if post_id else None
        if old and old.creator_id != creator_id:
            raise PermissionError("Nicht erlaubt")
        for item in self.list_creator_posts(creator_id):
            if item.slug == slug and (not old or item.id != old.id):
                raise ValueError("Slug ist bereits vergeben")
        now = utc_now()
        post = CreatorPost(old.id if old else uuid.uuid4().hex, creator_id, title, slug, body, visibility, status, old.created_at if old else now, now)
        self._write(self.CREATOR_POST_PREFIX, post.id, "creator_post", post, {
            "creator_idx": self.crypto.blind_index("creator-post-owner", creator_id),
            "slug_idx": self.crypto.blind_index(f"creator-post-slug:{creator_id}", slug),
        })
        self._checkpoint()
        return post

    # Membership -------------------------------------------------------
    def is_member(self, shop_id: str, user_id: str) -> bool:
        idx = self.crypto.blind_index("membership-pair", f"{shop_id}:{user_id}")
        return bool(self._list(self.MEMBER_PREFIX, ShopMembership, ("pair_idx", idx)))

    def join_shop(self, shop_id: str, user_id: str) -> ShopMembership:
        if not self.webshop.get_shop(shop_id) or not self.webshop.get_user(user_id):
            raise ValueError("Shop oder Benutzer nicht gefunden")
        idx = self.crypto.blind_index("membership-pair", f"{shop_id}:{user_id}")
        existing = self._list(self.MEMBER_PREFIX, ShopMembership, ("pair_idx", idx))
        if existing:
            return existing[0]
        membership = ShopMembership(uuid.uuid4().hex, shop_id, user_id, utc_now(), "active")
        self._write(self.MEMBER_PREFIX, membership.id, "membership", membership, {
            "shop_idx": self.crypto.blind_index("membership-shop", shop_id),
            "user_idx": self.crypto.blind_index("membership-user", user_id),
            "pair_idx": idx,
        })
        self._checkpoint()
        return membership

    def leave_shop(self, shop_id: str, user_id: str) -> bool:
        idx = self.crypto.blind_index("membership-pair", f"{shop_id}:{user_id}")
        members = self._list(self.MEMBER_PREFIX, ShopMembership, ("pair_idx", idx))
        for member in members:
            self._delete(self.MEMBER_PREFIX, member.id)
        if members:
            self._checkpoint()
        return bool(members)

    def list_members(self, shop_id: str) -> list[ShopMembership]:
        idx = self.crypto.blind_index("membership-shop", shop_id)
        return self._list(self.MEMBER_PREFIX, ShopMembership, ("shop_idx", idx))

    # Download portal --------------------------------------------------
    def save_download(self, owner_id: str, asset_id: str | None, title: str, slug: str, description: str, filename: str, mime_type: str, content: bytes | None, visibility: str, active: bool) -> DownloadAsset:
        shop = self.webshop.get_shop_for_owner(owner_id)
        if not shop:
            raise ValueError("Shop erforderlich")
        title = validate_title(title)
        slug = normalize_slug(slug)
        description = validate_richtext(description, "standard", max_chars=40_000, required=False)
        if visibility not in {"public", "members"}:
            raise ValueError("Ungültige Sichtbarkeit")
        old = self._decode(self.DOWNLOAD_PREFIX, asset_id, DownloadAsset) if asset_id else None
        if old and old.owner_id != owner_id:
            raise PermissionError("Nicht erlaubt")
        if content is None and not old:
            raise ValueError("Datei erforderlich")
        if content is not None and len(content) > MAX_UPLOAD_BYTES:
            raise ValueError(f"Die Datei ist zu groß. Erlaubt sind maximal {MAX_UPLOAD_BYTES // 1000} KB. Bitte verkleinere oder komprimiere die Datei.")
        now = utc_now()
        asset = DownloadAsset(
            old.id if old else uuid.uuid4().hex,
            shop.id, owner_id, title, slug, description,
            filename or (old.filename if old else "download.bin"),
            mime_type or (old.mime_type if old else "application/octet-stream"),
            base64.b64encode(content).decode("ascii") if content is not None else old.content_b64,
            visibility, old.created_at if old else now, now, active,
        )
        self._write(self.DOWNLOAD_PREFIX, asset.id, "download", asset, {
            "shop_idx": self.crypto.blind_index("download-shop", shop.id),
            "owner_idx": self.crypto.blind_index("download-owner", owner_id),
            "slug_idx": self.crypto.blind_index(f"download-slug:{shop.id}", slug),
        })
        self._checkpoint()
        return asset

    def list_downloads(self, shop_id: str, *, active_only: bool = False) -> list[DownloadAsset]:
        idx = self.crypto.blind_index("download-shop", shop_id)
        items = self._list(self.DOWNLOAD_PREFIX, DownloadAsset, ("shop_idx", idx))
        if active_only:
            items = [x for x in items if x.active]
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items

    def get_download(self, asset_id: str) -> DownloadAsset | None:
        return self._decode(self.DOWNLOAD_PREFIX, asset_id, DownloadAsset)

    def delete_download(self, owner_id: str, asset_id: str) -> None:
        item = self.get_download(asset_id)
        if not item or item.owner_id != owner_id:
            raise PermissionError("Nicht erlaubt")
        self._delete(self.DOWNLOAD_PREFIX, asset_id)
        self._checkpoint()

    # Ticketing --------------------------------------------------------
    def create_ticket(self, shop_id: str, customer_id: str, subject: str, body: str) -> SupportTicket:
        shop = self.webshop.get_shop(shop_id)
        if not shop:
            raise ValueError("Shop nicht gefunden")
        subject = validate_title(subject)
        body = validate_richtext(body, "compact", max_chars=50_000, required=True)
        now = utc_now()
        ticket = SupportTicket(uuid.uuid4().hex, shop_id, customer_id, subject, "open", now, now)
        self._write(self.TICKET_PREFIX, ticket.id, "ticket", ticket, {
            "shop_idx": self.crypto.blind_index("ticket-shop", shop_id),
            "customer_idx": self.crypto.blind_index("ticket-customer", customer_id),
        })
        self.add_ticket_message(ticket.id, customer_id, body, checkpoint=False)
        self._checkpoint()
        return ticket

    def get_ticket(self, ticket_id: str) -> SupportTicket | None:
        return self._decode(self.TICKET_PREFIX, ticket_id, SupportTicket)

    def list_tickets_for_customer(self, user_id: str) -> list[SupportTicket]:
        idx = self.crypto.blind_index("ticket-customer", user_id)
        items = self._list(self.TICKET_PREFIX, SupportTicket, ("customer_idx", idx))
        items.sort(key=lambda x: x.updated_at, reverse=True)
        return items

    def list_tickets_for_shop(self, shop_id: str) -> list[SupportTicket]:
        idx = self.crypto.blind_index("ticket-shop", shop_id)
        items = self._list(self.TICKET_PREFIX, SupportTicket, ("shop_idx", idx))
        items.sort(key=lambda x: x.updated_at, reverse=True)
        return items

    def add_ticket_message(self, ticket_id: str, author_id: str, body: str, *, checkpoint: bool = True) -> TicketMessage:
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError("Ticket nicht gefunden")
        if ticket.status == "closed":
            raise ValueError("Ticket ist geschlossen")
        body = validate_richtext(body, "compact", max_chars=50_000, required=True)
        msg = TicketMessage(uuid.uuid4().hex, ticket_id, author_id, body, utc_now())
        self._write(self.TICKET_MSG_PREFIX, msg.id, "ticket_message", msg, {
            "ticket_idx": self.crypto.blind_index("ticket-message-ticket", ticket_id),
            "author_idx": self.crypto.blind_index("ticket-message-author", author_id),
        })
        ticket.updated_at = utc_now()
        self._write(self.TICKET_PREFIX, ticket.id, "ticket", ticket, {
            "shop_idx": self.crypto.blind_index("ticket-shop", ticket.shop_id),
            "customer_idx": self.crypto.blind_index("ticket-customer", ticket.customer_id),
        })
        if checkpoint:
            self._checkpoint()
        return msg

    def get_ticket_message(self, message_id: str) -> TicketMessage | None:
        return self._decode(self.TICKET_MSG_PREFIX, message_id, TicketMessage)

    def list_ticket_messages(self, ticket_id: str) -> list[TicketMessage]:
        idx = self.crypto.blind_index("ticket-message-ticket", ticket_id)
        items = self._list(self.TICKET_MSG_PREFIX, TicketMessage, ("ticket_idx", idx))
        items.sort(key=lambda x: x.created_at)
        return items

    def update_ticket_status(self, ticket_id: str, owner_id: str, status: str) -> SupportTicket:
        if status not in {"open", "waiting_customer", "waiting_shop", "closed"}:
            raise ValueError("Ungültiger Ticketstatus")
        ticket = self.get_ticket(ticket_id)
        shop = self.webshop.get_shop_for_owner(owner_id)
        if not ticket or not shop or ticket.shop_id != shop.id:
            raise PermissionError("Nicht erlaubt")
        ticket.status = status
        ticket.updated_at = utc_now()
        self._write(self.TICKET_PREFIX, ticket.id, "ticket", ticket, {
            "shop_idx": self.crypto.blind_index("ticket-shop", ticket.shop_id),
            "customer_idx": self.crypto.blind_index("ticket-customer", ticket.customer_id),
        })
        self._checkpoint()
        return ticket

    # Knowledge Base ---------------------------------------------------
    def get_kb(self, article_id: str) -> KnowledgeArticle | None:
        return self._decode(self.KB_PREFIX, article_id, KnowledgeArticle)

    def list_kb(self, shop_id: str | None = None, *, published_only: bool = True) -> list[KnowledgeArticle]:
        if shop_id:
            idx = self.crypto.blind_index("kb-shop", shop_id)
            items = self._list(self.KB_PREFIX, KnowledgeArticle, ("shop_idx", idx))
        else:
            items = [x for x in self._list(self.KB_PREFIX, KnowledgeArticle) if x.shop_id is None]
        if published_only:
            items = [x for x in items if x.status == "published"]
        items.sort(key=lambda x: x.updated_at, reverse=True)
        return items

    def list_kb_overview(self, shop_ids: set[str], *, published_only: bool = True) -> list[KnowledgeArticle]:
        """Return global articles plus articles from the visible shops."""
        items = [
            item for item in self._list(self.KB_PREFIX, KnowledgeArticle)
            if item.shop_id is None or item.shop_id in shop_ids
        ]
        if published_only:
            items = [item for item in items if item.status == "published"]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def save_kb(self, author_id: str, article_id: str | None, title: str, slug: str, body: str, status: str, shop_id: str | None) -> KnowledgeArticle:
        title = validate_title(title); slug = normalize_slug(slug); body = validate_richtext(body, "document", max_chars=200_000, required=True)
        if status not in {"draft", "published"}: raise ValueError("Ungültiger Status")
        if shop_id:
            shop = self.webshop.get_shop_for_owner(author_id)
            if not shop or shop.id != shop_id: raise PermissionError("Nur der Shopbesitzer darf Shop-Wissen veröffentlichen")
        old = self.get_kb(article_id) if article_id else None
        if old and old.author_id != author_id: raise PermissionError("Nicht erlaubt")
        now = utc_now()
        item = KnowledgeArticle(old.id if old else uuid.uuid4().hex, author_id, shop_id, title, slug, body, status, old.created_at if old else now, now)
        props = {"author_idx": self.crypto.blind_index("kb-author", author_id), "scope": "shop" if shop_id else "global"}
        if shop_id: props["shop_idx"] = self.crypto.blind_index("kb-shop", shop_id)
        self._write(self.KB_PREFIX, item.id, "knowledge_article", item, props)
        self._checkpoint(); return item

    def delete_kb(self, author_id: str, article_id: str) -> None:
        item = self.get_kb(article_id)
        if not item or item.author_id != author_id: raise PermissionError("Nicht erlaubt")
        self._delete(self.KB_PREFIX, article_id); self._checkpoint()

    # Forum ------------------------------------------------------------
    def create_forum_topic(self, author_id: str, title: str, body: str, shop_id: str | None = None) -> ForumTopic:
        title = validate_title(title); body = validate_richtext(body, "compact", max_chars=80_000, required=True)
        if shop_id and not self.webshop.get_shop(shop_id): raise ValueError("Shop nicht gefunden")
        now = utc_now(); topic = ForumTopic(uuid.uuid4().hex, author_id, shop_id, title, now, now, False)
        props = {"author_idx": self.crypto.blind_index("forum-topic-author", author_id), "scope": "shop" if shop_id else "global"}
        if shop_id: props["shop_idx"] = self.crypto.blind_index("forum-topic-shop", shop_id)
        self._write(self.FORUM_TOPIC_PREFIX, topic.id, "forum_topic", topic, props)
        self.add_forum_reply(topic.id, author_id, body, checkpoint=False)
        self._checkpoint(); return topic

    def get_forum_topic(self, topic_id: str) -> ForumTopic | None:
        return self._decode(self.FORUM_TOPIC_PREFIX, topic_id, ForumTopic)

    def list_forum_topics(self, shop_id: str | None = None) -> list[ForumTopic]:
        if shop_id:
            idx = self.crypto.blind_index("forum-topic-shop", shop_id)
            items = self._list(self.FORUM_TOPIC_PREFIX, ForumTopic, ("shop_idx", idx))
        else:
            items = [x for x in self._list(self.FORUM_TOPIC_PREFIX, ForumTopic) if x.shop_id is None]
        items.sort(key=lambda x: x.updated_at, reverse=True); return items

    def list_forum_overview(self, shop_ids: set[str]) -> list[ForumTopic]:
        """Return global topics plus topics from the visible shops."""
        items = [
            item for item in self._list(self.FORUM_TOPIC_PREFIX, ForumTopic)
            if item.shop_id is None or item.shop_id in shop_ids
        ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def add_forum_reply(self, topic_id: str, author_id: str, body: str, *, checkpoint: bool = True) -> ForumReply:
        topic = self.get_forum_topic(topic_id)
        if not topic: raise ValueError("Thema nicht gefunden")
        if topic.locked: raise ValueError("Thema ist geschlossen")
        body = validate_richtext(body, "compact", max_chars=80_000, required=True)
        reply = ForumReply(uuid.uuid4().hex, topic_id, author_id, body, utc_now())
        self._write(self.FORUM_REPLY_PREFIX, reply.id, "forum_reply", reply, {
            "topic_idx": self.crypto.blind_index("forum-reply-topic", topic_id),
            "author_idx": self.crypto.blind_index("forum-reply-author", author_id),
        })
        topic.updated_at = utc_now()
        props = {"author_idx": self.crypto.blind_index("forum-topic-author", topic.author_id), "scope": "shop" if topic.shop_id else "global"}
        if topic.shop_id: props["shop_idx"] = self.crypto.blind_index("forum-topic-shop", topic.shop_id)
        self._write(self.FORUM_TOPIC_PREFIX, topic.id, "forum_topic", topic, props)
        if checkpoint: self._checkpoint()
        return reply

    def get_forum_reply(self, reply_id: str) -> ForumReply | None:
        return self._decode(self.FORUM_REPLY_PREFIX, reply_id, ForumReply)

    def list_forum_replies(self, topic_id: str) -> list[ForumReply]:
        idx = self.crypto.blind_index("forum-reply-topic", topic_id)
        items = self._list(self.FORUM_REPLY_PREFIX, ForumReply, ("topic_idx", idx))
        items.sort(key=lambda x: x.created_at); return items

    # Documents --------------------------------------------------------
    def get_document(self, doc_id: str) -> DocumentRecord | None:
        return self._decode(self.DOC_PREFIX, doc_id, DocumentRecord)

    def list_documents(self, shop_id: str, *, published_only: bool = False) -> list[DocumentRecord]:
        idx = self.crypto.blind_index("doc-shop", shop_id)
        items = self._list(self.DOC_PREFIX, DocumentRecord, ("shop_idx", idx))
        if published_only: items = [x for x in items if x.status == "published"]
        items.sort(key=lambda x: x.updated_at, reverse=True); return items

    def save_document(self, owner_id: str, doc_id: str | None, title: str, slug: str, body: str, visibility: str, status: str) -> DocumentRecord:
        shop = self.webshop.get_shop_for_owner(owner_id)
        if not shop: raise ValueError("Shop erforderlich")
        title = validate_title(title); slug = normalize_slug(slug); body = validate_richtext(body, "document", max_chars=200_000, required=True)
        if visibility not in {"public", "members", "private"}: raise ValueError("Ungültige Sichtbarkeit")
        if status not in {"draft", "published"}: raise ValueError("Ungültiger Status")
        old = self.get_document(doc_id) if doc_id else None
        if old and old.owner_id != owner_id: raise PermissionError("Nicht erlaubt")
        now = utc_now(); item = DocumentRecord(old.id if old else uuid.uuid4().hex, shop.id, owner_id, title, slug, body, visibility, status, old.created_at if old else now, now)
        self._write(self.DOC_PREFIX, item.id, "document", item, {
            "shop_idx": self.crypto.blind_index("doc-shop", shop.id),
            "owner_idx": self.crypto.blind_index("doc-owner", owner_id),
            "slug_idx": self.crypto.blind_index(f"doc-slug:{shop.id}", slug),
        })
        self._checkpoint(); return item

    def delete_document(self, owner_id: str, doc_id: str) -> None:
        item = self.get_document(doc_id)
        if not item or item.owner_id != owner_id: raise PermissionError("Nicht erlaubt")
        self._delete(self.DOC_PREFIX, doc_id); self._checkpoint()

    # Community --------------------------------------------------------
    def create_community_post(self, author_id: str, body: str) -> CommunityPost:
        body = validate_richtext(body, "compact", max_chars=20_000, required=True); now = utc_now()
        item = CommunityPost(uuid.uuid4().hex, author_id, body, now, now)
        self._write(self.COMMUNITY_POST_PREFIX, item.id, "community_post", item, {"author_idx": self.crypto.blind_index("community-author", author_id)})
        self._checkpoint(); return item

    def list_community_posts(self) -> list[CommunityPost]:
        items = self._list(self.COMMUNITY_POST_PREFIX, CommunityPost); items.sort(key=lambda x: x.created_at, reverse=True); return items

    def get_community_post(self, post_id: str) -> CommunityPost | None:
        return self._decode(self.COMMUNITY_POST_PREFIX, post_id, CommunityPost)

    def add_community_comment(self, post_id: str, author_id: str, body: str) -> CommunityComment:
        if not self.get_community_post(post_id): raise ValueError("Beitrag nicht gefunden")
        body = validate_richtext(body, "compact", max_chars=10_000, required=True)
        item = CommunityComment(uuid.uuid4().hex, post_id, author_id, body, utc_now())
        self._write(self.COMMUNITY_COMMENT_PREFIX, item.id, "community_comment", item, {
            "post_idx": self.crypto.blind_index("community-comment-post", post_id),
            "author_idx": self.crypto.blind_index("community-comment-author", author_id),
        })
        self._checkpoint(); return item

    def get_community_comment(self, comment_id: str) -> CommunityComment | None:
        return self._decode(self.COMMUNITY_COMMENT_PREFIX, comment_id, CommunityComment)

    def list_community_comments(self, post_id: str) -> list[CommunityComment]:
        idx = self.crypto.blind_index("community-comment-post", post_id)
        items = self._list(self.COMMUNITY_COMMENT_PREFIX, CommunityComment, ("post_idx", idx)); items.sort(key=lambda x: x.created_at); return items

    # Marketplace ------------------------------------------------------
    def marketplace_products(self, query: str = ""):
        q = query.strip().casefold()
        out = []
        for shop in self.webshop.list_shops(active_only=True):
            for product in self.webshop.list_products(shop.id, active_only=True):
                if q and q not in product.name.casefold() and q not in richtext_plain(product.description).casefold() and q not in shop.name.casefold():
                    continue
                out.append((shop, product))
        out.sort(key=lambda pair: pair[1].created_at, reverse=True)
        return out

    # Privacy ----------------------------------------------------------
    def export_user_data(self, user_id: str) -> dict[str, Any]:
        shop = self.webshop.get_shop_for_owner(user_id)
        creator = self.get_creator(user_id)
        result: dict[str, Any] = {
            "creator_profile": asdict(creator) if creator else None,
            "creator_posts": [asdict(x) for x in self.list_creator_posts(user_id)] if creator else [],
            "memberships": [asdict(x) for x in self._list(self.MEMBER_PREFIX, ShopMembership, ("user_idx", self.crypto.blind_index("membership-user", user_id)))],
            "customer_tickets": [asdict(x) for x in self.list_tickets_for_customer(user_id)],
            "forum_topics": [asdict(x) for x in self._list(self.FORUM_TOPIC_PREFIX, ForumTopic, ("author_idx", self.crypto.blind_index("forum-topic-author", user_id)))],
            "forum_replies": [asdict(x) for x in self._list(self.FORUM_REPLY_PREFIX, ForumReply, ("author_idx", self.crypto.blind_index("forum-reply-author", user_id)))],
            "knowledge_articles": [asdict(x) for x in self._list(self.KB_PREFIX, KnowledgeArticle, ("author_idx", self.crypto.blind_index("kb-author", user_id)))],
            "community_posts": [asdict(x) for x in self._list(self.COMMUNITY_POST_PREFIX, CommunityPost, ("author_idx", self.crypto.blind_index("community-author", user_id)))],
            "community_comments": [asdict(x) for x in self._list(self.COMMUNITY_COMMENT_PREFIX, CommunityComment, ("author_idx", self.crypto.blind_index("community-comment-author", user_id)))],
        }
        if shop:
            result["shop_memberships_count"] = len(self.list_members(shop.id))
            result["downloads"] = [{k:v for k,v in asdict(x).items() if k != "content_b64"} for x in self.list_downloads(shop.id)]
            result["documents"] = [asdict(x) for x in self.list_documents(shop.id)]
            result["shop_tickets"] = [asdict(x) for x in self.list_tickets_for_shop(shop.id)]
        return result

    def delete_user_data(self, user_id: str) -> int:
        targets: set[str] = set()
        prefixes_and_prop = [
            (self.CREATOR_PREFIX, "user_idx", self.crypto.blind_index("creator-user", user_id)),
            (self.CREATOR_POST_PREFIX, "creator_idx", self.crypto.blind_index("creator-post-owner", user_id)),
            (self.MEMBER_PREFIX, "user_idx", self.crypto.blind_index("membership-user", user_id)),
            (self.TICKET_PREFIX, "customer_idx", self.crypto.blind_index("ticket-customer", user_id)),
            (self.TICKET_MSG_PREFIX, "author_idx", self.crypto.blind_index("ticket-message-author", user_id)),
            (self.KB_PREFIX, "author_idx", self.crypto.blind_index("kb-author", user_id)),
            (self.FORUM_TOPIC_PREFIX, "author_idx", self.crypto.blind_index("forum-topic-author", user_id)),
            (self.FORUM_REPLY_PREFIX, "author_idx", self.crypto.blind_index("forum-reply-author", user_id)),
            (self.COMMUNITY_POST_PREFIX, "author_idx", self.crypto.blind_index("community-author", user_id)),
            (self.COMMUNITY_COMMENT_PREFIX, "author_idx", self.crypto.blind_index("community-comment-author", user_id)),
        ]
        authored_topic_ids: list[str] = []
        authored_community_ids: list[str] = []
        customer_ticket_ids: list[str] = []
        for prefix, prop, value in prefixes_and_prop:
            for node_id in self.db.list_node_ids(prefix):
                node = self.db.get_node(node_id)
                if node.properties.get(prop) == value:
                    targets.add(node_id)
                    rid = node_id.split(":")[-1]
                    if prefix == self.FORUM_TOPIC_PREFIX:
                        authored_topic_ids.append(rid)
                    elif prefix == self.COMMUNITY_POST_PREFIX:
                        authored_community_ids.append(rid)
                    elif prefix == self.TICKET_PREFIX:
                        customer_ticket_ids.append(rid)

        # A customer ticket is personal correspondence. If the account is erased,
        # erase the complete message thread so no orphaned counterparty messages
        # remain attached to a deleted ticket.
        for ticket_id in customer_ticket_ids:
            idx = self.crypto.blind_index("ticket-message-ticket", ticket_id)
            for node_id in self.db.list_node_ids(self.TICKET_MSG_PREFIX):
                if self.db.get_node(node_id).properties.get("ticket_idx") == idx:
                    targets.add(node_id)

        # Forum/community conversations can contain content from other accounts.
        # Preserve those users' contributions by anonymising the parent object when
        # foreign replies/comments exist; otherwise the complete object can be erased.
        zero_user = "0" * 32
        for topic_id in authored_topic_ids:
            topic = self.get_forum_topic(topic_id)
            if topic is None:
                continue
            replies = self.list_forum_replies(topic_id)
            if any(r.author_id != user_id for r in replies):
                topic.author_id = zero_user
                topic.title = "[Thema eines gelöschten Kontos]"
                self._write(self.FORUM_TOPIC_PREFIX, topic.id, "forum_topic", topic, {
                    "author_idx": self.crypto.blind_index("forum-topic-author", zero_user),
                    "scope": "shop" if topic.shop_id else "global",
                    **({"shop_idx": self.crypto.blind_index("forum-topic-shop", topic.shop_id)} if topic.shop_id else {}),
                })
                targets.discard(self._node(self.FORUM_TOPIC_PREFIX, topic.id))
            else:
                for reply in replies:
                    targets.add(self._node(self.FORUM_REPLY_PREFIX, reply.id))

        for post_id in authored_community_ids:
            post = self.get_community_post(post_id)
            if post is None:
                continue
            comments = self.list_community_comments(post_id)
            if any(c.author_id != user_id for c in comments):
                post.author_id = zero_user
                post.body = validate_richtext("[Beitrag eines gelöschten Kontos]", "compact", max_chars=20_000, required=True)
                post.updated_at = utc_now()
                self._write(self.COMMUNITY_POST_PREFIX, post.id, "community_post", post, {
                    "author_idx": self.crypto.blind_index("community-author", zero_user)
                })
                targets.discard(self._node(self.COMMUNITY_POST_PREFIX, post.id))
            else:
                for comment in comments:
                    targets.add(self._node(self.COMMUNITY_COMMENT_PREFIX, comment.id))

        shop = self.webshop.get_shop_for_owner(user_id)
        if shop:
            for prefix, namespace in [
                (self.MEMBER_PREFIX, "membership-shop"),
                (self.DOWNLOAD_PREFIX, "download-shop"),
                (self.TICKET_PREFIX, "ticket-shop"),
                (self.DOC_PREFIX, "doc-shop"),
            ]:
                idx = self.crypto.blind_index(namespace, shop.id)
                prop = "shop_idx"
                for node_id in self.db.list_node_ids(prefix):
                    if self.db.get_node(node_id).properties.get(prop) == idx:
                        targets.add(node_id)
            # ticket messages tied to tickets in this shop
            ticket_ids = [self._decode(self.TICKET_PREFIX, nid.split(":")[-1], SupportTicket).id for nid in targets if nid.startswith(self.TICKET_PREFIX)]
            for tid in ticket_ids:
                idx = self.crypto.blind_index("ticket-message-ticket", tid)
                for node_id in self.db.list_node_ids(self.TICKET_MSG_PREFIX):
                    if self.db.get_node(node_id).properties.get("ticket_idx") == idx:
                        targets.add(node_id)
        deleted = 0
        for node_id in sorted(targets):
            try:
                self.db.delete_node(node_id); deleted += 1
            except MyceliaDBError as exc:
                if "missing node" not in str(exc): raise
        if deleted:
            self._checkpoint()
        return deleted
