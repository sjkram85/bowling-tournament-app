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
    assert any("Undo last change" in e.label for e in at.expander)
