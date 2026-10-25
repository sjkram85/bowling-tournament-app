"""Prism Tournament Control Center entrypoint."""

from html import escape

import streamlit as st

st.set_page_config(page_title="Prism Tournament Control Center (PTCC)", layout="wide")

from components.about_dialog import show_about_dialog
from components.header import CHUSBC_LOGO, _logo_tag
from components.prism_dock import collect_view_state, render_prism_dock
from components.hide_chrome import hide_streamlit_chrome
from components.styles import apply_clean_theme
from modules import auth
from modules.constants import CENTERS
from modules.db_state import init_db, storage_label, using_turso
from views.bowler_portal import render_bowler_portal
from views.hubs.active_squad import render_active_squad
from views.hubs.archive_vault import render_archive_vault
from views.hubs.finals_close import render_finals_close
from views.hubs.staff_accounts import render_staff_accounts
from views.intake_gateway import render_intake_gateway
from views.kiosk import render_kiosk
from views.mobile_scoring import render_mobile_scoring


@st.cache_resource(show_spinner=False)
def _init_turso_once() -> bool:
    init_db()  # Turso: run schema checks / first-time copy once per server start, not every click
    return True


if using_turso():
    _init_turso_once()
else:
    init_db()
apply_clean_theme()
hide_streamlit_chrome()

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
        f'<div class="ptcc-side-brand">{seal}<div class="ptcc-side-text"><div class="ptcc-side-title">'
        'Prism Tournament Control Center</div>'
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
        if is_admin:
            st.caption(("🟢 " if using_turso() else "🟠 ") + storage_label())
        about, sign_out = st.columns(2)
        if about.button("About", key="side_about", use_container_width=True):
            show_about_dialog()
        if sign_out.button("Sign Out", key="side_signout", use_container_width=True):
            auth.logout()
            st.rerun()


def render_desk() -> None:
    # A session signed in before the scott repair still has role td, which hides this desk's admin pages.
    auth.apply_shifted_scott_session_repair()
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
        from views.hubs.backup_restore import render_backup_restore
        management.append(st.Page(render_backup_restore, title="Backup & Restore", icon="💾", url_path="backup"))
    page = st.navigation(operations + management, position="hidden")

    _sidebar_brand()
    for heading, items in (("OPERATIONS", operations), ("MANAGEMENT", management)):
        st.sidebar.markdown(f'<div class="ptcc-nav-heading">{heading}</div>', unsafe_allow_html=True)
        for item in items:
            state = "active" if item.url_path == page.url_path else "idle"
            with st.sidebar.container(key=f"nav_{state}_{item.url_path}"):
                st.page_link(item, use_container_width=True)
    _sidebar_identity(user)

    # Render Prism A.I assistant into sidebar before page.run()
    render_prism_dock(current_view=page.title, view_state=collect_view_state(page.title))


    from components.event_picker import staff_event_bar
    if st.session_state.get("intake_new_event") and page.url_path != "intake":
        st.switch_page(operations[0])
    ready = staff_event_bar()
    # The fragment heartbeats on this run and again every 30s. A second write here
    # was a Turso round trip on every click and did not change who shows as on duty.
    _heartbeat_tick(user)
    _practice_banner()
    if ready or page.url_path == "backup":  # restore must work even when no events exist
        page.run()


@st.fragment(run_every=30)
def _heartbeat_tick(user: dict) -> None:
    """Keeps this TD showing as 'on duty' while the screen is open."""
    from modules.td_team import heartbeat
    heartbeat(user.get("username") or user["display_name"], user["display_name"],
              st.session_state.get("active_tournament_id"))


def _practice_banner() -> None:
    """Big, unmissable warning on every screen while a practice tournament is open."""
    from modules.practice import is_practice

    t_id = st.session_state.get("active_tournament_id")
    if is_practice(t_id):
        st.markdown(
            '<div style="background:#B45309; color:#FFFFFF; font-size:26px; font-weight:800; text-align:center; '
            'padding:14px; border-radius:8px; margin-bottom:14px; letter-spacing:1px;">'
            "🧪 PRACTICE MODE - not real data</div>"
            '<div style="text-align:center; font-size:16px; color:#FDE68A; margin:-8px 0 12px;">'
            "When you're done, go to Intake Gateway and press \"End &amp; Delete Practice Tournament\".</div>",
            unsafe_allow_html=True,
        )


mode = st.query_params.get("mode")
PUBLIC_MODES.get(mode, render_desk)()