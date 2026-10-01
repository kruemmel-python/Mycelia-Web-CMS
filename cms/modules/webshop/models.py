from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class UserAccount:
    id: str
    username: str
    email: str
    display_name: str
    password_hash: str
    created_at: str
    updated_at: str
    privacy_version: str
    deleted: bool = False
    email_verified: bool = False
    email_verified_at: str | None = None


@dataclass(slots=True)
class PendingRegistration:
    id: str
    username: str
    email: str
    display_name: str
    password_hash: str
    privacy_version: str
    created_at: str


@dataclass(slots=True)
class PendingEmailChange:
    id: str
    user_id: str
    new_email: str
    created_at: str


@dataclass(slots=True)
class Shop:
    id: str
    owner_id: str
    name: str
    slug: str
    description: str
    contact_email: str
    payment_instructions: str
    created_at: str
    updated_at: str
    active: bool = True


@dataclass(slots=True)
class Product:
    id: str
    shop_id: str
    owner_id: str
    name: str
    slug: str
    description: str
    price_cents: int
    currency: str
    stock: int
    product_type: str
    created_at: str
    updated_at: str
    active: bool = True
    image_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProductImage:
    id: str
    product_id: str
    shop_id: str
    owner_id: str
    original_name: str
    mime_type: str
    content_b64: str
    sha256: str
    width: int
    height: int
    position: int
    created_at: str


@dataclass(slots=True)
class BlogPost:
    id: str
    shop_id: str
    owner_id: str
    title: str
    slug: str
    body: str
    status: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class Order:
    id: str
    shop_id: str
    seller_id: str
    buyer_id: str
    product_id: str
    product_name: str
    quantity: int
    unit_price_cents: int
    total_cents: int
    currency: str
    buyer_email: str
    shipping_address: dict[str, str] = field(default_factory=dict)
    payment_instructions: str = ""
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""
    # None marks legacy v0.7 orders whose stock was already decremented at creation.
    inventory_committed: bool | None = None


@dataclass(slots=True)
class NewsletterSubscriber:
    id: str
    shop_id: str
    email: str
    name: str
    status: str
    consent_at: str
    confirmed_at: str | None
    confirm_token: str
    unsubscribe_token: str
    source_fingerprint: str
    created_at: str
    updated_at: str
    # Set only when a verified WebCMS account explicitly owns this address.
    account_id: str | None = None


@dataclass(slots=True)
class NewsletterCampaign:
    id: str
    shop_id: str
    owner_id: str
    subject: str
    body: str
    status: str
    created_at: str
    sent_at: str | None
    delivered: int = 0
    failed: int = 0
