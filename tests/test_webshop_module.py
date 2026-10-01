from __future__ import annotations

import hashlib
import hmac
import json
import io

from PIL import Image
from cms.db import MyceliaDBError, Node
from cms.modules.webshop.media import sanitize_product_image
from cms.modules.webshop.repository import WebshopRepository


class FakeCrypto:
    def __init__(self) -> None:
        self.key = b"test-key"

    def encrypt_json(self, record_id: str, value: dict) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def decrypt_json(self, record_id: str, token: str) -> dict:
        return json.loads(token)

    def blind_index(self, namespace: str, value: str) -> str:
        normalized = " ".join(value.casefold().split()).encode()
        return hmac.new(self.key, namespace.encode() + b"\0" + normalized, hashlib.sha256).hexdigest()


class FakeDB:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, str]] = {}

    def list_node_ids(self, prefix: str = "") -> list[str]:
        return [node_id for node_id in self.nodes if node_id.startswith(prefix)]

    def get_node(self, node_id: str) -> Node:
        if node_id not in self.nodes:
            raise MyceliaDBError("ERR missing node")
        return Node(node_id, dict(self.nodes[node_id]))

    def set_property(self, node_id: str, key: str, value: str) -> None:
        self.nodes.setdefault(node_id, {})[key] = value

    def delete_node(self, node_id: str) -> str:
        if node_id not in self.nodes:
            raise MyceliaDBError("ERR missing node")
        del self.nodes[node_id]
        return f"OK ERASED {node_id}"


class FakeBackups:
    def __init__(self) -> None:
        self.checkpoints = 0
        self.purges = 0

    def save_checkpoint(self) -> str:
        self.checkpoints += 1
        return "OK"

    def purge_historical_backups(self) -> int:
        self.purges += 1
        return 2


def make_repo() -> WebshopRepository:
    return WebshopRepository(FakeDB(), FakeCrypto(), FakeBackups())


def test_user_shop_product_blog_and_export_roundtrip() -> None:
    repo = make_repo()
    user = repo.register_user(
        username="ralf",
        email="ralf@example.test",
        display_name="Ralf",
        password="eine-sehr-lange-passphrase",
        privacy_ack=True,
        email_verified_proof=True,
    )
    assert repo.verify_user("ralf", "eine-sehr-lange-passphrase").id == user.id

    shop = repo.save_shop(
        owner_id=user.id,
        name="Klanggeist Shop",
        slug="klanggeist",
        description="Eigener Shop",
        contact_email=user.email,
        payment_instructions="Überweisung nach Bestellung",
    )
    product = repo.save_product(
        owner_id=user.id,
        product_id=None,
        name="Album",
        slug="album",
        description="Digitales Album",
        price_cents=2000,
        currency="EUR",
        stock=100,
        product_type="digital",
        active=True,
    )
    post = repo.save_blog_post(
        owner_id=user.id,
        post_id=None,
        title="Neuigkeiten",
        slug="neuigkeiten",
        body="Willkommen im Blog.",
        status="published",
    )

    export = repo.export_user_data(user.id)
    assert export["account"]["email"] == user.email
    assert "password_hash" not in export["account"]
    assert export["shop"]["id"] == shop.id
    assert export["products"][0]["id"] == product.id
    assert export["blog_posts"][0]["id"] == post.id


def test_privacy_hard_delete_does_not_cross_admin_backup_boundary() -> None:
    repo = make_repo()
    user = repo.register_user(
        username="privacyuser",
        email="privacy@example.test",
        display_name="Privacy User",
        password="noch-eine-lange-passphrase",
        privacy_ack=True,
        email_verified_proof=True,
    )
    shop = repo.save_shop(
        owner_id=user.id,
        name="Privacy Shop",
        slug="privacy-shop",
        description="Test",
        contact_email=user.email,
        payment_instructions="",
    )
    repo.save_product(
        owner_id=user.id,
        product_id=None,
        name="Produkt",
        slug="produkt",
        description="Test",
        price_cents=100,
        currency="EUR",
        stock=1,
        product_type="physical",
        active=True,
    )
    result = repo.delete_user_data(user.id)
    assert result["deleted_nodes"] >= 3
    assert result["purged_historical_backups"] == 0
    assert repo.backups.purges == 0
    assert repo.get_user(user.id) is None
    assert repo.get_shop_for_owner(user.id) is None


