import time

import pytest

from modules import db_state, rolloff, stepladder
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _add(tid, scores, division=None, gender="Girls", prefix="G"):
    conn = db_state.get_connection()
    with conn:
        for i, s in enumerate(scores):
            cur = conn.execute("INSERT INTO bowlers (tournament_id, name, gender, entering_avg, division)"
                               " VALUES (?, ?, ?, 220, ?)", (tid, f"{prefix}{i}", gender, division))
            conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score)"
                         " VALUES (?,?,1,?,?)", (tid, cur.lastrowid, s, s))
    conn.close()


def _plain_event():
    conn = db_state.get_connection()
    with conn:
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(tournaments)")}
        vals = {c: ("Open" if c == "name" else 0) for c, r in cols.items() if r[3] and r[4] is None and c != "id"}
        vals["name"] = "Open"
        cur = conn.execute(f"INSERT INTO tournaments ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})",
                           list(vals.values()))
    conn.close()
    return cur.lastrowid


def _play_out(tid, group):
    """Higher seed always loses -> lowest seed climbs to champion."""
    while True:
        active = [m for m in stepladder.get_stepladder_state(tid, group) if m["status"] == "active"]
        if not active:
            return
        assert stepladder.record_stepladder_score(active[0]["id"], 250, 200)


def test_overall_no_lock_and_full_ladder(db):
    tid = _plain_event()
    _add(tid, [700, 690, 680, 670, 660, 650], prefix="B")
    t0 = time.perf_counter()
    assert stepladder.initialize_stepladder(tid)
    ms = stepladder.get_stepladder_state(tid, stepladder.OVERALL)
    assert time.perf_counter() - t0 < 2  # old code hung ~5s then 'database is locked'
    assert len(ms) == 4 and ms[0]["low_name"] == "B4" and ms[0]["high_name"] == "B3" and ms[3]["high_name"] == "B0"
    _play_out(tid, stepladder.OVERALL)
    assert stepladder.champion(tid) == "B4"
    conn = db_state.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action_description LIKE '%tepladder%'").fetchone()[0] == 5
    conn.close()


def test_tie_needs_rolloff(db):
    tid = _plain_event()
    _add(tid, [700, 690, 680, 670, 660])
    stepladder.initialize_stepladder(tid)
    m = stepladder.get_stepladder_state(tid)[0]
    assert not stepladder.record_stepladder_score(m["id"], 200, 200)
    assert stepladder.record_stepladder_score(m["id"], 200, 200, 9, 8)
    assert stepladder.get_stepladder_state(tid)[1]["low_name"] == m["low_name"]


def test_per_group_seeding_and_rolloff_winner(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    _add(tid, [700, 680, 646, 646, 600], "Division 1 – Girls", "Girls", "G")
    _add(tid, [710, 705, 690, 500], "Division 1 – Boys", "Boys", "B")
    info = stepladder.seeds(tid)
    girls = next(k for k in info if k.startswith("Division 1") and "Girls" in k)
    boys = next(k for k in info if k.startswith("Division 1") and "Boys" in k)
    assert not info[girls]["ready"] and not stepladder.initialize_stepladder(tid, girls)
    assert [r["name"] for r in info[boys]["seeds"]] == ["B0", "B1", "B2"]
    assert stepladder.initialize_stepladder(tid, boys)
    ms = stepladder.get_stepladder_state(tid, boys)
    assert len(ms) == 2 and ms[0]["low_name"] == "B2" and ms[0]["high_name"] == "B1"
    conn = db_state.get_connection()
    g3 = conn.execute("SELECT id FROM bowlers WHERE name='G3' AND tournament_id=?", (tid,)).fetchone()["id"]
    conn.close()
    rolloff.record_winner(tid, girls, g3, 646, "TD")
    info = stepladder.seeds(tid)
    assert info[girls]["ready"] and [r["name"] for r in info[girls]["seeds"]] == ["G0", "G1", "G3"]
    assert stepladder.initialize_stepladder(tid, girls)
    assert stepladder.get_stepladder_state(tid, girls)[0]["low_name"] == "G3"
    assert len(stepladder.get_stepladder_state(tid, boys)) == 2  # groups don't mix
    _play_out(tid, girls)
    assert stepladder.champion(tid, girls) == "G3" and stepladder.champion(tid, boys) is None


def test_top5_group(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    _add(tid, [800 - i * 5 for i in range(28)], "Division 2 – Boys", "Boys", "B")
    info = stepladder.seeds(tid)
    g = next(k for k in info if info[k]["seeds"])
    assert len(info[g]["seeds"]) == 5
    stepladder.initialize_stepladder(tid, g)
    ms = stepladder.get_stepladder_state(tid, g)
    assert len(ms) == 4 and ms[0]["low_name"] == "B4" and ms[0]["high_name"] == "B3"
    _play_out(tid, g)
    assert stepladder.champion(tid, g) == "B4"


def test_old_table_without_group_column(db):
    conn = db_state.get_connection()
    conn.execute("CREATE TABLE stepladder_matches (id INTEGER PRIMARY KEY, tournament_id INTEGER, match_number INTEGER,"
                 " match_name TEXT, bowler_low_id INTEGER, bowler_high_id INTEGER, score_low INTEGER, score_high INTEGER,"
                 " rolloff_low INTEGER, rolloff_high INTEGER, winner_id INTEGER, status TEXT DEFAULT 'pending')")
    conn.commit(); conn.close()
    tid = _plain_event()
    _add(tid, [700, 690, 680, 670, 660])
    assert stepladder.initialize_stepladder(tid) and len(stepladder.get_stepladder_state(tid)) == 4
