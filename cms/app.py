from __future__ import annotations

from datetime import timedelta
import atexit
from functools import wraps
import hmac
import logging
from typing import Any, Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from urllib.parse import urlsplit
from werkzeug.exceptions import BadRequest, InternalServerError, MethodNotAllowed, NotFound, RequestEntityTooLarge, TooManyRequests
from werkzeug.middleware.proxy_fix import ProxyFix

from .audit import AuditLog
from .backup import BackupIntegrityError, NativeBackupManager
from .config import Settings
from .db import MyceliaDBClient, MyceliaDBError
from .hardening import (
    RateLimiter,
    RatePolicy,
    client_key,
    csrf_token,
    enforce_csrf,
    rotate_csrf_token,
    utc_expired,
    validate_page_id,
)
from .repository import CMSRepository
from .media import SecureMediaRepository
from .media_routes import create_media_blueprint
from .security import MyceliaCryptoError, MyceliaSecuritySDK
from .richtext import canonical_json as richtext_json, normalize_document as richtext_document, plain_text as richtext_plain, excerpt as richtext_excerpt
from .modules.webshop.mailer import MailerError, MailSettings, SMTPMailer
from .modules.webshop.repository import WebshopRepository
from .modules.webshop.routes import create_webshop_blueprint
from .modules.ecosystem.repository import EcosystemRepository
from .modules.ecosystem.routes import create_ecosystem_blueprint


PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
LOGIN_POLICY = RatePolicy(limit=5, window_seconds=300, block_seconds=900)


def _safe_feedback_target() -> str:
    """Return a same-origin page for user-facing validation feedback.

    POST-only action routes should return to the page that submitted them.  Never
    trust an external Referer as a redirect destination.
    """
    referrer = request.referrer
    if referrer:
        parsed = urlsplit(referrer)
        if parsed.netloc == request.host and parsed.scheme in {"http", "https"}:
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            return target
    return request.path


def _friendly_input_message(exc: Exception) -> str:
    text = str(exc).strip()
    return text or "Die Eingabe ist ungültig. Bitte prüfe die markierten Angaben und versuche es erneut."


