import tomllib
from pathlib import Path

from components.hide_chrome import HIDE_CHROME_CSS

ROOT = Path(__file__).resolve().parent.parent


def test_config_hides_toolbar_and_error_details():
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    assert cfg["client"]["toolbarMode"] in ("viewer", "minimal")
    assert cfg["client"]["showErrorDetails"] is False


def test_css_hides_chrome_and_app_applies_it():
    for sel in ("#MainMenu", "footer", "stToolbar", "stAppDeployButton", "stStatusWidget", "viewerBadge"):
        assert sel in HIDE_CHROME_CSS
    assert "stSidebar" not in HIDE_CHROME_CSS  # sidebar/login must stay usable
    assert "hide_streamlit_chrome()" in (ROOT / "app.py").read_text()
