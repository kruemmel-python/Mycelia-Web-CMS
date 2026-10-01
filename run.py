from __future__ import annotations

from waitress import serve
from cms.app import create_app
from cms.config import Settings


if __name__ == "__main__":
    settings = Settings.load()
    app = create_app(settings)
    serve(app, host=settings.host, port=settings.port, threads=8)
