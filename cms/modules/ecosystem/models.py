from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CreatorProfile:
    id: str
    user_id: str
    display_name: str
    bio: str
    website: str
    created_at: str
    updated_at: str
    active: bool = True


@dataclass(slots=True)
class CreatorPost:
    id: str
    creator_id: str
    title: str
    slug: str
    body: str
    visibility: str
    status: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ShopMembership:
    id: str
    shop_id: str
    user_id: str
    created_at: str
    status: str = "active"


@dataclass(slots=True)
class DownloadAsset:
    id: str
    shop_id: str
    owner_id: str
    title: str
    slug: str
    description: str
    filename: str
    mime_type: str
    content_b64: str
    visibility: str
    created_at: str
    updated_at: str
    active: bool = True


@dataclass(slots=True)
class SupportTicket:
    id: str
    shop_id: str
    customer_id: str
    subject: str
    status: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class TicketMessage:
    id: str
    ticket_id: str
    author_id: str
    body: str
    created_at: str


@dataclass(slots=True)
class KnowledgeArticle:
    id: str
    author_id: str
    shop_id: str | None
    title: str
    slug: str
    body: str
    status: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ForumTopic:
    id: str
    author_id: str
    shop_id: str | None
    title: str
    created_at: str
    updated_at: str
    locked: bool = False


@dataclass(slots=True)
class ForumReply:
    id: str
    topic_id: str
    author_id: str
    body: str
    created_at: str


@dataclass(slots=True)
class DocumentRecord:
    id: str
    shop_id: str
    owner_id: str
    title: str
    slug: str
    body: str
    visibility: str
    status: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class CommunityPost:
    id: str
    author_id: str
    body: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class CommunityComment:
    id: str
    post_id: str
    author_id: str
    body: str
    created_at: str
