import pytest

from modules import db_state, event_logos, rolloff, stepladder, td_team
from modules.event_delete import can_delete, delete_event, hide_in_closeout


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _event(status="active", practice=0, name="Ev"):
    conn = db_state.get_connection()
    with conn:
        tid = conn.execute("INSERT INTO tournaments (name, host_center, game_count, status, is_practice) VALUES (?,?,?,?,?)",
                           (name, "FHL", 3, status, practice)).lastrowid
        ids = []
        for i in range(3):
            b = conn.execute("INSERT INTO bowlers (tournament_id, name) VALUES (?,?)", (tid, f"B{i}")).lastrowid
            ids.append(b)
            conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score) VALUES (?,?,1,?,?)",
                         (tid, b, 200 - i, 200 - i))
        br = conn.execute("INSERT INTO brackets (tournament_id, bracket_number) VALUES (?, 1)", (tid,)).lastrowid if _has(conn, "brackets") else None
        if br:
            conn.execute("INSERT INTO bracket_entries (bracket_id, bowler_id, seed_position) VALUES (?,?,1)", (br, ids[0]))
    conn.close()
    td_team.send_message(tid, "Scott", "hi")
    event_logos.set_logo(tid, "event", b"png")
    rolloff.record_winner(tid, "G", ids[0], 200, "Scott")
    stepladder.init_stepladder_tables()
    return tid


def _has(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone())


def _leftovers(tid):
    conn = db_state.get_connection()
    try:
        out = {}
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info({name})")]
            if "tournament_id" in cols:
                n = conn.execute(f"SELECT COUNT(*) FROM {name} WHERE tournament_id=?", (tid,)).fetchone()[0]
                if n:
                    out[name] = n
        out["bracket_entries"] = conn.execute("SELECT COUNT(*) FROM bracket_entries").fetchone()[0]
        out["tournaments"] = conn.execute("SELECT COUNT(*) FROM tournaments WHERE id=?", (tid,)).fetchone()[0]
        return {k: v for k, v in out.items() if v}
    finally:
        conn.close()


def test_practice_any_status_deleted_with_all_children(db):
    keep = _event(name="Real")
    tid = _event(status="active", practice=1)
    assert can_delete(tid) and delete_event(tid, "Admin")
    assert _leftovers(tid) == {"bracket_entries": 1}  # only the other event's bracket entry remains
    assert _leftovers(keep)["tournaments"] == 1
    log = db_state.get_connection().execute("SELECT * FROM audit_log ORDER BY rowid DESC LIMIT 1").fetchone()
    assert f"#{tid}" in str(tuple(log))


def test_cancelled_real_event_deletable(db):
    tid = _event(status="cancelled")
    assert delete_event(tid, "Admin") and _leftovers(tid) == {}


@pytest.mark.parametrize("status", ["active", "closed", "completed", "certified"])
def test_real_events_protected(db, status):
    tid = _event(status=status)
    assert not can_delete(tid) and not delete_event(tid, "Admin")
    assert _leftovers(tid)["tournaments"] == 1


def test_archived_cancelled_real_event_protected(db):
    tid = _event(status="cancelled")
    conn = db_state.get_connection()
    with conn:
        conn.execute("INSERT INTO tournament_archives (tournament_id, archived_by, snapshot_json, certified_pdf, smart_csv)"
                     " VALUES (?, 'x', '{}', x'00', '')", (tid,))
    conn.close()
    assert not can_delete(tid)


def test_picker_hides_cancelled_practice_only():
    assert hide_in_closeout({"is_practice": 1, "status": "cancelled"})
    assert not hide_in_closeout({"is_practice": 1, "status": "active"})
    assert not hide_in_closeout({"is_practice": 0, "status": "cancelled"})
