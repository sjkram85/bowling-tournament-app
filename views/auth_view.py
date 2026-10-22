"""Desk sign-in and self-service access request screen."""

import streamlit as st

from components.header import CHUSBC_LOGO, _logo_tag
from modules import auth
from modules.constants import CENTERS
from modules.mailer import send_admin_registration_alert

CENTER_CODES = {meta["name"]: code for code, meta in CENTERS.items()}
LOGIN_MESSAGES = {
    "locked": "Too many failed attempts. Reload the page to try again.",
    "invalid": "Invalid username or password.",
}


def _sign_in_tab() -> None:
    with st.form("desk_login"):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign In", type="primary", width="stretch")
    if not submitted:
        return
    outcome = auth.try_login(username, password)
    if outcome == "pending":
        st.info("Your registration is currently pending administrator approval.")
    elif outcome:
        st.error(LOGIN_MESSAGES[outcome])


def _request_access_tab() -> None:
    with st.form("access_request", clear_on_submit=True):
        display_name = st.text_input("Full Display Name")
        username = st.text_input("Desired Username")
        email = st.text_input("Email Address")
        password = st.text_input(
            f"Password (min {auth.MIN_PASSWORD_LENGTH} characters)", type="password"
        )
        center_name = st.selectbox("Center Affiliation", list(CENTER_CODES), index=None, placeholder="Select a center")
        submitted = st.form_submit_button("Submit Access Request", type="primary", width="stretch")
    if not submitted:
        return
    if center_name is None:
        st.error("Select your center affiliation.")
        return
    error = auth.register_applicant(display_name, username, email, password, CENTER_CODES[center_name])
    if error:
        st.error(error)
        return
    applicant = {
        "display_name": display_name.strip(),
        "username": username.strip().lower(),
        "email": email.strip(),
        "center_affiliation": center_name,
        "role": "td",
    }
    try:
        sent = send_admin_registration_alert(applicant)
    except Exception:
        sent = False
    if sent:
        st.success(
            "Access request submitted. An email has been dispatched to the tournament administrator for review."
        )
    else:
        st.warning(
            "Access request submitted, but the alert email could not be sent. "
            "Please contact the tournament administrator directly."
        )


def render_auth_view() -> None:
    st.markdown('<div style="height:6vh"></div>', unsafe_allow_html=True)
    _, middle, _ = st.columns([1, 1.6, 1])
    with middle:
        with st.container(key="auth_card"):
            seal = _logo_tag(str(CHUSBC_LOGO), 80) if CHUSBC_LOGO.is_file() else ""
            st.markdown(
                f'<div style="text-align:center">{seal}'
                '<div class="ptcc-auth-title">Prism Tournament Control Center</div>'
                '<div class="ptcc-auth-subtitle">Cecil Harford USBC Official Tournament Operations</div></div>',
                unsafe_allow_html=True,
            )
            sign_in, request = st.tabs(["Staff Sign In", "Request Access"])
            with sign_in:
                _sign_in_tab()
            with request:
                _request_access_tab()
        st.markdown(
            '<div style="text-align:center;margin-top:14px;color:#64748B;font-size:0.8rem">'
            "Dedicated to the bowlers of CHUSBC.</div>",
            unsafe_allow_html=True,
        )
