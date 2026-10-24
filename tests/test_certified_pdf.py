import subprocess

import pytest

from modules import db_state, rolloff, stepladder
from modules.placement import event_slug, group_placement
from modules.divisions import grouped_results
from modules.reports import build_certified_pdf, certified_pdf_filename
from modules.smart_export import build_smart_export, save_place_amounts
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template

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
            cur = conn.execute("INSERT INTO bowlers (tournament_id, name, usbc_id, smart_account_id, gender, entering_avg,"
                               " division, is_youth) VALUES (?, ?, ?, 'S1', 'Girls', 220, ?, 1)",
                               (tid, f"Amy Bowler{i}", f"1234-{10000 + i}", GROUP))
            conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score)"
                         " VALUES (?,?,1,?,?)", (tid, cur.lastrowid, s, s))
    conn.close()
    return tid


def _text(pdf, tmp_path):
    f = tmp_path / "o.pdf"
    f.write_bytes(pdf)
    return subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True, text=True).stdout


def _play_ladder(tid, low_wins=True):
    stepladder.initialize_stepladder(tid, GROUP)
    for _ in range(5):
        for m in stepladder.get_stepladder_state(tid, GROUP):
            if m["status"] == "active":
                stepladder.record_stepladder_score(m["id"], 250 if low_wins else 150, 200)


def _order(tid):
    g = next(g for g in grouped_results(tid) if g["group"] == GROUP)
    return group_placement(tid, g)


def test_no_ladder_falls_back_to_qualifying(db):
    tid = _event([700, 680, 650, 600])
    p = _order(tid)
    assert p["status"] == "qualifying" and [r["name"] for r in p["order"]][:2] == ["Amy Bowler0", "Amy Bowler1"]


def test_champion_from_low_seed_gets_first_in_pdf_and_smart(db, tmp_path):
    tid = _event([700, 680, 650, 600])
    save_place_amounts(tid, "Division 1", [500, 250, 100])
    _play_ladder(tid, low_wins=True)  # #3 seed wins every match
    p = _order(tid)
    assert p["status"] == "final" and p["champion"] == "Amy Bowler2"
    assert [r["name"] for r in p["order"]] == ["Amy Bowler2", "Amy Bowler0", "Amy Bowler1", "Amy Bowler3"]
    rows = build_smart_export(tid)["rows"]
    assert [(r["First Name"] + " " + r["Last Name"], r["Scholarship Amount"]) for r in rows] == [
        ("Amy Bowler2", "500.00"), ("Amy Bowler0", "250.00"), ("Amy Bowler1", "100.00")]
    txt = _text(build_certified_pdf(tid, "TD"), tmp_path)
    line = next(l for l in txt.splitlines() if "Amy Bowler2" in l and "1234-" in l)
    assert "$500.00" in line and "1st" in line
    assert "Champion: Amy Bowler2" in txt and "STEPLADDER FINALS" in txt
    assert "ADULT CASH" not in txt


def test_unfinished_ladder_withholds_awards(db, tmp_path):
    tid = _event([700, 680, 650, 600])
    stepladder.initialize_stepladder(tid, GROUP)
    assert build_smart_export(tid)["rows"] == []
    txt = _text(build_certified_pdf(tid, "TD"), tmp_path)
    assert "$500.00" not in txt.split("STEPLADDER")[0].split("PRIZE POOL")[1].split("\n", 2)[2]
    assert "finals not finished" in txt


def test_rolloff_note(db, tmp_path):
    tid = _event([700, 680, 646, 646, 600])
    g = next(g for g in grouped_results(tid) if g["group"] == GROUP)
    win = g["rolloff"]["bowlers"][1]
    rolloff.record_winner(tid, GROUP, win["id"], win["total"], "Scott")
    txt = " ".join(_text(build_certified_pdf(tid, "TD"), tmp_path).split())
    assert "tied at 646" in txt and f"{win['name']} won the roll-off (recorded by Scott)" in txt
    assert "did not advance" in txt


def test_filename_slug(db):
    assert event_slug("2nd Annual Rose/Murphy: Youth!") == "2nd_Annual_Rose_Murphy_Youth"
    assert certified_pdf_filename({"name": "Rose Murphy"}) == "Rose_Murphy_certified_results.pdf"
    assert certified_pdf_filename(None) == "tournament_certified_results.pdf"
