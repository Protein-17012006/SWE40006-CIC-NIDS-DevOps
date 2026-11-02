from pathlib import Path

from streamlit.testing.v1 import AppTest

MAIN = str(Path(__file__).resolve().parents[2] / "app" / "main.py")


def test_no_legacy_pages_directory():
    """Streamlit serves a pages/ folder beside main.py as an old-style multipage app on a
    server's first deep link, bypassing st.navigation and the banner; views live elsewhere."""
    assert not (Path(MAIN).parent / "pages").exists()


def test_shell_runs_and_shows_banner(settings_env, clear_caches):
    at = AppTest.from_file(MAIN, default_timeout=30).run()
    assert not at.exception
    assert at.warning[0].value == "TEST environment · version abc1234 · not production data"


def test_shell_reports_invalid_app_env(settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("APP_ENV", "prod")
    clear_caches()
    at = AppTest.from_file(MAIN, default_timeout=30).run()
    assert "APP_ENV must be one of" in at.error[0].value


def test_no_view_shadows_a_package():
    """AppTest puts app/views first on sys.path when it runs a page, so a view named like a
    package (pipeline) would be imported in the package's place."""
    root = Path(MAIN).parents[1]
    views = {path.stem for path in (root / "app" / "views").glob("*.py")}
    packages = {path.parent.name for path in root.glob("*/__init__.py")}
    assert not views & packages
