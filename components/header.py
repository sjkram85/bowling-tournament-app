"""Top navigation header."""

from html import escape
from pathlib import Path

import streamlit as st

from modules.constants import CENTERS

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHUSBC_LOGO = ASSETS_DIR / "CHUSBC.jpg"
FALLBACK_LOGO = ASSETS_DIR / "maryland-flag-800.jpg"


def resolve_host_logo(host_center_code: str | None, logo_path: str | None = None) -> Path:
    """Pick a tournament's custom logo, else the center's logo_file, else a fallback."""
    logo_file = CENTERS.get(host_center_code or "", {}).get("logo_file")
    for candidate in (Path(logo_path) if logo_path else None, ASSETS_DIR / logo_file if logo_file else None):
        if candidate and candidate.is_file():
            return candidate
    return FALLBACK_LOGO


def render_header(
    tournament_name: str,
    host_center_code: str | None,
    active_game: int | None = None,
    total_games: int | None = None,
    logo_path: str | None = None,
) -> None:
    """Render CHUSBC logo (left); name, center info and game badge (center); host logo (right)."""
    center_info = CENTERS.get(host_center_code or "", {})
    left, center, right = st.columns([1, 3, 1], vertical_alignment="center")
    with left:
        st.image(str(CHUSBC_LOGO), width=96)
    with center:
        badge = ""
        if active_game:
            label = f"Game {active_game} of {total_games}" if total_games else f"Game {active_game}"
            badge = f'<span class="ptcc-game-badge">{escape(label)}</span>'
        info = " &middot; ".join(
            escape(str(part)) for part in (center_info.get("name"), center_info.get("address")) if part
        )
        st.markdown(
            f'<div class="ptcc-header-title">{escape(tournament_name)}</div>'
            f'<div style="text-align:center;color:#64748B;font-size:0.9rem">{info}</div>'
            f'<div style="text-align:center;margin-top:6px">{badge}</div>',
            unsafe_allow_html=True,
        )
    with right:
        _, logo_col = st.columns([1, 2])
        with logo_col:
            st.image(str(resolve_host_logo(host_center_code, logo_path)), width=96)
