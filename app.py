"""Prism Tournament Control Center entrypoint."""

import streamlit as st

st.set_page_config(page_title="Prism Tournament Control Center", layout="wide")

from components.about_dialog import show_about_dialog
from components.styles import apply_clean_theme
from modules import auth
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


def render_desk() -> None:
    user = auth.require_login()
    if user is None:
        return
    pages = [
        st.Page(render_intake_gateway, title="Intake Gateway", url_path="intake", default=True),
        st.Page(render_active_squad, title="Active Squad Hub", url_path="squad"),
        st.Page(render_finals_close, title="Finals Closeout", url_path="finals"),
        st.Page(render_archive_vault, title="Historical Archive Vault", url_path="archive"),
    ]
    if auth.is_admin():
        pages.append(st.Page(render_staff_accounts, title="Staff Accounts", url_path="staff"))
    page = st.navigation(pages)
    st.sidebar.caption(f"Signed in as {user['display_name']} ({user['role']})")
    if st.sidebar.button("About", width="stretch"):
        show_about_dialog()
    if st.sidebar.button("Sign out", width="stretch"):
        auth.logout()
        st.rerun()
    page.run()


mode = st.query_params.get("mode")
PUBLIC_MODES.get(mode, render_desk)()
