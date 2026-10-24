"""Hub / Needs verifying / TD chat stay a handful of statements per rerun on the libsql adapter.

Remote Turso sends one network round trip per statement, so this budget is the lag we removed.
Scores are not cached: verify and undo are asserted fresh in test_td_team and test_undo.
"""
from streamlit.testing.v1 import AppTest

from modules import db_state, td_team
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
from views.hubs.active_squad import _matrix_snapshot


def _count(monkeypatch):
    statements = []
    orig = db_state.LibsqlConnection.execute

    def execute(self, sql, params=()):
        statements.append(" ".join(str(sql).split()))
        return orig(self, sql, params)

    monkeypatch.setattr(db_state.LibsqlConnection, "execute", execute)
    return statements


def _hub_script(path, tid: int) -> str:
    # Same database work as a logged-in Active Squad rerun (see app.py render_desk).
    return f"""
from pathlib import Path
import os
os.environ["PRISM_DB_ENGINE"] = "libsql-file"
from modules import db_state
db_state.DB_PATH = Path({str(path)!r})
import streamlit as st
st.session_state["user"] = {{"username": "scott", "display_name": "Scott", "role": "admin", "center_affiliation": "CHUSBC"}}
st.session_state["active_tournament_id"] = {tid}
from components.event_picker import staff_event_bar
from components.prism_dock import collect_view_state
from modules.practice import is_practice
from modules.td_team import heartbeat
from views.hubs.active_squad import render_active_squad
collect_view_state("Active Squad Hub")
staff_event_bar()
heartbeat("scott", "Scott", {tid})
is_practice({tid})
render_active_squad()
"""


def test_hub_and_fragments_stay_within_budget(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("PRISM_DB_ENGINE", "libsql-file")
    path = tmp_path / "t.db"
    monkeypatch.setattr(db_state, "DB_PATH", path)
    statements = _count(monkeypatch)
    db_state.init_db()
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "FHL")
    conn = db_state.get_connection()
    with conn:
        bid = conn.execute(
            "INSERT INTO bowlers (tournament_id, name, entering_avg, handicap, lane_assignment, lineup_position) "
            "VALUES (?, 'Ann', 180, 36, 1, 1)",
            (tid,),
        ).lastrowid
        conn.execute(
            "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, hdcp_score, total_score, recorded_by, verified) "
            "VALUES (?, ?, 1, 150, 36, 186, 'floor', 0)",
            (tid, bid),
        )
        conn.execute("INSERT INTO td_messages (tournament_id, user, text) VALUES (?, 'Pat', 'lane 1')", (tid,))
    conn.close()

    script = _hub_script(path, tid)
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    statements.clear()
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    # Steady state: connection already open, logos already cached. Before this work the
    # same rerun was 46 statements / 18 connections (divisions squad, two heartbeats).
    assert len(statements) <= 16, statements
    assert not any(s.startswith("PRAGMA") for s in statements), statements
    assert not any("event_logos" in s for s in statements), statements

    statements.clear()
    queue, done = td_team.verification_board(tid)
    assert len(statements) == 1
    assert [r["name"] for r in queue] == ["Ann"] and done == []
    statements.clear()
    assert td_team.get_messages(tid)[0]["text"] == "lane 1"
    assert len(statements) == 1
    statements.clear()
    td_team.tds_on_duty(tid)
    assert len(statements) == 1
    statements.clear()
    scores, _done = _matrix_snapshot(tid, 1)
    assert len(statements) == 1 and list(scores.values())[0]["scratch_score"] == 150

    td_team.verify_score(queue[0]["id"], "Scott")
    assert td_team.verification_board(tid)[0] == []
    assert td_team.needs_verifying(tid) == []
