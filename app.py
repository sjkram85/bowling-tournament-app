"""Prism Tournament Control Center entrypoint."""

from html import escape

import streamlit as st

st.set_page_config(page_title="Prism Tournament Control Center", layout="wide")

from components.about_dialog import show_about_dialog
from components.header import CHUSBC_LOGO, _logo_tag
from components.styles import apply_clean_theme
from modules import auth
from modules.constants import CENTERS
from modules.db_state import init_db
from views.bowler_portal import render_bowler_portal
from views.hubs.active_squad import render_active_squad
from views.hubs.archive_vault import render_archive_vault
from views.hubs.finals_close import render_finals_close
from views.hubs.staff_accounts import render_staff_accounts
from views.intake_gateway import render_intake_gateway
from views.kiosk import render_kiosk
from views.mobile_scoring import render_mobile_scoring

init_db()
apply_clean_theme()

PUBLIC_MODES = {
    "score": render_mobile_scoring,
    "bowler": render_bowler_portal,
    "kiosk": render_kiosk,
}


def _initials(name: str) -> str:
    parts = [p for p in name.replace("_", " ").split() if p]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def _sidebar_brand() -> None:
    seal = _logo_tag(str(CHUSBC_LOGO), 48) if CHUSBC_LOGO.is_file() else ""
    st.sidebar.markdown(
        f'<div class="ptcc-side-brand">{seal}<div><div class="ptcc-side-title">PTCC</div>'
        '<span class="ptcc-side-badge">Tournament Control</span></div></div>',
        unsafe_allow_html=True,
    )


def _sidebar_identity(user: dict) -> None:
    is_admin = user["role"] == "admin"
    role_label, role_class = ("ADMIN", "admin") if is_admin else ("DIRECTOR", "td")
    center = CENTERS.get(user.get("center_affiliation") or "", {}).get("name") or user.get("center_affiliation") or ""
    with st.sidebar.container(key="side_identity"):
        st.markdown(
            f'<div class="ptcc-id-row"><div class="ptcc-avatar">{escape(_initials(user["display_name"]))}</div>'
            f'<div><div class="ptcc-id-name">{escape(user["display_name"])}</div>'
            f'<span class="ptcc-role-pill ptcc-role-{role_class}">{role_label}</span></div></div>'
            f'<div class="ptcc-id-center">{escape(center)}</div>',
            unsafe_allow_html=True,
        )
        about, sign_out = st.columns(2)
        if about.button("About", key="side_about", width="stretch"):
            show_about_dialog()
        if sign_out.button("Sign Out", key="side_signout", width="stretch"):
            auth.logout()
            st.rerun()


def render_desk() -> None:
    user = auth.require_login()
    if user is None:
        return
    operations = [
        st.Page(render_intake_gateway, title="Intake Gateway", icon="📥", url_path="intake", default=True),
        st.Page(render_active_squad, title="Active Squad Hub", icon="🎳", url_path="squad"),
        st.Page(render_finals_close, title="Finals Closeout", icon="🏆", url_path="finals"),
    ]
    management = [st.Page(render_archive_vault, title="Historical Archive Vault", icon="🗄️", url_path="archive")]
    if auth.is_admin():
        management.append(st.Page(render_staff_accounts, title="Staff Accounts", icon="👥", url_path="staff"))
    page = st.navigation(operations + management, position="hidden")

    _sidebar_brand()
    for heading, items in (("OPERATIONS", operations), ("MANAGEMENT", management)):
        st.sidebar.markdown(f'<div class="ptcc-nav-heading">{heading}</div>', unsafe_allow_html=True)
        for item in items:
            state = "active" if item.url_path == page.url_path else "idle"
            with st.sidebar.container(key=f"nav_{state}_{item.url_path}"):
                st.page_link(item, width="stretch")
    _sidebar_identity(user)
    page.run()


mode = st.query_params.get("mode")
PUBLIC_MODES.get(mode, render_desk)()
