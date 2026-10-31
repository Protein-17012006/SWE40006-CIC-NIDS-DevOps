from streamlit.testing.v1 import AppTest


def _banner_app(env, version):
    from app.components.layout import env_banner
    from app.config import load_settings

    env_banner(load_settings({"APP_ENV": env, "APP_VERSION": version}))


def test_banner_shown_outside_production():
    at = AppTest.from_function(_banner_app, kwargs={"env": "staging", "version": "7c41e0b"}).run()
    assert at.warning[0].value == "STAGING environment · version 7c41e0b · not production data"


def test_no_banner_in_production():
    at = AppTest.from_function(
        _banner_app, kwargs={"env": "production", "version": "7c41e0b"}
    ).run()
    assert not at.exception
    assert len(at.warning) == 0
