from __future__ import annotations

import argparse
import getpass
import re
import secrets
from pathlib import Path

from argon2 import PasswordHasher

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
USER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV.exists():
        for raw in ENV.read_text(encoding="utf-8").splitlines():
            if not raw or raw.lstrip().startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def prompt_password() -> str:
    while True:
        password = getpass.getpass("Admin-Passwort (mind. 14 Zeichen): ")
        confirm = getpass.getpass("Passwort wiederholen: ")
        if password != confirm:
            print("Passwörter stimmen nicht überein.")
            continue
        if len(password) < 14:
            print("Passwort ist zu kurz.")
            continue
        if password.casefold() in {"passwordpassword", "administrator", "myceliamycelia"}:
            print("Passwort ist zu vorhersehbar.")
            continue
        return password


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-password", action="store_true")
    args = parser.parse_args()

    old = read_env()
    print("Mycelia WebCMS v0.8.0 Identity & Inventory Hardened Setup")

    default_admin = old.get("MYCELIA_CMS_ADMIN_USER", "admin")
    admin = input(f"Admin-Benutzer [{default_admin}]: ").strip() or default_admin
    if not USER_RE.fullmatch(admin):
        raise SystemExit("Admin-Benutzer darf nur A-Z, a-z, 0-9, _, . und - enthalten.")

    current_hash = old.get("MYCELIA_CMS_ADMIN_PASSWORD_HASH", "")
    if args.force_password or not current_hash.startswith("$argon2id$"):
        if current_hash:
            print("Vorhandener Passwort-Hash ist nicht Argon2id und wird ersetzt.")
        password_hash = HASHER.hash(prompt_password())
    else:
        password_hash = current_hash
        print("Vorhandener Argon2id-Hash bleibt erhalten.")

    master_key = old.get("MYCELIA_CMS_MASTER_KEY") or secrets.token_hex(32)
    session_key = old.get("MYCELIA_CMS_SESSION_KEY") or secrets.token_urlsafe(64)

    lines = [
        "MYCELIA_CMS_HOST=127.0.0.1",
        "MYCELIA_CMS_PORT=8088",
        "MYCELIA_DB_HOST=127.0.0.1",
        "MYCELIA_DB_PORT=4555",
        "MYCELIA_SDK_DLL=vendor/CC_OpenCl.dll",
        f"MYCELIA_CMS_MASTER_KEY={master_key}",
        f"MYCELIA_CMS_SESSION_KEY={session_key}",
        f"MYCELIA_CMS_ADMIN_USER={admin}",
        f"MYCELIA_CMS_ADMIN_PASSWORD_HASH={password_hash}",
        "MYCELIA_CMS_BACKUP_DIR=data/backups",
        "MYCELIA_CMS_COOKIE_SECURE=0",
        "MYCELIA_CMS_SESSION_MINUTES=30",
        "MYCELIA_CMS_ALLOWED_HOSTS=127.0.0.1,localhost,[::1]",
        f"MYCELIA_CMS_TRUSTED_PROXY_HOPS={old.get('MYCELIA_CMS_TRUSTED_PROXY_HOPS', '0')}",
        f"MYCELIA_CMS_PUBLIC_BASE_URL={old.get('MYCELIA_CMS_PUBLIC_BASE_URL', '')}",
        f"MYCELIA_SMTP_HOST={old.get('MYCELIA_SMTP_HOST', '')}",
        f"MYCELIA_SMTP_PORT={old.get('MYCELIA_SMTP_PORT', '587')}",
        f"MYCELIA_SMTP_USERNAME={old.get('MYCELIA_SMTP_USERNAME', '')}",
        f"MYCELIA_SMTP_PASSWORD={old.get('MYCELIA_SMTP_PASSWORD', '')}",
        f"MYCELIA_SMTP_FROM_EMAIL={old.get('MYCELIA_SMTP_FROM_EMAIL', '')}",
        f"MYCELIA_SMTP_FROM_NAME={old.get('MYCELIA_SMTP_FROM_NAME', 'Mycelia')}",
        f"MYCELIA_SMTP_MODE={old.get('MYCELIA_SMTP_MODE', 'starttls')}",
    ]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Konfiguration geschrieben: {ENV}")
    print("MASTER_KEY und .env müssen für Wiederherstellung sicher gesichert werden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