def test_newsletter_requires_confirmation_before_confirmed_list() -> None:
    repo = make_repo()
    user = repo.register_user(
        username="shopowner",
        email="owner@example.test",
        display_name="Owner",
        password="lange-passphrase-fuer-owner",
        privacy_ack=True,
        email_verified_proof=True,
    )
    shop = repo.save_shop(
        owner_id=user.id,
        name="Newsletter Shop",
        slug="newsletter-shop",
        description="Test",
        contact_email=user.email,
        payment_instructions="",
    )
    sub = repo.create_or_refresh_subscription(
        shop_id=shop.id,
        email="subscriber@example.test",
        name="Subscriber",
        source="127.0.0.1",
    )
    assert sub.status == "pending"
    assert repo.list_confirmed_subscribers(shop.id) == []
    confirmed = repo.confirm_subscription(shop.id, sub.confirm_token)
    assert confirmed is not None and confirmed.status == "confirmed"
    assert len(repo.list_confirmed_subscribers(shop.id)) == 1
    assert repo.unsubscribe(shop.id, confirmed.unsubscribe_token)
    assert repo.list_confirmed_subscribers(shop.id) == []


class _Upload:
    def __init__(self, data: bytes, filename: str) -> None:
        self._stream = io.BytesIO(data)
        self.filename = filename
    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def _png_upload(name: str = "photo.png") -> _Upload:
    buf = io.BytesIO()
    Image.new("RGBA", (64, 48), (20, 120, 200, 180)).save(buf, format="PNG")
    return _Upload(buf.getvalue(), name)


def test_product_gallery_is_sanitized_encrypted_and_deleted_with_product() -> None:
    repo = make_repo()
    user = repo.register_user(
        username="galleryuser",
        email="gallery@example.test",
        display_name="Gallery User",
        password="gallery-passphrase-sehr-lang",
        privacy_ack=True,
        email_verified_proof=True,
    )
    shop = repo.save_shop(
        owner_id=user.id,
        name="Gallery Shop",
        slug="gallery-shop",
        description="Test",
        contact_email=user.email,
        payment_instructions="",
    )
    clean = sanitize_product_image(_png_upload())
    assert clean.mime_type == "image/jpeg"
    assert clean.content.startswith(b"\xff\xd8")
    product = repo.save_product(
        owner_id=user.id,
        product_id=None,
        name="Bildprodukt",
        slug="bildprodukt",
        description="Mit Galerie",
        price_cents=100,
        currency="EUR",
        stock=1,
        product_type="physical",
        active=True,
        new_images=[clean],
    )
    assert len(product.image_ids) == 1
    image = repo.get_product_image(product.image_ids[0])
    assert image is not None
    assert repo.product_image_bytes(image).startswith(b"\xff\xd8")
    assert image.content_b64 not in repo.db.nodes[f"shop:product:{product.id}"]["data"]
    repo.delete_product(user.id, product.id)
    assert repo.get_product_image(image.id) is None
    assert repo.get_product(product.id) is None


def test_product_gallery_max_three_images() -> None:
    repo = make_repo()
    user = repo.register_user(
        username="gallerymax",
        email="gallerymax@example.test",
        display_name="Gallery Max",
        password="gallery-passphrase-sehr-lang",
        privacy_ack=True,
        email_verified_proof=True,
    )
    repo.save_shop(
        owner_id=user.id,
        name="Gallery Max Shop",
        slug="gallery-max-shop",
        description="Test",
        contact_email=user.email,
        payment_instructions="",
    )
    images = [sanitize_product_image(_png_upload(f"{i}.png")) for i in range(4)]
    try:
        repo.save_product(
            owner_id=user.id,
            product_id=None,
            name="Zu viele Bilder",
            slug="zu-viele-bilder",
            description="Test",
            price_cents=100,
            currency="EUR",
            stock=1,
            product_type="physical",
            active=True,
            new_images=images,
        )
    except ValueError as exc:
        assert "maximal drei" in str(exc)
    else:
        raise AssertionError("Vier Produktbilder wurden unerwartet akzeptiert")


def test_pending_registration_requires_email_token_before_account_exists() -> None:
    repo = make_repo()
    pending, token = repo.create_pending_registration(
        username="verifyme",
        email="verifyme@example.test",
        display_name="Verify Me",
        password="verification-passphrase-long",
        privacy_ack=True,
    )
    assert repo.find_user_by_email("verifyme@example.test") is None
    assert pending.email == "verifyme@example.test"
    assert repo.confirm_pending_registration("wrong-token-that-is-long-enough") is None
    user = repo.confirm_pending_registration(token)
    assert user is not None
    assert user.email_verified is True
    assert repo.find_user_by_email("verifyme@example.test").id == user.id