def _verify_admin_password(stored_hash: str, password: str) -> bool:
    if not stored_hash.startswith("$argon2id$"):
        return False
    try:
        return PASSWORD_HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_app(settings: Settings | None = None) -> Flask:
    cfg = settings or Settings.load()
    if not cfg.admin_password_hash.startswith("$argon2id$"):
        raise RuntimeError("Admin-Passwort ist nicht mit Argon2id gespeichert. install.ps1 erneut ausführen.")

    app = Flask(__name__, template_folder=str(cfg.root / "templates"), static_folder=str(cfg.root / "static"))
    if cfg.trusted_proxy_hops:
        # Trust forwarding metadata only when the deployment explicitly declares
        # the exact proxy hop count. The proxy must overwrite inbound forwarded headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=cfg.trusted_proxy_hops, x_proto=cfg.trusted_proxy_hops)
    app.secret_key = cfg.session_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=cfg.cookie_secure,
        SESSION_COOKIE_NAME="__Host-mycelia-cms" if cfg.cookie_secure else "mycelia-cms-local",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=cfg.session_minutes),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )

    db = MyceliaDBClient(cfg.db_host, cfg.db_port, cfg.db_auth_token, pool_size=cfg.db_pool_size)
    db.require_secure_snapshot_engine()
    crypto = MyceliaSecuritySDK(cfg.sdk_dll, cfg.master_key)
    atexit.register(crypto.close)
    backups = NativeBackupManager(db, cfg.backup_dir, cfg.master_key)
    restore_status = backups.restore_checkpoint_if_present()
    logging.getLogger("cms.app").info(restore_status)
    repo = CMSRepository(db, crypto, backups)
    media_repo = SecureMediaRepository(db, crypto, backups)
    audit = AuditLog(cfg.root / "data" / "audit" / "admin-events.jsonl", cfg.master_key)
    webshop_repo = WebshopRepository(db, crypto, backups)
    ecosystem_repo = EcosystemRepository(db, crypto, backups, webshop_repo)
    mailer = SMTPMailer(
        MailSettings(
            host=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_username,
            password=cfg.smtp_password,
            from_email=cfg.smtp_from_email,
            from_name=cfg.smtp_from_name,
            mode=cfg.smtp_mode,
            public_base_url=cfg.public_base_url,
        )
    )
    limiter = RateLimiter()

    app.extensions.update(
        mycelia_db=db,
        mycelia_crypto=crypto,
        mycelia_backups=backups,
        cms_repo=repo,
        cms_settings=cfg,
        cms_audit=audit,
        webshop_repo=webshop_repo,
        ecosystem_repo=ecosystem_repo,
        secure_media=media_repo,
        webshop_mailer=mailer,
    )
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["richtext_json"] = richtext_json
    app.jinja_env.globals["richtext_doc"] = richtext_document
    app.jinja_env.globals["richtext_plain"] = richtext_plain
    app.jinja_env.globals["richtext_excerpt"] = richtext_excerpt
    app.register_blueprint(
        create_webshop_blueprint(
            webshop_repo,
            mailer=mailer,
            audit=audit,
            session_minutes=cfg.session_minutes,
            ecosystem_repo=ecosystem_repo,
            media_repo=media_repo,
        )
    )
    app.register_blueprint(
        create_ecosystem_blueprint(
            ecosystem_repo, webshop_repo, audit=audit, session_minutes=cfg.session_minutes, media_repo=media_repo
        )
    )
    app.register_blueprint(
        create_media_blueprint(media_repo, repo, webshop_repo, ecosystem_repo, session_minutes=cfg.session_minutes)
    )

    @app.before_request
    def reject_untrusted_host() -> None:
        # Host-header poisoning must not influence redirects or generated URLs.
        raw_host = request.host.strip().lower()
        if raw_host.startswith("[") and "]" in raw_host:
            host = raw_host[: raw_host.index("]") + 1]
        elif raw_host.count(":") == 1:
            host = raw_host.rsplit(":", 1)[0]
        else:
            host = raw_host
        if host not in cfg.allowed_hosts:
            abort(400, description="Unzulässiger Host-Header")

    @app.before_request
    def csrf_guard() -> None:
        enforce_csrf()

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), usb=(), payment=()"
        if cfg.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.path.startswith("/cms"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    def admin_required(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not session.get("cms_admin") or utc_expired(session.get("auth_at"), cfg.session_minutes):
                session.clear()
                return redirect(url_for("login"))
            return func(*args, **kwargs)
        return wrapped

    def cms_image_uploads(max_count: int = 3):
        files = request.files.getlist("image_files")
        nonempty = [f for f in files if f and (f.filename or "").strip()]
        if len(nonempty) > max_count:
            raise ValueError(f"Maximal {max_count} Bilder sind erlaubt")
        return [media_repo.sanitize_upload(f) for f in nonempty]

    @app.get("/")
    def home():
        page = repo.find_by_slug("home")
        if page:
            return render_template("public_page.html", page=page, page_images=media_repo.list_for_parent("cms-page", page.id))
        return render_template("public_home.html")

    @app.get("/p/<slug>")
    def public_page(slug: str):
        try:
            page = repo.find_by_slug(slug)
        except ValueError:
            abort(404)
        if not page:
            abort(404)
        return render_template("public_page.html", page=page, page_images=media_repo.list_for_parent("cms-page", page.id))

    @app.route("/cms/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            key = f"login:{client_key()}"
            if not limiter.allow(key, LOGIN_POLICY):
                audit.record("login_rate_limited", actor="anonymous", remote=client_key())
                abort(429, description="Zu viele Anmeldeversuche")
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            user_ok = hmac.compare_digest(username, cfg.admin_user)
            pass_ok = _verify_admin_password(cfg.admin_password_hash, password)
            if user_ok and pass_ok:
                from datetime import datetime, timezone
                session.clear()
                session.permanent = True
                session["cms_admin"] = True
                session["auth_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                rotate_csrf_token()
                limiter.reset(key)
                audit.record("login_success", actor=cfg.admin_user, remote=client_key())
                return redirect(url_for("dashboard"))
            audit.record("login_failed", actor="anonymous", remote=client_key(), detail={"username_match": user_ok})
            flash("Anmeldung fehlgeschlagen.", "error")
        return render_template("login.html")

    @app.post("/cms/logout")
    @admin_required
    def logout():
        audit.record("logout", actor=cfg.admin_user, remote=client_key())
        session.clear()
        return redirect(url_for("login"))

    @app.get("/cms")
    @admin_required
    def dashboard():
        pages = repo.list_pages()
        return render_template("dashboard.html", pages=pages, page_count=len(pages))

    @app.get("/cms/pages")
    @admin_required
    def pages():
        return render_template("pages.html", pages=repo.list_pages())

    @app.route("/cms/pages/new", methods=["GET", "POST"])
    @admin_required
    def page_new():
        if request.method == "POST":
            try:
                page = repo.save_page(
                    page_id=None,
                    title=request.form.get("title", ""),
                    slug=request.form.get("slug", ""),
                    body=request.form.get("body", ""),
                    status=request.form.get("status", "draft"),
                )
                media_repo.add_uploads(owner_id=cfg.admin_user, parent_kind="cms-page", parent_id=page.id, uploads=cms_image_uploads(), max_count=3)
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template("page_edit.html", page=None, page_images=[]), 400
            audit.record("page_created", actor=cfg.admin_user, remote=client_key(), detail={"page_id": page.id, "slug": page.slug})
            flash("Seite verschlüsselt und nativ in MyceliaDB gespeichert.", "success")
            return redirect(url_for("page_edit", page_id=page.id))
        return render_template("page_edit.html", page=None, page_images=[])

    @app.route("/cms/pages/<page_id>", methods=["GET", "POST"])
    @admin_required
    def page_edit(page_id: str):
        try:
            validate_page_id(page_id)
        except ValueError:
            abort(404)
        page = repo.get_page(page_id)
        if not page:
            abort(404)
        if request.method == "POST":
            try:
                page = repo.save_page(
                    page_id=page.id,
                    title=request.form.get("title", ""),
                    slug=request.form.get("slug", ""),
                    body=request.form.get("body", ""),
                    status=request.form.get("status", "draft"),
                )
                media_repo.add_uploads(owner_id=cfg.admin_user, parent_kind="cms-page", parent_id=page.id, uploads=cms_image_uploads(), max_count=3, remove_ids=set(request.form.getlist("remove_image_ids")))
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template("page_edit.html", page=page, page_images=media_repo.list_for_parent("cms-page", page.id)), 400
            audit.record("page_updated", actor=cfg.admin_user, remote=client_key(), detail={"page_id": page.id, "slug": page.slug})
            flash("Seite aktualisiert; native Live-Persistenz bestätigt.", "success")
        return render_template("page_edit.html", page=page, page_images=media_repo.list_for_parent("cms-page", page.id))

    @app.post("/cms/pages/<page_id>/delete")
    @admin_required
    def page_delete(page_id: str):
        try:
            validate_page_id(page_id)
        except ValueError:
            abort(404)
        media_repo.delete_parent("cms-page", page_id, checkpoint=False)
        if repo.delete_page(page_id):
            audit.record("page_deleted", actor=cfg.admin_user, remote=client_key(), detail={"page_id": page_id})
            flash("Seite gelöscht und nativ persistiert.", "success")
        return redirect(url_for("pages"))

    @app.get("/cms/system")
    @admin_required
    def system():
        db_status = db.require_secure_snapshot_engine()
        return render_template(
            "system.html",
            db_status=db_status,
            dll_path=cfg.sdk_dll,
            live_snapshot=backups.checkpoint_path,
            backups=backups.list(),
        )

    @app.post("/cms/system/backup")
    @admin_required
    def system_backup():
        info, message = backups.create()
        audit.record("native_backup_created", actor=cfg.admin_user, remote=client_key(), detail={"name": info.name, "size": info.size})
        flash(f"Native MyceliaDB-Sicherung erstellt: {info.name} · {message}", "success")
        return redirect(url_for("system"))

    @app.post("/cms/system/backups/purge")
    @admin_required
    def system_backup_purge():
        if request.form.get("confirmation", "") != "PURGE BACKUPS":
            abort(400, description="Backup-Löschbestätigung fehlt")
        removed = backups.purge_historical_backups()
        audit.record("historical_backups_purged", actor=cfg.admin_user, remote=client_key(), detail={"removed": removed})
        flash(f"{removed} historische Sicherungen gelöscht.", "success")
        return redirect(url_for("system"))

    @app.post("/cms/system/restore")
    @admin_required
    def system_restore():
        name = request.form.get("backup", "")
        confirmation = request.form.get("confirmation", "")
        if confirmation != "RESTORE":
            abort(400, description="Restore-Bestätigung fehlt")
        message = backups.restore(name)
        # Re-create the canonical live checkpoint from the just-restored DB.
        backups.save_checkpoint()
        audit.record("native_backup_restored", actor=cfg.admin_user, remote=client_key(), detail={"name": name})
        flash(f"Native MyceliaDB-Sicherung wiederhergestellt: {message}", "success")
        return redirect(url_for("system"))

    @app.get("/healthz")
    def healthz():
        # Do not leak paths, GPU details or exception strings to unauthenticated callers.
        try:
            db.require_secure_snapshot_engine()
            return {"ok": True, "service": "mycelia-cms"}
        except Exception:
            return {"ok": False, "service": "mycelia-cms"}, 503

    @app.errorhandler(ValueError)
    def unhandled_user_value_error(exc: ValueError):
        # Repository/media validators deliberately raise ValueError for rejected
        # user input. A missed route-level catch must still never become a 500.
        logging.getLogger("cms.app").warning("Rejected user input on %s: %s", request.path, exc)
        flash(_friendly_input_message(exc), "error")
        return redirect(_safe_feedback_target()), 303

    @app.errorhandler(MailerError)
    def unhandled_mailer_error(exc: MailerError):
        logging.getLogger("cms.app").warning("Mail operation rejected on %s: %s", request.path, exc)
        flash(_friendly_input_message(exc) + " Bitte prüfe die SMTP-Konfiguration oder versuche es später erneut.", "error")
        return redirect(_safe_feedback_target()), 303

    @app.errorhandler(PermissionError)
    def unhandled_user_permission_error(exc: PermissionError):
        logging.getLogger("cms.app").warning("Rejected user action on %s", request.path)
        flash("Diese Aktion ist für dein Konto nicht erlaubt. Bitte prüfe Anmeldung, Besitz und Berechtigungen.", "error")
        return redirect(_safe_feedback_target()), 303

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(exc: RequestEntityTooLarge):
        flash(
            "Die gesamte Anfrage ist zu groß. Maximal 2 MB pro Formular sind erlaubt; Bilder dürfen jeweils höchstens 280 KB groß sein. "
            "Bitte verkleinere die Dateien und versuche es erneut.",
            "error",
        )
        return redirect(_safe_feedback_target()), 303

    @app.errorhandler(TooManyRequests)
    def too_many_requests(exc: TooManyRequests):
        message = getattr(exc, "description", None) or "Zu viele Anfragen in kurzer Zeit. Bitte warte einen Moment und versuche es erneut."
        flash(str(message), "error")
        return redirect(_safe_feedback_target()), 303

    @app.errorhandler(BadRequest)
    def bad_request(exc: BadRequest):
        # A hostile Host header has no trustworthy same-origin redirect target.
        if "Host-Header" in str(getattr(exc, "description", "")):
            return render_template("error.html", message="Die Anfrage wurde aus Sicherheitsgründen abgelehnt."), 400
        message = getattr(exc, "description", None) or "Die Anfrage enthält ungültige Daten."
        flash(str(message) + " Bitte prüfe deine Eingaben und versuche es erneut.", "error")
        return redirect(_safe_feedback_target()), 303

    @app.errorhandler(NotFound)
    def not_found(exc: NotFound):
        return render_template("error.html", message="Die angeforderte Seite oder Ressource wurde nicht gefunden."), 404

    @app.errorhandler(MethodNotAllowed)
    def method_not_allowed(exc: MethodNotAllowed):
        return render_template("error.html", message="Diese Aktion ist auf diesem Weg nicht erlaubt. Bitte verwende die vorgesehenen Schaltflächen und Formulare."), 405

    @app.errorhandler(InternalServerError)
    def internal_server_error(exc: InternalServerError):
        logging.getLogger("cms.app").error("Unhandled application error on %s", request.path, exc_info=exc.original_exception or exc)
        return render_template(
            "error.html",
            message="Die Aktion konnte wegen eines internen Fehlers nicht abgeschlossen werden. Es wurden keine technischen Details offengelegt; Details stehen im lokalen Log.",
        ), 500

    @app.errorhandler(MyceliaDBError)
    @app.errorhandler(MyceliaCryptoError)
    @app.errorhandler(BackupIntegrityError)
    def integration_error(exc: Exception):
        logging.getLogger("cms.app").exception("Mycelia integration failure")
        return render_template("error.html", message="Sicherheits- oder Integritätsprüfung fehlgeschlagen. Details stehen im lokalen Log."), 503

    return app
