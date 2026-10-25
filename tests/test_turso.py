"""Turso switch: the libSQL adapter behaves like sqlite3, backend choice, backups, one-time copy.

Uses libSQL's embedded file mode (no network, no credentials). Skipped if libsql isn't installed.
"""
import sqlite3

import pytest

from modules import db_state

libsql = pytest.importorskip("libsql")


@pytest.fixture
def lib_db(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("PRISM_DB_ENGINE", "libsql-file")
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "lib.db")
    db_state.init_db()
    return tmp_path


def test_fallback_is_local_sqlite_without_secrets(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PRISM_DB_ENGINE", raising=False)
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "x.db")
    conn = db_state.get_connection()
    assert isinstance(conn, sqlite3.Connection)
    conn.close()
    assert not db_state.using_turso()
    assert db_state.storage_label() == "Data: local (temporary)"


def test_turso_chosen_only_when_both_settings_present(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.invalid")
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    assert not db_state.using_turso()
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "placeholder")
    assert db_state.using_turso()
    assert db_state.storage_label() == "Data: Turso (permanent)"


def test_adapter_rows_lastrowid_errors_and_migrations(lib_db):
    conn = db_state.get_connection()
    assert isinstance(conn, db_state.LibsqlConnection)
    cols = [c[1] for c in conn.execute("PRAGMA table_info(tournaments)")]
    assert "cert_number" in cols and "is_practice" in cols  # guarded ALTER TABLE ran
    with conn:
        cur = conn.execute("INSERT INTO tournaments (name, host_center, squad_format, game_count, pin_verifier)"
                           " VALUES (?, ?, ?, ?, ?)", ("Test Open", "FHL", "Singles", 3, "1111"))
        tid = cur.lastrowid
    row = conn.execute("SELECT id, name FROM tournaments WHERE id = ?", (tid,)).fetchone()
    assert row["name"] == "Test Open" and row[0] == tid and dict(row)["id"] == tid and row.keys() == ["id", "name"]
    assert [r["name"] for r in conn.execute("SELECT name FROM tournaments")] == ["Test Open"]
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT nope FROM tournaments")
    conn.executescript("CREATE TABLE IF NOT EXISTS z (a TEXT UNIQUE); INSERT INTO z VALUES ('x');")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO z VALUES ('x')")
    try:
        with conn:
            conn.execute("INSERT INTO z VALUES ('y')")
            raise RuntimeError
    except RuntimeError:
        pass
    assert conn.execute("SELECT COUNT(*) FROM z").fetchone()[0] == 1  # rolled back
    conn.close()
    db_state.init_db()  # second run on an existing database is harmless


def test_libsql_connection_is_reused_and_close_still_rolls_back(lib_db):
    a = db_state.get_connection()
    a.execute("CREATE TABLE IF NOT EXISTS reuse_probe (n INT)")
    a.commit()
    with a:
        a.execute("INSERT INTO reuse_probe VALUES (1)")
    a.execute("INSERT INTO reuse_probe VALUES (7)")  # left uncommitted on purpose
    a.close()
    a.close()  # returning to the pool twice must not hand the same connection out twice
    b = db_state.get_connection()
    assert b is a
    assert [r[0] for r in b.execute("SELECT n FROM reuse_probe").fetchall()] == [1]
    assert b.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    b.close()


def test_backup_and_restore_through_adapter(lib_db):
    from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "FHL")
    data = db_state.backup_bytes()
    info = db_state.inspect_backup(data)
    assert info["events"] == 1
    conn = db_state.get_connection()
    with conn:
        conn.execute("DELETE FROM tournaments")
    conn.close()
    db_state.restore_from_bytes(data)
    conn = db_state.get_connection()
    assert conn.execute("SELECT id FROM tournaments").fetchone()["id"] == tid
    conn.close()


def test_copy_local_into_empty_turso_and_refuse_overwrite(tmp_path, monkeypatch):
    local = tmp_path / "tournament.db"
    monkeypatch.setattr(db_state, "DB_PATH", local)
    monkeypatch.delenv("PRISM_DB_ENGINE", raising=False)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db_state.init_db()
    from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
    create_tournament_from_template(ROSE_MURPHY_KEY, "FHL")
    # Pretend Turso = a separate libSQL file (embedded mode), no network.
    remote = tmp_path / "remote.db"
    monkeypatch.setenv("TURSO_DATABASE_URL", str(remote))
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "placeholder")
    monkeypatch.setattr(db_state, "_connect_libsql", lambda target, token=None: db_state.LibsqlConnection(libsql.connect(target)))
    assert not db_state.turso_has_data()
    assert db_state.auto_migrate_to_turso() is True
    assert db_state.turso_has_data()
    conn = db_state.get_connection()
    assert conn.execute("SELECT COUNT(*) AS n FROM tournaments").fetchone()["n"] == 1
    conn.close()
    assert db_state.auto_migrate_to_turso() is False  # never overwrites
    with pytest.raises(ValueError):
        db_state.copy_local_to_turso()
    db_state.copy_local_to_turso(replace=True)  # explicit replace saves a safety copy first
    assert list((tmp_path / "backups").glob("pre-copy-turso-*.db"))


