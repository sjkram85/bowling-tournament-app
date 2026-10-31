"""Dry-run fixes: director floor scores, stable lane board, desk auto-save.

Scott's rules, checked without the browser:
- A tournament director on the floor phone is already checked. A floor helper is not.
- The lane board reads saved scores again on each poll. It does not reuse the first look.
- The desk writes only cells the TD changed. Blank is not a score. 0 is a score.
"""

from pathlib import Path

import pytest

from modules import db_state, run_memo, td_team
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
from views.hubs.active_squad import (
    _matrix_snapshot,
    apply_desk_editor,
    baseline_needs_refresh,
    changed_cells_from_editor,
    lane_status_label,
)
from views.mobile_scoring import _record_score

ROOT = Path(__file__).resolve().parents[1]


class _Run:
    """Stand-in for Streamlit's reused script context. poll() is the next 8s refresh."""

    def __init__(self):
        self.cursors = {}
        self.widget_ids_this_run = set()
        self.tracked_commands = []
        self.fragment_ids_this_run = []

    def poll(self):
        self.cursors = {}
        self.widget_ids_this_run = set()
        self.tracked_commands = []
        self.fragment_ids_this_run = []


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _staff(username, display_name, *, role="td", approved=1, active=1):
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO staff_users (username, password_hash, display_name, role, is_approved, is_active) "
            "VALUES (?, 'x', ?, ?, ?, ?)",
            (username, display_name, role, approved, active),
        )
    conn.close()


def _event():
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
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
    conn.close()
    return tid, ann, bea


def _score_row(bowler_id, game=1):
    conn = db_state.get_connection()
    row = conn.execute(
        "SELECT scratch_score, hdcp_score, total_score, verified, verified_by, recorded_by "
        "FROM scores WHERE bowler_id=? AND game_number=?",
        (bowler_id, game),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def test_director_name_matches_full_name_username_or_a_unique_first_name(db):
    _staff("skramer", "Scott Kramer", role="admin")
    _staff("pat", "Pat Lee")
    assert td_team.tournament_director_name("Scott Kramer") == "Scott Kramer"
    assert td_team.tournament_director_name("skramer") == "Scott Kramer"
    assert td_team.tournament_director_name("Scott") == "Scott Kramer"
    assert td_team.tournament_director_name("  scott  ") == "Scott Kramer"
    assert td_team.tournament_director_name("Pat") == "Pat Lee"
    assert td_team.tournament_director_name("Mike") is None
    assert td_team.tournament_director_name("") is None
    assert td_team.tournament_director_name("Scott (photo)") == "Scott Kramer"

    _staff("slee", "Scott Lee")
    assert td_team.tournament_director_name("Scott") is None  # two Scotts — type the full name
    assert td_team.tournament_director_name("Scott Lee") == "Scott Lee"
    assert td_team.tournament_director_name("Scott Kramer") == "Scott Kramer"

    _staff("old", "Old Timer", approved=0)
    _staff("gone", "Gone Fishing", active=0)
    assert td_team.tournament_director_name("Old Timer") is None
    assert td_team.tournament_director_name("Gone Fishing") is None


def test_floor_td_score_is_already_verified_and_a_helper_still_needs_a_check(db):
    tid, ann, bea = _event()
    _staff("skramer", "Scott Kramer", role="admin")

    _record_score(tid, ann, 1, 200, 10, "Scott")
    ann_row = _score_row(ann)
    assert ann_row["scratch_score"] == 200 and ann_row["total_score"] == 210
    assert ann_row["verified"] == 1 and ann_row["verified_by"] == "Scott Kramer"
    assert ann_row["recorded_by"] == "Scott"
    assert td_team.needs_verifying(tid) == []

    _record_score(tid, bea, 1, 120, 8, "Mike")
    bea_row = _score_row(bea)
    assert bea_row["scratch_score"] == 120 and bea_row["verified"] == 0 and bea_row["verified_by"] is None
    assert [row["name"] for row in td_team.needs_verifying(tid)] == ["Bea"]

    # A director who checks a photo and saves it is done. A helper's photo is not.
    _record_score(tid, ann, 2, 180, 10, "Scott (photo)", source="photo")
    photo = _score_row(ann, 2)
    assert photo["verified"] == 1 and photo["verified_by"] == "Scott Kramer"
    assert photo["recorded_by"] == "Scott (photo)"
    _record_score(tid, bea, 2, 0, 8, "Mike (photo)", source="photo")
    helper_photo = _score_row(bea, 2)
    assert helper_photo["scratch_score"] == 0 and helper_photo["verified"] == 0
    waiting = {(row["name"], row["game_number"], row["scratch_score"]) for row in td_team.needs_verifying(tid)}
    assert waiting == {("Bea", 1, 120), ("Bea", 2, 0)}


def test_lane_status_follows_saved_scores_only():
    assert lane_status_label(2, 2) == "COMPLETED"
    assert lane_status_label(2, 0) == "PENDING"
    assert lane_status_label(2, 1) == "1/2 ENTERED"
    assert lane_status_label(0, 0) == "PENDING"
    # A saved zero is still a score, so a full lane of zeros is completed.
    assert lane_status_label(1, 1) == "COMPLETED"


def test_each_poll_reads_scores_again_and_does_not_flip_back(db, monkeypatch):
    tid, ann, bea = _event()
    ctx = _Run()
    monkeypatch.setattr(run_memo, "_script_context", lambda: ctx)

    assert _matrix_snapshot(tid, 1)[0] == {}
    # Same run keeps the snapshot (the grid and the board share one read).
    assert _matrix_snapshot(tid, 1)[0] == {}

    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score, verified) "
            "VALUES (?, ?, 1, 200, 210, 1)",
            (tid, ann),
        )
        conn.execute(
            "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score, verified) "
            "VALUES (?, ?, 1, 0, 8, 1)",
            (tid, bea),
        )
    conn.close()

    # This run keeps the first read. The following polls see both saves, including the zero.
    assert _matrix_snapshot(tid, 1)[0] == {}
    ctx.poll()
    seen = _matrix_snapshot(tid, 1)[0]
    assert set(seen) == {ann, bea} and seen[bea]["scratch_score"] == 0
    assert lane_status_label(2, sum(1 for bid in (ann, bea) if bid in seen)) == "COMPLETED"
    ctx.poll()
    assert set(_matrix_snapshot(tid, 1)[0]) == {ann, bea}

    # One score removed: the lane is partial, not a flip back to pending.
    conn = db_state.get_connection()
    with conn:
        conn.execute("DELETE FROM scores WHERE bowler_id=?", (bea,))
    conn.close()
    ctx.poll()
    left = _matrix_snapshot(tid, 1)[0]
    assert set(left) == {ann}
    assert lane_status_label(2, len(left)) == "1/2 ENTERED"


