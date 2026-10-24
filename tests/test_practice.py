import pytest

from modules import db_state, practice


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _count(sql, args=()):
    conn = db_state.get_connection()
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def test_practice_create_contents_and_delete(db):
    conn = db_state.get_connection()
    with conn:
        conn.execute("INSERT INTO tournaments (name, host_center) VALUES ('Real Open', 'C')")
        conn.execute("INSERT INTO bowlers (tournament_id, name) VALUES (1, 'Real Person')")
    conn.close()
    t = practice.create_practice_tournament()
    assert practice.create_practice_tournament() == t  # only one at a time
    assert practice.is_practice(t) and not practice.is_practice(1)
    assert _count("SELECT COUNT(*) FROM bowlers WHERE tournament_id=?", (t,)) == 12
    assert _count("SELECT COUNT(*) FROM bowlers WHERE tournament_id=? AND checked_in=0", (t,)) == 1
    assert _count("SELECT COUNT(*) FROM bowlers WHERE tournament_id=? AND paid_status='unpaid'", (t,)) == 2
    assert _count("SELECT COUNT(DISTINCT lane_assignment) FROM bowlers WHERE tournament_id=?", (t,)) == 4
    assert _count("SELECT COUNT(*) FROM scores WHERE tournament_id=?", (t,)) == 9

    assert practice.delete_practice_tournament(1) is False  # never deletes a real tournament
    assert practice.delete_practice_tournament(t) is True
    assert _count("SELECT COUNT(*) FROM tournaments WHERE id=?", (t,)) == 0
    assert _count("SELECT COUNT(*) FROM bowlers WHERE tournament_id=?", (t,)) == 0
    assert _count("SELECT COUNT(*) FROM scores WHERE tournament_id=?", (t,)) == 0
    assert _count("SELECT COUNT(*) FROM bowlers WHERE tournament_id=1") == 1


def test_practice_blocked_from_archive_exports_email(db):
    from modules import cde_bls_bridge, mailer, reports

    t = practice.create_practice_tournament()
    for fn in (lambda: reports.freeze_tournament(t), lambda: reports.build_certified_pdf(t, "TD"),
               lambda: reports.build_smart_scholarship_csv(t), lambda: cde_bls_bridge.build_bls_streams(t)):
        with pytest.raises(practice.PracticeBlocked):
            fn()
    assert mailer.dispatch_bowler_recap_email({"email": "x@example.com", "tournament_id": t, "name": "Practice Pat"}, [], {}) is False
    assert _count("SELECT status FROM tournaments WHERE id=?", (t,)) == "active"
