"""Cold open skips schema DDL once the stamp is current. Desk reruns skip Co-Pilot queries.

Remote Turso sends one round trip per statement, so the counts below are the lag we removed.
"""
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from modules import db_state


def _statements(monkeypatch):
    executed = []
    commits = []
    orig_execute = db_state.LibsqlConnection.execute
    orig_commit = db_state.LibsqlConnection.commit

    def execute(self, sql, params=()):
        executed.append(" ".join(str(sql).split()))
        return orig_execute(self, sql, params)

    def commit(self):
        commits.append("commit")
        return orig_commit(self)

    monkeypatch.setattr(db_state.LibsqlConnection, "execute", execute)
    monkeypatch.setattr(db_state.LibsqlConnection, "commit", commit)
    return executed, commits


def _drain_pool():
    with db_state._pool_guard:
        idle = [c for conns in db_state._pool_idle.values() for c in conns]
        db_state._pool_idle.clear()
    for conn in idle:
        db_state._really_close(conn)


def _use_libsql(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("PRISM_DB_ENGINE", "libsql-file")
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")


def test_old_database_without_version_still_migrates(tmp_path, monkeypatch):
    """A pre-stamp database is missing later columns. init_db must add them and then stamp."""
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PRISM_DB_ENGINE", raising=False)
    path = tmp_path / "old.db"
    monkeypatch.setattr(db_state, "DB_PATH", path)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE tournaments (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            host_center TEXT NOT NULL,
            squad_format TEXT NOT NULL DEFAULT 'Singles',
            game_count INTEGER NOT NULL DEFAULT 3,
            pin_verifier TEXT NOT NULL DEFAULT '6199',
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE bowlers (
            id INTEGER PRIMARY KEY,
            tournament_id INTEGER NOT NULL,
            name TEXT NOT NULL
        );
        CREATE TABLE scores (
            id INTEGER PRIMARY KEY,
            tournament_id INTEGER NOT NULL,
            bowler_id INTEGER NOT NULL,
            game_number INTEGER NOT NULL,
            scratch_score INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE staff_users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'td'
        );
        INSERT INTO tournaments (name, host_center) VALUES ('Old Event', 'FHL');
        INSERT INTO bowlers (tournament_id, name) VALUES (1, 'Ann');
        """
    )
    conn.commit()
    conn.close()

    db_state.init_db()

    conn = sqlite3.connect(path)
    try:
        tournament_cols = {row[1] for row in conn.execute("PRAGMA table_info(tournaments)")}
        staff_cols = {row[1] for row in conn.execute("PRAGMA table_info(staff_users)")}
        bowler_cols = {row[1] for row in conn.execute("PRAGMA table_info(bowlers)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute("SELECT version FROM prism_schema").fetchone()[0]
        assert conn.execute("SELECT name FROM tournaments").fetchone()[0] == "Old Event"
        assert conn.execute("SELECT name FROM bowlers").fetchone()[0] == "Ann"
    finally:
        conn.close()
    assert {"is_practice", "cert_number", "lane_pattern", "handicap_base"} <= tournament_cols
    assert "email" in staff_cols and "age_group" in bowler_cols
    assert {"cut_rolloffs", "score_history", "td_messages", "prism_schema"} <= tables
    assert version == db_state.SCHEMA_VERSION


def test_current_database_skips_schema_ddl(tmp_path, monkeypatch):
    """A stamped database does not CREATE or ALTER. The round trips are the version read plus the scott check."""
    libsql = pytest.importorskip("libsql")
    assert libsql is not None
    _use_libsql(tmp_path, monkeypatch)
    executed, commits = _statements(monkeypatch)

    db_state.init_db()
    first_exec, first_commits = len(executed), len(commits)
    assert any(sql.lstrip().upper().startswith("CREATE TABLE") for sql in executed)
    assert db_state.SCHEMA_VERSION >= 1

    executed.clear()
    commits.clear()
    _drain_pool()
    db_state.init_db()

    assert not any(sql.lstrip().upper().startswith(("CREATE", "ALTER")) for sql in executed), executed
    assert len(executed) <= 6, executed
    assert len(commits) <= 2, commits
    assert len(executed) * 3 < first_exec, (len(executed), first_exec)
    assert len(commits) < first_commits, (len(commits), first_commits)
    # Cold open of a current database: version read, then the idempotent scott repair.
    assert any("prism_schema" in sql for sql in executed)
    assert any("LOWER(username) = 'scott'" in sql for sql in executed)

    # Dropping the stamp is an old/missing-version database that already has tables.
    # The next open must migrate again, not trust a missing version.
    conn = db_state.get_connection()
    conn.execute("DROP TABLE prism_schema")
    conn.commit()
    conn.close()
    executed.clear()
    commits.clear()
    _drain_pool()
    db_state.init_db()
    assert any(sql.lstrip().upper().startswith("CREATE TABLE") for sql in executed), executed
    assert len(executed) > 15, executed
    conn = db_state.get_connection()
    try:
        version = conn.execute("SELECT version FROM prism_schema").fetchone()[0]
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tournaments)")}
    finally:
        conn.close()
    assert version == db_state.SCHEMA_VERSION
    assert "is_practice" in cols


def test_collect_view_state_does_not_build_screen_context(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("screen context was built during collect_view_state")

    monkeypatch.setattr("components.prism_dock.build_screen_context", boom)
    script = """
import streamlit as st
st.session_state["active_tournament_id"] = 7
from components.prism_dock import collect_view_state
state = collect_view_state("Intake Gateway")
assert state["view"] == "Intake Gateway"
assert state["active_tournament_id"] == 7
assert "screen_context" not in state
"""
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception, app.exception


def test_analyze_click_builds_screen_context(monkeypatch):
    built = []

    def fake_context(view, tournament_id):
        built.append((view, tournament_id))
        return {"page": view, "warnings": ["from test"]}

    monkeypatch.setattr("components.prism_dock.build_screen_context", fake_context)
    monkeypatch.setattr("components.prism_dock.get_prism_ai_guidance", lambda state, user_prompt=None: "tips")
    script = """
import streamlit as st
st.session_state["active_tournament_id"] = 7
from components.prism_dock import collect_view_state, render_prism_dock
render_prism_dock("Intake Gateway", collect_view_state("Intake Gateway"))
"""
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception, app.exception
    assert built == []
    analyze = next(button for button in app.button if "Analyze" in button.label)
    app = analyze.click().run()
    assert not app.exception, app.exception
    assert built == [("Intake Gateway", 7)]


def test_load_copilot_state_keeps_a_context_it_was_given():
    from components.prism_dock import load_copilot_state

    state = {"view": "Intake Gateway", "screen_context": {"page": "Intake Gateway"}}
    assert load_copilot_state(state) is state


def test_intake_reuses_the_tournament_loaded_for_practice(tmp_path, monkeypatch):
    pytest.importorskip("libsql")
    _use_libsql(tmp_path, monkeypatch)
    executed, _commits = _statements(monkeypatch)
    db_state.init_db()
    conn = db_state.get_connection()
    with conn:
        tournament_id = conn.execute(
            "INSERT INTO tournaments (name, host_center, squad_format, game_count, pin_verifier, status, is_practice) "
            "VALUES ('PRACTICE - Not Real', 'Practice Lanes', 'Singles', 3, '0000', 'active', 1)"
        ).lastrowid
    conn.close()
    _drain_pool()
    executed.clear()

    script = f"""
from pathlib import Path
import os
os.environ["PRISM_DB_ENGINE"] = "libsql-file"
from modules import db_state
db_state.DB_PATH = Path({str(tmp_path / "t.db")!r})
import streamlit as st
st.session_state["active_tournament_id"] = {tournament_id}
from components.prism_dock import collect_view_state
from modules.practice import is_practice
from views.intake_gateway import _get_active_tournament
collect_view_state("Intake Gateway")
assert is_practice({tournament_id})
row = _get_active_tournament()
assert row["id"] == {tournament_id}
assert row["is_practice"] == 1
"""
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception, app.exception
    tournament_reads = [sql for sql in executed if "FROM TOURNAMENTS" in sql.upper()]
    assert tournament_reads == ["SELECT * FROM tournaments WHERE id = ?"], executed
    assert not any("per_game" in sql or "group_concat" in sql.lower() for sql in executed), executed
