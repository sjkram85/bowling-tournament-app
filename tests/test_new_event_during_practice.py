"""New on the intake gateway while a practice session is open.

The intake page is the app default, so Streamlit's page.url_path is "" and the
path "intake" passed to st.Page is ignored. Guarding st.switch_page with
`url_path != "intake"` is true on that page, and the switch runs forever.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from components.event_picker import should_switch_to_intake_for_new_event
from modules import db_state, practice

_APP = Path(__file__).resolve().parent.parent / "app.py"
_SCOTT = {
    "id": 1,
    "username": "scott",
    "display_name": "Scott",
    "email": "",
    "center_affiliation": "CHUSBC",
    "role": "admin",
}


def test_default_intake_page_does_not_switch_again():
    # Old guard `page.url_path != "intake"` stays true on this page: the default
    # page's url_path is "" even though the page was registered as "intake".
    assert should_switch_to_intake_for_new_event(True, "Intake Gateway") is False
    assert should_switch_to_intake_for_new_event(True, "Active Squad Hub") is True
    assert should_switch_to_intake_for_new_event(True, "Finals Closeout") is True
    assert should_switch_to_intake_for_new_event(False, "Active Squad Hub") is False
    assert should_switch_to_intake_for_new_event(None, "Intake Gateway") is False


def _click(at, label):
    found = [button for button in at.button if label in button.label]
    assert found, (label, [button.label for button in at.button])
    return found[0].click().run()


def test_new_during_practice_opens_a_real_intake(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "desk.db")
    db_state.init_db()
    practice_id = practice.create_practice_tournament()

    at = AppTest.from_file(str(_APP), default_timeout=45)
    at.session_state["user"] = dict(_SCOTT)
    at.session_state["active_tournament_id"] = practice_id
    at = at.run()
    assert not at.exception, at.exception
    assert any("PRACTICE MODE" in item.value for item in at.markdown)

    at = _click(at, "➕ New")
    assert not at.exception, at.exception
    assert any("Starting a new event" in item.value for item in at.info)
    assert not any("PRACTICE MODE" in item.value for item in at.markdown)
    assert any("Initialize Squad" in button.label for button in at.button)
    # Practice stays selected underneath so Back returns to it. The create
    # form must not treat that id as the event being built.
    assert at.session_state["active_tournament_id"] == practice_id
    assert at.session_state["intake_new_event"] is True

    at = _click(at, "← Back to my events")
    assert not at.exception, at.exception
    assert any("PRACTICE MODE" in item.value for item in at.markdown)
    assert "intake_new_event" not in at.session_state

    at = _click(at, "➕ New")
    at = _click(at, "🚀 Initialize Squad & Unlock Intake")
    assert not at.exception, at.exception
    assert not any("PRACTICE MODE" in item.value for item in at.markdown)
    assert any("CHUSBC Championship Squad" in item.value for item in at.markdown)

    conn = db_state.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, COALESCE(is_practice, 0) AS is_practice FROM tournaments WHERE status = 'active' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    by_id = {row["id"]: row for row in rows}
    assert by_id[practice_id]["is_practice"] == 1
    created = [row for row in rows if row["id"] != practice_id]
    assert len(created) == 1
    assert created[0]["is_practice"] == 0
    assert created[0]["name"] == "CHUSBC Championship Squad"
    assert at.session_state["active_tournament_id"] == created[0]["id"]
    assert "intake_new_event" not in at.session_state
