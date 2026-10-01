from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_global_form_validator_is_loaded_by_both_base_templates() -> None:
    for rel in ("templates/base.html", "templates/webshop/base.html"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "js/form-validation.js" in text


def test_validator_covers_core_server_side_constraints() -> None:
    text = (ROOT / "static/js/form-validation.js").read_text(encoding="utf-8")
    for required_fragment in (
        "SLUG_RE", "USERNAME_RE", "CURRENCY_RE", "EMAIL_RE",
        "price_cents", "100000000", "stock", "10000000",
        "shipping_street", "160", "https://", "password_repeat",
        "new_password_repeat", "validateRichText", "validateFileInput",
        "PURGE BACKUPS", "RESTORE", "DELETE",
    ):
        assert required_fragment in text


def test_privacy_and_backup_confirmations_have_exact_html_constraints() -> None:
    privacy = (ROOT / "templates/webshop/privacy_center.html").read_text(encoding="utf-8")
    system = (ROOT / "templates/system.html").read_text(encoding="utf-8")
    assert 'pattern="DELETE"' in privacy
    assert 'pattern="RESTORE"' in system
    assert 'pattern="PURGE BACKUPS"' in system


def test_richtext_editor_exposes_required_and_character_limit_metadata() -> None:
    text = (ROOT / "templates/richtext/editor.html").read_text(encoding="utf-8")
    assert "data-rt-required" in text
    assert "data-rt-max-chars" in text
    assert "effective_max" in text


def test_shop_richtext_limits_match_repository_contract() -> None:
    text = (ROOT / "templates/webshop/shop_manage.html").read_text(encoding="utf-8")
    assert "'Beschreibung', false, 20000" in text
    assert "'Zahlungshinweise', false, 8000" in text
