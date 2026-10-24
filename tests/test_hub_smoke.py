"""Headless smoke: the Active Squad hub renders with the undo box (catches NameErrors in the page)."""
from streamlit.testing.v1 import AppTest

from modules import db_state
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template


def test_hub_renders_with_undo(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setattr(db_state, "DB_PATH", path)
    db_state.init_db()
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "FHL")
    conn = db_state.get_connection()
    with conn:
        conn.execute("UPDATE tournaments SET status='active' WHERE id=?", (tid,))
        conn.execute("INSERT INTO bowlers (tournament_id, name, handicap, lane_assignment) VALUES (?, 'Ann', 0, 1)", (tid,))
    conn.close()
    from views.hubs.active_squad import _save_score
    _save_score(tid, 1, 1, 200, 0, "Scott")
    at = AppTest.from_string(
        "from pathlib import Path\nfrom modules import db_state\n"
        f"db_state.DB_PATH = Path({str(path)!r})\n"
        "import streamlit as st\n"
        "st.session_state['user'] = {'username': 'a', 'display_name': 'Scott', 'role': 'admin'}\n"
        f"st.session_state['active_tournament_id'] = {tid}\n"
        "from views.hubs.active_squad import render_active_squad\nrender_active_squad()\n", default_timeout=30).run()
    assert not at.exception, at.exception
    # Fresh change -> open undo box; setup links tucked into one collapsed expander; chat is compact.
    assert any("Undo last change" in m.value for m in at.markdown)
    labels = [e.label for e in at.expander]
    assert any("Event setup" in l for l in labels) and any("Chat" in l for l in labels)
    assert not any("Floor-phone scoring link" in l or "Open kiosk" in l for l in labels)
    assert any("Needs verifying" in m.value for m in at.markdown)


def test_undo_box_collapses_when_changes_are_old():
    from components.undo_box import _is_fresh
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    assert _is_fresh((now - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"))
    assert not _is_fresh((now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"))
    assert not _is_fresh(None)
