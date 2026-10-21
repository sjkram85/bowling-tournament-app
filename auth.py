import os
import hashlib
from datetime import datetime

import pandas as pd
import streamlit as st
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from db_state import fetch_td_pins, fetch_users_df, write_td_pin, write_users_df


PASSWORD_HASHER = PasswordHasher(type=Type.ID)
DEFAULT_STAFF = [
    {
        "username": "admin",
        "name": "Tournament Administrator",
        "role": "admin",
        "password_setting": "PRISM_ADMIN_PASSWORD",
    },
    {
        "username": "kiosk_tv",
        "name": "Concourse TV",
        "role": "kiosk_tv",
        "password_setting": "PRISM_KIOSK_TV_PASSWORD",
    },
]


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password must not be empty.")
    return PASSWORD_HASHER.hash(password)


def hash_secret(secret_text: str) -> str:
    return hash_password(str(secret_text).strip())


def verify_secret(stored_hash: str, plain_secret: str):
    if not stored_hash or not plain_secret:
        return False, False
    encoded = str(stored_hash).strip()
    secret = str(plain_secret).strip()
    if encoded.startswith("$argon2"):
        try:
            valid = PASSWORD_HASHER.verify(encoded, secret)
            return valid, PASSWORD_HASHER.check_needs_rehash(encoded)
        except (InvalidHashError, VerifyMismatchError, TypeError):
            return False, False
    legacy_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return (encoded == legacy_hash, encoded == legacy_hash)


def register_td_pin(td_name: str, pin: str) -> bool:
    clean_name = str(td_name or "").strip()
    clean_pin = str(pin or "").strip()
    if not clean_name or len(clean_pin) < 4 or len(clean_pin) > 6 or not clean_pin.isdigit():
        return False
    pin_hash = hash_secret(clean_pin)
    if not write_td_pin(
        clean_name,
        pin_hash,
        st.session_state.get("tournament_config", {}),
        st.session_state.get("brackets", []),
    ):
        return False
    st.session_state.setdefault("td_pins", {})[clean_name] = pin_hash
    return True


def verify_td_pin(td_name: str, pin: str) -> bool:
    clean_name = str(td_name or "").strip()
    clean_pin = str(pin or "").strip()
    stored_hash = fetch_td_pins().get(clean_name, "")
    valid, needs_rehash = verify_secret(stored_hash, clean_pin)
    if valid and needs_rehash:
        register_td_pin(clean_name, clean_pin)
    return valid


def _configured_password(setting_name: str):
    value = os.environ.get(setting_name)
    if value:
        return value
    try:
        return st.secrets.get(setting_name)
    except Exception:
        return None


def _ensure_default_staff():
    users = fetch_users_df()
    changed = False
    for staff in DEFAULT_STAFF:
        matching = users.index[users["username"] == staff["username"]].tolist()
        configured_password = _configured_password(staff["password_setting"])
        if matching:
            index = matching[0]
            if not users.loc[index, "password_hash"] and configured_password:
                users.loc[index, "password_hash"] = hash_password(configured_password)
                changed = True
            continue
        users.loc[len(users)] = {
            "username": staff["username"],
            "name": staff["name"],
            "email": "",
            "password_hash": hash_password(configured_password) if configured_password else "",
            "role": staff["role"],
            "status": "active",
            "center_id": "association",
            "preferred_mode": "Advanced",
            "must_change_password": False,
            "created_at": "",
        }
        changed = True
    if changed:
        write_users_df(users)


def submit_user_registration(username: str, name: str, email: str, password: str):
    clean_username = str(username or "").strip().casefold()
    clean_name = str(name or "").strip()
    clean_email = str(email or "").strip().casefold()
    if not clean_username or not clean_name or not clean_email or not password:
        return False, "Username, name, email, and password are required."
    if "@" not in clean_email or "." not in clean_email.rsplit("@", 1)[-1]:
        return False, "Enter a valid email address."
    if len(password) < 6:
        return False, "Password must contain at least six characters."

    users = fetch_users_df()
    if users["username"].astype(str).str.casefold().eq(clean_username).any():
        return False, "That username is already registered or awaiting approval."
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    row = {
        "username": clean_username,
        "name": clean_name,
        "email": clean_email,
        "password_hash": hash_password(password),
        "role": "td",
        "status": "pending",
        "center_id": "association",
        "preferred_mode": "Advanced",
        "must_change_password": False,
        "created_at": timestamp,
    }
    updated = pd.concat([users, pd.DataFrame([row])], ignore_index=True)
    if not write_users_df(updated):
        return False, "Could not save the registration request."
    try:
        from engine_support import notify_admin_new_registration

        notify_admin_new_registration(clean_username, clean_name, clean_email, timestamp)
    except Exception:
        pass
    return True, "Registration submitted for administrator approval."


