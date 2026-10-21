import os

import streamlit as st
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from db_state import fetch_users_df, write_users_df


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


def _verify_password(password_hash: str, password: str) -> bool:
    if not password_hash or not password:
        return False
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError, TypeError):
        return False


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
    if not _verify_password(str(user["password_hash"]), password):
        return None
    if PASSWORD_HASHER.check_needs_rehash(str(user["password_hash"])):
        users.loc[user.name, "password_hash"] = hash_password(password)
        write_users_df(users)
    return user.to_dict()


def render_auth_portal():
    _ensure_default_staff()
    st.title("Prism Lane Control")
    st.subheader("Staff sign in")
    with st.form("staff_login"):
        username = st.text_input("Username").strip()
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submitted:
        user = verify_user_login(username, password)
        if user:
            st.session_state.authenticated = True
            st.session_state.username = user["username"]
            st.session_state.td_name = user["name"] or user["username"]
            st.session_state.td_role = user["role"]
            st.session_state.center_id = user["center_id"]
            st.session_state.preferred_mode = user["preferred_mode"]
            st.rerun()
        st.error("Invalid username or password, or the account is not active.")
    if not all(_configured_password(staff["password_setting"]) for staff in DEFAULT_STAFF):
        st.info(
            "Configure PRISM_ADMIN_PASSWORD and PRISM_KIOSK_TV_PASSWORD "
            "in the environment or Streamlit secrets to activate the default accounts."
        )


__all__ = [
    "DEFAULT_STAFF", "fetch_users_df", "hash_password", "render_auth_portal",
    "verify_user_login", "write_users_df",
]