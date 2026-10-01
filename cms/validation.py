from __future__ import annotations

import re

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")
PAGE_ID_RE = re.compile(r"^[a-f0-9]{32}$")


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
    if len(value.encode("utf-8")) > 512 * 1024:
        raise ValueError("Seiteninhalt ist größer als 512 KiB.")
    if "\x00" in value:
        raise ValueError("Seiteninhalt enthält ein NUL-Zeichen.")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def validate_page_id(value: str) -> str:
    if not PAGE_ID_RE.fullmatch(value):
        raise ValueError("Ungültige Seiten-ID.")
    return value
