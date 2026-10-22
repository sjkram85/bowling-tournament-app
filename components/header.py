"""Carded top banner: CHUSBC branding, tournament info, host center logo."""

import base64
from functools import lru_cache
from html import escape
from pathlib import Path

import streamlit as st

from modules.constants import CENTERS

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHUSBC_LOGO = ASSETS_DIR / "CHUSBC.jpg"
LOGO_HEIGHT = 65


@lru_cache(maxsize=16)
def _logo_tag(path: str, height: int) -> str:
    """Inline <img> at a fixed pixel height on a white plate, so the logo reads on a dark card."""
    file = Path(path)
    mime = "image/png" if file.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(file.read_bytes()).decode()
    return (
        f'<span class="ptcc-logo-plate"><img src="data:{mime};base64,{data}" '
        f'style="height:{height}px;width:auto;display:block" alt=""></span>'
    )


def resolve_host_logo(host_center_code: str | None, logo_path: str | None = None) -> Path | None:
    """A tournament's custom logo, else the center's logo_file; None if neither exists."""
    logo_file = CENTERS.get(host_center_code or "", {}).get("logo_file")
    for candidate in (Path(logo_path) if logo_path else None, ASSETS_DIR / logo_file if logo_file else None):
        if candidate and candidate.is_file():
            return candidate
    return None


def render_header(
    tournament_name: str,
    host_center_code: str | None,
    active_game: int | None = None,
    total_games: int | None = None,
    logo_path: str | None = None,
    squad_format: str | None = None,
) -> None:
    """Render the banner: branding (left), tournament details (center), host center (right)."""
    center_info = CENTERS.get(host_center_code or "", {})
    with st.container(key="ptcc_header"):
        left, center, right = st.columns([3, 5, 2], vertical_alignment="center")
        with left:
            brand = (
                _logo_tag(str(CHUSBC_LOGO), LOGO_HEIGHT)
                if CHUSBC_LOGO.is_file()
                else ""
            )
            st.markdown(
                '<div style="display:flex;align-items:center;gap:14px">'
                f"{brand}"
                '<div class="ptcc-brand">Cecil Harford USBC'
                "<small>Prism Tournament Control Center</small></div></div>",
                unsafe_allow_html=True,
            )
        with center:
            badges = []
            if squad_format:
                badges.append(f'<span class="ptcc-pill ptcc-pill-amber">{escape(squad_format)}</span>')
            if active_game:
                label = f"Game {active_game} of {total_games}" if total_games else f"Game {active_game}"
                badges.append(f'<span class="ptcc-game-badge">{escape(label)}</span>')
            meta = " &middot; ".join(
                escape(str(part)) for part in (center_info.get("name"), center_info.get("address")) if part
            )
            st.markdown(
                f'<div class="ptcc-header-title">{escape(tournament_name)}</div>'
                f'<div style="text-align:center;margin-top:8px">{" ".join(badges)}</div>'
                f'<div class="ptcc-header-meta">{meta}</div>',
                unsafe_allow_html=True,
            )
        with right:
            logo = resolve_host_logo(host_center_code, logo_path)
            content = (
                _logo_tag(str(logo), LOGO_HEIGHT)
                if logo
                else f'<span class="ptcc-center-badge">{escape(host_center_code or "Host")}</span>'
            )
            st.markdown(f'<div style="text-align:right">{content}</div>', unsafe_allow_html=True)
