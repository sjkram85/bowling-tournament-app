import sqlite3

import pytest

from modules import db_state, kiosk_data, rolloff
from modules.divisions import grouped_results
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
from views.kiosk import build_html

GROUP = "Division 1 – Girls"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _event(scores):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    conn = db_state.get_connection()
    with conn:
        for i, s in enumerate(scores):
            cur = conn.execute("INSERT INTO bowlers (tournament_id, name, gender, entering_avg, division)"
                               " VALUES (?, ?, 'Girls', 220, ?)", (tid, f"G{i}", GROUP))
            conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score)"
                         " VALUES (?,?,1,?,?)", (tid, cur.lastrowid, s, s))
    conn.close()
    return tid


def _group(tid):
    return next(g for g in grouped_results(tid) if g["rows"])


def test_tie_at_cut_flags_rolloff(db):
    tid = _event([700, 680, 646, 646, 600])  # 5 bowlers -> top 3; two tied at 646 for the last spot
    g = _group(tid)
    by = {r["name"]: r for r in g["rows"]}
    assert by["G0"]["finalist"] and by["G1"]["finalist"]
    assert by["G2"]["rolloff"] and by["G3"]["rolloff"]
    assert not by["G2"]["finalist"] and not by["G3"]["finalist"] and not by["G4"]["rolloff"]
    assert g["rolloff"]["spots"] == 1 and len(g["rolloff"]["bowlers"]) == 2
    html = "".join(build_html(kiosk_data.load_board(tid), i, "t") for i in range(5))
    assert "TIE – ROLL-OFF" in html


def test_tie_inside_cut_stays_finalists(db):
    g = _group(_event([700, 690, 690, 600, 590]))
    by = {r["name"]: r for r in g["rows"]}
    assert all(by[n]["finalist"] for n in ("G0", "G1", "G2"))
    assert by["G1"]["tied"] and by["G2"]["tied"] and not any(r["rolloff"] for r in g["rows"])
    assert g["rolloff"] is None


def test_rolloff_resolution(db):
    tid = _event([700, 680, 646, 646, 646])
    g = _group(tid)
    loser, winner = g["rolloff"]["bowlers"][0], g["rolloff"]["bowlers"][2]
    assert rolloff.record_winner(tid, g["group"], winner["id"], winner["total"], "Scott")
    g = _group(tid)
    by = {r["id"]: r for r in g["rows"]}
    assert by[winner["id"]]["finalist"] and not by[winner["id"]]["rolloff"]
    assert not by[loser["id"]]["finalist"] and not by[loser["id"]]["rolloff"]
    assert g["rolloff"] is None and sum(r["finalist"] for r in g["rows"]) == 3
    conn = db_state.get_connection()
    row = conn.execute("SELECT decided_by, decided_at FROM cut_rolloffs").fetchone()
    conn.close()
    assert row["decided_by"] == "Scott" and row["decided_at"]


def test_top5_group_two_spots(db):
    scores = [800, 790, 780, 646, 646, 646] + [500 - i for i in range(22)]  # 28 bowlers -> top 5
    tid = _event(scores)
    g = _group(tid)
    assert g["finalists"] == 5 and g["rolloff"]["spots"] == 2 and len(g["rolloff"]["bowlers"]) == 3
    tied = g["rolloff"]["bowlers"]
    rolloff.record_winner(tid, g["group"], tied[1]["id"], 646, "TD")
    g = _group(tid)
    assert g["rolloff"]["spots"] == 1 and len(g["rolloff"]["bowlers"]) == 2
    rolloff.record_winner(tid, g["group"], g["rolloff"]["bowlers"][0]["id"], 646, "TD")
    g = _group(tid)
    assert g["rolloff"] is None and sum(r["finalist"] for r in g["rows"]) == 5


def test_old_database_without_table(db):
    tid = _event([700, 680, 646, 646])
    conn = db_state.get_connection()
    conn.execute("DROP TABLE cut_rolloffs")
    conn.commit()
    conn.close()
    assert _group(tid)["rolloff"]["spots"] == 1  # still works, no crash
    assert rolloff.record_winner(tid, GROUP, 1, 646, "TD")  # recreates table
