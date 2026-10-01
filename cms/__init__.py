from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask


def create_app(*args: Any, **kwargs: Any) -> "Flask":
    # Lazy import keeps low-level modules such as cms.db testable without
    # requiring Flask to be imported just by importing the package.
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)


__all__ = ["create_app"]
