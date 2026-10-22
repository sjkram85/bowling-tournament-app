"""Staff authentication for the tournament desk (Argon2 password hashes in staff_users)."""

import sqlite3

import streamlit as st
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from modules.db_state import get_connection

ROLES = ("admin", "td")
MIN_PASSWORD_LENGTH = 8
MAX_LOGIN_ATTEMPTS = 5
SESSION_KEY = "auth_user"

_hasher = PasswordHasher()
# Verified against when the username is unknown so response time doesn't reveal valid usernames.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def staff_count() -> int:
    connection = get_connection()
    try:
        return connection.execute("SELECT COUNT(*) FROM staff_users").fetchone()[0]
    finally:
        connection.close()


def create_staff_user(
    username: str, password: str, display_name: str, center_affiliation: str, role: str
) -> str | None:
    """Create an account; returns an error message, or None on success."""
    username = username.strip().lower()
    if not username or not display_name.strip():
        return "Username and display name are required."
    if role not in ROLES:
        return "Invalid role."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO staff_users "
                "(username, password_hash, display_name, center_affiliation, role, is_approved) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (username, hash_password(password), display_name.strip(), center_affiliation, role),
            )
    except sqlite3.IntegrityError:
        return "That username is already taken."
    finally:
        connection.close()
    return None


def register_applicant(
    display_name: str, username: str, email: str, password: str, center_affiliation: str
) -> str | None:
    """Store a self-service access request (role 'td', not approved); returns an error or None."""
    username = username.strip().lower()
    email = email.strip()
    if not (display_name.strip() and username and email and center_affiliation):
        return "All fields are required."
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return "Enter a valid email address."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO staff_users "
                "(username, password_hash, display_name, email, center_affiliation, role, is_approved) "
                "VALUES (?, ?, ?, ?, ?, 'td', 0)",
                (username, hash_password(password), display_name.strip(), email, center_affiliation),
            )
    except sqlite3.IntegrityError:
        return "That username is already taken."
    finally:
        connection.close()
    return None


def approve_user(user_id: int, actor: str) -> str | None:
    """Approve a pending applicant and email them; returns an error message or None."""
    connection = get_connection()
    try:
        with connection:
            row = connection.execute(
                "SELECT username, display_name, email FROM staff_users WHERE id = ? AND is_approved = 0",
                (user_id,),
            ).fetchone()
            if row is None:
                return "That request is no longer pending."
            connection.execute("UPDATE staff_users SET is_approved = 1 WHERE id = ?", (user_id,))
    finally:
        connection.close()
    _audit(actor, f"Approved staff access request for '{row['username']}'")
    if row["email"]:
        from modules.mailer import send_applicant_approval_notice

        try:
            send_applicant_approval_notice(row["email"], row["display_name"])
        except Exception:
            pass
    return None


def authenticate(username: str, password: str) -> dict | None:
    """Return the staff record (without the hash) if the credentials are valid."""
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM staff_users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        verify_password(_DUMMY_HASH, password)
        return None
    if not verify_password(row["password_hash"], password):
        return None
    if _hasher.check_needs_rehash(row["password_hash"]):
        connection = get_connection()
        try:
            with connection:
                connection.execute(
                    "UPDATE staff_users SET password_hash = ? WHERE id = ?",
                    (hash_password(password), row["id"]),
                )
        finally:
            connection.close()
    return {key: row[key] for key in row.keys() if key != "password_hash"}


def _admin_count(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM staff_users WHERE role = 'admin'").fetchone()[0]


def _audit(actor: str, description: str) -> None:
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO audit_log (user_name, role, action_description) VALUES (?, 'admin', ?)",
                (actor, description),
            )
    finally:
        connection.close()


