from datetime import datetime

import pytest

from modules import db_state, divisions as dv
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _t(tid):
    conn = db_state.get_connection()
    try:
        return dict(conn.execute("SELECT * FROM tournaments WHERE id=?", (tid,)).fetchone())
    finally:
        conn.close()


GOOD = {"name": "Kid", "usbc_id": "1-2", "is_youth": 1, "smart_account_id": "S1", "gender": "Girls",
        "birth_date": "2012-05-01", "entering_avg": 150, "bowls_scratch": 0}


def test_preset_locked_and_rules(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    t = _t(tid)
    assert t["host_center"] == "FHL" and t["rules_locked"] and t["no_walkins"] and t["fees_at_front_desk"]
    assert t["game_count"] == 3 and t["handicap_pct"] == 90 and t["handicap_base"] == 220
    assert t["grouping"] == "division_gender" and t["entry_fee"] == 0
    divs = dv.get_divisions(t)
    assert dv.division_for(160, divs) == "Division 1" and dv.division_for(159, divs) == "Division 2"
    assert dv.division_for(126, divs) == "Division 2" and dv.division_for(125, divs) == "Division 3"
    assert dv.group_for({"entering_avg": 140, "gender": "Girls"}, t) == "Division 2 – Girls"
    assert dv.handicap_for(150, t, False) == 63 and dv.handicap_for(150, t, True) == 0
    assert dv.finalists_count(25) == 3 and dv.finalists_count(26) == 5
    assert dv.age_group_for("2015-07-31", t) == "Prep" or dv.age_group_for("2015-07-31", t) == "Preps"  # 11
    assert dv.age_group_for("2012-08-01", t) == "Juniors"  # 13 on 7/31/26
    assert dv.age_group_for("2010-07-31", t) == "Majors"  # 16
    early = datetime(2026, 11, 1)
    assert dv.entry_problems(t, GOOD, early) == []
    for k in ("gender", "smart_account_id", "birth_date"):
        assert dv.entry_problems(t, {**GOOD, k: ""}, early)
    late = datetime(2026, 11, 30, 9)
    assert dv.entry_problems(t, GOOD, late)
    assert dv.entry_problems(t, GOOD, late, override=True) == []
    assert dv.entry_problems(t, {**GOOD, "entering_avg": 0, "bowls_scratch": 1}, early) == []


def test_group_standings_reranks(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "FHL")
    t = _t(tid)
    rows = [{"id": i, "name": n, "entering_avg": a, "gender": g, "handicap_total": s, "rank": i}
            for i, (n, a, g, s) in enumerate([("A", 170, "Boys", 700), ("B", 130, "Girls", 650),
                                              ("C", 172, "Boys", 600), ("D", 120, "Girls", 500)], 1)]
    groups = dict(dv.group_standings(rows, t))
    assert [r["name"] for r in groups["Division 1 – Boys"]] == ["A", "C"]
    assert [r["rank"] for r in groups["Division 1 – Boys"]] == [1, 2]
    assert groups["Division 2 – Girls"][0]["rank"] == 1
