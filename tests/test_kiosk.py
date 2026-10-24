import sqlite3
from datetime import datetime, timezone

import pytest

from modules import db_state, kiosk_data, practice
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
from views.kiosk import build_html


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def test_parse_id_and_eastern_time():
    assert kiosk_data.parse_tournament_id({"t": "7"}) == 7
    assert kiosk_data.parse_tournament_id({"tournament": "3"}) == 3
    assert kiosk_data.parse_tournament_id({"t": "x; drop"}) is None
    assert kiosk_data.parse_tournament_id({}) is None
    assert kiosk_data.eastern_now(datetime(2026, 12, 6, 15, 5, tzinfo=timezone.utc)) == "10:05:00 AM ET"


def test_rose_murphy_groups_finalists_and_no_private_fields(db):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    conn = db_state.get_connection()
    with conn:
        for i in range(4):
            conn.execute("INSERT INTO bowlers (tournament_id, name, gender, entering_avg, email, paid_status, division)"
                         " VALUES (?, ?, 'Girls', 170, 'kid@x.com', 'unpaid', 'Division 1 – Girls')", (tid, f"Girl{i}"))
        conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score) VALUES (?,1,1,200)", (tid,))
    conn.close()
    board = kiosk_data.load_board(tid)
    labels = [g["label"] for g in board["groups"]]
    assert len(labels) >= 6  # 3 divisions x boys/girls
    girls = next(g for g in board["groups"] if g["rows"])
    assert girls["rows"][0]["name"] == "Girl0" and girls["rows"][0]["finalist"]
    assert not any(r["finalist"] for r in girls["rows"][1:])  # no games bowled yet
    html = build_html(board, 0, "now")
    for secret in ("kid@x.com", "unpaid", "fee", "Paid"):
        assert secret not in html
    assert "FINALIST" in "".join(build_html(board, i, "now") for i in range(len(kiosk_data.paginate(board["groups"]))))


def test_pagination_rotates():
    groups = [{"label": f"G{i}", "rows": [{"rank": 1, "name": "x", "games": 0, "total": 0, "finalist": False}] * 12}
              for i in range(6)]
    pages = kiosk_data.paginate(groups)
    assert len(pages) > 1 and all(len(p) <= 2 for p in pages)
    big = kiosk_data.paginate([{"label": "All", "rows": [{}] * 45}])
    assert len(big) == 3 and all(len(b["rows"]) <= 8 for pg in big for b in pg)  # 45 rows -> 6 blocks -> 3 pages
    board = {"name": "E", "center": "C", "practice": False, "groups": groups}
    assert "Page 1 of" in build_html(board, 0, "t") and "Page 2 of" in build_html(board, 1, "t")


def test_practice_banner_and_missing_things_never_crash(db, tmp_path, monkeypatch):
    t = practice.create_practice_tournament()
    assert "PRACTICE" in build_html(kiosk_data.load_board(t), 0, "t")
    assert kiosk_data.load_board(9999) is None
    bad = tmp_path / "empty.db"
    sqlite3.connect(bad).close()
    monkeypatch.setattr(db_state, "DB_PATH", bad)
    assert kiosk_data.load_board(1) is None


def test_center_full_name(db):
    from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    assert kiosk_data.load_board(tid)["center"] == "Forest Hill Lanes"