def verify_user_login(username: str, password: str):
    _ensure_default_staff()
    users = fetch_users_df()
    matches = users[
        (users["username"].str.casefold() == str(username).strip().casefold())
        & (users["status"].str.casefold() == "active")
    ]
    if matches.empty:
        return None
    user = matches.iloc[0]
    valid, needs_rehash = verify_secret(str(user["password_hash"]), password)
    if not valid:
        return None
    if needs_rehash:
        users.loc[user.name, "password_hash"] = hash_password(password)
        write_users_df(users)
    return user.to_dict()


def render_auth_portal():
    _ensure_default_staff()
    st.title("Prism Lane Control")
    login_tab, request_tab = st.tabs(["Staff sign in", "Request access"])
    with login_tab:
        with st.form("staff_login"):
            username = st.text_input("Username").strip()
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            user = verify_user_login(username, password)
            if user:
                st.session_state.authenticated = True
                st.session_state.username = user["username"]
                st.session_state.td_name = user["name"] or user["username"]
                st.session_state.td_role = user["role"]
                st.session_state.center_id = user["center_id"]
                st.session_state.preferred_mode = user["preferred_mode"]
                st.session_state.must_change_password = bool(user.get("must_change_password", False))
                st.rerun()
            users = fetch_users_df()
            pending = users[
                users["username"].astype(str).str.casefold().eq(username.casefold())
                & users["status"].astype(str).str.casefold().eq("pending")
            ]
            if not pending.empty:
                st.warning("This registration is awaiting administrator approval.")
            else:
                st.error("Invalid username or password, or the account is not active.")

    with request_tab:
        with st.form("staff_registration_request"):
            requested_username = st.text_input("Desired username").strip()
            requested_name = st.text_input("Full name").strip()
            requested_email = st.text_input("Email address").strip()
            requested_password = st.text_input("Password", type="password")
            request_submitted = st.form_submit_button("Submit access request", width="stretch")
        if request_submitted:
            success, message = submit_user_registration(
                requested_username, requested_name, requested_email, requested_password,
            )
            (st.success if success else st.error)(message)
            if success:
                from db_state import log_audit_event

                log_audit_event("STAFF_REGISTRATION_REQUESTED", f"{requested_username} ({requested_name}).")
    if not all(_configured_password(staff["password_setting"]) for staff in DEFAULT_STAFF):
        st.info(
            "Configure PRISM_ADMIN_PASSWORD and PRISM_KIOSK_TV_PASSWORD "
            "in the environment or Streamlit secrets to activate the default accounts."
        )


def render_password_change_portal():
    st.title("Change your password")
    st.info("An administrator requires a password change before you can continue.")
    with st.form("required_password_change"):
        new_password = st.text_input("New password", type="password")
        confirm_password = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Update password", type="primary")
    if not submitted:
        return
    if len(new_password) < 6:
        st.error("Password must contain at least six characters.")
        return
    if new_password != confirm_password:
        st.error("Passwords do not match.")
        return
    users = fetch_users_df()
    matches = users.index[users["username"].astype(str).str.casefold() == st.session_state.username.casefold()].tolist()
    if not matches:
        st.session_state.authenticated = False
        st.error("Your staff record could not be found. Please sign in again.")
        return
    users.loc[matches[0], "password_hash"] = hash_password(new_password)
    users.loc[matches[0], "must_change_password"] = False
    if not write_users_df(users):
        st.error("Could not save the new password.")
        return
    from db_state import log_audit_event

    log_audit_event("STAFF_PASSWORD_CHANGED", f"{st.session_state.username} completed a required password change.")
    st.session_state.must_change_password = False
    st.success("Password updated.")
    st.rerun()


__all__ = [
    "DEFAULT_STAFF", "fetch_users_df", "hash_password", "hash_secret", "register_td_pin",
    "render_auth_portal", "render_password_change_portal", "submit_user_registration",
    "verify_secret", "verify_td_pin", "verify_user_login", "write_users_df",
]