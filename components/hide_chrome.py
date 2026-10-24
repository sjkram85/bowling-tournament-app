"""Hide Streamlit (for everyone but logged-in admins)/hosting chrome (menu, deploy button, footer, badges, status) on every page.

Can't be hidden by app code on Streamlit Community Cloud: the owner-only GitHub / edit /
Manage app controls (shown only to the signed-in owner) and anything the host draws in its
own frame outside the app.
"""

import streamlit as st

HIDE_CHROME_CSS = """
<style>
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stAppDeployButton"], .stAppDeployButton,
[data-testid="stDecoration"], [data-testid="stStatusWidget"], [data-testid="stMainMenu"],
.viewerBadge_container__1QSob, .viewerBadge_link__1S137, [class*="viewerBadge"],
[data-testid="manage-app-button"], [class*="styles_viewerBadge"] {display: none !important; visibility: hidden !important;}
header[data-testid="stHeader"] {background: transparent !important;}
</style>
"""


PUBLIC_MODES = ("kiosk", "score", "bowler")


def should_hide(user: dict | None, mode: str | None) -> bool:
    """Hide for everyone except a logged-in admin on the desk. Public screens (kiosk, floor phone,
    bowler portal) always hide, even for an admin."""
    if (mode or "") in PUBLIC_MODES:
        return True
    return not (user and user.get("role") == "admin")


def hide_streamlit_chrome() -> None:
    from modules.auth import current_user
    try:
        user = current_user()
    except Exception:
        user = None
    if should_hide(user, st.query_params.get("mode")):
        st.markdown(HIDE_CHROME_CSS, unsafe_allow_html=True)
