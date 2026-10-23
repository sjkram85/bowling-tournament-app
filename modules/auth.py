"""Authentication, user sessions, role-based access control, and registration."""

import base64
import os
from pathlib import Path
import sqlite3
import streamlit as st
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from modules.constants import CENTERS
from modules.db_state import get_connection, log_desk_action

ph = PasswordHasher()

# Public constants required by staff account management
MIN_PASSWORD_LENGTH = 8
ROLES = ["td", "admin"]

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHUSBC_LOGO = ASSETS_DIR / "CHUSBC.jpg"


def _get_chusbc_logo_tag(height: int = 70) -> str:
    """Generate an inline base64 image tag for the official CHUSBC sanction logo."""
    if CHUSBC_LOGO.is_file():
        data = base64.b64encode(CHUSBC_LOGO.read_bytes()).decode()
        return (
            f'<div style="text-align: center; margin-bottom: 12px;">'
            f'<img src="data:image/jpeg;base64,{data}" '
            f'style="height:{height}px; width:auto; border-radius:6px; background:#FFFFFF; padding:4px; box-shadow:0 2px 8px rgba(0,0,0,0.4);" '
            f'alt="USBC Cecil Harford Association">'
            f'</div>'
        )
    return '<div style="font-size: 36px; text-align: center; margin-bottom: 8px;">🎳</div>'


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password against an Argon2id hash."""
    try:
        return ph.verify(password_hash, password)
    except (VerifyMismatchError, Exception):
        return False


def _bootstrap_admin() -> None:
    """Bootstrap default administrator from secrets or environment if no admin exists."""
    admin_conf = st.secrets.get("admin_bootstrap", {})
    username = admin_conf.get("username", "admin")
    password = admin_conf.get("password", "AdminPass2026!")
    display_name = admin_conf.get("display_name", "Scott Kramer")
    email = admin_conf.get("email", "scott@chusbc.org")
    affiliation = admin_conf.get("center_affiliation", "CHUSBC")

    conn = get_connection()
    try:
        with conn:
            existing = conn.execute(
                "SELECT id FROM staff_users WHERE role = 'admin' LIMIT 1"
            ).fetchone()
            if not existing:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO staff_users 
                    (username, password_hash, display_name, email, center_affiliation, role, is_approved)
                    VALUES (?, ?, ?, ?, ?, 'admin', 1)
                    """,
                    (username, hash_password(password), display_name, email, affiliation),
                )
    finally:
        conn.close()


def authenticate(username: str, password: str) -> dict | None:
    """Authenticate a staff user against SQLite."""
    conn = get_connection()
    try:
        user = conn.execute(
            "SELECT * FROM staff_users WHERE username = ? AND is_approved = 1",
            (username.strip(),),
        ).fetchone()

        if user and verify_password(user["password_hash"], password):
            user_dict = dict(user)
            log_desk_action(
                user_dict["display_name"],
                user_dict["role"],
                f"Staff user '{user_dict['username']}' logged in successfully",
            )
            return user_dict
        return None
    finally:
        conn.close()


def create_staff_user(
    username: str,
    password: str,
    display_name: str,
    email: str = "",
    center_affiliation: str = "CHUSBC",
    role: str = "td",
    is_approved: int = 1,
) -> tuple[bool, str]:
    """Create a staff user directly (used by admin console in staff_accounts.py)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if role not in ROLES:
        return False, f"Invalid role: {role}."

    conn = get_connection()
    try:
        with conn:
            existing = conn.execute(
                "SELECT id FROM staff_users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
            if existing:
                return False, "Username is already taken."

            conn.execute(
                """
                INSERT INTO staff_users 
                (username, password_hash, display_name, email, center_affiliation, role, is_approved)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username.strip(),
                    hash_password(password),
                    display_name.strip(),
                    email.strip(),
                    center_affiliation,
                    role,
                    int(is_approved),
                ),
            )
            log_desk_action(
                "Admin",
                "admin",
                f"Created staff account '{username.strip()}' with role '{role}'",
            )
        return True, "Staff account created successfully."
    except Exception as exc:
        return False, f"Account creation failed: {str(exc)}"
    finally:
        conn.close()


