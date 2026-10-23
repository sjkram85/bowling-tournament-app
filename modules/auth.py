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
from modules.mailer import send_admin_registration_alert

ph = PasswordHasher()

# Public constants required by staff account management
MIN_PASSWORD_LENGTH = 8
ROLES = ["td", "admin"]

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHUSBC_LOGO = ASSETS_DIR / "CHUSBC.jpg"

LICENSE_SNIPPET = (
    "This software is provided freely to the Cecil Harford United States Bowling Congress (CHUSBC) "
    "and dedicated to the bowlers of CHUSBC, may our sport provide friendly competition, enduring "
    "friendships and life long memories.\n\n"
    "Licensed under the MIT License. Copyright (c) 2026 Scott Kramer / CHUSBC. Free for association "
    "use, tournament administration, and non-commercial bowling operations."
)


def _get_chusbc_logo_tag(height: int = 110) -> str:
    """Generate an inline base64 image tag for the official CHUSBC sanction logo."""
    if CHUSBC_LOGO.is_file():
        data = base64.b64encode(CHUSBC_LOGO.read_bytes()).decode()
        return (
            f'<div style="text-align: center; margin-bottom: 16px;">'
            f'<img src="data:image/jpeg;base64,{data}" '
            f'style="height:{height}px; max-width:90%; width:auto; border-radius:8px; background:#FFFFFF; padding:6px; box-shadow:0 4px 12px rgba(0,0,0,0.45);" '
            f'alt="USBC Cecil Harford Association">'
            f'</div>'
        )
    return '<div style="font-size: 48px; text-align: center; margin-bottom: 12px;">🎳</div>'


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
    """Bootstrap default administrator in SQLite with Scott Kramer's credentials."""
    username = "skramer"
    password = "Gussierocks1"
    display_name = "Scott Kramer"
    email = "scottjk85@gmail.com"
    affiliation = "CHUSBC"

    conn = get_connection()
    try:
        with conn:
            existing = conn.execute(
                "SELECT id FROM staff_users WHERE username = ?",
                (username,),
            ).fetchone()
            if not existing:
                conn.execute(
                    """
                    INSERT INTO staff_users 
                    (username, password_hash, display_name, email, center_affiliation, role, is_approved)
                    VALUES (?, ?, ?, ?, ?, 'admin', 1)
                    """,
                    (username, hash_password(password), display_name, email, affiliation),
                )
            else:
                conn.execute(
                    """
                    UPDATE staff_users 
                    SET password_hash = ?, display_name = ?, email = ?, center_affiliation = ?, role = 'admin', is_approved = 1 
                    WHERE username = ?
                    """,
                    (hash_password(password), display_name, email, affiliation, username),
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
    except Exception as exc:
        return False, f"Account creation failed: {str(exc)}"
    finally:
        conn.close()

    # Log action outside transaction scope to prevent database lockups
    log_desk_action(
        "Admin",
        "admin",
        f"Created staff account '{username.strip()}' with role '{role}'",
    )
    return True, "Staff account created successfully."


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
    except Exception as exc:
        return False, f"Registration failed: {str(exc)}"
    finally:
        conn.close()

    # Log audit entry after transaction commit
    log_desk_action(
        display_name.strip(),
        "applicant",
        f"New staff access request submitted for affiliation: {center_affiliation}",
    )

    # Dispatch email notification to chusbc.tournaments@gmail.com
    applicant_payload = {
        "display_name": display_name.strip(),
        "username": username.strip(),
        "email": email.strip(),
        "center_affiliation": center_affiliation,
        "role": "td",
    }
    try:
        send_admin_registration_alert(applicant_payload)
    except Exception:
        pass

    return True, "Access request submitted successfully! An administrator will review and activate your account."


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

    _, center_col, _ = st.columns([1.0, 1.8, 1.0])

    with center_col:
        logo_markup = _get_chusbc_logo_tag(height=110)
        st.markdown(
            f"""
            <div style="text-align: center; margin-bottom: 24px; padding-top: 10px;">
                {logo_markup}
                <h2 style="color: #F8FAFC; margin: 6px 0; font-size: 26px; font-weight: 800; letter-spacing: -0.5px;">
                    Prism Tournament Control Center
                </h2>
                <p style="color: #94A3B8; font-size: 14px; margin: 0;">
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
                                log_desk_action(
                                    user["display_name"],
                                    user["role"],
                                    f"Staff user '{user['username']}' logged in successfully",
                                )
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
            <div style="text-align: center; margin-top: 20px;">
                <p style="color: #94A3B8; font-size: 12px; margin-bottom: 6px;">
                    Dedicated to the bowlers of CHUSBC.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("⚖️ Software License & Terms", expanded=False):
            st.caption(LICENSE_SNIPPET)


def require_login() -> dict | None:
    """Enforces authentication guard; returns current user or renders login card."""
    user = current_user()
    if not user:
        render_login_screen()
        return None
    return user