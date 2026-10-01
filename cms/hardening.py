from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import ipaddress
import re
import secrets
import threading
import time
from typing import Deque, Protocol

from flask import abort, request, session


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")
PAGE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
BACKUP_NAME_RE = re.compile(r"^mycelia-cms-[0-9]{8}T[0-9]{6}Z\.mycdb$")


def is_loopback_host(host: str) -> bool:
    value = host.strip().lower()
    if value in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def normalize_slug(value: str) -> str:
    slug = value.strip().strip("/").casefold()
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("Slug darf nur Kleinbuchstaben, Ziffern und Bindestriche enthalten (max. 128 Zeichen).")
    return slug


def validate_title(value: str) -> str:
    title = " ".join(value.strip().split())
    if not title or len(title) > 180:
        raise ValueError("Titel muss zwischen 1 und 180 Zeichen lang sein.")
    return title


def validate_body(value: str) -> str:
    # Body is intentionally plain text. HTML is never interpreted by the public renderer.
    if len(value.encode("utf-8")) > 512 * 1024:
        raise ValueError("Seiteninhalt ist größer als 512 KiB.")
    if "\x00" in value:
        raise ValueError("Seiteninhalt enthält ein NUL-Zeichen.")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def validate_page_id(value: str) -> str:
    if not PAGE_ID_RE.fullmatch(value):
        raise ValueError("Ungültige Seiten-ID.")
    return value


def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(48)
        session["_csrf_token"] = token
    return token


def rotate_csrf_token() -> str:
    token = secrets.token_urlsafe(48)
    session["_csrf_token"] = token
    return token


def enforce_csrf() -> None:
    if request.method in SAFE_METHODS:
        return
    expected = session.get("_csrf_token")
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not isinstance(expected, str) or not isinstance(supplied, str):
        abort(400, description="Ungültiger oder fehlender CSRF-Token")
    if not hmac.compare_digest(expected, supplied):
        abort(400, description="Ungültiger oder fehlender CSRF-Token")


@dataclass(slots=True)
class RatePolicy:
    limit: int
    window_seconds: int
    block_seconds: int


class RateLimiter:
    """Small fail-closed in-process limiter for admin endpoints.

    It deliberately protects only the local CMS control plane. Internet-facing
    DDoS protection still belongs in front of the process (reverse proxy/WAF).
    """

    def __init__(self) -> None:
        self._events: dict[str, Deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.RLock()

    def allow(self, key: str, policy: RatePolicy) -> bool:
        now = time.monotonic()
        with self._lock:
            blocked_until = self._blocked_until.get(key, 0.0)
            if blocked_until > now:
                return False
            q = self._events[key]
            cutoff = now - policy.window_seconds
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= policy.limit:
                self._blocked_until[key] = now + policy.block_seconds
                q.clear()
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
            self._blocked_until.pop(key, None)


class BlindIndexer(Protocol):
    def blind_index(self, namespace: str, value: str) -> str: ...


def client_key() -> str:
    # Do not trust X-Forwarded-For here. A reverse proxy can set REMOTE_ADDR
    # after explicit ProxyFix configuration; accepting the header directly
    # would let clients bypass rate limiting.
    return request.remote_addr or "unknown"


def audit_remote_key(crypto: BlindIndexer) -> str:
    """Return a stable, privacy-preserving fingerprint for audit events.

    The raw client address is intentionally not written into user-facing
    audit events.  The same helper is shared by all public platform modules so
    every ``AuditLog.record`` call satisfies the mandatory ``remote`` contract
    without duplicating the blinding namespace.
    """
    return crypto.blind_index("audit-remote", client_key())


def utc_expired(iso_value: str | None, max_age_minutes: int) -> bool:
    if not iso_value:
        return True
    try:
        created = datetime.fromisoformat(iso_value)
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created > timedelta(minutes=max_age_minutes)
