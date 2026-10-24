import pytest

from modules import db_state, events, kiosk_data, practice, td_team
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template


@pytest.fixture
def two(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    a = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    conn = db_state.get_connection()
    with conn:
        b = conn.execute("INSERT INTO tournaments (name, host_center) VALUES ('Adult Open', 'C')").lastrowid
        conn.execute("INSERT INTO bowlers (tournament_id, name, gender, entering_avg) VALUES (?, 'Kid', 'Girls', 170)", (a,))
        conn.execute("INSERT INTO bowlers (tournament_id, name) VALUES (?, 'Adult')", (b,))
        conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score) VALUES (?, 1, 1, 180)", (a,))
        conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score) VALUES (?, 2, 1, 220)", (b,))
    conn.close()
    return a, b


def test_resolve_event_rules(two):
    a, b = two
    evs = events.active_events()
    assert {e["id"] for e in evs} == {a, b}
    assert events.resolve_event(evs, None) == (None, True)          # 2 active, no choice -> picker
    assert events.resolve_event(evs, str(b))[0]["id"] == b          # link / device choice wins
    assert events.resolve_event(evs, 999, a)[0]["id"] == a          # bad id falls through
    assert events.resolve_event(evs[:1], None)[0]["id"] == evs[0]["id"]  # one active -> no picker
    assert events.resolve_event([], None) == (None, False)
    assert events.parse_id("3; drop") is None


def test_two_events_never_mix(two):
    a, b = two
    assert [s["name"] for s in td_team.needs_verifying(a)] == ["Kid"]
    assert [s["name"] for s in td_team.needs_verifying(b)] == ["Adult"]
    td_team.send_message(a, "Scott", "youth lane 3")
    td_team.send_message(b, "Pat", "adult lane 9")
    assert [m["text"] for m in td_team.get_messages(a)] == ["youth lane 3"]
    assert [m["text"] for m in td_team.get_messages(b)] == ["adult lane 9"]
    names_a = [r["name"] for g in kiosk_data.load_board(a)["groups"] for r in g["rows"]]
    names_b = [r["name"] for g in kiosk_data.load_board(b)["groups"] for r in g["rows"]]
    assert names_a == ["Kid"] and names_b == ["Adult"]


def test_td_can_be_on_two_events(two):
    a, b = two
    td_team.heartbeat("scott", "Scott", a)
    td_team.heartbeat("scott", "Scott", b)
    td_team.heartbeat("pat", "Pat", b)
    assert [p["display_name"] for p in td_team.tds_on_duty(a)] == ["Scott"]
    assert sorted(p["display_name"] for p in td_team.tds_on_duty(b)) == ["Pat", "Scott"]
    assert td_team.heartbeat("scott", "Scott", None) is None


def test_practice_alongside_real_events(two):
    a, b = two
    p = practice.create_practice_tournament()
    evs = events.active_events()
    assert evs[-1]["id"] == p and evs[-1]["is_practice"]   # practice listed last
    assert practice.is_practice(p) and not practice.is_practice(a)
    practice.delete_practice_tournament(p)
    assert {e["id"] for e in events.active_events()} == {a, b}


def test_missing_tables_return_empty(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "x.db"; sqlite3.connect(path).close()
    monkeypatch.setattr(db_state, "DB_PATH", path)
    assert events.active_events() == []
