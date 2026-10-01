from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
import io
import json
import hmac
from typing import Any, Callable
from urllib.parse import urlsplit

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, session, url_for

from ...audit import AuditLog
from ...db import MyceliaDBError
from ...hardening import RateLimiter, RatePolicy, audit_remote_key, client_key, rotate_csrf_token, utc_expired
from ...media import SecureMediaRepository
from .mailer import MailerError, SMTPMailer
from .media import sanitize_product_image
from .models import Shop
from .repository import WebshopRepository, validate_id


USER_LOGIN_IP_POLICY = RatePolicy(limit=30, window_seconds=300, block_seconds=900)
USER_LOGIN_ACCOUNT_POLICY = RatePolicy(limit=6, window_seconds=300, block_seconds=900)
REGISTER_POLICY = RatePolicy(limit=4, window_seconds=1800, block_seconds=1800)
NEWSLETTER_POLICY = RatePolicy(limit=5, window_seconds=3600, block_seconds=3600)
ORDER_POLICY = RatePolicy(limit=20, window_seconds=3600, block_seconds=3600)


def _money(cents: int, currency: str) -> str:
    return f"{cents / 100:.2f} {currency}".replace(".", ",")


def create_webshop_blueprint(
    repo: WebshopRepository,
    *,
    mailer: SMTPMailer,
    audit: AuditLog,
    session_minutes: int,
    ecosystem_repo=None,
    media_repo: SecureMediaRepository | None = None,
) -> Blueprint:
    bp = Blueprint("webshop", __name__, url_prefix="")
    limiter = RateLimiter()

    def audit_remote() -> str:
        return audit_remote_key(repo.crypto)

    def product_image_uploads():
        uploads = []
        files = request.files.getlist("image_files")
        nonempty = [f for f in files if f and (f.filename or "").strip()]
        if len(nonempty) > 3:
            raise ValueError("Pro Produkt sind maximal drei Bilder erlaubt")
        for file_storage in nonempty:
            uploads.append(sanitize_product_image(file_storage))
        return uploads

    def secure_image_uploads(field: str = "image_files", *, max_count: int = 3):
        if media_repo is None:
            return []
        files = request.files.getlist(field)
        nonempty = [f for f in files if f and (f.filename or "").strip()]
        if len(nonempty) > max_count:
            raise ValueError(f"Maximal {max_count} Bilder sind erlaubt")
        return [media_repo.sanitize_upload(f) for f in nonempty]

    def single_image_upload(field: str):
        if media_repo is None:
            return []
        file_storage = request.files.get(field)
        if not file_storage or not (file_storage.filename or "").strip():
            return []
        return [media_repo.sanitize_upload(file_storage)]

    def current_user():
        user_id = session.get("user_id")
        if not isinstance(user_id, str) or utc_expired(session.get("user_auth_at"), session_minutes):
            return None
        try:
            return repo.get_user(user_id)
        except ValueError:
            return None

    def safe_next_url(value: str | None) -> str | None:
        """Accept only same-site absolute-path redirects (prevents open redirects)."""
        if not value:
            return None
        value = value.strip()
        parts = urlsplit(value)
        if parts.scheme or parts.netloc or not value.startswith("/") or value.startswith("//"):
            return None
        return value

    def user_required(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any):
            user = current_user()
            if user is None:
                session.pop("user_id", None)
                session.pop("user_auth_at", None)
                flash("Bitte melde dich an.", "error")
                return redirect(url_for("webshop.account_login", next=request.path))
            return func(user, *args, **kwargs)
        return wrapped

    @bp.app_context_processor
    def inject_webshop_context():
        return {"shop_user": current_user(), "money": _money}

    @bp.get("/privacy")
    def privacy_notice():
        return render_template("webshop/privacy_notice.html")

    @bp.get("/account")
    def account_home():
        user = current_user()
        if user is None:
            return redirect(url_for("webshop.account_login"))
        shop = repo.get_shop_for_owner(user.id)
        orders = repo.list_orders_for_buyer(user.id)
        return render_template("webshop/account.html", user=user, shop=shop, orders=orders)

    @bp.route("/account/register", methods=["GET", "POST"])
    def account_register():
        if current_user() is not None:
            return redirect(url_for("webshop.account_home"))
        if request.method == "POST":
            key = f"user-register:{client_key()}"
            if not limiter.allow(key, REGISTER_POLICY):
                abort(429, description="Zu viele Registrierungsversuche")
            if request.form.get("password", "") != request.form.get("password_repeat", ""):
                flash("Die Passwörter stimmen nicht überein.", "error")
                return render_template("webshop/register.html"), 400
            if not mailer.settings.enabled:
                flash("Kontoregistrierung benötigt eine konfigurierte E-Mail-Verifikation.", "error")
                return render_template("webshop/register.html"), 503
            pending = None
            try:
                pending, token = repo.create_pending_registration(
                    username=request.form.get("username", ""),
                    email=request.form.get("email", ""),
                    display_name=request.form.get("display_name", ""),
                    password=request.form.get("password", ""),
                    privacy_ack=request.form.get("privacy_ack") == "1",
                )
                verify_url = f"{mailer.settings.public_base_url.rstrip('/')}{url_for('webshop.account_verify_email', token=token)}"
                mailer.send(
                    to_email=pending.email,
                    subject="Mycelia-Konto bestätigen",
                    text=("Bitte bestätige den Besitz dieser E-Mail-Adresse, um dein Mycelia-Konto anzulegen:\n" + verify_url +
                          "\n\nWenn du diese Registrierung nicht ausgelöst hast, ignoriere die Nachricht."),
                )
            except (ValueError, MailerError) as exc:
                if pending is not None:
                    repo.discard_pending_registration(pending.id)
                flash(str(exc), "error")
                return render_template("webshop/register.html"), 400
            # No reset: successful registrations/challenges count against the abuse budget.
            audit.record("user_registration_challenge", actor="anonymous", remote=audit_remote())
            flash("Bestätigungs-E-Mail versendet. Das Konto wird erst nach Bestätigung angelegt.", "success")
            return redirect(url_for("webshop.account_login"))
        return render_template("webshop/register.html")

    @bp.get("/account/verify-email/<token>")
    def account_verify_email(token: str):
        try:
            user = repo.confirm_pending_registration(token)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("webshop.account_register"))
        if user is None:
            abort(404)
        audit.record("user_email_verified_and_registered", actor="user", remote=audit_remote(), detail={"user_id": user.id})
        flash("E-Mail bestätigt. Dein Konto ist jetzt aktiv; bitte melde dich an.", "success")
        return redirect(url_for("webshop.account_login"))

    @bp.route("/account/login", methods=["GET", "POST"])
    def account_login():
        if current_user() is not None:
            return redirect(url_for("webshop.account_home"))
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            ip_key = f"user-login-ip:{client_key()}"
            account_key = "user-login-account:" + repo.crypto.blind_index("login-rate-account", username.strip().casefold())
            if not limiter.allow(ip_key, USER_LOGIN_IP_POLICY) or not limiter.allow(account_key, USER_LOGIN_ACCOUNT_POLICY):
                abort(429, description="Zu viele Anmeldeversuche")
            user = repo.verify_user(username, password)
            if user is None:
                audit.record("user_login_failed", actor="anonymous", remote=audit_remote())
                flash("Anmeldung fehlgeschlagen.", "error")
                return render_template("webshop/user_login.html"), 401
            session.clear()
            session.permanent = True
            session["user_id"] = user.id
            session["user_auth_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rotate_csrf_token()
            # Reset only the successfully authenticated account budget. The IP-wide
            # abuse budget remains intact and cannot be cleared via an attacker's account.
            limiter.reset(account_key)
            audit.record("user_login_success", actor="user", remote=audit_remote())
            next_url = safe_next_url(request.form.get("next") or request.args.get("next"))
            return redirect(next_url or url_for("webshop.account_home"))
        return render_template("webshop/user_login.html", next_url=safe_next_url(request.args.get("next")))

    @bp.post("/account/logout")
    @user_required
    def account_logout(user):
        audit.record("user_logout", actor="user", remote=audit_remote())
        session.clear()
        return redirect(url_for("webshop.account_login"))

    @bp.route("/account/profile", methods=["GET", "POST"])
    @user_required
    def account_profile(user):
        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            verified = repo.verify_user(user.username, current_password)
            if verified is None or not hmac.compare_digest(verified.id, user.id):
                flash("Zur Änderung ist das aktuelle Passwort erforderlich.", "error")
                return render_template("webshop/profile.html", user=user), 401
            new_password = request.form.get("new_password", "").strip()
            if new_password and new_password != request.form.get("new_password_repeat", ""):
                flash("Die neuen Passwörter stimmen nicht überein.", "error")
                return render_template("webshop/profile.html", user=user), 400
            requested_email = request.form.get("email", "")
            try:
                # Save non-email profile changes first; email is changed only after
                # the new mailbox proves possession through its challenge token.
                user = repo.update_user_profile(
                    user_id=user.id, display_name=request.form.get("display_name", ""),
                    email=user.email, new_password=new_password or None,
                )
                if requested_email.strip().casefold() != user.email:
                    if not mailer.settings.enabled:
                        raise ValueError("E-Mail-Änderung benötigt eine konfigurierte E-Mail-Verifikation")
                    pending, token = repo.create_email_change_challenge(user_id=user.id, new_email=requested_email)
                    verify_url = f"{mailer.settings.public_base_url.rstrip('/')}{url_for('webshop.account_confirm_email_change', token=token)}"
                    try:
                        mailer.send(to_email=pending.new_email, subject="Neue Mycelia-E-Mail bestätigen",
                                    text="Bestätige die neue E-Mail-Adresse für dein Mycelia-Konto:\n" + verify_url)
                    except MailerError:
                        repo.discard_pending_email_change(pending.id)
                        raise
                    flash("Profil gespeichert. Die neue E-Mail wird erst nach Bestätigung übernommen.", "success")
                else:
                    flash("Profil wurde aktualisiert.", "success")
            except (ValueError, MailerError) as exc:
                flash(str(exc), "error")
                return render_template("webshop/profile.html", user=user), 400
            session["user_auth_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rotate_csrf_token()
            audit.record("user_profile_updated", actor="user", remote=audit_remote())
        return render_template("webshop/profile.html", user=user)

    @bp.post("/account/email/verify/request")
    @user_required
    def account_request_current_email_verification(user):
        if user.email_verified:
            flash("Diese E-Mail-Adresse ist bereits bestätigt.", "success")
            return redirect(url_for("webshop.account_profile"))
        if not mailer.settings.enabled:
            abort(503, description="E-Mail-Verifikation ist nicht konfiguriert")
        pending, token = repo.create_email_change_challenge(user_id=user.id, new_email=user.email)
        verify_url = f"{mailer.settings.public_base_url.rstrip('/')}{url_for('webshop.account_confirm_email_change', token=token)}"
        try:
            mailer.send(to_email=user.email, subject="Mycelia-E-Mail bestätigen", text="Bestätige deine E-Mail-Adresse:\n" + verify_url)
        except MailerError as exc:
            repo.discard_pending_email_change(pending.id)
            flash(str(exc), "error")
            return redirect(url_for("webshop.account_profile"))
        flash("Bestätigungs-E-Mail wurde versendet.", "success")
        return redirect(url_for("webshop.account_profile"))

    @bp.get("/account/email/change/<token>")
    @user_required
    def account_confirm_email_change(user, token: str):
        try:
            changed = repo.confirm_email_change(user_id=user.id, token=token)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("webshop.account_profile"))
        if changed is None:
            abort(404)
        audit.record("user_email_changed_verified", actor="user", remote=audit_remote())
        flash("E-Mail-Adresse wurde bestätigt und übernommen.", "success")
        return redirect(url_for("webshop.account_profile"))

    @bp.get("/account/privacy")
    @user_required
    def privacy_center(user):
        return render_template("webshop/privacy_center.html", user=user)

    @bp.post("/account/privacy/export")
    @user_required
    def privacy_export(user):
        data = repo.export_user_data(user.id)
        if ecosystem_repo is not None:
            data["platform"] = ecosystem_repo.export_user_data(user.id)
        if media_repo is not None:
            data["media"] = media_repo.export_owner(user.id)
        audit.record("user_privacy_export", actor="user", remote=audit_remote())
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            payload,
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="mycelia-data-{user.id}.json"',
                "Cache-Control": "no-store",
            },
        )

    @bp.post("/account/privacy/delete")
    @user_required
    def privacy_delete(user):
        if request.form.get("confirmation", "") != "DELETE":
            flash("Zur Löschung muss DELETE eingegeben werden.", "error")
            return redirect(url_for("webshop.privacy_center"))
        password = request.form.get("password", "")
        verified = repo.verify_user(user.username, password)
        if verified is None or not hmac.compare_digest(verified.id, user.id):
            flash("Passwortprüfung fehlgeschlagen.", "error")
            return redirect(url_for("webshop.privacy_center"))
        media_deleted = 0
        if media_repo is not None:
            # Ticket deletion removes complete correspondence threads. Remove all
            # media attached to those messages as well, including counterparty
            # screenshots, so no orphan encrypted blobs remain.
            if ecosystem_repo is not None:
                ticket_ids = {t.id for t in ecosystem_repo.list_tickets_for_customer(user.id)}
                owned_shop = repo.get_shop_for_owner(user.id)
                if owned_shop is not None:
                    ticket_ids.update(t.id for t in ecosystem_repo.list_tickets_for_shop(owned_shop.id))
                for ticket_id in ticket_ids:
                    for msg in ecosystem_repo.list_ticket_messages(ticket_id):
                        media_deleted += media_repo.delete_parent("ticket-message", msg.id, checkpoint=False)
            media_deleted += media_repo.delete_owner(user.id, checkpoint=False)
        platform_deleted = ecosystem_repo.delete_user_data(user.id) if ecosystem_repo is not None else 0
        result = repo.delete_user_data(user.id)
        result["platform_deleted_nodes"] = platform_deleted
        result["media_deleted_nodes"] = media_deleted
        audit.record("user_privacy_deleted", actor="deleted-user", remote=audit_remote(), detail=result)
        session.clear()
        flash("Konto und zugeordnete Mycelia-Datensätze wurden gelöscht.", "success")
        return redirect(url_for("webshop.account_login"))

    # ----- shop owner -----
    @bp.route("/account/shop", methods=["GET", "POST"])
    @user_required
    def shop_manage(user):
        shop = repo.get_shop_for_owner(user.id)
        if request.method == "POST":
            try:
                # Validate/decode uploads before mutating the shop record. User upload
                # errors must never escape as an HTTP 500 or leave an avoidable
                # half-saved form behind.
                logo = single_image_upload("logo_image") if media_repo is not None else []
                banner = single_image_upload("banner_image") if media_repo is not None else []
                shop = repo.save_shop(
                    owner_id=user.id,
                    name=request.form.get("name", ""),
                    slug=request.form.get("slug", ""),
                    description=request.form.get("description", ""),
                    contact_email=request.form.get("contact_email", user.email),
                    payment_instructions=request.form.get("payment_instructions", ""),
                )
                if media_repo is not None:
                    if logo or request.form.get("remove_logo") == "1":
                        media_repo.add_uploads(owner_id=user.id, parent_kind="shop-logo", parent_id=shop.id, uploads=logo, max_count=1, shop_id=shop.id, slot="logo", replace_slot=True)
                    if banner or request.form.get("remove_banner") == "1":
                        media_repo.add_uploads(owner_id=user.id, parent_kind="shop-banner", parent_id=shop.id, uploads=banner, max_count=1, shop_id=shop.id, slot="banner", replace_slot=True)
            except (ValueError, PermissionError) as exc:
                flash(str(exc), "error")
                logo_existing = media_repo.list_for_parent("shop-logo", shop.id, slot="logo") if media_repo is not None and shop else []
                banner_existing = media_repo.list_for_parent("shop-banner", shop.id, slot="banner") if media_repo is not None and shop else []
                return render_template(
                    "webshop/shop_manage.html",
                    user=user,
                    shop=shop,
                    shop_logo=logo_existing[0] if logo_existing else None,
                    shop_banner=banner_existing[0] if banner_existing else None,
                ), 400
            audit.record("shop_saved", actor="user", remote=audit_remote(), detail={"shop_id": shop.id})
            flash("Shop wurde sicher in MyceliaDB gespeichert.", "success")
            return redirect(url_for("webshop.shop_manage"))
        logo = media_repo.list_for_parent("shop-logo", shop.id, slot="logo") if media_repo is not None and shop else []
        banner = media_repo.list_for_parent("shop-banner", shop.id, slot="banner") if media_repo is not None and shop else []
        return render_template("webshop/shop_manage.html", user=user, shop=shop, shop_logo=logo[0] if logo else None, shop_banner=banner[0] if banner else None)

    @bp.get("/account/shop/products")
    @user_required
    def product_list(user):
        shop = repo.get_shop_for_owner(user.id)
        if not shop:
            return redirect(url_for("webshop.shop_manage"))
        return render_template("webshop/product_list.html", shop=shop, products=repo.list_products(shop.id))

    @bp.route("/account/shop/products/new", methods=["GET", "POST"])
    @user_required
    def product_new(user):
        shop = repo.get_shop_for_owner(user.id)
        if not shop:
            return redirect(url_for("webshop.shop_manage"))
        if request.method == "POST":
            try:
                product = repo.save_product(
                    owner_id=user.id,
                    product_id=None,
                    name=request.form.get("name", ""),
                    slug=request.form.get("slug", ""),
                    description=request.form.get("description", ""),
                    price_cents=request.form.get("price_cents", "0"),
                    currency=request.form.get("currency", "EUR"),
                    stock=request.form.get("stock", "0"),
                    product_type=request.form.get("product_type", "physical"),
                    active=request.form.get("active") == "1",
                    new_images=product_image_uploads(),
                )
            except (ValueError, PermissionError) as exc:
                flash(str(exc), "error")
                return render_template("webshop/product_edit.html", shop=shop, product=None, product_images=[]), 400
            audit.record("product_created", actor="user", remote=audit_remote(), detail={"product_id": product.id})
            return redirect(url_for("webshop.product_list"))
        return render_template("webshop/product_edit.html", shop=shop, product=None, product_images=[])

    @bp.route("/account/shop/products/<product_id>", methods=["GET", "POST"])
    @user_required
    def product_edit(user, product_id: str):
        try:
            validate_id(product_id)
        except ValueError:
            abort(404)
        product = repo.get_product(product_id)
        if product is None or product.owner_id != user.id:
            abort(404)
        shop = repo.get_shop(product.shop_id)
        if request.method == "POST":
            try:
                product = repo.save_product(
                    owner_id=user.id,
                    product_id=product.id,
                    name=request.form.get("name", ""),
                    slug=request.form.get("slug", ""),
                    description=request.form.get("description", ""),
                    price_cents=request.form.get("price_cents", "0"),
                    currency=request.form.get("currency", "EUR"),
                    stock=request.form.get("stock", "0"),
                    product_type=request.form.get("product_type", "physical"),
                    active=request.form.get("active") == "1",
                    new_images=product_image_uploads(),
                    remove_image_ids=set(request.form.getlist("remove_image_ids")),
                )
            except (ValueError, PermissionError) as exc:
                flash(str(exc), "error")
                return render_template("webshop/product_edit.html", shop=shop, product=product, product_images=repo.list_product_images(product)), 400
            audit.record("product_updated", actor="user", remote=audit_remote(), detail={"product_id": product.id})
            flash("Produkt gespeichert.", "success")
        return render_template("webshop/product_edit.html", shop=shop, product=product, product_images=repo.list_product_images(product))

    @bp.post("/account/shop/products/<product_id>/delete")
    @user_required
    def product_delete(user, product_id: str):
        try:
            repo.delete_product(user.id, product_id)
        except (ValueError, PermissionError):
            abort(404)
        audit.record("product_deleted", actor="user", remote=audit_remote(), detail={"product_id": product_id})
        return redirect(url_for("webshop.product_list"))

    @bp.get("/account/shop/blog")
    @user_required
    def blog_list(user):
        shop = repo.get_shop_for_owner(user.id)
        if not shop:
            return redirect(url_for("webshop.shop_manage"))
        return render_template("webshop/blog_list.html", shop=shop, posts=repo.list_blog_posts(shop.id))

    @bp.route("/account/shop/blog/new", methods=["GET", "POST"])
    @user_required
    def blog_new(user):
        shop = repo.get_shop_for_owner(user.id)
        if not shop:
            return redirect(url_for("webshop.shop_manage"))
        if request.method == "POST":
            try:
                post = repo.save_blog_post(
                    owner_id=user.id,
                    post_id=None,
                    title=request.form.get("title", ""),
                    slug=request.form.get("slug", ""),
                    body=request.form.get("body", ""),
                    status=request.form.get("status", "draft"),
                )
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="shop-blog", parent_id=post.id, uploads=secure_image_uploads(max_count=3), max_count=3, shop_id=shop.id, remove_ids=set())
            except (ValueError, PermissionError) as exc:
                flash(str(exc), "error")
                return render_template("webshop/blog_edit.html", shop=shop, post=None, blog_images=[]), 400
            audit.record("blog_created", actor="user", remote=audit_remote(), detail={"post_id": post.id})
            return redirect(url_for("webshop.blog_list"))
        return render_template("webshop/blog_edit.html", shop=shop, post=None, blog_images=[])

    @bp.route("/account/shop/blog/<post_id>", methods=["GET", "POST"])
    @user_required
    def blog_edit(user, post_id: str):
        post = repo.get_blog_post(post_id)
        if post is None or post.owner_id != user.id:
            abort(404)
        shop = repo.get_shop(post.shop_id)
        if request.method == "POST":
            try:
                post = repo.save_blog_post(
                    owner_id=user.id,
                    post_id=post.id,
                    title=request.form.get("title", ""),
                    slug=request.form.get("slug", ""),
                    body=request.form.get("body", ""),
                    status=request.form.get("status", "draft"),
                )
                if media_repo is not None:
                    media_repo.add_uploads(owner_id=user.id, parent_kind="shop-blog", parent_id=post.id, uploads=secure_image_uploads(max_count=3), max_count=3, shop_id=shop.id, remove_ids=set(request.form.getlist("remove_image_ids")))
            except (ValueError, PermissionError) as exc:
                flash(str(exc), "error")
                return render_template("webshop/blog_edit.html", shop=shop, post=post, blog_images=media_repo.list_for_parent("shop-blog", post.id) if media_repo else []), 400
            flash("Blogbeitrag gespeichert.", "success")
        return render_template("webshop/blog_edit.html", shop=shop, post=post, blog_images=media_repo.list_for_parent("shop-blog", post.id) if media_repo else [])

    @bp.post("/account/shop/blog/<post_id>/delete")
    @user_required
    def blog_delete(user, post_id: str):
        try:
            if media_repo is not None:
                media_repo.delete_parent("shop-blog", post_id, checkpoint=False)
            repo.delete_blog_post(user.id, post_id)
        except (ValueError, PermissionError):
            abort(404)
        return redirect(url_for("webshop.blog_list"))

    @bp.get("/account/shop/orders")
    @user_required
    def seller_orders(user):
        shop = repo.get_shop_for_owner(user.id)
        if not shop:
            return redirect(url_for("webshop.shop_manage"))
        return render_template("webshop/seller_orders.html", shop=shop, orders=repo.list_orders_for_seller(user.id))

    @bp.post("/account/shop/orders/<order_id>/status")
    @user_required
    def seller_order_status(user, order_id: str):
        try:
            repo.update_order_status(seller_id=user.id, order_id=order_id, status=request.form.get("status", ""))
        except (ValueError, PermissionError):
            abort(400)
        return redirect(url_for("webshop.seller_orders"))

    @bp.get("/account/shop/newsletter")
    @user_required
    def newsletter_dashboard(user):
        shop = repo.get_shop_for_owner(user.id)
        if not shop:
            return redirect(url_for("webshop.shop_manage"))
        repo.cleanup_expired_pending_subscriptions(shop.id)
        return render_template(
            "webshop/newsletter_dashboard.html",
            shop=shop,
            subscribers=repo.list_confirmed_subscribers(shop.id),
            campaigns=repo.list_campaigns(user.id),
            mail_enabled=mailer.settings.enabled,
        )

    @bp.post("/account/shop/newsletter/campaigns")
    @user_required
    def newsletter_campaign_create(user):
        try:
            campaign = repo.create_campaign(
                owner_id=user.id,
                subject=request.form.get("subject", ""),
                body=request.form.get("body", ""),
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("webshop.newsletter_dashboard"))
        audit.record("newsletter_campaign_created", actor="user", remote=audit_remote(), detail={"campaign_id": campaign.id})
        return redirect(url_for("webshop.newsletter_dashboard"))

    @bp.post("/account/shop/newsletter/campaigns/<campaign_id>/send")
    @user_required
    def newsletter_campaign_send(user, campaign_id: str):
        campaign = repo.get_campaign(campaign_id)
        shop = repo.get_shop_for_owner(user.id)
        if campaign is None or shop is None or campaign.owner_id != user.id or campaign.shop_id != shop.id:
            abort(404)
        if campaign.status != "draft":
            flash("Diese Kampagne wurde bereits versendet.", "error")
            return redirect(url_for("webshop.newsletter_dashboard"))
        if not mailer.settings.enabled:
            flash("SMTP ist nicht konfiguriert. Versand wurde fail-closed verweigert.", "error")
            return redirect(url_for("webshop.newsletter_dashboard"))
        subs = repo.list_confirmed_subscribers(shop.id)
        if len(subs) > 1000:
            flash("Mehr als 1000 Empfänger: Versand muss in einer späteren Queue-Version segmentiert werden.", "error")
            return redirect(url_for("webshop.newsletter_dashboard"))
        delivered = failed = 0
        for sub in subs:
            unsubscribe_url = f"{mailer.settings.public_base_url.rstrip('/')}{url_for('webshop.newsletter_unsubscribe_page', shop_id=shop.id, token=sub.unsubscribe_token)}"
            text = f"{campaign.body}\n\n---\nNewsletter von {shop.name}\nAbmelden: {unsubscribe_url}"
            try:
                mailer.send(to_email=sub.email, subject=campaign.subject, text=text, reply_to=shop.contact_email)
                delivered += 1
            except MailerError:
                failed += 1
        repo.mark_campaign_sent(campaign, delivered, failed)
        audit.record(
            "newsletter_campaign_sent",
            actor="user",
            remote=audit_remote(),
            detail={"campaign_id": campaign.id, "delivered": delivered, "failed": failed},
        )
        flash(f"Newsletter-Versand abgeschlossen: {delivered} zugestellt, {failed} fehlgeschlagen.", "success" if failed == 0 else "error")
        return redirect(url_for("webshop.newsletter_dashboard"))

    # ----- public shop -----
    @bp.get("/shops")
    def public_shops():
        shops = [s for s in repo._list(repo.SHOP_PREFIX, Shop) if s.active]
        shops.sort(key=lambda s: s.name.casefold())
        return render_template("webshop/public_shops.html", shops=shops)

    @bp.get("/s/<shop_slug>")
    def public_shop(shop_slug: str):
        try:
            shop = repo.find_shop_by_slug(shop_slug)
        except ValueError:
            abort(404)
        if shop is None:
            abort(404)
        products = repo.list_products(shop.id, active_only=True)
        cover_images = {product.id: (product.image_ids[0] if product.image_ids else None) for product in products}
        logo = media_repo.list_for_parent("shop-logo", shop.id, slot="logo") if media_repo is not None else []
        banner = media_repo.list_for_parent("shop-banner", shop.id, slot="banner") if media_repo is not None else []
        posts = repo.list_blog_posts(shop.id, published_only=True)[:5]
        blog_covers = {}
        if media_repo is not None:
            for post in posts:
                images = media_repo.list_for_parent("shop-blog", post.id)
                blog_covers[post.id] = images[0].id if images else None
        return render_template(
            "webshop/public_shop.html",
            shop=shop,
            products=products,
            cover_images=cover_images,
            shop_logo=logo[0] if logo else None,
            shop_banner=banner[0] if banner else None,
            posts=posts,
            blog_covers=blog_covers,
        )

    @bp.get("/s/<shop_slug>/products/<product_slug>")
    def public_product(shop_slug: str, product_slug: str):
        shop = repo.find_shop_by_slug(shop_slug)
        if shop is None:
            abort(404)
        product = repo.find_product_by_slug(shop.id, product_slug)
        if product is None or not product.active or product.stock == 0:
            abort(404)
        return render_template("webshop/public_product.html", shop=shop, product=product, product_images=repo.list_product_images(product))

    @bp.get("/media/products/<image_id>.jpg")
    def product_image(image_id: str):
        try:
            validate_id(image_id)
        except ValueError:
            abort(404)
        image = repo.get_product_image(image_id)
        if image is None:
            abort(404)
        product = repo.get_product(image.product_id)
        shop = repo.get_shop(image.shop_id)
        if product is None or shop is None or image.id not in product.image_ids:
            abort(404)
        user = current_user()
        owner_preview = user is not None and user.id == product.owner_id
        if not owner_preview and (not product.active or not shop.active):
            abort(404)
        try:
            data = repo.product_image_bytes(image)
        except MyceliaDBError:
            abort(404)
        response = Response(data, mimetype=image.mime_type)
        response.headers["Content-Disposition"] = f'inline; filename="product-{image.id}.jpg"'
        response.headers["Cache-Control"] = "private, max-age=300" if owner_preview and not product.active else "public, max-age=3600, immutable"
        response.headers["ETag"] = f'"{image.sha256}"'
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @bp.route("/s/<shop_slug>/products/<product_slug>/buy", methods=["GET", "POST"])
    @user_required
    def checkout(user, shop_slug: str, product_slug: str):
        shop = repo.find_shop_by_slug(shop_slug)
        if shop is None:
            abort(404)
        product = repo.find_product_by_slug(shop.id, product_slug)
        if product is None or not product.active:
            abort(404)
        if request.method == "POST":
            if not user.email_verified:
                flash("Vor einer Bestellung muss die Konto-E-Mail bestätigt werden.", "error")
                return redirect(url_for("webshop.account_profile"))
            order_key = f"order:{user.id}:{client_key()}"
            if not limiter.allow(order_key, ORDER_POLICY):
                abort(429, description="Zu viele Bestellversuche")
            try:
                quantity = int(request.form.get("quantity", "1"))
                order = repo.create_order(
                    buyer=user,
                    product=product,
                    quantity=quantity,
                    shipping_address={
                        "name": request.form.get("shipping_name", ""),
                        "street": request.form.get("shipping_street", ""),
                        "postal_code": request.form.get("shipping_postal_code", ""),
                        "city": request.form.get("shipping_city", ""),
                        "country": request.form.get("shipping_country", ""),
                    },
                )
            except (ValueError, TypeError) as exc:
                flash(str(exc), "error")
                return render_template("webshop/checkout.html", shop=shop, product=product, user=user), 400
            audit.record("order_created", actor="user", remote=audit_remote(), detail={"order_id": order.id, "shop_id": shop.id})
            return redirect(url_for("webshop.order_confirmation", order_id=order.id))
        return render_template("webshop/checkout.html", shop=shop, product=product, user=user)

    @bp.get("/account/orders/<order_id>")
    @user_required
    def order_confirmation(user, order_id: str):
        order = repo.get_order(order_id)
        if order is None or order.buyer_id != user.id:
            abort(404)
        shop = repo.get_shop(order.shop_id)
        return render_template("webshop/order_confirmation.html", order=order, shop=shop)

    @bp.get("/s/<shop_slug>/blog")
    def public_blog(shop_slug: str):
        shop = repo.find_shop_by_slug(shop_slug)
        if shop is None:
            abort(404)
        posts = repo.list_blog_posts(shop.id, published_only=True)
        blog_covers = {p.id: ((media_repo.list_for_parent("shop-blog", p.id)[0].id) if media_repo is not None and media_repo.list_for_parent("shop-blog", p.id) else None) for p in posts}
        return render_template("webshop/public_blog.html", shop=shop, posts=posts, blog_covers=blog_covers)

    @bp.get("/s/<shop_slug>/blog/<post_slug>")
    def public_blog_post(shop_slug: str, post_slug: str):
        shop = repo.find_shop_by_slug(shop_slug)
        if shop is None:
            abort(404)
        post = repo.find_blog_post(shop.id, post_slug)
        if post is None or post.status != "published":
            abort(404)
        return render_template("webshop/public_blog_post.html", shop=shop, post=post, blog_images=media_repo.list_for_parent("shop-blog", post.id) if media_repo else [])

    @bp.post("/s/<shop_slug>/newsletter/subscribe")
    def newsletter_subscribe(shop_slug: str):
        shop = repo.find_shop_by_slug(shop_slug)
        if shop is None:
            abort(404)
        key = f"newsletter:{shop.id}:{client_key()}"
        if not limiter.allow(key, NEWSLETTER_POLICY):
            abort(429, description="Zu viele Newsletter-Anfragen")
        if request.form.get("consent") != "1":
            flash("Für den Newsletter ist eine ausdrückliche Einwilligung erforderlich.", "error")
            return redirect(url_for("webshop.public_shop", shop_slug=shop.slug))
        if not mailer.settings.enabled:
            flash("Newsletter ist noch nicht vollständig konfiguriert. Es wurde keine Einwilligung aktiviert.", "error")
            return redirect(url_for("webshop.public_shop", shop_slug=shop.slug))
        sub = None
        try:
            repo.cleanup_expired_pending_subscriptions(shop.id)
            submitted_email = request.form.get("email", "")
            linked_user = current_user()
            account_id = None
            if linked_user is not None and linked_user.email_verified:
                try:
                    if submitted_email.strip().casefold() == linked_user.email:
                        account_id = linked_user.id
                except Exception:
                    account_id = None
            sub = repo.create_or_refresh_subscription(
                shop_id=shop.id, email=submitted_email, name=request.form.get("name", ""),
                source=client_key(), account_id=account_id,
            )
            if sub.status == "confirmed":
                flash("Wenn für diese Adresse noch eine Bestätigung erforderlich ist, wurde eine Nachricht versendet.", "success")
                return redirect(url_for("webshop.public_shop", shop_slug=shop.slug))
            confirm_url = f"{mailer.settings.public_base_url.rstrip('/')}{url_for('webshop.newsletter_confirm', shop_id=shop.id, token=sub.confirm_token)}"
            unsubscribe_url = f"{mailer.settings.public_base_url.rstrip('/')}{url_for('webshop.newsletter_unsubscribe_page', shop_id=shop.id, token=sub.unsubscribe_token)}"
            text = (
                f"Bitte bestätige den Newsletter von {shop.name}:\n{confirm_url}\n\n"
                f"Wenn du diese Anmeldung nicht ausgelöst hast, ignoriere diese Nachricht.\n"
                f"Abmelden/Löschen: {unsubscribe_url}"
            )
            mailer.send(to_email=sub.email, subject=f"Newsletter von {shop.name} bestätigen", text=text, reply_to=shop.contact_email)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("webshop.public_shop", shop_slug=shop.slug))
        except MailerError as exc:
            if sub is not None:
                repo.unsubscribe(shop.id, sub.unsubscribe_token)
            flash(str(exc), "error")
            return redirect(url_for("webshop.public_shop", shop_slug=shop.slug))
        flash("Wenn die Anmeldung zulässig ist, wurde eine Bestätigungs-E-Mail versendet. Erst nach Bestätigung wird der Newsletter aktiviert.", "success")
        return redirect(url_for("webshop.public_shop", shop_slug=shop.slug))

    @bp.get("/newsletter/confirm/<shop_id>/<token>")
    def newsletter_confirm(shop_id: str, token: str):
        try:
            sub = repo.confirm_subscription(shop_id, token)
        except ValueError:
            abort(404)
        if sub is None:
            abort(404)
        shop = repo.get_shop(shop_id)
        return render_template("webshop/newsletter_confirmed.html", shop=shop)

    @bp.get("/newsletter/unsubscribe/<shop_id>/<token>")
    def newsletter_unsubscribe_page(shop_id: str, token: str):
        sub = repo.get_subscription_for_unsubscribe(shop_id, token)
        if sub is None:
            abort(404)
        shop = repo.get_shop(shop_id)
        return render_template("webshop/newsletter_unsubscribe.html", shop=shop, shop_id=shop_id, token=token)

    @bp.post("/newsletter/unsubscribe/<shop_id>/<token>")
    def newsletter_unsubscribe(shop_id: str, token: str):
        if not repo.unsubscribe(shop_id, token):
            abort(404)
        flash("Newsletter-Abonnement und gespeicherte Abonnentendaten wurden gelöscht.", "success")
        return redirect(url_for("home"))

    return bp
