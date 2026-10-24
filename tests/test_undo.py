import pytest

from modules import db_state, score_history, td_team
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
from views.hubs.active_squad import _save_score
from views.mobile_scoring import _record_score


@pytest.fixture
def ev(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    conn = db_state.get_connection()
    with conn:
        conn.execute("INSERT INTO bowlers (tournament_id, name, handicap) VALUES (?, 'Ann', 10)", (tid,))
        conn.execute("INSERT INTO bowlers (tournament_id, name, handicap) VALUES (?, 'Bea', 0)", (tid,))
    conn.close()
    return tid


def _score(tid, bid=1, g=1):
    conn = db_state.get_connection()
    r = conn.execute("SELECT scratch_score, total_score, verified FROM scores WHERE tournament_id=? AND bowler_id=?"
                     " AND game_number=?", (tid, bid, g)).fetchone()
    conn.close()
    return dict(r) if r else None


def test_desk_new_score_undo_removes_it(ev):
    hid = _save_score(ev, 1, 1, 200, 10, "Scott")
    assert _score(ev)["scratch_score"] == 200 and score_history.recent(ev)[0]["source"] == "desk"
    ok, _ = score_history.undo(hid, "Scott")
    assert ok and _score(ev) is None and score_history.recent(ev) == []
    assert not score_history.undo(hid, "Scott")[0]  # can't undo twice


def test_change_undo_restores_old_value_into_verify_queue(ev):
    _save_score(ev, 1, 1, 200, 10, "Scott")  # desk saves as verified
    hid = _save_score(ev, 1, 1, 220, 10, "Scott")
    assert _save_score(ev, 1, 1, 220, 10, "Scott") is None  # unchanged -> no history
    assert score_history.undo(hid, "Scott")[0]
    s = _score(ev)
    assert s["scratch_score"] == 200 and s["total_score"] == 210 and s["verified"] == 0
    assert any(r["scratch_score"] == 200 for r in td_team.needs_verifying(ev))


def test_floor_phone_only_own_last_change(ev):
    a1 = _record_score(ev, 1, 1, 180, 10, "Mike", device="phoneA")
    a2 = _record_score(ev, 2, 1, 190, 0, "Mike", device="phoneA")
    b1 = _record_score(ev, 1, 2, 170, 10, "Pat", device="phoneB")
    assert not score_history.undo(b1, "Mike", device="phoneA")[0]  # someone else's
    assert not score_history.undo(a1, "Mike", device="phoneA")[0]  # not my last
    assert score_history.undo(a2, "Mike", device="phoneA")[0]
    assert score_history.undo(a1, "Mike", device="phoneA")[0]  # now it is my last
    assert score_history.undo(b1, "Scott")[0]  # TD hub can undo any


def test_verify_fix_logged_and_changed_again_blocked(ev):
    _record_score(ev, 1, 1, 180, 10, "Mike", device="p")
    sid = td_team.needs_verifying(ev)[0]["id"]
    td_team.verify_score(sid, "Scott", new_scratch=181)
    h = score_history.recent(ev)[0]
    assert h["source"] == "verify-fix" and h["old_scratch"] == 180 and h["new_scratch"] == 181
    older = score_history.recent(ev)[1]["id"]
    ok, msg = score_history.undo(older, "Scott")
    assert not ok and "changed again" in msg


def test_per_event_and_old_db(ev):
    other = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    _save_score(ev, 1, 1, 200, 10, "Scott")
    assert score_history.recent(other) == []
    conn = db_state.get_connection(); conn.execute("DROP TABLE score_history"); conn.commit(); conn.close()
    assert score_history.recent(ev) == []  # no crash
    assert _save_score(ev, 1, 1, 210, 10, "Scott")  # table recreated on next change
