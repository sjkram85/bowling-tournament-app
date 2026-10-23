"""Carded top banner: CHUSBC branding, tournament info, dynamic host center branding."""

import base64
from functools import lru_cache
from html import escape
from pathlib import Path

import streamlit as st

from modules.constants import CENTERS
from modules.db_state import get_connection

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHUSBC_LOGO = ASSETS_DIR / "CHUSBC.jpg"
LOGO_HEIGHT = 60


@lru_cache(maxsize=16)
def _logo_tag(path: str, height: int = LOGO_HEIGHT) -> str:
    """Inline <img> at a fixed pixel height on a clean white plate."""
    file = Path(path)
    if not file.is_file():
        return ""
    mime = "image/png" if file.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(file.read_bytes()).decode()
    return (
        f'<span class="ptcc-logo-plate" style="background:#FFFFFF; padding:4px 8px; border-radius:6px; display:inline-flex; align-items:center; box-shadow:0 2px 6px rgba(0,0,0,0.3);">'
        f'<img src="data:{mime};base64,{data}" style="height:{height}px; width:auto; display:block;" alt="">'
        f'</span>'
    )


def resolve_host_logo(host_center_code: str | None, logo_path: str | None = None) -> Path | None:
    """Resolve a tournament's custom logo, else the center's logo_file; None if neither exists."""
    logo_file = CENTERS.get(host_center_code or "", {}).get("logo_file")
    for candidate in (Path(logo_path) if logo_path else None, ASSETS_DIR / logo_file if logo_file else None):
        if candidate and candidate.is_file():
            return candidate
    return None


def _get_active_tournament_summary() -> dict | None:
    """Lightweight query to retrieve the active tournament title and host center."""
    conn = get_connection()
    try:
        t_id = st.session_state.get("active_tournament_id")
        if t_id:
            row = conn.execute(
                "SELECT name, host_center, squad_format, game_count FROM tournaments WHERE id = ?",
                (t_id,),
            ).fetchone()
            if row:
                return dict(row)
        row = conn.execute(
            "SELECT name, host_center, squad_format, game_count FROM tournaments WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def render_desk_topbar(user: dict) -> None:
    """
    Render persistent dynamic branding topbar across all desk management views.
    Left: CHUSBC Sanction Seal
    Center: Active Tournament / Operational Status
    Right: Authenticated User Affiliated Center Brand Badge
    """
    user_affiliation = user.get("center_affiliation") or "CHUSBC"
    affil_code = "CHUSBC"
    for code in ("FHL", "HL", "APG", "CHUSBC"):
        if code in user_affiliation.upper():
            affil_code = code
            break

    center_meta = CENTERS.get(affil_code, CENTERS["CHUSBC"])
    center_logo_file = center_meta.get("logo_file")
    center_logo_path = ASSETS_DIR / center_logo_file if center_logo_file else None

    tourney = _get_active_tournament_summary()

    with st.container():
        st.markdown(
            """
            <style>
            .ptcc-topbar-container {
                background: linear-gradient(90deg, #0B132B 0%, #1E293B 50%, #0B132B 100%);
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 10px 16px;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                box-shadow: 0 4px 14px rgba(0,0,0,0.35);
            }
            .ptcc-brand-title {
                color: #F8FAFC;
                font-size: 16px;
                font-weight: 800;
                letter-spacing: -0.3px;
                line-height: 1.2;
            }
            .ptcc-brand-sub {
                color: #94A3B8;
                font-size: 12px;
                font-weight: 500;
            }
            .ptcc-center-label {
                color: #E2E8F0;
                font-size: 13px;
                font-weight: 700;
                margin-bottom: 2px;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        col_l, col_c, col_r = st.columns([3, 4, 3], vertical_alignment="center")

        # LEFT: Official CHUSBC Seal & System Identity
        with col_l:
            seal_markup = _logo_tag(str(CHUSBC_LOGO), height=46) if CHUSBC_LOGO.is_file() else "🎳"
            st.markdown(
                f"""
                <div style="display:flex; align-items:center; gap:12px;">
                    {seal_markup}
                    <div>
                        <div class="ptcc-brand-title">Cecil Harford USBC</div>
                        <div class="ptcc-brand-sub">Prism Tournament Control Center</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # CENTER: Active Event Status
        with col_c:
            if tourney:
                st.markdown(
                    f"""
                    <div style="text-align:center;">
                        <span style="background:#064E3B; color:#6EE7B7; font-size:10px; font-weight:800; padding:2px 8px; border-radius:999px; text-transform:uppercase;">
                            ACTIVE SQUAD: {escape(tourney['squad_format'])}
                        </span>
                        <div style="color:#FFFFFF; font-weight:700; font-size:14px; margin-top:2px;">
                            {escape(tourney['name'])}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
                    <div style="text-align:center;">
                        <span style="background:#1E293B; color:#94A3B8; font-size:11px; font-weight:600; padding:3px 10px; border-radius:999px; border:1px solid #475569;">
                            DESK OPERATIONS STANDBY
                        </span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # RIGHT: Dynamic User Affiliated Center Branding
        with col_r:
            if center_logo_path and center_logo_path.is_file():
                center_tag = _logo_tag(str(center_logo_path), height=44)
            else:
                center_tag = f'<span style="background:#0F172A; border:1px solid #475569; color:#F8FAFC; padding:4px 10px; border-radius:6px; font-weight:700; font-size:12px;">{escape(affil_code)}</span>'

            st.markdown(
                f"""
                <div style="display:flex; align-items:center; justify-content:flex-end; gap:10px;">
                    <div style="text-align:right;">
                        <div class="ptcc-center-label">{escape(center_meta['name'])}</div>
                        <span style="color:#38BDF8; font-size:11px; font-weight:700;">AFFILIATED DESK</span>
                    </div>
                    {center_tag}
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)


def render_header(
    tournament_name: str,
    host_center_code: str | None,
    active_game: int | None = None,
    total_games: int | None = None,
    logo_path: str | None = None,
    squad_format: str | None = None,
) -> None:
    """Render the concourse / kiosk banner: branding (left), tournament details (center), host center (right)."""
    center_info = CENTERS.get(host_center_code or "", {})
    with st.container(key="ptcc_header"):
        left, center, right = st.columns([3, 5, 2], vertical_alignment="center")
        with left:
            brand = _logo_tag(str(CHUSBC_LOGO), LOGO_HEIGHT) if CHUSBC_LOGO.is_file() else ""
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