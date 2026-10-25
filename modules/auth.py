"""Authentication, user sessions, role-based access control, and registration."""

import base64
import os
from pathlib import Path
import sqlite3
import streamlit as st
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from modules.constants import CENTERS, HOST_CENTERS
from modules.db_state import get_connection, log_desk_action
from modules.mailer import send_admin_registration_alert, send_applicant_approval_notice

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
    """Bootstrap default administrator in SQLite with automatic column schema migration."""
    username = "skramer"
    password = "Gussierocks1"
    display_name = "Scott Kramer"
    email = "scottjk85@gmail.com"
    affiliation = "CHUSBC"

    conn = get_connection()
    try:
        with conn:
            # init_db already created staff_users. Re-sending this CREATE on
            # every logged-out open is the statement Turso fails (prepare tail
            # on the indented semicolon, or an idle Hrana stream). Skip it
            # when the table is there. No trailing semicolon: hosted prepare
            # treats the whitespace after one as a second statement.
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'staff_users'"
            ).fetchone()
            if not exists:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS staff_users ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "username TEXT UNIQUE NOT NULL, "
                    "password_hash TEXT NOT NULL, "
                    "display_name TEXT NOT NULL, "
                    "email TEXT DEFAULT '', "
                    "center_affiliation TEXT DEFAULT 'CHUSBC', "
                    "role TEXT NOT NULL DEFAULT 'td', "
                    "is_approved INTEGER DEFAULT 1, "
                    "is_active INTEGER DEFAULT 1, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )

            # Check and migrate columns on existing database files
            columns = [col[1] for col in conn.execute("PRAGMA table_info(staff_users)").fetchall()]
            if "email" not in columns:
                conn.execute("ALTER TABLE staff_users ADD COLUMN email TEXT DEFAULT ''")
            if "is_approved" not in columns:
                conn.execute("ALTER TABLE staff_users ADD COLUMN is_approved INTEGER DEFAULT 1")
            if "center_affiliation" not in columns:
                conn.execute("ALTER TABLE staff_users ADD COLUMN center_affiliation TEXT DEFAULT 'CHUSBC'")
            if "is_active" not in columns:
                conn.execute("ALTER TABLE staff_users ADD COLUMN is_active INTEGER DEFAULT 1")

            # 3. Check for existing admin record
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
    *,
    email: str = "",
    center_affiliation: str = "CHUSBC",
    role: str = "td",
    is_approved: int = 1,
) -> tuple[bool, str]:
    """Create a staff user directly (used by the Staff Accounts add form).

    email, center_affiliation, and role are keyword-only. Passing the center and
    role as the next positional arguments used to store the center in email and
    the role in center_affiliation, and left role as the default td.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    role = (role or "").strip()
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
                    (email or "").strip(),
                    (center_affiliation or "").strip(),
                    role,
                    int(is_approved),
                ),
            )
    except Exception as exc:
        return False, f"Account creation failed: {str(exc)}"
    finally:
        conn.close()

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

    log_desk_action(
        display_name.strip(),
        "applicant",
        f"New staff access request submitted for affiliation: {center_affiliation}",
    )

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


def approve_user(user_id: int, admin_name: str) -> str | None:
    """Approve a pending staff user access request."""
    conn = get_connection()
    user_info = None
    try:
        with conn:
            user_info = conn.execute(
                "SELECT username, email, display_name FROM staff_users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not user_info:
                return "User record not found."
            conn.execute("UPDATE staff_users SET is_approved = 1 WHERE id = ?", (user_id,))
    except Exception as exc:
        return f"Approval failed: {str(exc)}"
    finally:
        conn.close()

    log_desk_action(
        admin_name,
        "admin",
        f"Approved staff access request for '{user_info['username']}'",
    )
    if user_info["email"]:
        try:
            send_applicant_approval_notice(user_info["email"], user_info["display_name"])
        except Exception:
            pass
    return None


def delete_user(user_id: int, admin_id: int, admin_name: str) -> str | None:
    """Delete a staff user or reject a pending request."""
    if user_id == admin_id:
        return "You cannot delete your own active administrator account."

    conn = get_connection()
    target_username = ""
    try:
        with conn:
            row = conn.execute(
                "SELECT username FROM staff_users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return "User not found."
            target_username = row["username"]
            conn.execute("DELETE FROM staff_users WHERE id = ?", (user_id,))
    except Exception as exc:
        return f"Deletion failed: {str(exc)}"
    finally:
        conn.close()

    log_desk_action(
        admin_name,
        "admin",
        f"Deleted staff user '{target_username}' (ID: {user_id})",
    )
    return None


def reset_password(user_id: int, new_password: str, admin_name: str) -> str | None:
    """Reset a staff user's password."""
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."

    conn = get_connection()
    target_username = ""
    try:
        with conn:
            row = conn.execute(
                "SELECT username FROM staff_users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return "User not found."
            target_username = row["username"]
            conn.execute(
                "UPDATE staff_users SET password_hash = ? WHERE id = ?",
                (hash_password(new_password), user_id),
            )
    except Exception as exc:
        return f"Password reset failed: {str(exc)}"
    finally:
        conn.close()

    log_desk_action(
        admin_name,
        "admin",
        f"Reset password for staff user '{target_username}'",
    )
    return None


def _plain_text(value) -> str:
    """Strip a stored string. Anything else (None, a number) is blank, not a crash."""
    return value.strip() if isinstance(value, str) else ""


def shifted_staff_fields(email, center_affiliation, role) -> dict | None:
    """Recover columns written by the positional create_staff_user call.

    The add form passed center and role in the email and center slots, and the
    real role stayed the default ``td``. A match is only that shape: email is a
    host-center code, center is a role name, and role is ``td``. The recovered
    email is empty — a real address was never collected, so none is invented.
    """
    stored_email = _plain_text(email)
    stored_center = _plain_text(center_affiliation)
    stored_role = _plain_text(role)
    if stored_email not in HOST_CENTERS or stored_center not in ROLES or stored_role != "td":
        return None
    return {
        "email": "",
        "center_affiliation": stored_email,
        "role": stored_center,
    }


def repair_shifted_scott_account() -> bool:
    """Rewrite the scott row when it still has the positional-bug shape.

    username scott, email CHUSBC, center admin, role td becomes role admin,
    center CHUSBC, and a blank email. Any later edit no longer matches, so it
    is left alone. Other usernames are not changed; Staff Accounts can edit those.
    Returns True only when a row was rewritten.
    """
    conn = get_connection()
    changes: list[str] = []
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(staff_users);").fetchall()}
        if not {"username", "email", "center_affiliation", "role"}.issubset(columns):
            return False
        with conn:
            rows = conn.execute(
                """
                SELECT id, username, email, center_affiliation, role
                FROM staff_users
                WHERE LOWER(username) = 'scott'
                """
            ).fetchall()
            for row in rows:
                fields = shifted_staff_fields(row["email"], row["center_affiliation"], row["role"])
                if fields is None:
                    continue
                conn.execute(
                    """
                    UPDATE staff_users
                    SET email = ?, center_affiliation = ?, role = ?
                    WHERE id = ?
                      AND email = ?
                      AND center_affiliation = ?
                      AND role = ?
                    """,
                    (
                        fields["email"],
                        fields["center_affiliation"],
                        fields["role"],
                        row["id"],
                        row["email"],
                        row["center_affiliation"],
                        row["role"],
                    ),
                )
                checked = conn.execute(
                    "SELECT email, center_affiliation, role FROM staff_users WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                if (
                    checked
                    and (checked["email"] or "") == fields["email"]
                    and checked["center_affiliation"] == fields["center_affiliation"]
                    and checked["role"] == fields["role"]
                ):
                    changes.append(
                        f"{row['username']}: role {fields['role']}, "
                        f"center {fields['center_affiliation']}, email cleared"
                    )
    finally:
        conn.close()
    if not changes:
        return False
    log_desk_action(
        "System",
        "admin",
        "Repaired staff account after the positional create bug (" + "; ".join(changes) + ")",
    )
    return True


def apply_shifted_scott_session_repair() -> None:
    """Correct a signed-in scott session that still has the shifted columns.

    Startup rewrites the database row. A session from before that still says
    role td, which hides Staff Accounts. This only updates session state.
    """
    user = st.session_state.get("user")
    if not isinstance(user, dict):
        return
    username = user.get("username")
    if not isinstance(username, str) or username.strip().lower() != "scott":
        return
    fields = shifted_staff_fields(user.get("email"), user.get("center_affiliation"), user.get("role"))
    if fields is None:
        return
    updated = dict(user)
    updated.update(fields)
    st.session_state["user"] = updated


def update_staff_profile(
    user_id: int,
    *,
    display_name: str,
    email: str,
    center_affiliation: str,
    role: str,
    admin_name: str,
) -> str | None:
    """Set display name, email, center, and role for one staff account.

    Email may be blank. Center must be a host-center code. Role must be a known role.
    """
    name = (display_name or "").strip()
    if not name:
        return "Display name is required."
    cleaned_email = (email or "").strip()
    center = (center_affiliation or "").strip()
    if center not in HOST_CENTERS:
        return "Choose a center."
    role = (role or "").strip()
    if role not in ROLES:
        return f"Invalid role: {role}."

    conn = get_connection()
    target_username = ""
    try:
        with conn:
            row = conn.execute(
                "SELECT username FROM staff_users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return "User not found."
            target_username = row["username"]
            conn.execute(
                """
                UPDATE staff_users
                SET display_name = ?, email = ?, center_affiliation = ?, role = ?
                WHERE id = ?
                """,
                (name, cleaned_email, center, role, user_id),
            )
    except Exception as exc:
        return f"Profile update failed: {str(exc)}"
    finally:
        conn.close()

    log_desk_action(
        admin_name,
        "admin",
        f"Updated profile for staff user '{target_username}' (role {role}, center {center})",
    )
    return None


def set_role(user_id: int, new_role: str, admin_name: str) -> str | None:
    """Update role for a staff user."""
    if new_role not in ROLES:
        return f"Invalid role: {new_role}"

    conn = get_connection()
    target_username = ""
    try:
        with conn:
            row = conn.execute(
                "SELECT username FROM staff_users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return "User not found."
            target_username = row["username"]
            conn.execute(
                "UPDATE staff_users SET role = ? WHERE id = ?",
                (new_role, user_id),
            )
    except Exception as exc:
        return f"Role update failed: {str(exc)}"
    finally:
        conn.close()

    log_desk_action(
        admin_name,
        "admin",
        f"Updated role to '{new_role}' for staff user '{target_username}'",
    )
    return None


def change_own_password(user_id: int, current_password: str, new_password: str) -> str | None:
    """Allow logged in staff member to change their own password."""
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return f"New password must be at least {MIN_PASSWORD_LENGTH} characters."

    conn = get_connection()
    try:
        with conn:
            user = conn.execute(
                "SELECT password_hash, username FROM staff_users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not user or not verify_password(user["password_hash"], current_password):
                return "Current password does not match."
            conn.execute(
                "UPDATE staff_users SET password_hash = ? WHERE id = ?",
                (hash_password(new_password), user_id),
            )
    except Exception as exc:
        return f"Password change failed: {str(exc)}"
    finally:
        conn.close()

    return None


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
    """Clear active user session and reset navigation state."""
    user = current_user()
    if user:
        log_desk_action(user["display_name"], user["role"], "Staff user logged out")
    st.session_state.pop("user", None)
    st.query_params.clear()


def render_login_screen() -> None:
    """Render a compact, centered card layout for staff login and registration with official sanction branding."""
    _bootstrap_admin()

    # Hide sidebar completely on login/registration screen so the card is centered
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"],
        div[data-testid="collapsedControl"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

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