def test_newsletter_privacy_link_requires_explicit_verified_account_id() -> None:
    repo = make_repo()
    owner = repo.register_user(
        username="nlowner", email="nlowner@example.test", display_name="Owner",
        password="owner-password-very-long", privacy_ack=True,
        email_verified_proof=True,
    )
    shop = repo.save_shop(
        owner_id=owner.id, name="NL", slug="nl-identity", description="x",
        contact_email=owner.email, payment_instructions="",
    )
    victim_sub = repo.create_or_refresh_subscription(
        shop_id=shop.id, email="shared@example.test", name="Victim", source="127.0.0.1",
    )
    repo.confirm_subscription(shop.id, victim_sub.confirm_token)
    account = repo.register_user(
        username="sameemail", email="shared@example.test", display_name="Account",
        password="account-password-very-long", privacy_ack=True,
        email_verified_proof=True,
    )
    exported = repo.export_user_data(account.id)
    assert exported["newsletter_subscriptions"] == []
    result = repo.delete_user_data(account.id)
    assert result["deleted_nodes"] >= 1
    assert repo.find_subscriber_by_email(shop.id, "shared@example.test") is not None


def test_pending_order_does_not_consume_inventory_and_paid_transition_is_atomic() -> None:
    repo = make_repo()
    seller = repo.register_user(
        username="sellerx", email="sellerx@example.test", display_name="Seller",
        password="seller-password-very-long", privacy_ack=True,
        email_verified_proof=True,
    )
    buyer = repo.register_user(
        username="buyerx", email="buyerx@example.test", display_name="Buyer",
        password="buyer-password-very-long", privacy_ack=True,
        email_verified_proof=True,
    )
    repo.save_shop(
        owner_id=seller.id, name="Orders", slug="orders-safe", description="x",
        contact_email=seller.email, payment_instructions="pay later",
    )
    product = repo.save_product(
        owner_id=seller.id, product_id=None, name="Stock", slug="stock", description="x",
        price_cents=1000, currency="EUR", stock=5, product_type="digital", active=True,
    )
    order = repo.create_order(buyer=buyer, product=product, quantity=3, shipping_address={})
    assert order.status == "pending"
    assert order.inventory_committed is False
    assert repo.get_product(product.id).stock == 5
    paid = repo.update_order_status(seller_id=seller.id, order_id=order.id, status="paid")
    assert paid.inventory_committed is True
    assert repo.get_product(product.id).stock == 2
    cancelled = repo.update_order_status(seller_id=seller.id, order_id=order.id, status="cancelled")
    assert cancelled.inventory_committed is False
    assert repo.get_product(product.id).stock == 5
    try:
        repo.update_order_status(seller_id=seller.id, order_id=order.id, status="shipped")
    except ValueError as exc:
        assert "Statusübergang" in str(exc)
    else:
        raise AssertionError("cancelled -> shipped wurde unerwartet akzeptiert")


def test_verified_claimant_can_reclaim_email_from_legacy_unverified_account() -> None:
    repo = make_repo()
    legacy = repo.register_user(
        username="legacyuser", email="claimed@example.test", display_name="Legacy",
        password="legacy-password-very-long", privacy_ack=True,
        email_verified_proof=True,
    )
    # Simulate a persisted pre-v0.8 account: address was never challenged.
    legacy.email_verified = False
    legacy.email_verified_at = None
    repo._write(repo.USER_PREFIX, legacy.id, "user", legacy, {
        "username_idx": repo.crypto.blind_index("user-username", legacy.username),
        "email_idx": repo.crypto.blind_index("user-email", legacy.email),
    })
    pending, token = repo.create_pending_registration(
        username="realowner", email="claimed@example.test", display_name="Real Owner",
        password="real-owner-password-very-long", privacy_ack=True,
    )
    claimed = repo.confirm_pending_registration(token)
    assert claimed is not None and claimed.email_verified
    assert claimed.email == "claimed@example.test"
    legacy_after = repo.get_user(legacy.id)
    assert legacy_after is not None
    assert legacy_after.email.endswith("@account.invalid")
    assert legacy_after.email_verified is False


def test_direct_registration_requires_explicit_verified_email_proof() -> None:
    repo = make_repo()
    try:
        repo.register_user(
            username="noproof", email="noproof@example.test", display_name="No Proof",
            password="no-proof-password-very-long", privacy_ack=True,
        )
    except ValueError as exc:
        assert "verifizierten E-Mail-Besitz" in str(exc)
    else:
        raise AssertionError("Direkte Kontoanlage ohne E-Mail-Nachweis wurde akzeptiert")


def test_profile_repository_rejects_direct_email_rebinding() -> None:
    repo = make_repo()
    user = repo.register_user(
        username="profilemail", email="old@example.test", display_name="Profile",
        password="profile-password-very-long", privacy_ack=True, email_verified_proof=True,
    )
    try:
        repo.update_user_profile(
            user_id=user.id, display_name="Profile", email="new@example.test", new_password=None,
        )
    except ValueError as exc:
        assert "Verifikations-Workflow" in str(exc)
    else:
        raise AssertionError("Direkte E-Mail-Änderung ohne Challenge wurde akzeptiert")
