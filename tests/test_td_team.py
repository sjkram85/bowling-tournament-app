import sqlite3

import pytest

from modules import db_state, practice, td_team


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    conn = db_state.get_connection()
    with conn:
        conn.execute("INSERT INTO tournaments (name, host_center) VALUES ('A', 'C')")
        conn.execute("INSERT INTO tournaments (name, host_center) VALUES ('B', 'C')")
        conn.execute("INSERT INTO bowlers (tournament_id, name, lane_assignment) VALUES (1, 'Amy', 3)")
        conn.execute("INSERT INTO bowlers (tournament_id, name) VALUES (2, 'Bob')")
        conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, hdcp_score, total_score, recorded_by) VALUES (1,1,1,150,20,170,'floor')")
        conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score) VALUES (2,2,1,99,99)")
    conn.close()
    yield


def test_verify_queue_per_tournament_and_fix(db):
    q = td_team.needs_verifying(1)
    assert [s["name"] for s in q] == ["Amy"]
    assert td_team.verify_score(q[0]["id"], "Scott", new_scratch=155)
    assert td_team.needs_verifying(1) == []
    assert len(td_team.needs_verifying(2)) == 1
    done = td_team.recently_verified(1)[0]
    assert done["verified_by"] == "Scott" and done["scratch_score"] == 155
    conn = db_state.get_connection()
    assert conn.execute("SELECT total_score FROM scores WHERE id=?", (q[0]["id"],)).fetchone()[0] == 175
    conn.close()


def test_chat_and_presence_per_tournament(db):
    assert td_team.send_message(1, "Scott", " lane 3 needs a look ")
    assert not td_team.send_message(1, "Scott", "   ")
    td_team.send_message(2, "Pat", "other event")
    msgs = td_team.get_messages(1)
    assert [m["text"] for m in msgs] == ["lane 3 needs a look"]
    assert td_team.unread_count(msgs, 0, "Pat") == 1 and td_team.unread_count(msgs, 0, "Scott") == 0
    td_team.heartbeat("scott", "Scott", 1)
    td_team.heartbeat("pat", "Pat", 2)
    on = td_team.tds_on_duty(1)
    assert [p["display_name"] for p in on] == ["Scott"] and on[0]["online"]


def test_old_database_upgrades_and_missing_tables_never_crash(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE scores (id INTEGER PRIMARY KEY, tournament_id INT, bowler_id INT, game_number INT, scratch_score INT)")
    c.commit(); c.close()
    monkeypatch.setattr(db_state, "DB_PATH", path)
    assert td_team.get_messages(1) == []          # table missing -> empty, no crash
    assert td_team.tds_on_duty(1) == []
    assert td_team.heartbeat("x", "X", 1) is None
    db_state.init_db()
    cols = [r[1] for r in db_state.get_connection().execute("PRAGMA table_info(scores)")]
    assert {"verified", "verified_by", "verified_at", "updated_at"} <= set(cols)


def test_practice_chat_deleted_with_practice(db):
    t = practice.create_practice_tournament()
    td_team.send_message(t, "Scott", "test")
    practice.delete_practice_tournament(t)
    assert td_team.get_messages(t) == []
    assert td_team.get_messages(1) == []
