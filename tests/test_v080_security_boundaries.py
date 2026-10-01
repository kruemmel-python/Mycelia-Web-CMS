from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_account_delete_cannot_purge_admin_backups() -> None:
    source = (ROOT / "cms/modules/webshop/repository.py").read_text(encoding="utf-8")
    block = source[source.index("def delete_user_data"):]
    block = block[: block.index("\n    def ", 10) if "\n    def " in block[10:] else len(block)]
    assert "purge_historical_backups" not in block
    app = (ROOT / "cms/app.py").read_text(encoding="utf-8")
    assert 'def system_backup_purge' in app
    assert '@admin_required' in app[app.index('@app.post("/cms/system/backups/purge")'):app.index('def system_backup_purge')]


def test_proxy_trust_is_explicit_and_bounded() -> None:
    cfg = (ROOT / "cms/config.py").read_text(encoding="utf-8")
    app = (ROOT / "cms/app.py").read_text(encoding="utf-8")
    assert 'MYCELIA_CMS_TRUSTED_PROXY_HOPS' in cfg
    assert '0 <= trusted_proxy_hops <= 2' in cfg
    assert 'ProxyFix' in app
    assert 'if cfg.trusted_proxy_hops' in app


def test_registration_does_not_reset_abuse_budget_and_login_only_resets_account_budget() -> None:
    src = (ROOT / "cms/modules/webshop/routes.py").read_text(encoding="utf-8")
    register = src[src.index('def account_register'):src.index('def account_verify_email')]
    assert 'limiter.reset' not in register
    login = src[src.index('def account_login'):src.index('@bp.post("/account/logout")')]
    assert 'user-login-ip:' in login
    assert 'user-login-account:' in login
    assert 'limiter.reset(account_key)' in login
    assert 'limiter.reset(ip_key)' not in login
