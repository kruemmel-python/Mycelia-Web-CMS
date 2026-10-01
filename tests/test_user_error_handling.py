from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shop_uploads_are_inside_validation_boundary() -> None:
    source = (ROOT / "cms/modules/webshop/routes.py").read_text(encoding="utf-8")
    block = source[source.index('def shop_manage(user):'):source.index('@bp.get("/account/shop/products")')]
    assert 'logo = single_image_upload("logo_image")' in block
    assert 'banner = single_image_upload("banner_image")' in block
    assert 'except (ValueError, PermissionError) as exc:' in block
    assert block.index('logo = single_image_upload("logo_image")') < block.index('except (ValueError, PermissionError) as exc:')


def test_global_expected_input_error_handlers_exist() -> None:
    source = (ROOT / "cms/app.py").read_text(encoding="utf-8")
    for handler in (
        '@app.errorhandler(ValueError)',
        '@app.errorhandler(PermissionError)',
        '@app.errorhandler(MailerError)',
        '@app.errorhandler(RequestEntityTooLarge)',
        '@app.errorhandler(BadRequest)',
        '@app.errorhandler(TooManyRequests)',
        '@app.errorhandler(InternalServerError)',
    ):
        assert handler in source


def test_image_uploads_have_client_side_size_guards() -> None:
    html = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "templates").rglob("*.html"))
    image_inputs = [chunk for chunk in html.split("<input") if 'type="file"' in chunk and 'image/' in chunk]
    assert image_inputs
    assert all('data-max-bytes="280000"' in chunk for chunk in image_inputs)


def test_validation_script_is_loaded_in_both_base_templates() -> None:
    for relative in ("templates/base.html", "templates/webshop/base.html"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "js/form-validation.js" in source
        assert 'role="alert"' in source