def test_replaced_run_objects_are_a_new_run():
    ctx = _Run()
    first = run_memo._take_marker(ctx)
    assert run_memo._marker_alive(ctx, first) is True
    ctx.poll()
    assert run_memo._marker_alive(ctx, first) is False
    assert run_memo._marker_alive(ctx, run_memo._take_marker(ctx)) is True


def test_desk_auto_save_writes_only_changed_cells_and_keeps_them_verified(db):
    tid, ann, bea = _event()
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score, recorded_by, verified) "
            "VALUES (?, ?, 1, 180, 188, 'floor', 0)",
            (tid, bea),
        )
    conn.close()
    ids = [ann, bea]
    baseline = {ann: None, bea: 180}

    # Opening the grid, reloading, or an empty poll must not invent scores or re-verify Bea's.
    assert changed_cells_from_editor(ids, {}, baseline) == {}
    assert changed_cells_from_editor(ids, {"edited_rows": {0: {"Scratch": None}}}, baseline) == {}
    assert changed_cells_from_editor(ids, {"edited_rows": {1: {"Scratch": float("nan")}}}, baseline) == {}
    saved, history = apply_desk_editor(tid, 1, ids, {ann: 10, bea: 8}, {}, baseline, "Scott")
    assert saved == {} and history == []
    assert _score_row(ann) is None
    assert _score_row(bea)["verified"] == 0 and _score_row(bea)["scratch_score"] == 180

    # Typed 0 is a real score. Bea's unchanged 180 is not rewritten.
    state = {"edited_rows": {0: {"Scratch": 0}, 1: {"Scratch": 180}}}
    assert changed_cells_from_editor(ids, state, baseline) == {ann: 0}
    saved, history = apply_desk_editor(tid, 1, ids, {ann: 10, bea: 8}, state, baseline, "Scott")
    assert saved == {ann: 0} and history
    zero = _score_row(ann)
    assert zero["scratch_score"] == 0 and zero["total_score"] == 10 and zero["verified"] == 1
    assert zero["verified_by"] == "Scott" and zero["recorded_by"] == "Scott"
    assert _score_row(bea)["scratch_score"] == 180 and _score_row(bea)["verified"] == 0

    # The same edit again, once the baseline has caught up, writes nothing.
    baseline[ann] = 0
    saved, history = apply_desk_editor(tid, 1, ids, {ann: 10, bea: 8}, state, baseline, "Scott")
    assert saved == {} and history == []

    # Another TD's saved score shows up when this grid has no unsent edit.
    live = {ann: 0, bea: 190}
    assert baseline_needs_refresh(baseline, live, {}) is True
    assert baseline_needs_refresh(baseline, live, {"edited_rows": {0: {"Scratch": 15}}}) is False


