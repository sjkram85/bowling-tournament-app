"""Authentication, user sessions, role-based access control, and registration."""

import base64
import logging
import os
from pathlib import Path
import sqlite3
import streamlit as st
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from modules.constants import CENTERS, HOST_CENTERS
from modules.db_state import get_connection, log_desk_action
from modules.mailer import send_admin_registration_alert, send_applicant_approval_notice

log = logging.getLogger(__name__)
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


# init_db owns this table. Sign-in sends it only when a read says it is missing.
# No trailing semicolon: hosted Turso prepare treats whitespace after one as a
# second statement and raises ValueError, which the page shows redacted.
_STAFF_USERS_DDL = (
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
_STAFF_COLUMN_DDL = (
    ("email", "ALTER TABLE staff_users ADD COLUMN email TEXT DEFAULT ''"),
    ("is_approved", "ALTER TABLE staff_users ADD COLUMN is_approved INTEGER DEFAULT 1"),
    ("center_affiliation", "ALTER TABLE staff_users ADD COLUMN center_affiliation TEXT DEFAULT 'CHUSBC'"),
    ("is_active", "ALTER TABLE staff_users ADD COLUMN is_active INTEGER DEFAULT 1"),
)
_ADMIN_LOOKUP = "SELECT id FROM staff_users WHERE username = ?"


def _exception_text(exc: BaseException) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(str(current).lower())
        current = current.__cause__ or current.__context__
    return " ".join(parts)


def _schema_problem(exc: BaseException) -> str | None:
    """'table' or 'column' when SQLite reports staff_users is not usable yet."""
    msg = _exception_text(exc)
    if "no such table" in msg:
        return "table"
    # libsql says "no column named email"; sqlite3 says "no such column: email".
    if "no such column" in msg or "no column named" in msg:
        return "column"
    return None


def _lookup_admin(conn, username: str) -> tuple[bool, str]:
    """Return (row exists, 'ok'|'table'|'column'). Other database errors propagate."""
    try:
        row = conn.execute(_ADMIN_LOOKUP, (username,)).fetchone()
    except sqlite3.OperationalError as exc:
        kind = _schema_problem(exc)
        if kind is None:
            raise
        return False, kind
    return row is not None, "ok"


def _ensure_staff_columns(conn) -> None:
    columns = [col[1] for col in conn.execute("PRAGMA table_info(staff_users)").fetchall()]
    for name, ddl in _STAFF_COLUMN_DDL:
        if name in columns:
            continue
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in _exception_text(exc):
                raise


def _insert_default_admin(conn, username, password_hash, display_name, email, affiliation) -> None:
    conn.execute(
        "INSERT INTO staff_users "
        "(username, password_hash, display_name, email, center_affiliation, role, is_approved) "
        "VALUES (?, ?, ?, ?, ?, 'admin', 1)",
        (username, password_hash, display_name, email, affiliation),
    )


def _bootstrap_admin() -> None:
    """Ensure the default admin exists. Never raise into the sign-in page.

    init_db already creates staff_users. Re-sending CREATE/ALTER, and re-hashing
    the admin password, on every logged-out open is what Turso rejects inside
    one ``with conn:`` (prepare tail, a dead Hrana stream, or a commit after
    that stream is replaced). Streamlit then redacts the libsql message and the
    form never renders.

    A missing row is still inserted, including on the next open after a failed
    attempt. An existing row is left alone. Any libsql error is logged and the
    caller draws the form anyway.
    """
    try:
        _ensure_default_admin()
    except Exception as exc:
        log.exception(
            "Staff sign-in bootstrap failed; the login form will still load: %s",
            exc,
        )


def _ensure_default_admin() -> None:
    username = "skramer"
    password = "Gussierocks1"
    display_name = "Scott Kramer"
    email = "scottjk85@gmail.com"
    affiliation = "CHUSBC"

    conn = get_connection()
    try:
        found, schema = _lookup_admin(conn, username)
    finally:
        conn.close()
    if found:
        return

    # Argon2 can outlast Turso's 10s idle stream. Hash with no connection held.
    password_hash = hash_password(password)

    inserted = False
    conn = get_connection()
    try:
        if schema == "table":
            conn.execute(_STAFF_USERS_DDL)
        elif schema == "column":
            _ensure_staff_columns(conn)
        if _admin_row(conn, username) is not None:
            return
        try:
            _insert_default_admin(
                conn, username, password_hash, display_name, email, affiliation
            )
            inserted = True
        except sqlite3.OperationalError as exc:
            if _schema_problem(exc) != "column":
                raise
            conn.rollback()
            _ensure_staff_columns(conn)
            _insert_default_admin(
                conn, username, password_hash, display_name, email, affiliation
            )
            inserted = True
        except sqlite3.IntegrityError:
            # Another open inserted the same username. The row is the bootstrap.
            conn.rollback()
            return
        conn.commit()
    finally:
        conn.close()

    # Read it back on a new connection. A commit Turso answered with "no
    # transaction is active" can leave the insert uncommitted, and returning
    # this connection to the pool rolls that transaction back.
    conn = get_connection()
    try:
        if _admin_row(conn, username) is None:
            inserted = False
            log.error(
                "Staff sign-in bootstrap did not persist the default admin row. "
                "The login form will still load and the next open will try again."
            )
    finally:
        conn.close()
    if inserted:
        _save_staff_vault()


def _admin_row(conn, username: str):
    try:
        return conn.execute(_ADMIN_LOOKUP, (username,)).fetchone()
    except sqlite3.OperationalError as exc:
        if _schema_problem(exc) != "column":
            raise
        _ensure_staff_columns(conn)
        return conn.execute(_ADMIN_LOOKUP, (username,)).fetchone()


def _save_staff_vault() -> None:
    """Copy staff accounts into the durable vault. A vault problem must not undo the change."""
    try:
        from modules.staff_vault import save_staff_vault
        save_staff_vault()
    except Exception:
        log.exception("Staff vault save failed")


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
    _save_staff_vault()
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

    _save_staff_vault()
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
    _save_staff_vault()
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
    _save_staff_vault()
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
    _save_staff_vault()
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
    _save_staff_vault()
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
    _save_staff_vault()
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
    _save_staff_vault()
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

    _save_staff_vault()
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