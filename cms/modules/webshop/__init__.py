"""Mycelia Webshop module.

Imports are intentionally lazy so data-model tooling can inspect the repository
without importing Flask or the SMTP integration.
"""

__all__ = ["WebshopRepository", "create_webshop_blueprint"]


def __getattr__(name: str):
    if name == "WebshopRepository":
        from .repository import WebshopRepository
        return WebshopRepository
    if name == "create_webshop_blueprint":
        from .routes import create_webshop_blueprint
        return create_webshop_blueprint
    raise AttributeError(name)