def register_staff_user(
    username: str,
    password: str,
    display_name: str,
    email: str,
    center_affiliation: str,
) -> tuple[bool, str]:
    """Register a new staff account pending administrator approval."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."

    conn = get_connection()
    try:
        with conn:
            existing = conn.execute(
                "SELECT id FROM staff_users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
            if existing:
                return False, "Username is already taken. Choose another."

            conn.execute(
                """
                INSERT INTO staff_users 
                (username, password_hash, display_name, email, center_affiliation, role, is_approved)
                VALUES (?, ?, ?, ?, ?, 'td', 0)
                """,
                (
                    username.strip(),
                    hash_password(password),
                    display_name.strip(),
                    email.strip(),
                    center_affiliation,
                ),
            )
            log_desk_action(
                display_name.strip(),
                "applicant",
                f"New staff access request submitted for affiliation: {center_affiliation}",
            )
        return True, "Access request submitted successfully! An administrator will review and activate your account."
    except Exception as exc:
        return False, f"Registration failed: {str(exc)}"
    finally:
        conn.close()


def current_user() -> dict | None:
    """Get active session user."""
    return st.session_state.get("user")


def is_authenticated() -> bool:
    """Check if a valid session user is logged in."""
    return st.session_state.get("user") is not None


def is_admin() -> bool:
    """Check if the active user holds administrative privileges."""
    user = current_user()
    return bool(user and user.get("role") == "admin")


def logout() -> None:
    """Clear active user session."""
    user = current_user()
    if user:
        log_desk_action(user["display_name"], user["role"], "Staff user logged out")
    st.session_state.pop("user", None)


def render_login_screen() -> None:
    """Render a compact, centered card layout for staff login and registration with official sanction branding."""
    _bootstrap_admin()

    _, center_col, _ = st.columns([1.2, 1.6, 1.2])

    with center_col:
        logo_markup = _get_chusbc_logo_tag(height=72)
        st.markdown(
            f"""
            <div style="text-align: center; margin-bottom: 20px; padding-top: 10px;">
                {logo_markup}
                <h2 style="color: #F8FAFC; margin: 4px 0; font-size: 22px; font-weight: 800; letter-spacing: -0.5px;">
                    Prism Tournament Control Center
                </h2>
                <p style="color: #94A3B8; font-size: 13px; margin: 0;">
                    Cecil Harford USBC Official Tournament Operations
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab_login, tab_register = st.tabs(["Staff Sign In", "Request Access"])

        with tab_login:
            with st.container(border=True):
                with st.form("login_form", clear_on_submit=False):
                    username = st.text_input("Username", key="login_username")
                    password = st.text_input("Password", type="password", key="login_password")
                    submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)

                    if submitted:
                        if not username or not password:
                            st.error("Please enter both username and password.")
                        else:
                            user = authenticate(username, password)
                            if user:
                                st.session_state["user"] = user
                                st.rerun()
                            else:
                                st.error("Invalid username or password.")

        with tab_register:
            with st.container(border=True):
                with st.form("register_form", clear_on_submit=True):
                    new_username = st.text_input("Desired Username")
                    new_display = st.text_input("Display Name (e.g. Scott Kramer)")
                    new_email = st.text_input("Email Address")
                    affiliation = st.selectbox(
                        "Center / Organization Affiliation",
                        ["CHUSBC", "Forest Hill Bowl (FHL)", "Harford Lanes (HL)", "APG Bowling Center (APG)"],
                    )
                    new_password = st.text_input("Password", type="password")
                    reg_submitted = st.form_submit_button("Submit Access Request", use_container_width=True)

                    if reg_submitted:
                        if not (new_username and new_password and new_display):
                            st.error("Please fill in all required fields.")
                        else:
                            success, msg = register_staff_user(
                                new_username, new_password, new_display, new_email, affiliation
                            )
                            if success:
                                st.success(msg)
                            else:
                                st.error(msg)

        st.markdown(
            """
            <div style="text-align: center; margin-top: 24px;">
                <small style="color: #64748B;">Dedicated to the bowlers of CHUSBC.</small>
            </div>
            """,
            unsafe_allow_html=True,
        )


def require_login() -> dict | None:
    """Enforces authentication guard; returns current user or renders login card."""
    user = current_user()
    if not user:
        render_login_screen()
        return None
    return user