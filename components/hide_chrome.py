"""Hide Streamlit/hosting chrome (menu, deploy button, footer, badges, status) on every page.

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


def hide_streamlit_chrome() -> None:
    st.markdown(HIDE_CHROME_CSS, unsafe_allow_html=True)