def test_practice_auto_save_does_not_touch_other_lanes(db):
    from modules.practice import create_practice_tournament, is_practice

    pid = create_practice_tournament()
    assert is_practice(pid)
    conn = db_state.get_connection()
    rows = conn.execute(
        "SELECT id, name, handicap, lane_assignment FROM bowlers WHERE tournament_id=? ORDER BY id",
        (pid,),
    ).fetchall()
    before = {
        r["bowler_id"]: r["scratch_score"]
        for r in conn.execute(
            "SELECT bowler_id, scratch_score FROM scores WHERE tournament_id=? AND game_number=1",
            (pid,),
        )
    }
    conn.close()
    lane4 = [r for r in rows if r["lane_assignment"] == 4]
    assert lane4 and all(r["id"] not in before for r in lane4)
    target = lane4[0]
    ids = [r["id"] for r in rows]
    index = ids.index(target["id"])
    baseline = {r["id"]: before.get(r["id"]) for r in rows}
    state = {"edited_rows": {index: {"Scratch": 0}}}
    handicaps = {r["id"]: r["handicap"] for r in rows}
    saved, history = apply_desk_editor(pid, 1, ids, handicaps, state, baseline, "Scott")
    assert saved == {target["id"]: 0} and history
    assert _score_row(target["id"])["scratch_score"] == 0
    assert _score_row(target["id"])["verified"] == 1
    for bowler_id, scratch in before.items():
        assert _score_row(bowler_id)["scratch_score"] == scratch
    # The other two bowlers on lane 4 are still blank, so the lane is not finished.
    assert lane_status_label(len(lane4), 1) == f"1/{len(lane4)} ENTERED"


def test_desk_page_shows_real_lane_status_and_reload_does_not_write(db):
    from streamlit.testing.v1 import AppTest

    tid, ann, bea = _event()
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "UPDATE bowlers SET lane_assignment=2 WHERE id=?",
            (bea,),
        )
        conn.execute(
            "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score, recorded_by, verified) "
            "VALUES (?, ?, 1, 200, 210, 'floor', 0)",
            (tid, ann),
        )
    conn.close()
    path = str(db_state.DB_PATH)
    at = AppTest.from_string(
        "from pathlib import Path\nfrom modules import db_state\n"
        f"db_state.DB_PATH = Path({path!r})\n"
        "import streamlit as st\n"
        "st.session_state['user'] = {'username': 'skramer', 'display_name': 'Scott Kramer', 'role': 'admin'}\n"
        f"st.session_state['active_tournament_id'] = {tid}\n"
        "from views.hubs.active_squad import render_active_squad\n"
        "render_active_squad()\n",
        default_timeout=60,
    ).run()
    assert not at.exception, at.exception
    labels = [b.label for b in at.button]
    assert "Reload scores" in labels
    assert not any("Save Desk" in label for label in labels)
    board = " ".join(m.value for m in at.markdown)
    assert "COMPLETED" in board and "PENDING" in board
    next(b for b in at.button if b.label == "Reload scores").click().run()
    assert _score_row(ann)["scratch_score"] == 200 and _score_row(ann)["verified"] == 0
    assert _score_row(bea) is None


def test_floor_page_scott_does_not_land_in_needs_verifying(db):
    from streamlit.testing.v1 import AppTest

    tid, ann, bea = _event()
    _staff("skramer", "Scott Kramer", role="admin")
    path = str(db_state.DB_PATH)
    at = AppTest.from_string(
        "from pathlib import Path\nfrom modules import db_state\n"
        f"db_state.DB_PATH = Path({path!r})\n"
        "import streamlit as st\n"
        f"st.query_params['t'] = {str(tid)!r}\n"
        f"st.session_state['scorer_event'] = {tid}\n"
        "st.session_state['scorer_authenticated'] = True\n"
        "st.session_state['verifier_name'] = 'Scott'\n"
        "st.session_state['floor_device'] = 'phoneS'\n"
        "from views.mobile_scoring import render_mobile_scoring\n"
        "render_mobile_scoring()\n",
        default_timeout=60,
    ).run()
    assert not at.exception, at.exception
    next(n for n in at.number_input if n.label == "Scratch Score for Ann").set_value(200)
    at = at.form_submit_button[0].click().run()
    assert not at.exception, at.exception
    assert any("No second check is needed" in s.value for s in at.success)
    row = _score_row(ann)
    assert row["scratch_score"] == 200 and row["verified"] == 1
    assert row["verified_by"] == "Scott Kramer" and row["recorded_by"] == "Scott"
    assert td_team.needs_verifying(tid) == []
    assert _score_row(bea) is None


def test_desk_page_does_not_ask_for_a_save_click():
    text = (ROOT / "views/hubs/active_squad.py").read_text()
    assert "Save Desk Score Adjustments" not in text
    assert "A score saves when you leave the cell" in text
    assert "def _render_score_entry" in text
    body = text.split("def _render_score_entry", 1)[1][:400]
    assert "@st.fragment" not in body