def reset_password(user_id: int, new_password: str, actor: str) -> str | None:
    """Set a new password for any account; returns an error message, or None on success."""
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    connection = get_connection()
    try:
        with connection:
            cursor = connection.execute(
                "UPDATE staff_users SET password_hash = ? WHERE id = ?",
                (hash_password(new_password), user_id),
            )
            if cursor.rowcount == 0:
                return "User not found."
            username = connection.execute(
                "SELECT username FROM staff_users WHERE id = ?", (user_id,)
            ).fetchone()[0]
    finally:
        connection.close()
    _audit(actor, f"Reset password for staff user '{username}'")
    return None


def change_own_password(user_id: int, current_password: str, new_password: str) -> str | None:
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT username, password_hash FROM staff_users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        connection.close()
    if row is None or not verify_password(row["password_hash"], current_password):
        return "Current password is incorrect."
    error = reset_password(user_id, new_password, row["username"])
    return error


def set_role(user_id: int, role: str, actor: str) -> str | None:
    if role not in ROLES:
        return "Invalid role."
    connection = get_connection()
    try:
        with connection:
            row = connection.execute(
                "SELECT username, role FROM staff_users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                return "User not found."
            if row["role"] == "admin" and role != "admin" and _admin_count(connection) <= 1:
                return "Cannot demote the last administrator."
            connection.execute("UPDATE staff_users SET role = ? WHERE id = ?", (role, user_id))
    finally:
        connection.close()
    _audit(actor, f"Changed role of '{row['username']}' to {role}")
    return None


def delete_user(user_id: int, actor_id: int, actor: str) -> str | None:
    if user_id == actor_id:
        return "You cannot delete your own account."
    connection = get_connection()
    try:
        with connection:
            row = connection.execute(
                "SELECT username, role FROM staff_users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                return "User not found."
            if row["role"] == "admin" and _admin_count(connection) <= 1:
                return "Cannot delete the last administrator."
            connection.execute("DELETE FROM staff_users WHERE id = ?", (user_id,))
    finally:
        connection.close()
    _audit(actor, f"Deleted staff user '{row['username']}'")
    return None


def current_user() -> dict | None:
    return st.session_state.get(SESSION_KEY)


def is_admin() -> bool:
    user = current_user()
    return bool(user and user["role"] == "admin")


def logout() -> None:
    st.session_state.pop(SESSION_KEY, None)
    st.session_state.pop("td_name", None)


def _login_user(user: dict) -> None:
    st.session_state[SESSION_KEY] = user
    st.session_state["td_name"] = user["display_name"]
    st.session_state.pop("login_attempts", None)
    st.rerun()


def _center_options() -> list[str]:
    from modules.constants import HOST_CENTERS

    return [code for code in HOST_CENTERS if code != "CHUSBC"] + ["CHUSBC"]


def _setup_form() -> None:
    st.title("Create the first administrator")
    st.info("No staff accounts exist yet. This account will be able to add other tournament directors.")
    with st.form("first_admin"):
        username = st.text_input("Username")
        display_name = st.text_input("Display name")
        center = st.selectbox("Center", _center_options())
        password = st.text_input("Password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create administrator", type="primary")
    if not submitted:
        return
    if password != confirm:
        st.error("Passwords do not match.")
        return
    error = create_staff_user(username, password, display_name, center, "admin")
    if error:
        st.error(error)
        return
    user = authenticate(username, password)
    if user:
        _login_user(user)


def _login_form() -> None:
    from views.auth_view import render_auth_view

    render_auth_view()


def try_login(username: str, password: str) -> str | None:
    """Sign in on valid, approved credentials; otherwise returns a message kind: 'locked', 'invalid' or 'pending'."""
    attempts = st.session_state.get("login_attempts", 0)
    if attempts >= MAX_LOGIN_ATTEMPTS:
        return "locked"
    user = authenticate(username, password)
    if user is None:
        st.session_state["login_attempts"] = attempts + 1
        return "invalid"
    if not user.get("is_approved"):
        return "pending"
    _login_user(user)
    return None


def require_login() -> dict | None:
    """Render the setup or login form unless signed in; returns the user when authenticated."""
    user = current_user()
    if user:
        return user
    if staff_count() == 0:
        _setup_form()
    else:
        _login_form()
    return None
