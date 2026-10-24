import pytest

from modules import db_state, rolloff, stepladder
from modules.reports import build_smart_scholarship_csv
from modules.smart_export import build_smart_export, header_csv, save_header_fields, save_place_amounts
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template

GROUP = "Division 1 – Girls"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _event(scores, ids=None):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    conn = db_state.get_connection()
    with conn:
        for i, s in enumerate(scores):
            uid = ids[i] if ids else f"1234-{10000 + i}"
            cur = conn.execute("INSERT INTO bowlers (tournament_id, name, usbc_id, smart_account_id, gender, entering_avg,"
                               " division, is_youth) VALUES (?, ?, ?, 'S1', 'Girls', 220, ?, 1)",
                               (tid, f"Amy Bowler{i}", uid, GROUP))
            conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score)"
                         " VALUES (?,?,1,?,?)", (tid, cur.lastrowid, s, s))
    conn.close()
    return tid


def test_first_place_from_flyer_others_blank_with_warning(db):
    tid = _event([700, 680, 650, 600])
    data = build_smart_export(tid)
    rows = data["rows"]
    assert [r["Place"] for r in rows] == [1, 2, 3]
    assert rows[0]["Scholarship Amount"] == "500.00" and rows[0]["Last Name"] == "Bowler0" and rows[0]["First Name"] == "Amy"
    assert rows[1]["Scholarship Amount"] == "" and rows[2]["Scholarship Amount"] == ""
    assert any("no scholarship amount" in w for w in data["warnings"])
    assert data["header"]["Total Amount"] == "500.00"
    assert data["header"]["Date Event Ended"] == "2026-12-06"
    assert "120.00" not in build_smart_scholarship_csv(tid)


def test_configured_amounts_and_header_fields(db):
    tid = _event([700, 680, 650, 600])
    save_place_amounts(tid, "Division 1", [500, 250, 100])
    save_header_fields(tid, "2026-12-07", "CERT-9")
    data = build_smart_export(tid)
    assert [r["Scholarship Amount"] for r in data["rows"]] == ["500.00", "250.00", "100.00"]
    assert data["header"]["Total Amount"] == "850.00"
    assert "2026-12-07" in header_csv(data) and "CERT-9" in header_csv(data)
    assert not any("cert" in w.lower() for w in data["warnings"])


def test_unresolved_rolloff_blocks_group_then_resolves(db):
    tid = _event([700, 680, 646, 646, 600])
    data = build_smart_export(tid)
    assert data["rows"] == [] and any("roll-off" in w for w in data["warnings"])
    conn = db_state.get_connection()
    bid = conn.execute("SELECT id FROM bowlers WHERE name='Amy Bowler3'").fetchone()[0]
    conn.close()
    rolloff.record_winner(tid, GROUP, bid, 646, "TD")
    names = [r["Last Name"] for r in build_smart_export(tid)["rows"]]
    assert names == ["Bowler0", "Bowler1", "Bowler3"]


def test_stepladder_results_decide_places(db):
    tid = _event([700, 680, 650, 600])
    stepladder.init_stepladder_tables()
    assert stepladder.initialize_stepladder(tid, GROUP)
    data = build_smart_export(tid)
    assert data["rows"] == [] and any("stepladder" in w for w in data["warnings"])
    # #3 seed wins every match -> champion
    for m in stepladder.get_stepladder_state(tid, GROUP):
        cur = [x for x in stepladder.get_stepladder_state(tid, GROUP) if x["id"] == m["id"]][0]
        stepladder.record_stepladder_score(cur["id"], 250, 200)
    rows = build_smart_export(tid)["rows"]
    assert [r["Last Name"] for r in rows] == ["Bowler2", "Bowler0", "Bowler1"]
    assert rows[0]["Scholarship Amount"] == "500.00"


def test_bad_or_missing_usbc_id_and_smart_warned(db):
    tid = _event([700, 680, 650], ids=["", "abc", "1234-5678"])
    w = " ".join(build_smart_export(tid)["warnings"])
    assert "missing USBC ID" in w and "doesn't look right" in w
