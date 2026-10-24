import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from modules import db_state
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield tmp_path


def _count(table):
    conn = db_state.get_connection()
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_filename():
    t = datetime(2026, 12, 6, 9, 5, tzinfo=ZoneInfo("America/New_York"))
    assert db_state.backup_filename(t) == "prism-backup-2026-12-06-0905-ET.db"


def test_round_trip_with_safety_copy(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    conn = db_state.get_connection()
    with conn:
        conn.execute("INSERT INTO bowlers (tournament_id, name) VALUES (?, 'Ann')", (tid,))
        conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score) VALUES (?,1,1,200)", (tid,))
    conn.close()
    data = db_state.backup_bytes()
    info = db_state.inspect_backup(data)
    assert (info["events"], info["bowlers"], info["scores"]) == (1, 1, 1)
    # disaster: data changes / disappears
    conn = db_state.get_connection()
    with conn:
        conn.execute("DELETE FROM scores"); conn.execute("DELETE FROM bowlers")
        conn.execute("INSERT INTO bowlers (tournament_id, name) VALUES (?, 'New')", (tid,))
    conn.close()
    safety = db_state.restore_from_bytes(data)
    assert _count("bowlers") == 1 and _count("scores") == 1
    assert db_state.inspect_backup(safety.read_bytes())["scores"] == 0  # safety copy = pre-restore data


def test_old_backup_gets_migrated(db, tmp_path):
    old = tmp_path / "old.db"
    c = sqlite3.connect(old)
    c.executescript("CREATE TABLE tournaments (id INTEGER PRIMARY KEY, name TEXT);"
                    "CREATE TABLE bowlers (id INTEGER PRIMARY KEY, tournament_id INTEGER, name TEXT);"
                    "CREATE TABLE scores (id INTEGER PRIMARY KEY, tournament_id INTEGER, bowler_id INTEGER,"
                    " game_number INTEGER, scratch_score INTEGER);"
                    "CREATE TABLE staff_users (id INTEGER PRIMARY KEY, username TEXT);"
                    "INSERT INTO tournaments (name) VALUES ('Old Event');")
    c.close()
    db_state.restore_from_bytes(old.read_bytes())
    conn = db_state.get_connection()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tournaments)")}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "is_practice" in cols and "cut_rolloffs" in tables and _count("tournaments") == 1


def test_rejects_non_prism_files(db, tmp_path):
    with pytest.raises(ValueError):
        db_state.inspect_backup(b"hello, not a database")
    other = tmp_path / "other.db"
    c = sqlite3.connect(other); c.execute("CREATE TABLE pets (id INTEGER)"); c.commit(); c.close()
    with pytest.raises(ValueError, match="not a Prism backup"):
        db_state.inspect_backup(other.read_bytes())
    before = _count("tournaments")
    with pytest.raises(ValueError):
        db_state.restore_from_bytes(other.read_bytes())
    assert _count("tournaments") == before


def _page(role):
    return AppTest.from_string(
        "import streamlit as st\n"
        f"st.session_state['user'] = {{'username': 'u', 'display_name': 'U', 'role': '{role}'}}\n"
        "from views.hubs.backup_restore import render_backup_restore\nrender_backup_restore()\n").run()


def test_non_admin_hidden(db):
    at = _page("td")
    assert at.error and not at.button and not at.title
    nav = open("app.py").read()
    i = nav.index("if auth.is_admin():")
    assert nav.index("render_backup_restore", i) > i  # page only added for admins
    at = _page("admin")
    assert any("Backup" in t.value for t in at.title) and at.button
