from ess.web.templates import templates


def test_all_templates_compile():
    names = templates.env.list_templates()
    assert names
    for name in names:
        templates.env.get_template(name)
