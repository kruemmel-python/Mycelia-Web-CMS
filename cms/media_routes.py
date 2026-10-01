from __future__ import annotations

from flask import Blueprint, Response, abort, session

from .hardening import utc_expired
from .media import MediaImage, SecureMediaRepository
from .repository import CMSRepository
from .modules.webshop.repository import WebshopRepository
from .modules.ecosystem.repository import EcosystemRepository


def create_media_blueprint(
    media: SecureMediaRepository,
    cms: CMSRepository,
    webshop: WebshopRepository,
    ecosystem: EcosystemRepository,
    *,
    session_minutes: int,
) -> Blueprint:
    bp = Blueprint("media", __name__, url_prefix="")

    def current_user():
        user_id = session.get("user_id")
        if not isinstance(user_id, str) or utc_expired(session.get("user_auth_at"), session_minutes):
            return None
        try:
            return webshop.get_user(user_id)
        except Exception:
            return None

    def is_member(shop_id: str, user) -> bool:
        if user is None:
            return False
        shop = webshop.get_shop(shop_id)
        if shop and shop.owner_id == user.id:
            return True
        return ecosystem.is_member(shop_id, user.id)

    def allowed(image: MediaImage) -> bool:
        user = current_user()
        admin = bool(session.get("cms_admin")) and not utc_expired(session.get("auth_at"), session_minutes)
        kind = image.parent_kind

        if kind == "cms-page":
            page = cms.get_page(image.parent_id)
            return bool(page and (page.status == "published" or admin))

        if kind in {"shop-logo", "shop-banner"}:
            shop = webshop.get_shop(image.parent_id)
            return bool(shop and (shop.active or (user and shop.owner_id == user.id)))

        if kind == "shop-blog":
            post = webshop.get_blog_post(image.parent_id)
            if not post:
                return False
            shop = webshop.get_shop(post.shop_id)
            return bool(shop and ((shop.active and post.status == "published") or (user and post.owner_id == user.id)))

        if kind == "creator-avatar":
            profile = ecosystem.get_creator(image.parent_id)
            return bool(profile and (profile.active or (user and profile.user_id == user.id)))

        if kind == "creator-post":
            post = ecosystem.get_creator_post(image.parent_id)
            if not post:
                return False
            if user and post.creator_id == user.id:
                return True
            if post.status != "published":
                return False
            if post.visibility == "public":
                return True
            shop = webshop.get_shop_for_owner(post.creator_id)
            return bool(shop and is_member(shop.id, user))

        if kind == "forum-topic":
            return ecosystem.get_forum_topic(image.parent_id) is not None

        if kind == "forum-reply":
            reply = ecosystem.get_forum_reply(image.parent_id)
            return bool(reply and ecosystem.get_forum_topic(reply.topic_id))

        if kind == "knowledge":
            item = ecosystem.get_kb(image.parent_id)
            return bool(item and (item.status == "published" or (user and item.author_id == user.id)))

        if kind == "community-post":
            return ecosystem.get_community_post(image.parent_id) is not None

        if kind == "community-comment":
            comment = ecosystem.get_community_comment(image.parent_id)
            return bool(comment and ecosystem.get_community_post(comment.post_id))

        if kind == "ticket-message":
            msg = ecosystem.get_ticket_message(image.parent_id)
            if not msg or user is None:
                return False
            ticket = ecosystem.get_ticket(msg.ticket_id)
            if not ticket:
                return False
            shop = webshop.get_shop(ticket.shop_id)
            return ticket.customer_id == user.id or bool(shop and shop.owner_id == user.id)

        if kind == "document":
            item = ecosystem.get_document(image.parent_id)
            if not item or item.status != "published":
                return bool(item and user and item.owner_id == user.id)
            shop = webshop.get_shop(item.shop_id)
            if not shop:
                return False
            if user and shop.owner_id == user.id:
                return True
            if item.visibility == "public":
                return True
            if item.visibility == "members":
                return is_member(shop.id, user)
            return False

        return False

    @bp.get("/media/content/<image_id>.jpg")
    def content_image(image_id: str):
        try:
            image = media.get(image_id)
        except ValueError:
            abort(404)
        if image is None or not allowed(image):
            abort(404)
        payload = media.bytes(image)
        return Response(
            payload,
            mimetype="image/jpeg",
            headers={
                "Cache-Control": "private, no-store, max-age=0",
                "Content-Disposition": f'inline; filename="mycelia-{image.id}.jpg"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    return bp
