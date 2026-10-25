"""Should-fix-soon items: deadline timezone, flyer amounts, check-in privacy, score 0, desk flags."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from components.leaderboard import desk_standings_html
from modules import db_state, divisions as dv, kiosk_data, stepladder
from views.kiosk import build_html
from modules.events import (
    entry_package_labels,
    front_desk_fee_copy,
    mask_usbc_id,
    pick_public_event,
    public_checkin_url,
)
from modules.smart_export import confirm_flyer_amounts
from modules.standings import get_tournament
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
from views.hubs.active_squad import _matrix_snapshot, _save_score, changed_desk_scores
from views.mobile_scoring import scores_to_save
from views.hubs.backup_restore import SAFETY_COPY_PROMPT

ET = ZoneInfo("America/New_York")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _rose(db=None):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    return tid, get_tournament(tid)


def test_deadline_is_end_of_day_eastern(db):
    _tid, t = _rose()
    assert not dv.past_deadline(t, datetime(2026, 11, 29, 23, 30, tzinfo=ET))
    assert not dv.past_deadline(t, datetime(2026, 11, 29, 23, 59, 59, tzinfo=ET))
    assert dv.past_deadline(t, datetime(2026, 11, 30, 0, 0, tzinfo=ET))
    # 03:30 UTC on Nov 30 is still the evening of Nov 29 in Eastern (EST, UTC-5).
    assert not dv.past_deadline(t, datetime(2026, 11, 30, 3, 30, tzinfo=timezone.utc))
    assert dv.past_deadline(t, datetime(2026, 11, 30, 5, 0, tzinfo=timezone.utc))
    assert dv.handicap_for(151, t, False) == 62  # 62.1 dropped, not rounded to 62 or 63


def test_flyer_check_does_not_invent_lower_place_amounts(db):
    _tid, t = _rose()
    divs = dv.get_divisions(t)
    todo = dv.unconfirmed_items(t)
    firsts = {d["name"]: d["first_place"] for d in divs}
    blank = {d["name"]: "" for d in divs}
    saved, kept = confirm_flyer_amounts(divs, todo, firsts, blank)
    assert any("2nd place" in item for item in kept)
    assert all("place_amounts" not in d for d in saved)
    assert [d["first_place"] for d in saved] == [500, 300, 150]
    assert not any("Lane pairs" in item for item in kept)

    partial = {"Division 1": "200", "Division 2": "", "Division 3": ""}
    saved, kept = confirm_flyer_amounts(divs, todo, firsts, partial)
    assert any("2nd place" in item for item in kept)
    by_name = {d["name"]: d for d in saved}
    assert by_name["Division 1"]["place_amounts"] == [500, 200]
    assert "place_amounts" not in by_name["Division 2"]
    assert "place_amounts" not in by_name["Division 3"]

    filled = {d["name"]: "200, 50" for d in divs}
    saved, kept = confirm_flyer_amounts(divs, todo, firsts, filled)
    assert kept == []
    assert {d["name"]: d["place_amounts"] for d in saved} == {
        "Division 1": [500, 200, 50],
        "Division 2": [300, 200, 50],
        "Division 3": [150, 200, 50],
    }
    with pytest.raises(ValueError):
        confirm_flyer_amounts(divs, todo, firsts, {"Division 1": "abc", "Division 2": "", "Division 3": ""})


def test_add_bowler_hides_unused_side_events_and_checkin_is_private(db):
    _tid, t = _rose()
    labels = entry_package_labels(t)
    assert labels["offer_singles"] and not labels["show_picker"]
    assert not labels["offer_doubles"] and not labels["offer_team"] and not labels["offer_all_events"]
    open_fmt = entry_package_labels({"squad_format": "Team / Doubles / Singles"})
    assert open_fmt["show_picker"] and open_fmt["offer_doubles"] and open_fmt["offer_team"]
    assert not open_fmt["offer_all_events"]

    assert mask_usbc_id("8412-10921") == "••••0921"
    assert "8412" not in mask_usbc_id("8412-10921")
    assert mask_usbc_id("") == "Not on file"
    assert public_checkin_url("https://desk.example/", 4) == "https://desk.example/?mode=bowler&action=checkin&t=4"
    copy = front_desk_fee_copy(t)
    assert copy and "$30" in copy and "Forest Hill Lanes front desk" in copy
    assert "$25" not in copy and "unpaid" not in copy.lower()
    events = [{"id": 4, "name": "A"}, {"id": 9, "name": "B"}]
    picked, err = pick_public_event(events, {"t": "4"})
    assert picked["name"] == "A" and err is None
    picked, err = pick_public_event(events, {"t": "99"})
    assert picked is None and "does not match" in err
    assert pick_public_event(events, {}) == (None, None)
    assert pick_public_event([events[0]], {})[0]["id"] == 4


def test_desk_save_writes_a_real_zero_and_skips_unchanged_cells(db):
    tid, _t = _rose()
    conn = db_state.get_connection()
    with conn:
        bid = conn.execute(
            "INSERT INTO bowlers (tournament_id, name, handicap, lane_assignment) VALUES (?, 'Ann', 10, 1)",
            (tid,),
        ).lastrowid
        other = conn.execute(
            "INSERT INTO bowlers (tournament_id, name, handicap, lane_assignment) VALUES (?, 'Bea', 10, 2)",
            (tid,),
        ).lastrowid
        conn.execute(
            "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score) VALUES (?,?,1,180,190)",
            (tid, other),
        )
    conn.close()
    assert changed_desk_scores({bid: None, other: 180}, {bid: 0, other: 180}) == {bid: 0}
    assert changed_desk_scores({other: 180}, {other: 180}) == {}
    assert changed_desk_scores({bid: None}, {bid: None}) == {}
    assert changed_desk_scores({bid: None}, {bid: float("nan")}) == {}
    assert _save_score(tid, bid, 1, 0, 10, "Scott")
    conn = db_state.get_connection()
    zero = conn.execute(
        "SELECT scratch_score FROM scores WHERE bowler_id=? AND game_number=1", (bid,)
    ).fetchone()["scratch_score"]
    kept = conn.execute(
        "SELECT scratch_score FROM scores WHERE bowler_id=? AND game_number=1", (other,)
    ).fetchone()["scratch_score"]
    conn.close()
    assert zero == 0 and kept == 180
    for game in (2, 3):
        _save_score(tid, bid, game, 0, 10, "Scott")
    _scores, done = _matrix_snapshot(tid, 1)
    assert _scores[bid]["scratch_score"] == 0 and done == 1


def test_blank_is_not_a_zero_and_a_typed_zero_is_a_score():
    assert scores_to_save({1: 0, 2: None, 3: "", 4: "  ", 5: float("nan")}) == {1: 0}
    assert scores_to_save({1: "0", 2: 0.0, 3: 180}) == {1: 0, 2: 0, 3: 180}
    assert scores_to_save({}) == {}


def test_floor_phone_saves_a_typed_zero_and_skips_blank_boxes(db):
    from streamlit.testing.v1 import AppTest

    tid, _t = _rose()
    conn = db_state.get_connection()
    with conn:
        ann = conn.execute(
            "INSERT INTO bowlers (tournament_id, name, handicap, lane_assignment) VALUES (?, 'Ann', 10, 1)",
            (tid,),
        ).lastrowid
        bea = conn.execute(
            "INSERT INTO bowlers (tournament_id, name, handicap, lane_assignment) VALUES (?, 'Bea', 8, 1)",
            (tid,),
        ).lastrowid
        cal = conn.execute(
            "INSERT INTO bowlers (tournament_id, name, handicap, lane_assignment) VALUES (?, 'Cal', 12, 2)",
            (tid,),
        ).lastrowid
        conn.execute(
            "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, hdcp_score, total_score, recorded_by)"
            " VALUES (?,?,1,180,12,192,'Scott')",
            (tid, cal),
        )
    conn.close()
    path = str(db_state.DB_PATH)
    at = AppTest.from_string(
        "import streamlit as st\n"
        "from pathlib import Path\n"
        "from modules import db_state\n"
        f"db_state.DB_PATH = Path({path!r})\n"
        f"st.query_params['t'] = {str(tid)!r}\n"
        f"st.session_state['scorer_event'] = {tid}\n"
        "st.session_state['scorer_authenticated'] = True\n"
        "st.session_state['verifier_name'] = 'Mike'\n"
        "st.session_state['floor_device'] = 'phoneA'\n"
        "from views.mobile_scoring import render_mobile_scoring\n"
        "render_mobile_scoring()\n",
        default_timeout=30,
    ).run()
    assert not at.exception
    boxes = {n.label: n for n in at.number_input}
    assert boxes["Scratch Score for Ann"].value is None
    assert boxes["Scratch Score for Bea"].value is None
    assert "Scratch Score for Cal" not in boxes  # other lane, untouched
    boxes["Scratch Score for Ann"].set_value(0)
    at.form_submit_button[0].click().run()
    assert not at.exception

    def row(bid, game):
        c = db_state.get_connection()
        found = c.execute(
            "SELECT scratch_score, hdcp_score, total_score, verified, recorded_by FROM scores"
            " WHERE bowler_id=? AND game_number=?",
            (bid, game),
        ).fetchone()
        c.close()
        return dict(found) if found else None

    ann_g1 = row(ann, 1)
    assert ann_g1["scratch_score"] == 0 and ann_g1["hdcp_score"] == 10 and ann_g1["total_score"] == 10
    assert ann_g1["verified"] == 0 and ann_g1["recorded_by"] == "Mike"
    assert row(bea, 1) is None
    assert row(cal, 1)["scratch_score"] == 180

    for game in (2, 3):
        at.radio(key="mobile_game_radio").set_value(game).run()
        assert not at.exception
        next(n for n in at.number_input if n.label == "Scratch Score for Ann").set_value(0)
        at.form_submit_button[0].click().run()
        assert not at.exception
        assert row(ann, game)["scratch_score"] == 0
        assert row(bea, game) is None

    _scores, done = _matrix_snapshot(tid, 3)
    assert _scores[ann]["scratch_score"] == 0 and done == 1


def test_desk_standings_match_kiosk_cut_and_champion(db):
    tid, _t = _rose()
    conn = db_state.get_connection()
    with conn:
        for i, score in enumerate((700, 680, 646, 646, 600)):
            cur = conn.execute(
                "INSERT INTO bowlers (tournament_id, name, gender, entering_avg, division) VALUES (?,?, 'Girls', 170, ?)",
                (tid, f"G{i}", "Division 1 – Girls"),
            )
            conn.execute(
                "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score) VALUES (?,?,1,?,?)",
                (tid, cur.lastrowid, score, score),
            )
    conn.close()
    groups = kiosk_data.public_groups(tid)
    html = desk_standings_html(groups)
    assert "TIE – ROLL-OFF" in html and "Red line" in html and "IN CUT" in html
    kiosk_html = "".join(build_html(kiosk_data.load_board(tid), i, "t") for i in range(4))
    assert "TIE – ROLL-OFF" in kiosk_html

    tid2, _t2 = _rose()
    conn = db_state.get_connection()
    with conn:
        for i, score in enumerate((700, 680, 650, 600)):
            cur = conn.execute(
                "INSERT INTO bowlers (tournament_id, name, gender, entering_avg, division) VALUES (?,?, 'Girls', 170, ?)",
                (tid2, f"F{i}", "Division 1 – Girls"),
            )
            conn.execute(
                "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score) VALUES (?,?,1,?,?)",
                (tid2, cur.lastrowid, score, score),
            )
    conn.close()
    group = "Division 1 – Girls"
    assert stepladder.initialize_stepladder(tid2, group)
    while True:
        active = [m for m in stepladder.get_stepladder_state(tid2, group) if m["status"] == "active"]
        if not active:
            break
        stepladder.record_stepladder_score(active[0]["id"], 250, 200)
    groups = kiosk_data.public_groups(tid2)
    girls = next(g for g in groups if any(r["name"] == "F2" for r in g["rows"]))
    assert girls["rows"][0]["name"] == "F2" and girls["rows"][0]["champion"] and girls["rows"][0]["rank"] == 1
    final_html = desk_standings_html(groups)
    assert "CHAMPION" in final_html and "Final placement" in final_html
    assert "CHAMPION" in build_html(kiosk_data.load_board(tid2), 0, "t")


def test_restore_asks_for_the_safety_copy_immediately():
    assert "Download the safety copy now" in SAFETY_COPY_PROMPT
    assert "before you leave this page" in SAFETY_COPY_PROMPT
