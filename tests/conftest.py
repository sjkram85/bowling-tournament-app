"""Optional: run the whole suite against a local libSQL server (sqld) to exercise the Turso path.

    sqld --http-listen-addr 127.0.0.1:8089 -d /tmp/sqld-data &
    PRISM_TEST_TURSO_URL=http://127.0.0.1:8089 python3 -m pytest -q -p no:randomly

Each test starts from an empty server database. Never point this at a real Turso database.
"""
import os

import pytest

_URL = os.environ.get("PRISM_TEST_TURSO_URL", "")


@pytest.fixture(autouse=True)
def _fresh_sqld(monkeypatch):
    if not _URL:
        yield
        return
    assert "turso.io" not in _URL, "never run tests against a real Turso database"
    monkeypatch.setenv("TURSO_DATABASE_URL", _URL)
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "local-test")
    from modules import db_state
    conn = db_state.get_connection()
    conn.execute("PRAGMA foreign_keys = OFF")
    for t, n, _ in reversed(db_state._user_objects(conn)):
        if t in ("table", "view", "trigger"):
            conn.execute(f'DROP {t.upper()} IF EXISTS "{n}"')
    conn.commit()
    conn.close()
    yield
