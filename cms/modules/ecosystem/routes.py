from __future__ import annotations

import base64
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from ...audit import AuditLog
from ...hardening import audit_remote_key, utc_expired
from ...media import SecureMediaRepository
from ..webshop.repository import WebshopRepository
from .repository import EcosystemRepository


def create_ecosystem_blueprint(repo: EcosystemRepository, webshop: WebshopRepository, *, audit: AuditLog, session_minutes: int, media_repo: SecureMediaRepository | None = None) -> Blueprint:
    bp = Blueprint("ecosystem", __name__, url_prefix="")

    def audit_remote() -> str:
        return audit_remote_key(webshop.crypto)

    def current_user():
        user_id = session.get("user_id")
        if not isinstance(user_id, str) or utc_expired(session.get("user_auth_at"), session_minutes):
            return None
        return webshop.get_user(user_id)

    def required(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any):
            user = current_user()
            if user is None:
                flash("Bitte melde dich an.", "error")
                return redirect(url_for("webshop.account_login", next=request.path))
            return func(user, *args, **kwargs)
        return wrapped

    def shop_owner(user):
        return webshop.get_shop_for_owner(user.id)

    def can_member_content(shop_id: str, user) -> bool:
        if user:
            shop = webshop.get_shop(shop_id)
            if shop and shop.owner_id == user.id:
                return True
            return repo.is_member(shop_id, user.id)
        return False

    def overview_shops(user) -> dict[str, Any]:
        """Shops whose public platform content is visible in global overviews."""
        shops = {shop.id: shop for shop in webshop.list_shops(active_only=True)}
        if user:
            owned = webshop.get_shop_for_owner(user.id)
            if owned:
                shops[owned.id] = owned
        return shops

    def author_name(user_id: str) -> str:
        user = webshop.get_user(user_id)
        return user.display_name if user else "Gelöschtes Konto"

    def image_uploads(field: str = "image_files", *, max_count: int = 3):
        if media_repo is None:
            return []
        files = request.files.getlist(field)
        nonempty = [f for f in files if f and (f.filename or "").strip()]
        if len(nonempty) > max_count:
            raise ValueError(f"Maximal {max_count} Bilder sind erlaubt")
        return [media_repo.sanitize_upload(f) for f in nonempty]

    def media_map(parent_kind: str, items) -> dict[str, list]:
        if media_repo is None:
            return {}
        return {item.id: media_repo.list_for_parent(parent_kind, item.id) for item in items}

    @bp.app_context_processor
    def inject_platform_context():
        # Ecosystem templates must not depend on a context processor from a
        # different blueprint. In particular the forum needs the authenticated
        # account to decide whether reply/topic controls are shown.
        return {
            "platform_author_name": author_name,
            "ecosystem_user": current_user(),
        }

    # Marketplace ------------------------------------------------------
    @bp.get("/marketplace")
    def marketplace():
        q = request.args.get("q", "")[:120]
        return render_template("ecosystem/marketplace.html", products=repo.marketplace_products(q), query=q)

    # Creator platform -------------------------------------------------
    @bp.get("/creators")
    def creators():
        creators_list = repo.list_creators()
        avatars = {}
        if media_repo is not None:
            for creator in creators_list:
                images = media_repo.list_for_parent("creator-avatar", creator.user_id, slot="avatar")
                avatars[creator.user_id] = images[0] if images else None
        return render_template("ecosystem/creators.html", creators=creators_list, avatars=avatars)

    @bp.route("/account/creator", methods=["GET", "POST"])
    @required
    def creator_manage(user):
        profile = repo.get_creator(user.id)
        if request.method == "POST":
            try:
                profile = repo.save_creator(user.id, request.form.get("display_name", ""), request.form.get("bio", ""), request.form.get("website", ""))
                if media_repo is not None:
                    avatar_uploads = image_uploads("avatar_image", max_count=1)
                    if avatar_uploads or request.form.get("remove_avatar") == "1":
                        media_repo.add_uploads(owner_id=user.id, parent_kind="creator-avatar", parent_id=user.id, uploads=avatar_uploads, max_count=1, slot="avatar", replace_slot=True)
            except ValueError as exc:
                flash(str(exc), "error"); return render_template("ecosystem/creator_manage.html", profile=profile, avatar=(media_repo.list_for_parent("creator-avatar", user.id, slot="avatar")[0] if media_repo and media_repo.list_for_parent("creator-avatar", user.id, slot="avatar") else None)), 400
            audit.record("creator_profile_saved", actor="user", remote=audit_remote(), detail={"user_id": user.id})
            flash("Creator-Profil gespeichert.", "success")
        return render_template("ecosystem/creator_manage.html", profile=profile, avatar=(media_repo.list_for_parent("creator-avatar", user.id, slot="avatar")[0] if media_repo and media_repo.list_for_parent("creator-avatar", user.id, slot="avatar") else None))

    @bp.get("/account/creator/posts")
    @required
    def creator_posts(user):
        return render_template("ecosystem/creator_posts.html", profile=repo.get_creator(user.id), posts=repo.list_creator_posts(user.id))

    @bp.route("/account/creator/posts/new", methods=["GET", "POST"])
    @required
    def creator_post_new(user):
        if request.method == "POST":
            try:
                post = repo.save_creator_post(user.id, None, request.form.get("title", ""), request.form.get("slug", ""), request.form.get("body", ""), request.form.get("visibility", "public"), request.form.get("status", "draft"))
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="creator-post", parent_id=post.id, uploads=image_uploads(max_count=3), max_count=3)
            except (ValueError, PermissionError) as exc:
                flash(str(exc), "error"); return render_template("ecosystem/creator_post_edit.html", post=None, post_images=[]), 400
            return redirect(url_for("ecosystem.creator_posts"))
        return render_template("ecosystem/creator_post_edit.html", post=None, post_images=[])

    @bp.route("/account/creator/posts/<post_id>", methods=["GET", "POST"])
    @required
    def creator_post_edit(user, post_id: str):
        post = repo.get_creator_post(post_id)
        if not post or post.creator_id != user.id: abort(404)
        if request.method == "POST":
            try:
                post = repo.save_creator_post(user.id, post.id, request.form.get("title", ""), request.form.get("slug", ""), request.form.get("body", ""), request.form.get("visibility", "public"), request.form.get("status", "draft"))
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="creator-post", parent_id=post.id, uploads=image_uploads(max_count=3), max_count=3, remove_ids=set(request.form.getlist("remove_image_ids")))
            except (ValueError, PermissionError) as exc:
                flash(str(exc), "error"); return render_template("ecosystem/creator_post_edit.html", post=post, post_images=media_repo.list_for_parent("creator-post", post.id) if media_repo else []), 400
            flash("Creator-Beitrag gespeichert.", "success")
        return render_template("ecosystem/creator_post_edit.html", post=post, post_images=media_repo.list_for_parent("creator-post", post.id) if media_repo else [])

    @bp.get("/creator/<user_id>")
    def creator_public(user_id: str):
        profile = repo.get_creator(user_id)
        if not profile or not profile.active: abort(404)
        user = current_user(); shop = webshop.get_shop_for_owner(user_id)
        posts=[]
        for post in repo.list_creator_posts(user_id, public_only=True):
            if post.visibility == "public" or (shop and can_member_content(shop.id, user)):
                posts.append(post)
        avatar_list = media_repo.list_for_parent("creator-avatar", user_id, slot="avatar") if media_repo else []
        return render_template("ecosystem/creator_public.html", profile=profile, posts=posts, owner=webshop.get_user(user_id), shop=shop, avatar=avatar_list[0] if avatar_list else None, post_images=media_map("creator-post", posts))

    # Membership -------------------------------------------------------
    @bp.post("/s/<shop_slug>/membership/join")
    @required
    def membership_join(user, shop_slug: str):
        shop = webshop.find_shop_by_slug(shop_slug)
        if not shop: abort(404)
        repo.join_shop(shop.id, user.id)
        flash("Mitgliedschaft aktiviert.", "success")
        return redirect(request.referrer or url_for("webshop.public_shop", shop_slug=shop.slug))

    @bp.post("/s/<shop_slug>/membership/leave")
    @required
    def membership_leave(user, shop_slug: str):
        shop = webshop.find_shop_by_slug(shop_slug)
        if not shop: abort(404)
        repo.leave_shop(shop.id, user.id)
        flash("Mitgliedschaft beendet und Datensatz gelöscht.", "success")
        return redirect(request.referrer or url_for("webshop.public_shop", shop_slug=shop.slug))

    @bp.get("/account/shop/members")
    @required
    def member_dashboard(user):
        shop=shop_owner(user)
        if not shop: return redirect(url_for("webshop.shop_manage"))
        members=[]
        for membership in repo.list_members(shop.id):
            u=webshop.get_user(membership.user_id)
            if u: members.append((membership,u))
        return render_template("ecosystem/members.html", shop=shop, members=members)

    # Downloads --------------------------------------------------------
    @bp.get("/account/shop/downloads")
    @required
    def downloads_manage(user):
        shop=shop_owner(user)
        if not shop: return redirect(url_for("webshop.shop_manage"))
        return render_template("ecosystem/downloads_manage.html", shop=shop, downloads=repo.list_downloads(shop.id))

    @bp.route("/account/shop/downloads/new", methods=["GET","POST"])
    @required
    def download_new(user):
        shop=shop_owner(user)
        if not shop: return redirect(url_for("webshop.shop_manage"))
        if request.method == "POST":
            f=request.files.get("file")
            try:
                if not f or not f.filename: raise ValueError("Datei erforderlich")
                data=f.read(700001)
                # Download-MIME is never trusted from the browser. Files are
                # always served as opaque attachments.
                repo.save_download(user.id,None,request.form.get("title",""),request.form.get("slug",""),request.form.get("description",""),secure_filename(f.filename) or "download.bin","application/octet-stream",data,request.form.get("visibility","public"),request.form.get("active")=="1")
            except (ValueError, PermissionError) as exc:
                flash(str(exc),"error"); return render_template("ecosystem/download_edit.html", asset=None, shop=shop),400
            return redirect(url_for("ecosystem.downloads_manage"))
        return render_template("ecosystem/download_edit.html", asset=None, shop=shop)

    @bp.post("/account/shop/downloads/<asset_id>/delete")
    @required
    def download_delete(user, asset_id: str):
        try: repo.delete_download(user.id, asset_id)
        except (ValueError, PermissionError): abort(404)
        return redirect(url_for("ecosystem.downloads_manage"))

    @bp.get("/s/<shop_slug>/downloads")
    def downloads_public(shop_slug: str):
        shop=webshop.find_shop_by_slug(shop_slug)
        if not shop: abort(404)
        user=current_user(); allowed=[]
        for asset in repo.list_downloads(shop.id, active_only=True):
            if asset.visibility=="public" or can_member_content(shop.id,user): allowed.append(asset)
        return render_template("ecosystem/downloads_public.html", shop=shop, downloads=allowed, is_member=can_member_content(shop.id,user))

    @bp.get("/downloads/<asset_id>/file")
    def download_file(asset_id: str):
        asset=repo.get_download(asset_id)
        if not asset or not asset.active: abort(404)
        user=current_user()
        if asset.visibility == "public":
            pass
        elif asset.visibility == "members":
            if not can_member_content(asset.shop_id, user): abort(404)
        else:
            # Defense-in-depth: the repository currently only permits public
            # and members, but unknown/private states must never fall through.
            abort(404)
        try: data=base64.b64decode(asset.content_b64, validate=True)
        except Exception: abort(500)
        resp=Response(data, mimetype="application/octet-stream")
        resp.headers["Content-Disposition"] = f'attachment; filename="{secure_filename(asset.filename) or "download.bin"}"'
        resp.headers["Cache-Control"]="private, no-store"
        resp.headers["X-Content-Type-Options"]="nosniff"
        resp.headers["Content-Security-Policy"]="default-src 'none'; sandbox"
        return resp

    # Ticketing --------------------------------------------------------
    @bp.get("/account/tickets")
    @required
    def tickets_customer(user):
        return render_template("ecosystem/tickets.html", tickets=repo.list_tickets_for_customer(user.id), mode="customer")

    @bp.route("/s/<shop_slug>/support/new", methods=["GET","POST"])
    @required
    def ticket_new(user, shop_slug: str):
        shop=webshop.find_shop_by_slug(shop_slug)
        if not shop: abort(404)
        if request.method=="POST":
            try:
                ticket=repo.create_ticket(shop.id,user.id,request.form.get("subject",""),request.form.get("body",""))
                if media_repo is not None:
                    messages = repo.list_ticket_messages(ticket.id)
                    if messages:
                        media_repo.add_uploads(owner_id=user.id, parent_kind="ticket-message", parent_id=messages[0].id, uploads=image_uploads(max_count=3), max_count=3, shop_id=shop.id)
            except ValueError as exc:
                flash(str(exc),"error"); return render_template("ecosystem/ticket_new.html",shop=shop),400
            return redirect(url_for("ecosystem.ticket_view",ticket_id=ticket.id))
        return render_template("ecosystem/ticket_new.html",shop=shop)

    @bp.get("/account/shop/tickets")
    @required
    def tickets_shop(user):
        shop=shop_owner(user)
        if not shop: return redirect(url_for("webshop.shop_manage"))
        return render_template("ecosystem/tickets.html",tickets=repo.list_tickets_for_shop(shop.id),mode="shop")

    @bp.route("/account/tickets/<ticket_id>",methods=["GET","POST"])
    @required
    def ticket_view(user,ticket_id: str):
        ticket=repo.get_ticket(ticket_id)
        if not ticket: abort(404)
        shop=webshop.get_shop(ticket.shop_id)
        owner_ok=bool(shop and shop.owner_id==user.id); customer_ok=ticket.customer_id==user.id
        if not (owner_ok or customer_ok): abort(403)
        if request.method=="POST":
            if ticket.status == "closed":
                flash("Dieses Ticket ist geschlossen.", "error")
                return redirect(url_for("ecosystem.ticket_view",ticket_id=ticket.id)), 403
            try:
                msg = repo.add_ticket_message(ticket.id,user.id,request.form.get("body",""))
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="ticket-message", parent_id=msg.id, uploads=image_uploads(max_count=3), max_count=3, shop_id=ticket.shop_id)
            except ValueError as exc: flash(str(exc),"error")
            return redirect(url_for("ecosystem.ticket_view",ticket_id=ticket.id))
        messages=repo.list_ticket_messages(ticket.id)
        return render_template("ecosystem/ticket_view.html",ticket=ticket,messages=messages,shop=shop,is_owner=owner_ok,message_images=media_map("ticket-message", messages))

    @bp.post("/account/tickets/<ticket_id>/status")
    @required
    def ticket_status(user,ticket_id: str):
        try: repo.update_ticket_status(ticket_id,user.id,request.form.get("status",""))
        except (ValueError,PermissionError): abort(400)
        return redirect(url_for("ecosystem.ticket_view",ticket_id=ticket_id))

    # Knowledge Base ---------------------------------------------------
    @bp.get("/knowledge")
    def knowledge():
        shops = overview_shops(current_user())
        articles = repo.list_kb_overview(set(shops))
        return render_template(
            "ecosystem/knowledge.html",
            articles=articles,
            article_shops={article.id: shops.get(article.shop_id) for article in articles if article.shop_id},
            scope="overview",
            shop=None,
        )

    @bp.get("/s/<shop_slug>/knowledge")
    def shop_knowledge(shop_slug: str):
        shop=webshop.find_shop_by_slug(shop_slug)
        if not shop: abort(404)
        return render_template("ecosystem/knowledge.html",articles=repo.list_kb(shop.id),article_shops={},scope="shop",shop=shop)

    @bp.get("/knowledge/<article_id>")
    def knowledge_view(article_id: str):
        item=repo.get_kb(article_id)
        if not item or item.status!="published": abort(404)
        shop=webshop.get_shop(item.shop_id) if item.shop_id else None
        return render_template("ecosystem/knowledge_view.html",article=item,shop=shop,article_images=media_repo.list_for_parent("knowledge", item.id) if media_repo else [])

    @bp.route("/account/knowledge/new",methods=["GET","POST"])
    @required
    def knowledge_new(user):
        shop=shop_owner(user); use_shop=request.args.get("shop")=="1" or request.form.get("scope")=="shop"
        if request.method=="POST":
            try:
                item = repo.save_kb(user.id,None,request.form.get("title",""),request.form.get("slug",""),request.form.get("body",""),request.form.get("status","draft"),shop.id if use_shop and shop else None)
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="knowledge", parent_id=item.id, uploads=image_uploads(max_count=3), max_count=3, shop_id=item.shop_id)
            except (ValueError,PermissionError) as exc:
                flash(str(exc),"error"); return render_template("ecosystem/knowledge_edit.html",article=None,shop=shop,use_shop=use_shop),400
            return redirect(url_for("ecosystem.shop_knowledge",shop_slug=shop.slug) if use_shop and shop else url_for("ecosystem.knowledge"))
        return render_template("ecosystem/knowledge_edit.html",article=None,shop=shop,use_shop=use_shop)

    # Forum ------------------------------------------------------------
    @bp.get("/forum")
    def forum():
        shops = overview_shops(current_user())
        topics = repo.list_forum_overview(set(shops))
        return render_template(
            "ecosystem/forum.html",
            topics=topics,
            topic_shops={topic.id: shops.get(topic.shop_id) for topic in topics if topic.shop_id},
            shop=None,
            viewer=current_user(),
        )

    @bp.get("/s/<shop_slug>/forum")
    def shop_forum(shop_slug: str):
        shop=webshop.find_shop_by_slug(shop_slug)
        if not shop: abort(404)
        return render_template(
            "ecosystem/forum.html", topics=repo.list_forum_topics(shop.id), topic_shops={}, shop=shop, viewer=current_user()
        )

    @bp.route("/forum/new",methods=["GET","POST"])
    @required
    def forum_new(user):
        shop_id=request.args.get("shop_id") or request.form.get("shop_id") or None
        shop=webshop.get_shop(shop_id) if shop_id else None
        if shop_id and not shop: abort(404)
        if request.method=="POST":
            try:
                topic=repo.create_forum_topic(user.id,request.form.get("title",""),request.form.get("body",""),shop_id)
                if media_repo is not None:
                    replies = repo.list_forum_replies(topic.id)
                    if replies:
                        media_repo.add_uploads(owner_id=user.id, parent_kind="forum-reply", parent_id=replies[0].id, uploads=image_uploads(max_count=3), max_count=3, shop_id=shop_id)
            except ValueError as exc: flash(str(exc),"error"); return render_template("ecosystem/forum_new.html",shop=shop),400
            return redirect(url_for("ecosystem.forum_topic",topic_id=topic.id))
        return render_template("ecosystem/forum_new.html",shop=shop)

    @bp.route("/forum/<topic_id>",methods=["GET","POST"])
    def forum_topic(topic_id: str):
        topic=repo.get_forum_topic(topic_id)
        if not topic: abort(404)
        user=current_user()
        if request.method=="POST":
            if not user: return redirect(url_for("webshop.account_login",next=request.path))
            if topic.locked:
                flash("Dieses Thema ist geschlossen.", "error")
                return redirect(url_for("ecosystem.forum_topic",topic_id=topic.id)), 403
            try:
                reply=repo.add_forum_reply(topic.id,user.id,request.form.get("body",""))
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="forum-reply", parent_id=reply.id, uploads=image_uploads(max_count=3), max_count=3, shop_id=topic.shop_id)
            except ValueError as exc:
                flash(str(exc), "error")
                replies=repo.list_forum_replies(topic.id)
                shop=webshop.get_shop(topic.shop_id) if topic.shop_id else None
                return render_template(
                    "ecosystem/forum_topic.html",
                    topic=topic,
                    replies=replies,
                    shop=shop,
                    viewer=user,
                    reply_body=request.form.get("body", ""),
                    reply_images=media_map("forum-reply", replies),
                ), 400
            return redirect(url_for("ecosystem.forum_topic",topic_id=topic.id))
        shop=webshop.get_shop(topic.shop_id) if topic.shop_id else None
        replies=repo.list_forum_replies(topic.id)
        return render_template(
            "ecosystem/forum_topic.html",
            topic=topic,
            replies=replies,
            shop=shop,
            viewer=user,
            reply_body="",
            reply_images=media_map("forum-reply", replies),
        )

    # Document portal --------------------------------------------------
    @bp.get("/account/shop/documents")
    @required
    def documents_manage(user):
        shop=shop_owner(user)
        if not shop: return redirect(url_for("webshop.shop_manage"))
        return render_template("ecosystem/documents_manage.html",shop=shop,documents=repo.list_documents(shop.id))

    @bp.route("/account/shop/documents/new",methods=["GET","POST"])
    @required
    def document_new(user):
        shop=shop_owner(user)
        if not shop: return redirect(url_for("webshop.shop_manage"))
        if request.method=="POST":
            try:
                item = repo.save_document(user.id,None,request.form.get("title",""),request.form.get("slug",""),request.form.get("body",""),request.form.get("visibility","public"),request.form.get("status","draft"))
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="document", parent_id=item.id, uploads=image_uploads(max_count=3), max_count=3, shop_id=shop.id)
            except (ValueError,PermissionError) as exc: flash(str(exc),"error"); return render_template("ecosystem/document_edit.html",document=None,shop=shop,document_images=[]),400
            return redirect(url_for("ecosystem.documents_manage"))
        return render_template("ecosystem/document_edit.html",document=None,shop=shop,document_images=[])

    @bp.route("/account/shop/documents/<doc_id>",methods=["GET","POST"])
    @required
    def document_edit(user,doc_id: str):
        item=repo.get_document(doc_id)
        if not item or item.owner_id!=user.id: abort(404)
        shop=shop_owner(user)
        if request.method=="POST":
            try:
                item=repo.save_document(user.id,item.id,request.form.get("title",""),request.form.get("slug",""),request.form.get("body",""),request.form.get("visibility","public"),request.form.get("status","draft"))
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="document", parent_id=item.id, uploads=image_uploads(max_count=3), max_count=3, shop_id=shop.id, remove_ids=set(request.form.getlist("remove_image_ids")))
            except (ValueError,PermissionError) as exc: flash(str(exc),"error"); return render_template("ecosystem/document_edit.html",document=item,shop=shop,document_images=media_repo.list_for_parent("document", item.id) if media_repo else []),400
        return render_template("ecosystem/document_edit.html",document=item,shop=shop,document_images=media_repo.list_for_parent("document", item.id) if media_repo else [])

    @bp.get("/s/<shop_slug>/documents")
    def documents_public(shop_slug: str):
        shop=webshop.find_shop_by_slug(shop_slug)
        if not shop: abort(404)
        user=current_user(); docs=[]
        for item in repo.list_documents(shop.id,published_only=True):
            if item.visibility=="public" or (item.visibility=="members" and can_member_content(shop.id,user)) or (user and shop.owner_id==user.id): docs.append(item)
        return render_template("ecosystem/documents_public.html",shop=shop,documents=docs)

    @bp.get("/documents/<doc_id>")
    def document_public(doc_id: str):
        item=repo.get_document(doc_id)
        if not item or item.status!="published": abort(404)
        shop=webshop.get_shop(item.shop_id); user=current_user()
        if not shop: abort(404)
        if item.visibility=="private" and (not user or shop.owner_id!=user.id): abort(404)
        if item.visibility=="members" and not can_member_content(shop.id,user): abort(403)
        return render_template("ecosystem/document_public.html",shop=shop,document=item,document_images=media_repo.list_for_parent("document", item.id) if media_repo else [])

    # Community --------------------------------------------------------
    @bp.route("/community",methods=["GET","POST"])
    def community():
        user=current_user()
        if request.method=="POST":
            if not user: return redirect(url_for("webshop.account_login",next=request.path))
            try:
                post=repo.create_community_post(user.id,request.form.get("body",""))
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="community-post", parent_id=post.id, uploads=image_uploads(max_count=3), max_count=3)
            except ValueError as exc: flash(str(exc),"error")
            return redirect(url_for("ecosystem.community"))
        posts=[]
        post_images={}
        comment_images={}
        for post in repo.list_community_posts():
            comments=repo.list_community_comments(post.id)
            posts.append((post,comments))
            if media_repo is not None:
                post_images[post.id]=media_repo.list_for_parent("community-post",post.id)
                for comment in comments:
                    comment_images[comment.id]=media_repo.list_for_parent("community-comment",comment.id)
        return render_template("ecosystem/community.html",posts=posts,post_images=post_images,comment_images=comment_images)

    @bp.post("/community/<post_id>/comment")
    @required
    def community_comment(user,post_id: str):
        try:
            comment=repo.add_community_comment(post_id,user.id,request.form.get("body",""))
            if media_repo is not None:
                media_repo.add_uploads(owner_id=user.id, parent_kind="community-comment", parent_id=comment.id, uploads=image_uploads(max_count=1), max_count=1)
        except ValueError as exc: flash(str(exc),"error")
        return redirect(url_for("ecosystem.community"))

    return bp
