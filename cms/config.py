from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .hardening import is_loopback_host


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Pflichtvariable fehlt: {name}")
    return value


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path
    host: str
    port: int
    db_host: str
    db_port: int
    db_auth_token: str
    db_pool_size: int
    trusted_proxy_hops: int
    sdk_dll: Path
    master_key: bytes
    session_key: str
    admin_user: str
    admin_password_hash: str
    backup_dir: Path
    cookie_secure: bool
    session_minutes: int
    allowed_hosts: tuple[str, ...]
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from_email: str
    smtp_from_name: str
    smtp_mode: str
    public_base_url: str

    @classmethod
    def load(cls) -> "Settings":
        root = Path(__file__).resolve().parents[1]
        master_hex = _required("MYCELIA_CMS_MASTER_KEY")
        try:
            master_key = bytes.fromhex(master_hex)
        except ValueError as exc:
            raise RuntimeError("MYCELIA_CMS_MASTER_KEY muss hex-kodiert sein") from exc
        if len(master_key) != 32:
            raise RuntimeError("MYCELIA_CMS_MASTER_KEY muss exakt 32 zufällige Bytes besitzen")

        session_key = _required("MYCELIA_CMS_SESSION_KEY")
        if len(session_key) < 48:
            raise RuntimeError("MYCELIA_CMS_SESSION_KEY ist zu kurz")

        host = os.getenv("MYCELIA_CMS_HOST", "127.0.0.1").strip()
        db_host = os.getenv("MYCELIA_DB_HOST", "127.0.0.1").strip()
        if not is_loopback_host(db_host):
            raise RuntimeError("MyceliaDB darf im CMS-Hardened-Modus nur über Loopback angesprochen werden")

        cookie_secure = _bool("MYCELIA_CMS_COOKIE_SECURE", False)
        if not is_loopback_host(host):
            raise RuntimeError(
                "Mycelia CMS darf im Hardened-Modus nur an Loopback binden. "
                "Für externen Zugriff muss ein TLS-Reverse-Proxy vor 127.0.0.1 stehen."
            )

        sdk = Path(os.getenv("MYCELIA_SDK_DLL", "vendor/CC_OpenCl.dll"))
        if not sdk.is_absolute():
            sdk = root / sdk
        backup_dir = Path(os.getenv("MYCELIA_CMS_BACKUP_DIR", "data/backups"))
        if not backup_dir.is_absolute():
            backup_dir = root / backup_dir
        backup_dir = backup_dir.resolve()
        if root.resolve() not in backup_dir.parents and backup_dir != root.resolve():
            raise RuntimeError("Backup-Verzeichnis muss innerhalb des CMS-Projektordners liegen")

        configured_hosts = [x.strip().lower() for x in os.getenv("MYCELIA_CMS_ALLOWED_HOSTS", "").split(",") if x.strip()]
        if not configured_hosts:
            configured_hosts = ["127.0.0.1", "localhost", "[::1]"] if is_loopback_host(host) else [host.lower()]

        session_minutes = int(os.getenv("MYCELIA_CMS_SESSION_MINUTES", "30"))
        if not 5 <= session_minutes <= 480:
            raise RuntimeError("MYCELIA_CMS_SESSION_MINUTES muss zwischen 5 und 480 liegen")

        db_pool_size = int(os.getenv("MYCELIA_DB_POOL_SIZE", "4"))
        if not 1 <= db_pool_size <= 16:
            raise RuntimeError("MYCELIA_DB_POOL_SIZE muss zwischen 1 und 16 liegen")
        trusted_proxy_hops = int(os.getenv("MYCELIA_CMS_TRUSTED_PROXY_HOPS", "0"))
        if not 0 <= trusted_proxy_hops <= 2:
            raise RuntimeError("MYCELIA_CMS_TRUSTED_PROXY_HOPS muss zwischen 0 und 2 liegen")

        smtp_mode = os.getenv("MYCELIA_SMTP_MODE", "starttls").strip().casefold()
        if smtp_mode not in {"starttls", "ssl"}:
            raise RuntimeError("MYCELIA_SMTP_MODE muss starttls oder ssl sein")
        public_base_url = os.getenv("MYCELIA_CMS_PUBLIC_BASE_URL", "").strip().rstrip("/")
        if public_base_url and not (
            public_base_url.startswith("https://")
            or public_base_url.startswith("http://127.0.0.1")
            or public_base_url.startswith("http://localhost")
        ):
            raise RuntimeError(
                "MYCELIA_CMS_PUBLIC_BASE_URL muss HTTPS verwenden; HTTP ist nur für Loopback-Tests erlaubt"
            )

        return cls(
            root=root,
            host=host,
            port=int(os.getenv("MYCELIA_CMS_PORT", "8088")),
            db_host=db_host,
            db_port=int(os.getenv("MYCELIA_DB_PORT", "4555")),
            db_auth_token=_required("MYCELIA_DB_AUTH_TOKEN"),
            db_pool_size=db_pool_size,
            trusted_proxy_hops=trusted_proxy_hops,
            sdk_dll=sdk.resolve(),
            master_key=master_key,
            session_key=session_key,
            admin_user=os.getenv("MYCELIA_CMS_ADMIN_USER", "admin"),
            admin_password_hash=_required("MYCELIA_CMS_ADMIN_PASSWORD_HASH"),
            backup_dir=backup_dir,
            cookie_secure=cookie_secure,
            session_minutes=session_minutes,
            allowed_hosts=tuple(configured_hosts),
            smtp_host=os.getenv("MYCELIA_SMTP_HOST", "").strip(),
            smtp_port=int(os.getenv("MYCELIA_SMTP_PORT", "587")),
            smtp_username=os.getenv("MYCELIA_SMTP_USERNAME", "").strip(),
            smtp_password=os.getenv("MYCELIA_SMTP_PASSWORD", ""),
            smtp_from_email=os.getenv("MYCELIA_SMTP_FROM_EMAIL", "").strip(),
            smtp_from_name=os.getenv("MYCELIA_SMTP_FROM_NAME", "Mycelia").strip(),
            smtp_mode=smtp_mode,
            public_base_url=public_base_url,
        )
