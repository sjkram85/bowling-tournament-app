from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from modules import db_state, td_team
from modules.photo_review import build_review, save_errors
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template

LANE = [{"id": 1, "name": "Ann Smith", "handicap": 10}, {"id": 2, "name": "Bea Jones", "handicap": 0},
        {"id": 3, "name": "Cal Ray", "handicap": 5}]


def test_build_review_flags():
    rv = build_review(LANE, [{"name": "ANN SMITH", "game_score": 201, "confidence": 0.95},
                             {"name": "Bea", "game_score": "312", "confidence": 0.9},
                             {"name": "Zed", "game_score": 150}, {"name": "Cal Ray", "game_score": 180, "confidence": 0.4}])
    by = {r["bowler_id"]: r for r in rv["rows"]}
    assert by[1]["value"] == 201 and by[1]["flags"] == []
    assert by[2]["value"] == 312 and "out of range (0–300)" in by[2]["flags"]
    assert "low confidence" in by[3]["flags"]
    assert rv["unmatched"] == ["Zed"]
    rv = build_review(LANE, [{"name": "Ann Smith", "game_score": None}])
    assert {r["bowler_id"]: r["flags"] for r in rv["rows"]}[1] == ["missing"]
    assert save_errors({1: 301}) and not save_errors({1: 300, 2: 0})


@pytest.fixture
def ev(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setattr(db_state, "DB_PATH", path)
    db_state.init_db()
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    conn = db_state.get_connection()
    with conn:
        for b in LANE:
            conn.execute("INSERT INTO bowlers (id, tournament_id, name, handicap, lane_assignment) VALUES (?,?,?,?,1)",
                         (b["id"], tid, b["name"], b["handicap"]))
    conn.close()
    return tid, path


def _review_app(tid, path, values):
    img = Path(path).parent / "m.png"
    from PIL import Image
    Image.new("RGB", (60, 40)).save(img)
    return AppTest.from_string(
        "from pathlib import Path\nfrom modules import db_state\n"
        f"db_state.DB_PATH = Path({str(path)!r})\n"
        "from modules.photo_review import build_review\nfrom views.mobile_scoring import _render_photo_review\n"
        f"rv = build_review({LANE!r}, {values!r})\n"
        f"_render_photo_review({{'id': {tid}, 'game_count': 3}}, 1, 1, Path({str(img)!r}).read_bytes(), rv, 'Mike')\n",
        default_timeout=30)


def _scores(tid):
    conn = db_state.get_connection()
    rows = conn.execute("SELECT bowler_id, scratch_score, verified, recorded_by FROM scores WHERE tournament_id=?",
                        (tid,)).fetchall()
    conn.close()
    return {r["bowler_id"]: dict(r) for r in rows}


def test_review_saves_only_after_button_and_goes_to_verify(ev):
    tid, path = ev
    at = _review_app(tid, path, [{"name": "Ann Smith", "game_score": 201}, {"name": "Bea Jones", "game_score": 190}]).run()
    assert not at.exception
    assert any("Does this look right" in m.value for m in at.markdown)
    assert _scores(tid) == {}  # nothing saved yet
    at.number_input[1].set_value(195).run()  # TD fixes Bea
    next(b for b in at.button if b.label == "Save these scores").click().run()
    s = _scores(tid)
    assert s[1]["scratch_score"] == 201 and s[2]["scratch_score"] == 195 and 3 not in s  # Cal missing -> skipped
    assert all(v["verified"] == 0 and v["recorded_by"] == "Mike (photo)" for v in s.values())
    assert len(td_team.needs_verifying(tid)) == 2


def test_over_300_blocks_save(ev):
    tid, path = ev
    at = _review_app(tid, path, [{"name": "Ann Smith", "game_score": 345}]).run()
    assert any("over 300" in e.value for e in at.error)
    assert next(b for b in at.button if b.label == "Save these scores").disabled


def test_ai_failure_returns_none(monkeypatch):
    import views.mobile_scoring as ms
    monkeypatch.setattr(ms, "extract_scores_from_overhead_photo", lambda b: {"status": "error", "message": "x", "extracted_data": []})
    assert ms.read_photo(b"img", LANE) is None
    def boom(b): raise RuntimeError("network")
    monkeypatch.setattr(ms, "extract_scores_from_overhead_photo", boom)
    assert ms.read_photo(b"img", LANE) is None
    monkeypatch.setattr(ms, "extract_scores_from_overhead_photo",
                        lambda b: {"status": "success", "extracted_data": [{"name": "Cal Ray", "game_score": 177}]})
    assert {r["bowler_id"]: r["value"] for r in ms.read_photo(b"img", LANE)["rows"]}[3] == 177
