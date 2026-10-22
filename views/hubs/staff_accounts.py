"""Admin-only staff account management."""

import streamlit as st

from modules import auth
from modules.auth import MIN_PASSWORD_LENGTH, ROLES, create_staff_user, is_admin
from modules.constants import HOST_CENTERS
from modules.standings import query


def _staff() -> list[dict]:
    return query(
        "SELECT id, username, display_name, email, center_affiliation, role, is_approved, created_at "
        "FROM staff_users ORDER BY username"
    )


def _pending_requests(pending: list[dict], me: dict) -> None:
    with st.container(border=True):
        st.subheader(f"Pending access requests ({len(pending)})")
        for row in pending:
            info, approve, reject = st.columns([5, 1, 1])
            info.markdown(
                f"**{row['display_name']}** ({row['username']}) · {row['center_affiliation']} · "
                f"{row['email'] or 'no email'}"
            )
            if approve.button("Approve", key=f"approve_{row['id']}", type="primary", width="stretch"):
                error = auth.approve_user(row["id"], me["display_name"])
                if error:
                    st.error(error)
                else:
                    st.rerun()
            if reject.button("Reject", key=f"reject_{row['id']}", width="stretch"):
                error = auth.delete_user(row["id"], me["id"], me["display_name"])
                if error:
                    st.error(error)
                else:
                    st.rerun()


def _report(error: str | None, success: str) -> None:
    if error:
        st.error(error)
    else:
        st.success(success)


def _manage_selected(user: dict, me: dict) -> None:
    with st.container(border=True):
        st.subheader(f"Manage {user['display_name']} ({user['username']})")

        with st.form(f"reset_{user['id']}", clear_on_submit=True):
            new_password = st.text_input(
                f"New password (min {MIN_PASSWORD_LENGTH} characters)", type="password"
            )
            confirm = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Reset password", type="primary"):
                if new_password != confirm:
                    st.error("Passwords do not match.")
                else:
                    _report(
                        auth.reset_password(user["id"], new_password, me["display_name"]),
                        f"Password reset for {user['username']}. Share it with them securely.",
                    )

        role_cols = st.columns([2, 1])
        new_role = role_cols[0].selectbox(
            "Role", ROLES, index=ROLES.index(user["role"]), key=f"role_{user['id']}"
        )
        if role_cols[1].button("Update role", key=f"role_btn_{user['id']}", width="stretch"):
            if new_role == user["role"]:
                st.info("Role unchanged.")
            else:
                error = auth.set_role(user["id"], new_role, me["display_name"])
                if error:
                    st.error(error)
                else:
                    st.rerun()

        confirm_delete = st.checkbox(
            f"Permanently delete {user['username']}", key=f"del_confirm_{user['id']}"
        )
        if st.button(
            "Delete account",
            key=f"del_{user['id']}",
            disabled=not confirm_delete,
            width="stretch",
        ):
            error = auth.delete_user(user["id"], me["id"], me["display_name"])
            if error:
                st.error(error)
            else:
                st.rerun()


def _my_password(me: dict) -> None:
    with st.expander("Change my password"):
        with st.form("own_password", clear_on_submit=True):
            current = st.text_input("Current password", type="password")
            new_password = st.text_input(
                f"New password (min {MIN_PASSWORD_LENGTH} characters)", type="password"
            )
            confirm = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Change password"):
                if new_password != confirm:
                    st.error("Passwords do not match.")
                else:
                    _report(
                        auth.change_own_password(me["id"], current, new_password),
                        "Password changed.",
                    )


def render_staff_accounts() -> None:
    st.title("Staff Accounts")
    me = auth.current_user()
    if not is_admin() or me is None:
        st.error("Administrator access required.")
        return

    staff = _staff()
    pending = [row for row in staff if not row["is_approved"]]
    if pending:
        _pending_requests(pending, me)
    st.dataframe(
        [{k: v for k, v in row.items() if k != "id"} for row in staff],
        hide_index=True,
        width="stretch",
    )

    selected_id = st.selectbox(
        "Select an account to manage",
        [row["id"] for row in staff],
        format_func=lambda i: next(
            f"{r['display_name']} ({r['username']}, {r['role']})" for r in staff if r["id"] == i
        ),
    )
    _manage_selected(next(row for row in staff if row["id"] == selected_id), me)
    _my_password(me)

    with st.form("add_staff", clear_on_submit=True):
        st.subheader("Add staff member")
        username = st.text_input("Username")
        display_name = st.text_input("Display name")
        center = st.selectbox("Center", list(HOST_CENTERS))
        role = st.selectbox("Role", ROLES, index=ROLES.index("td"))
        password = st.text_input(
            f"Temporary password (min {MIN_PASSWORD_LENGTH} characters)", type="password"
        )
        if st.form_submit_button("Add", type="primary"):
            _report(
                create_staff_user(username, password, display_name, center, role),
                f"Added {display_name.strip()}.",
            )
