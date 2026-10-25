"""Must-fix items for the Dec 6 closeout: lanes, stepladder, placement, roll-off, freeze, averages."""

from pathlib import Path

import pytest

from modules import db_state, rolloff, stepladder
from modules.brackets import create_brackets_for_tournament, event_uses_brackets, get_bracket_financial_ledger
from modules.divisions import UNASSIGNED, clean_average, division_for, entry_handicap, get_divisions
from modules.events import cancel_tournament, scoring_is_open
from modules.placement import closeout_standings
from modules.reports import freeze_tournament, latest_archive, reopen_tournament, save_tournament_archive
from modules.standings import current_lane, event_lane_pattern, get_tournament
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
from views.hubs.active_squad import _lane_now, _save_score
from views.kiosk import build_html
from views.mobile_scoring import _lane_for

ROOT = Path(__file__).resolve().parents[1]
GROUP = "Division 1 – Girls"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _scores(tid, scores, division=GROUP, gender="Girls", prefix="G", youth=1):
    conn = db_state.get_connection()
    ids = []
    with conn:
        for i, s in enumerate(scores):
            cur = conn.execute(
                "INSERT INTO bowlers (tournament_id, name, gender, entering_avg, division, is_youth, lane_assignment)"
                " VALUES (?,?,?,?,?,?,?)",
                (tid, f"{prefix}{i}", gender, 170, division, youth, 1 + (i % 4)),
            )
            ids.append(cur.lastrowid)
            conn.execute(
                "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score)"
                " VALUES (?,?,1,?,?)",
                (tid, cur.lastrowid, s, s),
            )
    conn.close()
    return ids


def _plain(name="Open"):
    conn = db_state.get_connection()
    with conn:
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(tournaments)")}
        vals = {c: ("Open" if c == "name" else 0) for c, r in cols.items() if r[3] and r[4] is None and c != "id"}
        vals["name"] = name
        cur = conn.execute(
            f"INSERT INTO tournaments ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})",
            list(vals.values()),
        )
    conn.close()
    return cur.lastrowid


