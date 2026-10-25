"""Staff Accounts: creating a user shows a success message and refreshes the list."""

import pytest
from streamlit.testing.v1 import AppTest

from modules import db_state
from modules.auth import MIN_PASSWORD_LENGTH, create_staff_user
from modules.standings import query
from views.hubs.staff_accounts import interpret_create_result


def test_create_result_is_a_message_not_the_tuple():
    level, message = interpret_create_result((True, "Staff account created successfully."))
    assert level == "success"
    assert message == "Staff account created successfully."
    assert not message.startswith("(")

    level, message = interpret_create_result((False, "Username is already taken."))
    assert level == "error"
    assert message == "Username is already taken."
    assert not message.startswith("(")


@pytest.fixture
def staff_db(tmp_path, monkeypatch):
    path = tmp_path / "staff.db"
    monkeypatch.setattr(db_state, "DB_PATH", path)
    db_state.init_db()
    ok, message = create_staff_user(
        "admin", "password1", "Ada Admin", center_affiliation="CHUSBC", role="admin"
    )
    assert ok, message
    return path


def _page(path):
    return AppTest.from_string(
        "from pathlib import Path\n"
        "from modules import db_state\n"
        f"db_state.DB_PATH = Path({str(path)!r})\n"
        "import streamlit as st\n"
        "st.session_state['user'] = {"
        "'id': 1, 'username': 'admin', 'display_name': 'Ada Admin', 'role': 'admin'}\n"
        "from views.hubs.staff_accounts import render_staff_accounts\n"
        "render_staff_accounts()\n",
        default_timeout=60,
    ).run()


def _one(widgets, label):
    found = [widget for widget in widgets if widget.label == label]
    assert len(found) == 1, (label, [widget.label for widget in widgets])
    return found[0]


def _submit(at, *, username, display_name, password, center="HL", role="admin"):
    _one(at.text_input, "Username").set_value(username)
    _one(at.text_input, "Display name").set_value(display_name)
    _one(
        at.text_input, f"Temporary password (min {MIN_PASSWORD_LENGTH} characters)"
    ).set_value(password)
    _one(at.selectbox, "Center").set_value(center)
    roles = [box for box in at.selectbox if box.label == "Role"]
    assert roles, [box.label for box in at.selectbox]
    roles[-1].set_value(role)
    return _one(at.button, "Add").click().run()


def _usernames(at):
    frame = at.dataframe[0].value
    return list(frame["username"])


def test_short_password_is_a_clear_error(staff_db):
    at = _submit(
        _page(staff_db),
        username="casey",
        display_name="Casey Director",
        password="short",
    )
    assert not at.exception, at.exception
    errors = [item.value for item in at.error]
    assert errors == [f"Password must be at least {MIN_PASSWORD_LENGTH} characters."]
    assert not any(item.value.startswith("(") for item in at.error)
    assert not at.success
    assert _usernames(at) == ["admin"]
    assert query("SELECT id FROM staff_users WHERE username = ?", ("casey",)) == []


def test_create_shows_success_and_refreshes_the_list(staff_db):
    at = _page(staff_db)
    assert not at.exception, at.exception
    assert _usernames(at) == ["admin"]

    at = _submit(
        at,
        username="casey",
        display_name="Casey Director",
        password="temporary1",
        center="HL",
        role="admin",
    )
    assert not at.exception, at.exception
    assert [item.value for item in at.success] == ["Staff account created successfully."]
    assert not any(str(item.value).startswith("(") for item in at.error)
    assert "casey" in _usernames(at)

    rows = query(
        "SELECT username, display_name, email, center_affiliation, role, is_approved "
        "FROM staff_users WHERE username = ?",
        ("casey",),
    )
    assert rows == [
        {
            "username": "casey",
            "display_name": "Casey Director",
            "email": "",
            "center_affiliation": "HL",
            "role": "admin",
            "is_approved": 1,
        }
    ]
