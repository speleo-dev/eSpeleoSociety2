from ess.web.templates import templates


def test_all_templates_compile():
    names = templates.env.list_templates()
    assert names
    for name in names:
        templates.env.get_template(name)


def test_static_assets_are_local():
    """Tabler, its icons and HTMX are served from /static (no CDN)."""
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent / "ess"
    html = (base / "templates" / "base.html").read_text()
    assert "/static/vendor/tabler/css/tabler.min.css" in html and "/static/vendor/htmx/htmx.min.js" in html
    assert "cdn." not in html and "unpkg" not in html
    for path in ("vendor/tabler/css/tabler.min.css", "vendor/tabler/js/tabler.min.js", "vendor/htmx/htmx.min.js", "ui.js"):
        assert (base / "static" / path).is_file()


def test_ui_script_respects_cancelled_submit_and_downloads():
    """Cancelled confirm dialogs and file downloads must not leave the form locked."""
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "ess" / "static" / "ui.js").read_text()
    assert "event.defaultPrevented" in js and "data-download" in js


def test_status_icons_are_not_shrunk_by_tabler():
    """Tabler sets img {max-width: 100%}; in the narrow icons column that made the icons invisible."""
    import re
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "ess" / "templates" / "base.html").read_text()
    rule = re.search(r"img\.icon \{(.*?)\}", css, re.S).group(1)
    assert "max-width: none" in rule
