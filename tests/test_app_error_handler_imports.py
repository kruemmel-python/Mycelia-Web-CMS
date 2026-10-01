from __future__ import annotations

import ast
from pathlib import Path


def test_app_imports_mailer_error_for_global_handler() -> None:
    source = Path("cms/app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "modules.webshop.mailer"
        for alias in node.names
    }
    # Relative imports retain level separately; module text is still this value.
    assert "MailerError" in imported
    assert "@app.errorhandler(MailerError)" in source
