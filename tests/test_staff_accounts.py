"""Staff Accounts: create stores email, center, and role, and an admin can edit them."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from modules import auth, db_state
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


def _labeled(widgets, label):
    found = [widget for widget in widgets if widget.label == label]
    assert found, (label, [widget.label for widget in widgets])
    return found


def _one(widgets, label):
    found = _labeled(widgets, label)
    assert len(found) == 1, (label, [widget.label for widget in widgets])
    return found[0]


def _submit(at, *, username, display_name, password, center="HL", role="admin", email=""):
    # The manage form sits above Add and repeats Display name, Email, Center, and Role.
    # The add form is last.
    _one(at.text_input, "Username").set_value(username)
    _labeled(at.text_input, "Display name")[-1].set_value(display_name)
    _labeled(at.text_input, "Email (optional)")[-1].set_value(email)
    _one(
        at.text_input, f"Temporary password (min {MIN_PASSWORD_LENGTH} characters)"
    ).set_value(password)
    _labeled(at.selectbox, "Center")[-1].set_value(center)
    _labeled(at.selectbox, "Role")[-1].set_value(role)
    return _one(at.button, "Add").click().run()


def _insert_staff(*, username, display_name, email, center, role, password_hash="hash"):
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO staff_users
            (username, password_hash, display_name, email, center_affiliation, role, is_approved)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (username, password_hash, display_name, email, center, role),
        )
    conn.close()


def _account(username):
    rows = query(
        """
        SELECT username, display_name, email, center_affiliation, role, is_approved, password_hash
        FROM staff_users WHERE username = ?
        """,
        (username,),
    )
    assert len(rows) == 1, username
    return rows[0]


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


def test_center_and_role_cannot_be_passed_positionally():
    with pytest.raises(TypeError):
        create_staff_user("scott", "password1", "Scott", "CHUSBC", "admin")


def test_create_stores_optional_email(staff_db):
    at = _submit(
        _page(staff_db),
        username="casey",
        display_name="Casey Director",
        password="temporary1",
        email="  casey@example.com  ",
        center="CHUSBC",
        role="td",
    )
    assert not at.exception, at.exception
    assert [item.value for item in at.success] == ["Staff account created successfully."]
    row = _account("casey")
    assert row["email"] == "casey@example.com"
    assert row["center_affiliation"] == "CHUSBC"
    assert row["role"] == "td"
    assert row["display_name"] == "Casey Director"


def test_keywords_do_not_shift_email_center_or_role(staff_db):
    ok, message = create_staff_user(
        "pat",
        "password1",
        "Pat Director",
        email="pat@example.com",
        center_affiliation="CHUSBC",
        role="admin",
    )
    assert ok, message
    row = _account("pat")
    assert row["email"] == "pat@example.com"
    assert row["center_affiliation"] == "CHUSBC"
    assert row["role"] == "admin"


def test_manage_saves_display_name_email_center_and_role(staff_db):
    ok, message = create_staff_user(
        "casey",
        "password1",
        "Casey Director",
        email="",
        center_affiliation="HL",
        role="td",
    )
    assert ok, message
    casey_id = query("SELECT id FROM staff_users WHERE username = ?", ("casey",))[0]["id"]

    at = _page(staff_db)
    _one(at.selectbox, "Select an account to manage").set_value(casey_id)
    at = at.run()
    assert not at.exception, at.exception

    _labeled(at.text_input, "Display name")[0].set_value("Casey D.")
    _labeled(at.text_input, "Email (optional)")[0].set_value("casey@example.com")
    _labeled(at.selectbox, "Center")[0].set_value("CHUSBC")
    _labeled(at.selectbox, "Role")[0].set_value("admin")
    at = _one(at.button, "Save account").click().run()

    assert not at.exception, at.exception
    assert [item.value for item in at.success] == ["Updated casey."]
    row = _account("casey")
    assert row["display_name"] == "Casey D."
    assert row["email"] == "casey@example.com"
    assert row["center_affiliation"] == "CHUSBC"
    assert row["role"] == "admin"
    assert _account("admin")["role"] == "admin"
    assert _account("admin")["email"] == ""


def test_manage_rejects_a_blank_display_name(staff_db):
    user_id = query("SELECT id FROM staff_users WHERE username = ?", ("admin",))[0]["id"]
    error = auth.update_staff_profile(
        user_id,
        display_name="   ",
        email="ada@example.com",
        center_affiliation="HL",
        role="admin",
        admin_name="Ada Admin",
    )
    assert error == "Display name is required."
    row = _account("admin")
    assert row["display_name"] == "Ada Admin"
    assert row["email"] == ""
    assert row["center_affiliation"] == "CHUSBC"


def test_shifted_shape_is_only_the_positional_bug():
    assert auth.shifted_staff_fields("CHUSBC", "admin", "td") == {
        "email": "",
        "center_affiliation": "CHUSBC",
        "role": "admin",
    }
    assert auth.shifted_staff_fields("HL", "td", "td") == {
        "email": "",
        "center_affiliation": "HL",
        "role": "td",
    }
    assert auth.shifted_staff_fields("scott@example.com", "CHUSBC", "admin") is None
    assert auth.shifted_staff_fields("CHUSBC", "HL", "td") is None
    assert auth.shifted_staff_fields("", "admin", "td") is None


def test_init_db_repairs_shifted_scott_and_leaves_everyone_else(staff_db):
    _insert_staff(
        username="scott",
        display_name="Scott",
        email="CHUSBC",
        center="admin",
        role="td",
        password_hash="keep-me",
    )
    _insert_staff(
        username="casey",
        display_name="Casey",
        email="CHUSBC",
        center="admin",
        role="td",
    )

    assert db_state.init_db() is None
    scott = _account("scott")
    assert scott["display_name"] == "Scott"
    assert scott["email"] == ""
    assert scott["center_affiliation"] == "CHUSBC"
    assert scott["role"] == "admin"
    assert scott["password_hash"] == "keep-me"

    # Same bad shape on a different username is left for an admin to edit.
    casey = _account("casey")
    assert casey["email"] == "CHUSBC"
    assert casey["center_affiliation"] == "admin"
    assert casey["role"] == "td"

    logged = query(
        "SELECT action_description FROM audit_log WHERE action_description LIKE ?",
        ("%Repaired staff account%",),
    )
    assert len(logged) == 1
    assert "email cleared" in logged[0]["action_description"]
    assert "@" not in logged[0]["action_description"]

    db_state.init_db()
    assert _account("scott")["email"] == ""
    assert _account("scott")["role"] == "admin"
    logged_again = query(
        "SELECT action_description FROM audit_log WHERE action_description LIKE ?",
        ("%Repaired staff account%",),
    )
    assert len(logged_again) == 1


def test_a_real_scott_profile_is_not_rewritten(staff_db):
    _insert_staff(
        username="scott",
        display_name="Scott Kramer",
        email="kept@example.com",
        center="HL",
        role="admin",
    )
    assert auth.repair_shifted_scott_account() is False
    row = _account("scott")
    assert row["email"] == "kept@example.com"
    assert row["center_affiliation"] == "HL"
    assert row["role"] == "admin"
    assert row["display_name"] == "Scott Kramer"


def test_shifted_account_form_offers_the_corrected_values(staff_db):
    _insert_staff(
        username="casey",
        display_name="Casey",
        email="HL",
        center="admin",
        role="td",
    )
    casey_id = query("SELECT id FROM staff_users WHERE username = ?", ("casey",))[0]["id"]
    at = _page(staff_db)
    _one(at.selectbox, "Select an account to manage").set_value(casey_id)
    at = at.run()
    assert not at.exception, at.exception
    assert _labeled(at.text_input, "Email (optional)")[0].value == ""
    assert _labeled(at.selectbox, "Center")[0].value == "HL"
    assert _labeled(at.selectbox, "Role")[0].value == "admin"
    assert any("email empty" in item.value for item in at.warning)
    # Still the bad row until an admin saves. Nothing was invented.
    assert _account("casey")["email"] == "HL"
    assert _account("casey")["role"] == "td"

    at = _one(at.button, "Save account").click().run()
    assert not at.exception, at.exception
    assert [item.value for item in at.success] == ["Updated casey."]
    row = _account("casey")
    assert row["email"] == ""
    assert row["center_affiliation"] == "HL"
    assert row["role"] == "admin"
    assert row["display_name"] == "Casey"


def test_signed_in_scott_session_is_corrected():
    at = AppTest.from_string(
        "import streamlit as st\n"
        "from modules.auth import apply_shifted_scott_session_repair\n"
        "st.session_state['user'] = {\n"
        "    'id': 7, 'username': 'scott', 'display_name': 'Scott',\n"
        "    'email': 'CHUSBC', 'center_affiliation': 'admin', 'role': 'td',\n"
        "}\n"
        "apply_shifted_scott_session_repair()\n"
        "user = st.session_state['user']\n"
        "st.text_input('role', value=user['role'])\n"
        "st.text_input('center', value=user['center_affiliation'])\n"
        "st.text_input('email', value=user['email'])\n"
        "st.text_input('name', value=user['display_name'])\n",
        default_timeout=30,
    ).run()
    assert not at.exception, at.exception
    values = {item.label: item.value for item in at.text_input}
    assert values == {"role": "admin", "center": "CHUSBC", "email": "", "name": "Scott"}


def test_shifted_fields_do_not_crash_on_non_strings():
    assert auth.shifted_staff_fields(None, None, None) is None
    assert auth.shifted_staff_fields(1, "admin", "td") is None
    assert auth.shifted_staff_fields("CHUSBC", None, "td") is None


_APP = Path(__file__).resolve().parent.parent / "app.py"


def _desk(user):
    at = AppTest.from_file(str(_APP), default_timeout=60)
    at.session_state["user"] = user
    at.run()
    return at


_SHIFTED_SCOTT = {
    "id": 7,
    "username": "scott",
    "display_name": "Scott",
    "email": "CHUSBC",
    "center_affiliation": "admin",
    "role": "td",
}


def test_desk_repairs_shifted_scott_session(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "desk.db")
    at = _desk(dict(_SHIFTED_SCOTT))
    assert not at.exception, at.exception
    user = at.session_state["user"]
    assert user["role"] == "admin"
    assert user["center_affiliation"] == "CHUSBC"
    assert user["email"] == ""
    assert user["display_name"] == "Scott"
    assert any("ADMIN" in item.value for item in at.markdown)


def test_desk_opens_when_auth_has_no_session_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "desk.db")
    monkeypatch.delattr(auth, "apply_shifted_scott_session_repair")
    at = _desk(dict(_SHIFTED_SCOTT))
    assert not at.exception, at.exception
    user = at.session_state["user"]
    assert user["role"] == "admin"
    assert user["center_affiliation"] == "CHUSBC"
    assert user["email"] == ""
    assert user["display_name"] == "Scott"
