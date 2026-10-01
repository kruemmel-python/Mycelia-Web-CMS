from __future__ import annotations

from dataclasses import asdict
import base64
from datetime import datetime, timezone, timedelta
import re
import hmac
import secrets
import threading
import uuid
from typing import Any, Iterable, TypeVar, Type

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ...backup import NativeBackupManager
from ...db import MyceliaDBClient, MyceliaDBError
from ...validation import normalize_slug, validate_body, validate_title
from ...richtext import validate_richtext, plain_text as richtext_plain
from ...security import MyceliaSecuritySDK
from .media import SanitizedProductImage
from .models import (
    BlogPost, NewsletterCampaign, NewsletterSubscriber, Order, Product, ProductImage,
    Shop, UserAccount, PendingRegistration, PendingEmailChange,
)


PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")
EMAIL_RE = re.compile(r"^[^\s@]{1,128}@[^\s@]{1,190}\.[^\s@]{2,63}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
ID_RE = re.compile(r"^[a-f0-9]{32}$")
T = TypeVar("T")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_id(value: str) -> str:
    if not ID_RE.fullmatch(value):
        raise ValueError("Ungültige ID")
    return value


def validate_username(value: str) -> str:
    username = value.strip()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("Benutzername: 3-32 Zeichen; erlaubt sind Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich.")
    return username


def validate_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise ValueError("Ungültige E-Mail-Adresse")
    return email


def validate_display_name(value: str) -> str:
    name = " ".join(value.strip().split())
    if not 1 <= len(name) <= 100:
        raise ValueError("Anzeigename muss zwischen 1 und 100 Zeichen lang sein")
    return name


def validate_password(value: str) -> str:
    if len(value) < 14 or len(value) > 256:
        raise ValueError("Passwort muss zwischen 14 und 256 Zeichen lang sein")
    return value


def validate_price_cents(value: str | int) -> int:
    try:
        cents = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Preis ist ungültig") from exc
    if cents < 0 or cents > 100_000_000:
        raise ValueError("Preis liegt außerhalb des erlaubten Bereichs")
    return cents


def validate_stock(value: str | int) -> int:
    try:
        stock = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Bestand ist ungültig") from exc
    if stock < 0 or stock > 10_000_000:
        raise ValueError("Bestand liegt außerhalb des erlaubten Bereichs")
    return stock


def validate_currency(value: str) -> str:
    currency = value.strip().upper()
    if not CURRENCY_RE.fullmatch(currency):
        raise ValueError("Währung muss aus genau drei Großbuchstaben bestehen")
    return currency


class WebshopRepository:
    USER_PREFIX = "acct:user:"
    PENDING_REG_PREFIX = "acct:pending-registration:"
    PENDING_EMAIL_PREFIX = "acct:pending-email:"
    SHOP_PREFIX = "shop:store:"
    PRODUCT_PREFIX = "shop:product:"
    PRODUCT_IMAGE_PREFIX = "shop:product-image:"
    BLOG_PREFIX = "shop:blog:"
    ORDER_PREFIX = "shop:order:"
    SUB_PREFIX = "shop:newsletter:sub:"
    CAMPAIGN_PREFIX = "shop:newsletter:campaign:"
    PRIVACY_VERSION = "2026-09-29-v1"

    def __init__(self, db: MyceliaDBClient, crypto: MyceliaSecuritySDK, backups: NativeBackupManager) -> None:
        self.db = db
        self.crypto = crypto
        self.backups = backups
        self._mutation_lock = threading.RLock()

    @staticmethod
    def _node(prefix: str, record_id: str) -> str:
        return prefix + validate_id(record_id)

    def _decode(self, node_id: str, model: Type[T]) -> T:
        node = self.db.get_node(node_id)
        token = node.properties.get("data")
        if not token:
            raise MyceliaDBError("Datensatz besitzt keinen verschlüsselten Payload")
        data = self.crypto.decrypt_json(node_id, token)
        return model(**data)

    def _list(self, prefix: str, model: Type[T], *, prop: tuple[str, str] | None = None) -> list[T]:
        out: list[T] = []
        for node_id in self.db.list_node_ids(prefix):
            node = self.db.get_node(node_id)
            if prop is not None and node.properties.get(prop[0]) != prop[1]:
                continue
            token = node.properties.get("data")
            if not token:
                continue
            out.append(model(**self.crypto.decrypt_json(node_id, token)))
        return out

    def _write(self, prefix: str, record_id: str, kind: str, value: Any, properties: dict[str, str]) -> None:
        node_id = self._node(prefix, record_id)
        self.db.set_property(node_id, "kind", kind)
        for key, prop_value in properties.items():
            self.db.set_property(node_id, key, prop_value)
        self.db.set_property(node_id, "data", self.crypto.encrypt_json(node_id, asdict(value)))

    def _checkpoint(self) -> None:
        self.backups.save_checkpoint()

    # ----- users -----
    def find_user_by_username(self, username: str) -> UserAccount | None:
        username = validate_username(username)
        idx = self.crypto.blind_index("user-username", username)
        for node_id in self.db.list_node_ids(self.USER_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("username_idx") == idx:
                user = UserAccount(**self.crypto.decrypt_json(node_id, node.properties["data"]))
                return None if user.deleted else user
        return None

    def find_user_by_email(self, email: str) -> UserAccount | None:
        email = validate_email(email)
        idx = self.crypto.blind_index("user-email", email)
        for node_id in self.db.list_node_ids(self.USER_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("email_idx") == idx:
                user = UserAccount(**self.crypto.decrypt_json(node_id, node.properties["data"]))
                return None if user.deleted else user
        return None

    def get_user(self, user_id: str) -> UserAccount | None:
        try:
            user = self._decode(self._node(self.USER_PREFIX, user_id), UserAccount)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise
        return None if user.deleted else user

    def register_user(self, *, username: str, email: str, display_name: str, password: str, privacy_ack: bool, email_verified_proof: bool = False) -> UserAccount:
        username = validate_username(username)
        email = validate_email(email)
        display_name = validate_display_name(display_name)
        password = validate_password(password)
        if not privacy_ack:
            raise ValueError("Die Datenschutzhinweise müssen vor der Registrierung bestätigt werden")
        if not email_verified_proof:
            raise ValueError("Direkte Kontoanlage ohne verifizierten E-Mail-Besitz ist verboten")
        if self.find_user_by_username(username):
            raise ValueError("Benutzername oder E-Mail-Adresse ist bereits vergeben")
        if self.find_user_by_email(email):
            raise ValueError("Benutzername oder E-Mail-Adresse ist bereits vergeben")
        now = utc_now()
        user = UserAccount(
            id=uuid.uuid4().hex,
            username=username,
            email=email,
            display_name=display_name,
            password_hash=PASSWORD_HASHER.hash(password),
            created_at=now,
            updated_at=now,
            privacy_version=self.PRIVACY_VERSION,
            email_verified=True,
            email_verified_at=now,
        )
        self._write(self.USER_PREFIX, user.id, "user", user, {
            "username_idx": self.crypto.blind_index("user-username", username),
            "email_idx": self.crypto.blind_index("user-email", email),
        })
        self._checkpoint()
        return user

    def _delete_pending_node(self, prefix: str, record_id: str, *, checkpoint: bool = True) -> None:
        try:
            self.db.delete_node(self._node(prefix, record_id))
        except MyceliaDBError as exc:
            if "missing node" not in str(exc):
                raise
        if checkpoint:
            self._checkpoint()

    def cleanup_pending_registrations(self, max_age_hours: int = 24) -> int:
        now = datetime.now(timezone.utc)
        removed = 0
        for node_id in list(self.db.list_node_ids(self.PENDING_REG_PREFIX)):
            pending = PendingRegistration(**self.crypto.decrypt_json(node_id, self.db.get_node(node_id).properties["data"]))
            try:
                created = datetime.fromisoformat(pending.created_at)
            except ValueError:
                created = datetime.fromtimestamp(0, tz=timezone.utc)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if now - created >= timedelta(hours=max_age_hours):
                self.db.delete_node(node_id)
                removed += 1
        if removed:
            self._checkpoint()
        return removed

    def _release_unverified_email_conflict(self, email: str, *, claimant_user_id: str | None = None) -> None:
        conflict = self.find_user_by_email(email)
        if conflict is None or conflict.id == claimant_user_id:
            return
        if conflict.email_verified:
            raise ValueError("E-Mail-Adresse ist bereits einem bestätigten Konto zugeordnet")
        # Legacy accounts from before v0.8 may contain an address that was never
        # proven. A verified claimant may take that address; the legacy account
        # remains intact but loses the unproven address binding.
        conflict.email = f"unverified-{conflict.id}@account.invalid"
        conflict.email_verified = False
        conflict.email_verified_at = None
        conflict.updated_at = utc_now()
        self._write(self.USER_PREFIX, conflict.id, "user", conflict, {
            "username_idx": self.crypto.blind_index("user-username", conflict.username),
            "email_idx": self.crypto.blind_index("user-email", conflict.email),
        })

    def create_pending_registration(self, *, username: str, email: str, display_name: str, password: str, privacy_ack: bool) -> tuple[PendingRegistration, str]:
        username = validate_username(username)
        email = validate_email(email)
        display_name = validate_display_name(display_name)
        password = validate_password(password)
        if not privacy_ack:
            raise ValueError("Die Datenschutzhinweise müssen vor der Registrierung bestätigt werden")
        # Only verified/active accounts reserve identifiers. Pending requests do not
        # allow an attacker to squat an address he cannot prove ownership of.
        existing_email = self.find_user_by_email(email)
        if self.find_user_by_username(username) or (existing_email is not None and existing_email.email_verified):
            raise ValueError("Benutzername oder bestätigte E-Mail-Adresse ist bereits vergeben")
        self.cleanup_pending_registrations()
        now = utc_now()
        pending = PendingRegistration(
            id=uuid.uuid4().hex, username=username, email=email, display_name=display_name,
            password_hash=PASSWORD_HASHER.hash(password), privacy_version=self.PRIVACY_VERSION, created_at=now,
        )
        token = secrets.token_urlsafe(32)
        self._write(self.PENDING_REG_PREFIX, pending.id, "pending_registration", pending, {
            "token_idx": self.crypto.blind_index("pending-registration-token", token),
        })
        self._checkpoint()
        return pending, token

    def discard_pending_registration(self, pending_id: str) -> None:
        self._delete_pending_node(self.PENDING_REG_PREFIX, pending_id)

    def discard_pending_email_change(self, pending_id: str) -> None:
        self._delete_pending_node(self.PENDING_EMAIL_PREFIX, pending_id)

    def confirm_pending_registration(self, token: str, max_age_hours: int = 24) -> UserAccount | None:
        if not isinstance(token, str) or len(token) < 20 or len(token) > 256:
            return None
        token_idx = self.crypto.blind_index("pending-registration-token", token)
        for node_id in self.db.list_node_ids(self.PENDING_REG_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("token_idx") != token_idx:
                continue
            pending = PendingRegistration(**self.crypto.decrypt_json(node_id, node.properties["data"]))
            created = datetime.fromisoformat(pending.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created >= timedelta(hours=max_age_hours):
                self.db.delete_node(node_id); self._checkpoint(); return None
            if self.find_user_by_username(pending.username):
                self.db.delete_node(node_id); self._checkpoint()
                raise ValueError("Benutzername wurde inzwischen vergeben")
            existing_email = self.find_user_by_email(pending.email)
            if existing_email is not None and existing_email.email_verified:
                self.db.delete_node(node_id); self._checkpoint()
                raise ValueError("E-Mail-Adresse wurde inzwischen bestätigt vergeben")
            self._release_unverified_email_conflict(pending.email)
            now = utc_now()
            user = UserAccount(
                id=uuid.uuid4().hex, username=pending.username, email=pending.email,
                display_name=pending.display_name, password_hash=pending.password_hash,
                created_at=now, updated_at=now, privacy_version=pending.privacy_version,
                email_verified=True, email_verified_at=now,
            )
            self._write(self.USER_PREFIX, user.id, "user", user, {
                "username_idx": self.crypto.blind_index("user-username", user.username),
                "email_idx": self.crypto.blind_index("user-email", user.email),
            })
            self.db.delete_node(node_id)
            self._checkpoint()
            return user
        return None

    def create_email_change_challenge(self, *, user_id: str, new_email: str) -> tuple[PendingEmailChange, str]:
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("Benutzer nicht gefunden")
        new_email = validate_email(new_email)
        existing = self.find_user_by_email(new_email)
        if existing is not None and existing.id != user.id and existing.email_verified:
            raise ValueError("E-Mail-Adresse ist bereits einem bestätigten Konto zugeordnet")
        # Invalidate older challenges for this account.
        user_idx = self.crypto.blind_index("pending-email-user", user.id)
        for node_id in list(self.db.list_node_ids(self.PENDING_EMAIL_PREFIX)):
            node = self.db.get_node(node_id)
            if node.properties.get("user_idx") == user_idx:
                self.db.delete_node(node_id)
        pending = PendingEmailChange(id=uuid.uuid4().hex, user_id=user.id, new_email=new_email, created_at=utc_now())
        token = secrets.token_urlsafe(32)
        self._write(self.PENDING_EMAIL_PREFIX, pending.id, "pending_email_change", pending, {
            "user_idx": user_idx,
            "token_idx": self.crypto.blind_index("pending-email-token", token),
        })
        self._checkpoint()
        return pending, token

    def confirm_email_change(self, *, user_id: str, token: str, max_age_hours: int = 24) -> UserAccount | None:
        validate_id(user_id)
        if not isinstance(token, str) or len(token) < 20 or len(token) > 256:
            return None
        token_idx = self.crypto.blind_index("pending-email-token", token)
        for node_id in self.db.list_node_ids(self.PENDING_EMAIL_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("token_idx") != token_idx:
                continue
            pending = PendingEmailChange(**self.crypto.decrypt_json(node_id, node.properties["data"]))
            if pending.user_id != user_id:
                return None
            created = datetime.fromisoformat(pending.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created >= timedelta(hours=max_age_hours):
                self.db.delete_node(node_id); self._checkpoint(); return None
            user = self.get_user(user_id)
            if user is None:
                return None
            existing = self.find_user_by_email(pending.new_email)
            if existing is not None and existing.id != user.id and existing.email_verified:
                raise ValueError("E-Mail-Adresse wurde inzwischen bestätigt vergeben")
            self._release_unverified_email_conflict(pending.new_email, claimant_user_id=user.id)
            user.email = pending.new_email
            user.email_verified = True
            user.email_verified_at = utc_now()
            user.updated_at = utc_now()
            self._write(self.USER_PREFIX, user.id, "user", user, {
                "username_idx": self.crypto.blind_index("user-username", user.username),
                "email_idx": self.crypto.blind_index("user-email", user.email),
            })
            self.db.delete_node(node_id)
            self._checkpoint()
            return user
        return None

    def verify_user(self, username: str, password: str) -> UserAccount | None:
        try:
            user = self.find_user_by_username(username)
        except ValueError:
            return None
        if user is None or not user.password_hash.startswith("$argon2id$"):
            return None
        try:
            if PASSWORD_HASHER.verify(user.password_hash, password):
                return user
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return None
        return None

    def update_user_profile(
        self,
        *,
        user_id: str,
        display_name: str,
        email: str,
        new_password: str | None = None,
    ) -> UserAccount:
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("Benutzer nicht gefunden")
        display_name = validate_display_name(display_name)
        email = validate_email(email)
        if email != user.email:
            raise ValueError("E-Mail-Änderungen sind nur über den Verifikations-Workflow erlaubt")
        existing_email = self.find_user_by_email(email)
        if existing_email is not None and existing_email.id != user.id:
            raise ValueError("Benutzername oder E-Mail-Adresse ist bereits vergeben")
        if new_password:
            validate_password(new_password)
            user.password_hash = PASSWORD_HASHER.hash(new_password)
        user.display_name = display_name
        user.email = email
        user.updated_at = utc_now()
        self._write(self.USER_PREFIX, user.id, "user", user, {
            "username_idx": self.crypto.blind_index("user-username", user.username),
            "email_idx": self.crypto.blind_index("user-email", email),
        })
        self._checkpoint()
        return user

    # ----- shops -----
    def list_shops(self, *, active_only: bool = False) -> list[Shop]:
        shops = self._list(self.SHOP_PREFIX, Shop)
        if active_only:
            shops = [s for s in shops if s.active]
        shops.sort(key=lambda s: s.name.casefold())
        return shops

    def get_shop(self, shop_id: str) -> Shop | None:
        try:
            return self._decode(self._node(self.SHOP_PREFIX, shop_id), Shop)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise

    def get_shop_for_owner(self, owner_id: str) -> Shop | None:
        validate_id(owner_id)
        owner_idx = self.crypto.blind_index("shop-owner", owner_id)
        shops = self._list(self.SHOP_PREFIX, Shop, prop=("owner_idx", owner_idx))
        return shops[0] if shops else None

    def find_shop_by_slug(self, slug: str) -> Shop | None:
        slug = normalize_slug(slug)
        slug_idx = self.crypto.blind_index("shop-slug", slug)
        shops = self._list(self.SHOP_PREFIX, Shop, prop=("slug_idx", slug_idx))
        return next((shop for shop in shops if shop.active), None)

    def save_shop(self, *, owner_id: str, name: str, slug: str, description: str, contact_email: str, payment_instructions: str) -> Shop:
        validate_id(owner_id)
        name = validate_title(name)
        slug = normalize_slug(slug)
        description = validate_richtext(description, "standard", max_chars=20_000, required=False)
        contact_email = validate_email(contact_email)
        payment_instructions = validate_richtext(payment_instructions, "compact", max_chars=8_000, required=False)
        existing_slug = self.find_shop_by_slug(slug)
        current = self.get_shop_for_owner(owner_id)
        if existing_slug and (current is None or existing_slug.id != current.id):
            raise ValueError("Shop-Slug ist bereits vergeben")
        now = utc_now()
        shop = Shop(
            id=current.id if current else uuid.uuid4().hex,
            owner_id=owner_id,
            name=name,
            slug=slug,
            description=description,
            contact_email=contact_email,
            payment_instructions=payment_instructions,
            created_at=current.created_at if current else now,
            updated_at=now,
            active=True,
        )
        self._write(self.SHOP_PREFIX, shop.id, "shop", shop, {
            "owner_idx": self.crypto.blind_index("shop-owner", owner_id),
            "slug_idx": self.crypto.blind_index("shop-slug", slug),
        })
        self._checkpoint()
        return shop

    # ----- products -----
    def list_products(self, shop_id: str, *, active_only: bool = False) -> list[Product]:
        validate_id(shop_id)
        idx = self.crypto.blind_index("product-shop", shop_id)
        products = self._list(self.PRODUCT_PREFIX, Product, prop=("shop_idx", idx))
        if active_only:
            products = [p for p in products if p.active and p.stock != 0]
        products.sort(key=lambda p: p.updated_at, reverse=True)
        return products

    def get_product(self, product_id: str) -> Product | None:
        try:
            return self._decode(self._node(self.PRODUCT_PREFIX, product_id), Product)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise

    def find_product_by_slug(self, shop_id: str, slug: str) -> Product | None:
        validate_id(shop_id)
        slug = normalize_slug(slug)
        shop_idx = self.crypto.blind_index("product-shop", shop_id)
        slug_idx = self.crypto.blind_index(f"product-slug:{shop_id}", slug)
        for node_id in self.db.list_node_ids(self.PRODUCT_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("shop_idx") == shop_idx and node.properties.get("slug_idx") == slug_idx:
                return Product(**self.crypto.decrypt_json(node_id, node.properties["data"]))
        return None

    def save_product(self, *, owner_id: str, product_id: str | None, name: str, slug: str, description: str,
                     price_cents: str | int, currency: str, stock: str | int, product_type: str, active: bool,
                     new_images: list[SanitizedProductImage] | None = None,
                     remove_image_ids: set[str] | None = None) -> Product:
        shop = self.get_shop_for_owner(owner_id)
        if shop is None:
            raise ValueError("Zuerst muss ein Shop angelegt werden")
        name = validate_title(name)
        slug = normalize_slug(slug)
        description = validate_richtext(description, "standard", max_chars=100_000, required=False)
        cents = validate_price_cents(price_cents)
        currency = validate_currency(currency)
        stock_i = validate_stock(stock)
        if product_type not in {"physical", "digital", "service"}:
            raise ValueError("Ungültiger Produkttyp")
        current = self.get_product(product_id) if product_id else None
        if current and current.owner_id != owner_id:
            raise PermissionError("Produkt gehört nicht zu diesem Benutzer")
        same_slug = self.find_product_by_slug(shop.id, slug)
        if same_slug and (current is None or same_slug.id != current.id):
            raise ValueError("Produkt-Slug ist in diesem Shop bereits vergeben")
        now = utc_now()
        current_image_ids = list(current.image_ids) if current else []
        remove_ids = {validate_id(x) for x in (remove_image_ids or set())}
        if not remove_ids.issubset(set(current_image_ids)):
            raise ValueError("Ungültige Bildauswahl")
        retained_image_ids = [image_id for image_id in current_image_ids if image_id not in remove_ids]
        images_to_add = list(new_images or [])
        if len(retained_image_ids) + len(images_to_add) > 3:
            raise ValueError("Pro Produkt sind maximal drei Bilder erlaubt")

        product_id_final = current.id if current else uuid.uuid4().hex
        created_image_ids: list[str] = []
        try:
            for position, upload in enumerate(images_to_add, start=len(retained_image_ids)):
                image_id = uuid.uuid4().hex
                image = ProductImage(
                    id=image_id,
                    product_id=product_id_final,
                    shop_id=shop.id,
                    owner_id=owner_id,
                    original_name=upload.original_name,
                    mime_type=upload.mime_type,
                    content_b64=base64.b64encode(upload.content).decode("ascii"),
                    sha256=upload.sha256,
                    width=upload.width,
                    height=upload.height,
                    position=position,
                    created_at=now,
                )
                self._write(self.PRODUCT_IMAGE_PREFIX, image.id, "product_image", image, {
                    "product_idx": self.crypto.blind_index("product-image-product", product_id_final),
                    "shop_idx": self.crypto.blind_index("product-image-shop", shop.id),
                    "owner_idx": self.crypto.blind_index("product-image-owner", owner_id),
                })
                created_image_ids.append(image.id)

            final_image_ids = retained_image_ids + created_image_ids
            # Keep gallery ordering canonical after removals/additions.
            for position, image_id in enumerate(final_image_ids):
                image = self.get_product_image(image_id)
                if image is not None and image.position != position:
                    image.position = position
                    self._write(self.PRODUCT_IMAGE_PREFIX, image.id, "product_image", image, {
                        "product_idx": self.crypto.blind_index("product-image-product", product_id_final),
                        "shop_idx": self.crypto.blind_index("product-image-shop", shop.id),
                        "owner_idx": self.crypto.blind_index("product-image-owner", owner_id),
                    })

            product = Product(
                id=product_id_final,
                shop_id=shop.id,
                owner_id=owner_id,
                name=name,
                slug=slug,
                description=description,
                price_cents=cents,
                currency=currency,
                stock=stock_i,
                product_type=product_type,
                created_at=current.created_at if current else now,
                updated_at=now,
                active=active,
                image_ids=final_image_ids,
            )
            self._write(self.PRODUCT_PREFIX, product.id, "product", product, {
                "shop_idx": self.crypto.blind_index("product-shop", shop.id),
                "owner_idx": self.crypto.blind_index("product-owner", owner_id),
                "slug_idx": self.crypto.blind_index(f"product-slug:{shop.id}", slug),
            })
            for image_id in remove_ids:
                try:
                    self.db.delete_node(self._node(self.PRODUCT_IMAGE_PREFIX, image_id))
                except MyceliaDBError as exc:
                    if "missing node" not in str(exc):
                        raise
            self._checkpoint()
            return product
        except Exception:
            # Avoid orphan media nodes when a later DB mutation fails.
            for image_id in created_image_ids:
                try:
                    self.db.delete_node(self._node(self.PRODUCT_IMAGE_PREFIX, image_id))
                except MyceliaDBError:
                    pass
            raise

    def get_product_image(self, image_id: str) -> ProductImage | None:
        try:
            return self._decode(self._node(self.PRODUCT_IMAGE_PREFIX, image_id), ProductImage)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise

    def list_product_images(self, product: Product) -> list[ProductImage]:
        images: list[ProductImage] = []
        for image_id in product.image_ids[:3]:
            image = self.get_product_image(image_id)
            if image is not None and image.product_id == product.id and image.shop_id == product.shop_id:
                images.append(image)
        images.sort(key=lambda image: image.position)
        return images

    def product_image_bytes(self, image: ProductImage) -> bytes:
        try:
            data = base64.b64decode(image.content_b64, validate=True)
        except Exception as exc:
            raise MyceliaDBError("Produktbild-Payload ist beschädigt") from exc
        import hashlib
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), image.sha256):
            raise MyceliaDBError("Produktbild-Integritätsprüfung fehlgeschlagen")
        return data

    def delete_product(self, owner_id: str, product_id: str) -> None:
        product = self.get_product(product_id)
        if product is None:
            return
        if product.owner_id != owner_id:
            raise PermissionError("Produkt gehört nicht zu diesem Benutzer")
        for image_id in product.image_ids:
            try:
                self.db.delete_node(self._node(self.PRODUCT_IMAGE_PREFIX, image_id))
            except MyceliaDBError as exc:
                if "missing node" not in str(exc):
                    raise
        self.db.delete_node(self._node(self.PRODUCT_PREFIX, product.id))
        self._checkpoint()

    # ----- blog -----
    def list_blog_posts(self, shop_id: str, *, published_only: bool = False) -> list[BlogPost]:
        validate_id(shop_id)
        idx = self.crypto.blind_index("blog-shop", shop_id)
        posts = self._list(self.BLOG_PREFIX, BlogPost, prop=("shop_idx", idx))
        if published_only:
            posts = [p for p in posts if p.status == "published"]
        posts.sort(key=lambda p: p.updated_at, reverse=True)
        return posts

    def get_blog_post(self, post_id: str) -> BlogPost | None:
        try:
            return self._decode(self._node(self.BLOG_PREFIX, post_id), BlogPost)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise

    def find_blog_post(self, shop_id: str, slug: str) -> BlogPost | None:
        validate_id(shop_id)
        slug = normalize_slug(slug)
        shop_idx = self.crypto.blind_index("blog-shop", shop_id)
        slug_idx = self.crypto.blind_index(f"blog-slug:{shop_id}", slug)
        for node_id in self.db.list_node_ids(self.BLOG_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("shop_idx") == shop_idx and node.properties.get("slug_idx") == slug_idx:
                return BlogPost(**self.crypto.decrypt_json(node_id, node.properties["data"]))
        return None

    def save_blog_post(self, *, owner_id: str, post_id: str | None, title: str, slug: str, body: str, status: str) -> BlogPost:
        shop = self.get_shop_for_owner(owner_id)
        if shop is None:
            raise ValueError("Zuerst muss ein Shop angelegt werden")
        title = validate_title(title)
        slug = normalize_slug(slug)
        body = validate_richtext(body, "document", max_chars=200_000, required=True)
        if status not in {"draft", "published"}:
            raise ValueError("Ungültiger Blogstatus")
        current = self.get_blog_post(post_id) if post_id else None
        if current and current.owner_id != owner_id:
            raise PermissionError("Blogbeitrag gehört nicht zu diesem Benutzer")
        same_slug = self.find_blog_post(shop.id, slug)
        if same_slug and (current is None or same_slug.id != current.id):
            raise ValueError("Blog-Slug ist bereits vergeben")
        now = utc_now()
        post = BlogPost(
            id=current.id if current else uuid.uuid4().hex,
            shop_id=shop.id,
            owner_id=owner_id,
            title=title,
            slug=slug,
            body=body,
            status=status,
            created_at=current.created_at if current else now,
            updated_at=now,
        )
        self._write(self.BLOG_PREFIX, post.id, "blog", post, {
            "shop_idx": self.crypto.blind_index("blog-shop", shop.id),
            "owner_idx": self.crypto.blind_index("blog-owner", owner_id),
            "slug_idx": self.crypto.blind_index(f"blog-slug:{shop.id}", slug),
        })
        self._checkpoint()
        return post

    def delete_blog_post(self, owner_id: str, post_id: str) -> None:
        post = self.get_blog_post(post_id)
        if post is None:
            return
        if post.owner_id != owner_id:
            raise PermissionError("Blogbeitrag gehört nicht zu diesem Benutzer")
        self.db.delete_node(self._node(self.BLOG_PREFIX, post.id))
        self._checkpoint()

    # ----- orders -----
    def create_order(self, *, buyer: UserAccount, product: Product, quantity: int, shipping_address: dict[str, str]) -> Order:
        with self._mutation_lock:
            current_product = self.get_product(product.id)
            if current_product is None:
                raise ValueError("Produkt ist nicht verfügbar")
            product = current_product
            if not product.active or product.stock == 0:
                raise ValueError("Produkt ist nicht verfügbar")
            if quantity < 1 or quantity > 100:
                raise ValueError("Ungültige Bestellmenge")
            if product.stock > 0 and quantity > product.stock:
                raise ValueError("Bestellmenge übersteigt den verfügbaren Bestand")
            shop = self.get_shop(product.shop_id)
            if shop is None or not shop.active:
                raise ValueError("Shop ist nicht verfügbar")
            if product.product_type == "physical":
                required = ("name", "street", "postal_code", "city", "country")
                cleaned = {k: " ".join(shipping_address.get(k, "").strip().split()) for k in required}
                if any(not cleaned[k] for k in required):
                    raise ValueError("Für physische Produkte ist eine vollständige Lieferadresse erforderlich")
                if any(len(v) > 160 for v in cleaned.values()):
                    raise ValueError("Lieferadresse enthält zu lange Felder")
                shipping_address = cleaned
            else:
                shipping_address = {}
            now = utc_now()
            order = Order(
                id=uuid.uuid4().hex,
                shop_id=shop.id,
                seller_id=shop.owner_id,
                buyer_id=buyer.id,
                product_id=product.id,
                product_name=product.name,
                quantity=quantity,
                unit_price_cents=product.price_cents,
                total_cents=product.price_cents * quantity,
                currency=product.currency,
                buyer_email=buyer.email,
                shipping_address=shipping_address,
                payment_instructions=shop.payment_instructions,
                status="pending",
                created_at=now,
                updated_at=now,
                inventory_committed=False,
            )
            self._write(self.ORDER_PREFIX, order.id, "order", order, {
                "shop_idx": self.crypto.blind_index("order-shop", shop.id),
                "seller_idx": self.crypto.blind_index("order-seller", shop.owner_id),
                "buyer_idx": self.crypto.blind_index("order-buyer", buyer.id),
            })
            # pending is only an order intent. Inventory is committed atomically
            # by the seller-authorized pending -> paid transition below.
            self._checkpoint()
            return order

    def list_orders_for_buyer(self, buyer_id: str) -> list[Order]:
        validate_id(buyer_id)
        idx = self.crypto.blind_index("order-buyer", buyer_id)
        orders = self._list(self.ORDER_PREFIX, Order, prop=("buyer_idx", idx))
        orders.sort(key=lambda o: o.created_at, reverse=True)
        return orders

    def list_orders_for_seller(self, seller_id: str) -> list[Order]:
        validate_id(seller_id)
        idx = self.crypto.blind_index("order-seller", seller_id)
        orders = self._list(self.ORDER_PREFIX, Order, prop=("seller_idx", idx))
        orders.sort(key=lambda o: o.created_at, reverse=True)
        return orders

    def get_order(self, order_id: str) -> Order | None:
        try:
            return self._decode(self._node(self.ORDER_PREFIX, order_id), Order)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise

    def update_order_status(self, *, seller_id: str, order_id: str, status: str) -> Order:
        transitions = {
            "pending": {"paid", "cancelled"},
            "paid": {"processing", "cancelled"},
            "processing": {"shipped", "cancelled"},
            "shipped": {"completed"},
            "completed": set(),
            "cancelled": set(),
        }
        if status not in transitions:
            raise ValueError("Ungültiger Bestellstatus")
        with self._mutation_lock:
            order = self.get_order(order_id)
            if order is None:
                raise ValueError("Bestellung nicht gefunden")
            if order.seller_id != seller_id:
                raise PermissionError("Bestellung gehört nicht zu diesem Shop")
            if status == order.status:
                return order
            if status not in transitions.get(order.status, set()):
                raise ValueError(f"Ungültiger Statusübergang: {order.status} -> {status}")

            # Legacy v0.7 orders had inventory deducted at pending creation. Treat
            # their missing marker as already committed to prevent double booking.
            committed = True if order.inventory_committed is None else bool(order.inventory_committed)
            product = self.get_product(order.product_id)

            if order.status == "pending" and status == "paid" and not committed:
                if product is None or not product.active:
                    raise ValueError("Produkt ist nicht mehr verfügbar")
                if product.stock < order.quantity:
                    raise ValueError("Bestand reicht für diese Bestellung nicht mehr aus")
                product.stock -= order.quantity
                product.updated_at = utc_now()
                self._write(self.PRODUCT_PREFIX, product.id, "product", product, {
                    "shop_idx": self.crypto.blind_index("product-shop", product.shop_id),
                    "owner_idx": self.crypto.blind_index("product-owner", product.owner_id),
                    "slug_idx": self.crypto.blind_index(f"product-slug:{product.shop_id}", product.slug),
                })
                committed = True

            if status == "cancelled" and committed:
                if product is not None:
                    product.stock = min(10_000_000, product.stock + order.quantity)
                    product.updated_at = utc_now()
                    self._write(self.PRODUCT_PREFIX, product.id, "product", product, {
                        "shop_idx": self.crypto.blind_index("product-shop", product.shop_id),
                        "owner_idx": self.crypto.blind_index("product-owner", product.owner_id),
                        "slug_idx": self.crypto.blind_index(f"product-slug:{product.shop_id}", product.slug),
                    })
                committed = False

            order.status = status
            order.inventory_committed = committed
            order.updated_at = utc_now()
            self._write(self.ORDER_PREFIX, order.id, "order", order, {
                "shop_idx": self.crypto.blind_index("order-shop", order.shop_id),
                "seller_idx": self.crypto.blind_index("order-seller", order.seller_id),
                "buyer_idx": self.crypto.blind_index("order-buyer", order.buyer_id),
            })
            self._checkpoint()
            return order

    # ----- newsletter -----
    def cleanup_expired_pending_subscriptions(self, shop_id: str, max_age_hours: int = 48) -> int:
        validate_id(shop_id)
        shop_idx = self.crypto.blind_index("newsletter-shop", shop_id)
        now = datetime.now(timezone.utc)
        removed = 0
        for node_id in list(self.db.list_node_ids(self.SUB_PREFIX)):
            node = self.db.get_node(node_id)
            if node.properties.get("shop_idx") != shop_idx:
                continue
            token = node.properties.get("data")
            if not token:
                continue
            sub = NewsletterSubscriber(**self.crypto.decrypt_json(node_id, token))
            if sub.status != "pending":
                continue
            try:
                consent = datetime.fromisoformat(sub.consent_at)
            except ValueError:
                consent = datetime.fromtimestamp(0, tz=timezone.utc)
            if consent.tzinfo is None:
                consent = consent.replace(tzinfo=timezone.utc)
            if (now - consent).total_seconds() >= max_age_hours * 3600:
                self.db.delete_node(node_id)
                removed += 1
        if removed:
            self._checkpoint()
        return removed

    def find_subscriber_by_email(self, shop_id: str, email: str) -> NewsletterSubscriber | None:
        validate_id(shop_id)
        email = validate_email(email)
        shop_idx = self.crypto.blind_index("newsletter-shop", shop_id)
        email_idx = self.crypto.blind_index(f"newsletter-email:{shop_id}", email)
        for node_id in self.db.list_node_ids(self.SUB_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("shop_idx") == shop_idx and node.properties.get("email_idx") == email_idx:
                return NewsletterSubscriber(**self.crypto.decrypt_json(node_id, node.properties["data"]))
        return None

    def create_or_refresh_subscription(self, *, shop_id: str, email: str, name: str, source: str, account_id: str | None = None) -> NewsletterSubscriber:
        shop = self.get_shop(shop_id)
        if shop is None:
            raise ValueError("Shop nicht gefunden")
        email = validate_email(email)
        name = " ".join(name.strip().split())[:100]
        existing = self.find_subscriber_by_email(shop_id, email)
        now = utc_now()
        sub = existing or NewsletterSubscriber(
            id=uuid.uuid4().hex,
            shop_id=shop_id,
            email=email,
            name=name,
            status="pending",
            consent_at=now,
            confirmed_at=None,
            confirm_token="",
            unsubscribe_token="",
            source_fingerprint="",
            created_at=now,
            updated_at=now,
            account_id=account_id,
        )
        if account_id is not None:
            validate_id(account_id)
            if sub.account_id != account_id:
                sub.account_id = account_id
                sub.updated_at = now
                if sub.status == "confirmed":
                    self._write(self.SUB_PREFIX, sub.id, "newsletter_subscriber", sub, {
                        "shop_idx": self.crypto.blind_index("newsletter-shop", shop_id),
                        "email_idx": self.crypto.blind_index(f"newsletter-email:{shop_id}", email),
                        "confirm_idx": self.crypto.blind_index(f"newsletter-confirm:{shop_id}", "revoked:" + sub.id),
                        "unsubscribe_idx": self.crypto.blind_index(f"newsletter-unsubscribe:{shop_id}", sub.unsubscribe_token),
                        "status_idx": self.crypto.blind_index(f"newsletter-status:{shop_id}", sub.status),
                    })
                    self._checkpoint()
        if sub.status == "confirmed":
            return sub
        sub.name = name
        sub.status = "pending"
        sub.consent_at = now
        sub.confirmed_at = None
        sub.confirm_token = secrets.token_urlsafe(32)
        sub.unsubscribe_token = sub.unsubscribe_token or secrets.token_urlsafe(32)
        sub.source_fingerprint = self.crypto.blind_index(f"newsletter-source:{shop_id}", source or "unknown")
        sub.updated_at = now
        self._write(self.SUB_PREFIX, sub.id, "newsletter_subscriber", sub, {
            "shop_idx": self.crypto.blind_index("newsletter-shop", shop_id),
            "email_idx": self.crypto.blind_index(f"newsletter-email:{shop_id}", email),
            "confirm_idx": self.crypto.blind_index(f"newsletter-confirm:{shop_id}", sub.confirm_token),
            "unsubscribe_idx": self.crypto.blind_index(f"newsletter-unsubscribe:{shop_id}", sub.unsubscribe_token),
            "status_idx": self.crypto.blind_index(f"newsletter-status:{shop_id}", sub.status),
        })
        self._checkpoint()
        return sub

    def _find_sub_by_token(self, shop_id: str, token: str, purpose: str) -> NewsletterSubscriber | None:
        if len(token) < 20:
            return None
        shop_idx = self.crypto.blind_index("newsletter-shop", shop_id)
        token_idx = self.crypto.blind_index(f"newsletter-{purpose}:{shop_id}", token)
        prop_name = "confirm_idx" if purpose == "confirm" else "unsubscribe_idx"
        for node_id in self.db.list_node_ids(self.SUB_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("shop_idx") == shop_idx and node.properties.get(prop_name) == token_idx:
                return NewsletterSubscriber(**self.crypto.decrypt_json(node_id, node.properties["data"]))
        return None

    def confirm_subscription(self, shop_id: str, token: str) -> NewsletterSubscriber | None:
        sub = self._find_sub_by_token(shop_id, token, "confirm")
        if sub is None:
            return None
        sub.status = "confirmed"
        sub.confirmed_at = utc_now()
        sub.confirm_token = ""
        sub.updated_at = utc_now()
        self._write(self.SUB_PREFIX, sub.id, "newsletter_subscriber", sub, {
            "shop_idx": self.crypto.blind_index("newsletter-shop", shop_id),
            "email_idx": self.crypto.blind_index(f"newsletter-email:{shop_id}", sub.email),
            "confirm_idx": self.crypto.blind_index(f"newsletter-confirm:{shop_id}", "revoked:" + sub.id),
            "unsubscribe_idx": self.crypto.blind_index(f"newsletter-unsubscribe:{shop_id}", sub.unsubscribe_token),
            "status_idx": self.crypto.blind_index(f"newsletter-status:{shop_id}", sub.status),
        })
        self._checkpoint()
        return sub

    def get_subscription_for_unsubscribe(self, shop_id: str, token: str) -> NewsletterSubscriber | None:
        return self._find_sub_by_token(shop_id, token, "unsubscribe")

    def unsubscribe(self, shop_id: str, token: str) -> bool:
        sub = self._find_sub_by_token(shop_id, token, "unsubscribe")
        if sub is None:
            return False
        self.db.delete_node(self._node(self.SUB_PREFIX, sub.id))
        self._checkpoint()
        return True

    def list_confirmed_subscribers(self, shop_id: str) -> list[NewsletterSubscriber]:
        shop_idx = self.crypto.blind_index("newsletter-shop", shop_id)
        status_idx = self.crypto.blind_index(f"newsletter-status:{shop_id}", "confirmed")
        subs: list[NewsletterSubscriber] = []
        for node_id in self.db.list_node_ids(self.SUB_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("shop_idx") == shop_idx and node.properties.get("status_idx") == status_idx:
                subs.append(NewsletterSubscriber(**self.crypto.decrypt_json(node_id, node.properties["data"])))
        return subs

    def create_campaign(self, *, owner_id: str, subject: str, body: str) -> NewsletterCampaign:
        shop = self.get_shop_for_owner(owner_id)
        if shop is None:
            raise ValueError("Zuerst muss ein Shop angelegt werden")
        subject = validate_title(subject)
        body = validate_body(body)
        if not body.strip() or len(body) > 100_000:
            raise ValueError("Newsletter-Inhalt ist leer oder zu lang")
        campaign = NewsletterCampaign(
            id=uuid.uuid4().hex,
            shop_id=shop.id,
            owner_id=owner_id,
            subject=subject,
            body=body,
            status="draft",
            created_at=utc_now(),
            sent_at=None,
        )
        self._write(self.CAMPAIGN_PREFIX, campaign.id, "newsletter_campaign", campaign, {
            "shop_idx": self.crypto.blind_index("campaign-shop", shop.id),
            "owner_idx": self.crypto.blind_index("campaign-owner", owner_id),
        })
        self._checkpoint()
        return campaign

    def get_campaign(self, campaign_id: str) -> NewsletterCampaign | None:
        try:
            return self._decode(self._node(self.CAMPAIGN_PREFIX, campaign_id), NewsletterCampaign)
        except MyceliaDBError as exc:
            if "missing node" in str(exc):
                return None
            raise

    def list_campaigns(self, owner_id: str) -> list[NewsletterCampaign]:
        idx = self.crypto.blind_index("campaign-owner", owner_id)
        campaigns = self._list(self.CAMPAIGN_PREFIX, NewsletterCampaign, prop=("owner_idx", idx))
        campaigns.sort(key=lambda c: c.created_at, reverse=True)
        return campaigns

    def mark_campaign_sent(self, campaign: NewsletterCampaign, delivered: int, failed: int) -> None:
        campaign.status = "sent" if failed == 0 else "sent_with_errors"
        campaign.sent_at = utc_now()
        campaign.delivered = delivered
        campaign.failed = failed
        self._write(self.CAMPAIGN_PREFIX, campaign.id, "newsletter_campaign", campaign, {
            "shop_idx": self.crypto.blind_index("campaign-shop", campaign.shop_id),
            "owner_idx": self.crypto.blind_index("campaign-owner", campaign.owner_id),
        })
        self._checkpoint()

    # ----- privacy -----
    def export_user_data(self, user_id: str) -> dict[str, Any]:
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("Benutzer nicht gefunden")
        shop = self.get_shop_for_owner(user_id)
        own_subscriptions = []
        for node_id in self.db.list_node_ids(self.SUB_PREFIX):
            node = self.db.get_node(node_id)
            token = node.properties.get("data")
            if not token:
                continue
            sub = NewsletterSubscriber(**self.crypto.decrypt_json(node_id, token))
            # A matching email string is not identity. Only an explicit link created
            # while the account email was verified is included in account privacy data.
            if sub.account_id == user.id:
                own_subscriptions.append({
                    "shop_id": sub.shop_id,
                    "status": sub.status,
                    "consent_at": sub.consent_at,
                    "confirmed_at": sub.confirmed_at,
                })
        result: dict[str, Any] = {
            "exported_at": utc_now(),
            "privacy_version": self.PRIVACY_VERSION,
            "account": {k: v for k, v in asdict(user).items() if k != "password_hash"},
            "buyer_orders": [asdict(o) for o in self.list_orders_for_buyer(user_id)],
            "newsletter_subscriptions": own_subscriptions,
        }
        if shop:
            result["shop"] = asdict(shop)
            products = self.list_products(shop.id)
            result["products"] = [asdict(p) for p in products]
            result["product_images"] = [
                {
                    "id": image.id,
                    "product_id": image.product_id,
                    "original_name": image.original_name,
                    "mime_type": image.mime_type,
                    "content_b64": image.content_b64,
                    "sha256": image.sha256,
                    "width": image.width,
                    "height": image.height,
                    "position": image.position,
                    "created_at": image.created_at,
                }
                for product in products
                for image in self.list_product_images(product)
            ]
            result["blog_posts"] = [asdict(p) for p in self.list_blog_posts(shop.id)]
            result["newsletter_campaigns"] = [asdict(c) for c in self.list_campaigns(user_id)]
            result["shop_operational_counts"] = {
                "orders": len(self.list_orders_for_seller(user_id)),
                "confirmed_newsletter_subscribers": len(self.list_confirmed_subscribers(shop.id)),
            }
        return result

    def delete_user_data(self, user_id: str) -> dict[str, int]:
        user = self.get_user(user_id)
        if user is None:
            return {"deleted_nodes": 0}
        targets: set[str] = {self._node(self.USER_PREFIX, user_id)}
        shop = self.get_shop_for_owner(user_id)
        if shop:
            targets.add(self._node(self.SHOP_PREFIX, shop.id))
            for product in self.list_products(shop.id):
                targets.add(self._node(self.PRODUCT_PREFIX, product.id))
                for image_id in product.image_ids:
                    targets.add(self._node(self.PRODUCT_IMAGE_PREFIX, image_id))
            for post in self.list_blog_posts(shop.id):
                targets.add(self._node(self.BLOG_PREFIX, post.id))
            for campaign in self.list_campaigns(user_id):
                targets.add(self._node(self.CAMPAIGN_PREFIX, campaign.id))
            shop_idx = self.crypto.blind_index("newsletter-shop", shop.id)
            for node_id in self.db.list_node_ids(self.SUB_PREFIX):
                node = self.db.get_node(node_id)
                if node.properties.get("shop_idx") == shop_idx:
                    targets.add(node_id)
        # Hard-delete orders in which this account is buyer or seller. This is the
        # privacy-maximal CMS behaviour; deployments with statutory retention duties
        # must move legally required accounting records to a separate retention system.
        buyer_idx = self.crypto.blind_index("order-buyer", user_id)
        seller_idx = self.crypto.blind_index("order-seller", user_id)
        for node_id in self.db.list_node_ids(self.ORDER_PREFIX):
            node = self.db.get_node(node_id)
            if node.properties.get("buyer_idx") == buyer_idx or node.properties.get("seller_idx") == seller_idx:
                targets.add(node_id)
        # Newsletter ownership is an explicit verified account link, never a
        # bare equality check against an account email string.
        for node_id in self.db.list_node_ids(self.SUB_PREFIX):
            node = self.db.get_node(node_id)
            token = node.properties.get("data")
            if not token:
                continue
            sub = NewsletterSubscriber(**self.crypto.decrypt_json(node_id, token))
            if sub.account_id == user.id:
                targets.add(node_id)
        deleted = 0
        for node_id in sorted(targets):
            try:
                self.db.delete_node(node_id)
                deleted += 1
            except MyceliaDBError as exc:
                if "missing node" not in str(exc):
                    raise
        # Account privacy deletion must never cross the administrative backup
        # authority boundary. Historical backup retention is admin-only.
        self._checkpoint()
        return {"deleted_nodes": deleted, "purged_historical_backups": 0}
