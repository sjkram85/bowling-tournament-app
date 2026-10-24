import tomllib
from pathlib import Path

from components.hide_chrome import HIDE_CHROME_CSS, should_hide

ROOT = Path(__file__).resolve().parent.parent


def test_config_hides_toolbar_and_error_details():
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    assert cfg["client"]["toolbarMode"] == "auto"
    assert cfg["client"]["showErrorDetails"] is False


def test_css_hides_chrome_and_app_applies_it():
    for sel in ("#MainMenu", "footer", "stToolbar", "stAppDeployButton", "stStatusWidget", "viewerBadge"):
        assert sel in HIDE_CHROME_CSS
    assert "stSidebar" not in HIDE_CHROME_CSS  # sidebar/login must stay usable
    assert "hide_streamlit_chrome()" in (ROOT / "app.py").read_text()


def test_admin_sees_chrome_td_and_public_do_not():
    admin, td = {"role": "admin"}, {"role": "td"}
    assert not should_hide(admin, None)
    assert should_hide(td, None)
    assert should_hide(None, None)
    for mode in ("kiosk", "score", "bowler"):
        assert should_hide(admin, mode) and should_hide(td, mode) and should_hide(None, mode)