# The sign-in screen runs this CREATE on every logged-out desk open. The semicolon
# and the newline after it are what Turso prepare treats as a second statement.
_BOOTSTRAP_CREATE = """
                CREATE TABLE IF NOT EXISTS staff_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    email TEXT DEFAULT '',
                    center_affiliation TEXT DEFAULT 'CHUSBC',
                    role TEXT NOT NULL DEFAULT 'td',
                    is_approved INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """


def _drain_pool():
    with db_state._pool_guard:
        idle = [c for conns in db_state._pool_idle.values() for c in conns]
        db_state._pool_idle.clear()
    for conn in idle:
        db_state._really_close(conn)


class _RawProxy:
    """Stand-in for libsql's Connection. Its cursor() and execute are read-only, so tests wrap it."""

    def __init__(self, raw, on_execute):
        self._raw = raw
        self._on_execute = on_execute

    def cursor(self):
        return _CursorProxy(self._raw.cursor(), self._on_execute)

    def __getattr__(self, name):
        return getattr(self._raw, name)


class _CursorProxy:
    def __init__(self, cur, on_execute):
        self._cur = cur
        self._on_execute = on_execute

    def execute(self, sql, params=None):
        self._on_execute(sql)
        if params is None:
            return self._cur.execute(sql)
        return self._cur.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._cur, name)


def _has_statement_tail(sql) -> bool:
    return isinstance(sql, str) and ";" in sql and sql[sql.rfind(";") + 1:] != ""


def test_statement_tail_is_stripped_before_libsql_sees_it():
    stripped = db_state._without_statement_tail(_BOOTSTRAP_CREATE)
    assert stripped.lstrip().startswith("CREATE TABLE IF NOT EXISTS staff_users")
    assert stripped.rstrip().endswith(")")
    assert ";" not in stripped
    # Leading whitespace stays. Only a semicolon whose tail is whitespace is removed.
    assert stripped.startswith("\n")
    assert db_state._without_statement_tail("SELECT 1;\n    ") == "SELECT 1"
    assert db_state._without_statement_tail("SELECT 1;") == "SELECT 1"
    # A real second statement is not turned into the first one.
    assert db_state._without_statement_tail("SELECT 1; SELECT 2") == "SELECT 1; SELECT 2"
    assert db_state._without_statement_tail("SELECT 1; SELECT 2;") == "SELECT 1; SELECT 2"


def test_bootstrap_create_runs_when_turso_rejects_a_statement_tail(lib_db, monkeypatch):
    from modules.auth import _bootstrap_admin

    seen = []
    real_connect = db_state._connect_libsql

    def connect(target, token=None):
        conn = real_connect(target, token)

        def on_execute(sql):
            seen.append(sql)
            # Hosted Turso raises ValueError for this. Embedded libSQL does not, so the test does.
            if _has_statement_tail(sql):
                raise ValueError("SQL string contains more than one statement")

        conn._raw = _RawProxy(conn._raw, on_execute)
        return conn

    monkeypatch.setattr(db_state, "_connect_libsql", connect)
    _drain_pool()
    try:
        _bootstrap_admin()
        assert seen, "bootstrap did not execute any SQL"
        assert any(sql.lstrip().upper().startswith("CREATE TABLE") for sql in seen)
        assert all(not _has_statement_tail(sql) for sql in seen)
        conn = db_state.get_connection()
        row = conn.execute(
            "SELECT username, role FROM staff_users WHERE username = ?",
            ("skramer",),
        ).fetchone()
        conn.close()
        assert row["username"] == "skramer"
        assert row["role"] == "admin"
    finally:
        _drain_pool()


def test_expired_turso_stream_is_reopened_for_the_same_call(lib_db):
    _drain_pool()
    conn = db_state.get_connection()
    state = {"n": 0}

    def on_execute(sql):
        state["n"] += 1
        if state["n"] == 1:
            raise ValueError(
                'Hrana: api error: {"message":"The stream has expired due to inactivity",'
                '"code":"STREAM_EXPIRED"}'
            )

    conn._raw = _RawProxy(conn._raw, on_execute)
    try:
        # Same shape as opening the desk: the first statement is the login bootstrap.
        conn.execute(_BOOTSTRAP_CREATE)
        assert state["n"] == 1  # the dead stream failed; the retry used a new connection
        row = conn.execute("SELECT COUNT(*) FROM staff_users").fetchone()
        assert row[0] >= 0
    finally:
        conn.close()
        _drain_pool()