def test_same_pair_desk_and_floor_agree_and_do_not_cross(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    t = get_tournament(tid)
    assert event_lane_pattern(t) == "same_pair"
    squad = [{"id": i, "lane_assignment": lane} for i, lane in enumerate((1, 2, 7, 8), start=1)]
    for game in (1, 2, 3):
        for b in squad:
            assert _lane_now(b, game, t, squad) == _lane_for(t, b, game, squad) == b["lane_assignment"]
    cross = {"host_center": "FHL", "lane_pattern": "cross"}
    assert current_lane(1, 2, cross, squad) == _lane_for(cross, squad[0], 2, squad)
    assert current_lane(1, 2, cross, squad) != 1  # across the house, not used for Rose Murphy
    desk = (ROOT / "views/hubs/active_squad.py").read_text()
    assert "index=min(2" not in desk
    assert "def _render_score_entry" in desk and "@st.fragment" not in desk.split("def _render_score_entry")[1][:400]


def test_score_saves_to_the_selected_game(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    bid = _scores(tid, [100])[0]
    assert _save_score(tid, bid, 2, 180, 12, "Scott")
    conn = db_state.get_connection()
    rows = conn.execute("SELECT game_number, scratch_score FROM scores WHERE bowler_id=?", (bid,)).fetchall()
    conn.close()
    by_game = {r["game_number"]: r["scratch_score"] for r in rows}
    assert by_game[2] == 180 and 3 not in by_game


def test_blank_average_is_not_division_1_and_handicap_follows_average(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    t = get_tournament(tid)
    divs = get_divisions(t)
    assert clean_average(None) is None and clean_average(0) is None and clean_average("") is None
    assert division_for(None, divs) == UNASSIGNED
    assert division_for(200, divs) == "Division 1"
    assert entry_handicap(t, None, False) is None
    assert entry_handicap(t, 150, False) == 63
    assert entry_handicap(t, 150, True) == 0
    conn = db_state.get_connection()
    with conn:
        conn.execute("INSERT INTO bowlers (tournament_id, name) VALUES (?, 'Kid')", (tid,))
        avg = conn.execute("SELECT entering_avg FROM bowlers WHERE name='Kid'").fetchone()["entering_avg"]
    conn.close()
    assert avg is None
    src = (ROOT / "views/intake_gateway.py").read_text()
    assert "value=200" not in src and "value=18" not in src


def test_stepladder_accepts_handicap_total_and_can_be_cleared(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    t = get_tournament(tid)
    assert stepladder.max_match_score(t) == 300 + int(220 * 90 / 100)
    assert stepladder.max_match_score(t) > 300
    _scores(tid, [700, 680, 650], "Division 1 – Boys", "Boys", "B")
    boys = next(k for k, g in stepladder.seeds(tid).items() if g["seeds"] and "Boys" in k)
    assert stepladder.initialize_stepladder(tid, boys)
    n_scores = db_state.get_connection().execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    db_state.get_connection().close()
    cleared = stepladder.clear_stepladder(tid, boys, "Scott")
    assert cleared["ok"] and stepladder.get_stepladder_state(tid, boys) == []
    assert db_state.get_connection().execute("SELECT COUNT(*) FROM scores").fetchone()[0] == n_scores
    db_state.get_connection().close()
    assert stepladder.initialize_stepladder(tid, boys)
    match = stepladder.get_stepladder_state(tid, boys)[0]
    assert stepladder.record_stepladder_score(match["id"], 420, 410)
    assert stepladder.get_stepladder_state(tid, boys)[0]["winner_id"] == match["bowler_low_id"]
    assert not stepladder.clear_stepladder(tid, boys)["ok"]
    assert stepladder.clear_stepladder(tid, boys, force=True)["ok"]
    assert db_state.get_connection().execute("SELECT COUNT(*) FROM scores").fetchone()[0] == n_scores


def test_closeout_champion_is_first_and_unfinished_withholds_awards(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    _scores(tid, [700, 680, 650, 600])
    before = [r for r in closeout_standings(tid)["rows"] if r["group"] == GROUP]
    assert before[0]["name"] == "G0" and before[0]["place"] == 1 and before[0]["prize"] == 500
    stepladder.initialize_stepladder(tid, GROUP)
    held = closeout_standings(tid)
    girls = [r for r in held["rows"] if r["group"] == GROUP]
    assert any("no awards shown" in w.lower() or "Finals not finished" in w for w in held["warnings"])
    assert all(r["prize"] == 0 and r["place"] is None for r in girls)
    while True:
        active = [m for m in stepladder.get_stepladder_state(tid, GROUP) if m["status"] == "active"]
        if not active:
            break
        stepladder.record_stepladder_score(active[0]["id"], 250, 200)  # low seed climbs
    after = [r for r in closeout_standings(tid)["rows"] if r["group"] == GROUP]
    assert after[0]["name"] == "G2" and after[0]["place"] == 1 and after[0]["champion"]
    assert after[0]["prize"] == 500 and after[0]["qual_rank"] == 3
    assert not closeout_standings(tid)["warnings"]


def test_rolloff_pending_withholds_and_winner_can_be_replaced(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    ids = _scores(tid, [700, 680, 646, 646, 600])
    held = closeout_standings(tid)
    assert any("Roll-off" in w for w in held["warnings"])
    assert all(r["prize"] == 0 for r in held["rows"] if r["group"] == GROUP)
    wrong, right = ids[2], ids[3]
    assert rolloff.record_winner(tid, GROUP, wrong, 646, "Scott", rolloff_score=150)
    conn = db_state.get_connection()
    assert conn.execute("SELECT rolloff_score FROM cut_rolloffs WHERE bowler_id=?", (wrong,)).fetchone()["rolloff_score"] == 150
    conn.close()
    assert rolloff.record_winner(tid, GROUP, right, 646, "Scott", rolloff_score=170, replace=True)
    from modules.divisions import grouped_results
    g = next(g for g in grouped_results(tid) if g["group"] == GROUP)
    by = {r["id"]: r for r in g["rows"]}
    assert by[right]["finalist"] and not by[wrong]["finalist"]
    assert rolloff.remove_winner(tid, GROUP, right)
    g = next(g for g in grouped_results(tid) if g["group"] == GROUP)
    assert g["rolloff"] and any(r["id"] == right for r in g["rolloff"]["bowlers"])


def test_freeze_archives_pdf_keeps_scores_and_reopens(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    bid = _scores(tid, [700, 680, 650])[0]
    before = db_state.get_connection().execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    db_state.get_connection().close()
    archive_id = save_tournament_archive(tid, "Scott")
    assert archive_id and latest_archive(tid)["certified_pdf"][:4] == b"%PDF"
    assert scoring_is_open(tid)
    freeze_tournament(tid, "Scott")
    assert not scoring_is_open(tid)
    assert _save_score(tid, bid, 2, 150, 0, "Scott") is None
    conn = db_state.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == before
    assert conn.execute("SELECT status FROM tournaments WHERE id=?", (tid,)).fetchone()["status"] == "closed"
    assert conn.execute("SELECT COUNT(*) FROM tournament_archives WHERE tournament_id=?", (tid,)).fetchone()[0] >= 1
    conn.close()
    assert reopen_tournament(tid, "Scott")
    assert scoring_is_open(tid)
    assert _save_score(tid, bid, 2, 155, 0, "Scott")
    conn = db_state.get_connection()
    assert conn.execute("SELECT scratch_score FROM scores WHERE bowler_id=? AND game_number=2", (bid,)).fetchone()["scratch_score"] == 155
    conn.close()


def test_cancel_keeps_scores(db):
    tid = _plain()
    conn = db_state.get_connection()
    with conn:
        bid = conn.execute("INSERT INTO bowlers (tournament_id, name) VALUES (?, 'Ann')", (tid,)).lastrowid
        conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score) VALUES (?,?,1,180,180)",
                     (tid, bid))
    conn.close()
    cancel_tournament(tid, "Scott")
    conn = db_state.get_connection()
    status = conn.execute("SELECT status FROM tournaments WHERE id=?", (tid,)).fetchone()["status"]
    scores = conn.execute("SELECT COUNT(*) FROM scores WHERE tournament_id=?", (tid,)).fetchone()[0]
    conn.close()
    assert status == "cancelled" and scores == 1


def test_rose_murphy_brackets_do_not_invent_money(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    t = get_tournament(tid)
    assert not event_uses_brackets(t)
    for i in range(10):
        _scores(tid, [100], prefix=f"X{i}")
    assert create_brackets_for_tournament(tid) == 0
    ledger = get_bracket_financial_ledger(tid)
    assert ledger["enabled"] is False
    assert ledger["bracket_payout_liability"] == 0 and ledger["total_collected"] == 0


def test_kiosk_shows_champion_as_first(db):
    from modules.kiosk_data import load_board
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    _scores(tid, [700, 680, 650, 600])
    stepladder.initialize_stepladder(tid, GROUP)
    pending = load_board(tid)
    girls = next(g for g in pending["groups"] if g["rows"] and g["rows"][0]["name"].startswith("G"))
    assert girls["rows"][0]["name"] == "G0" and not girls["rows"][0].get("champion")
    assert "Finals not finished" in (girls.get("note") or "")
    while True:
        active = [m for m in stepladder.get_stepladder_state(tid, GROUP) if m["status"] == "active"]
        if not active:
            break
        stepladder.record_stepladder_score(active[0]["id"], 250, 200)
    board = load_board(tid)
    girls = next(g for g in board["groups"] if any(r["name"] == "G2" for r in g["rows"]))
    assert girls["rows"][0]["name"] == "G2" and girls["rows"][0]["rank"] == 1 and girls["rows"][0]["champion"]
    html = "".join(build_html(board, i, "t") for i in range(4))
    assert "CHAMPION" in html and "Final placement" in html
