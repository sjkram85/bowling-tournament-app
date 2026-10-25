"""libSQL file adapter behaves like sqlite3. The live engine stays the local SQLite file.

Uses libSQL's embedded file mode (no network, no credentials). Skipped if libsql isn't installed.
TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must not select a database.
"""
import logging
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
    assert db_state.storage_label() == "Data: local SQLite"


def test_turso_secrets_do_not_select_a_database(tmp_path, monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.invalid")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "placeholder")
    monkeypatch.delenv("PRISM_DB_ENGINE", raising=False)
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "x.db")
    assert db_state.turso_config() is None
    assert not db_state.using_turso()
    assert db_state.storage_label() == "Data: local SQLite"
    conn = db_state.get_connection()
    assert isinstance(conn, sqlite3.Connection)
    conn.close()


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


def test_turso_secrets_do_not_copy_or_switch_the_file(tmp_path, monkeypatch):
    local = tmp_path / "tournament.db"
    monkeypatch.setattr(db_state, "DB_PATH", local)
    monkeypatch.delenv("PRISM_DB_ENGINE", raising=False)
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.invalid")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "placeholder")
    db_state.init_db()
    from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
    create_tournament_from_template(ROSE_MURPHY_KEY, "FHL")
    assert db_state.auto_migrate_to_turso() is False
    assert not db_state.turso_has_data()
    assert not db_state.using_turso()
    conn = db_state.get_connection()
    assert isinstance(conn, sqlite3.Connection)
    assert conn.execute("SELECT COUNT(*) AS n FROM tournaments").fetchone()["n"] == 1
    conn.close()
    with pytest.raises(ValueError, match="local SQLite"):
        db_state.copy_local_to_turso()
    with pytest.raises(ValueError, match="local SQLite"):
        db_state.copy_local_to_turso(replace=True)


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


def _install_sql_probe(monkeypatch, seen, reject=None):
    """Record SQL. ``reject(sql)`` may raise ValueError the way hosted Turso does."""
    real_connect = db_state._connect_libsql

    def connect(target, token=None):
        conn = real_connect(target, token)

        def on_execute(sql):
            seen.append(sql)
            if reject is not None:
                reject(sql)

        conn._raw = _RawProxy(conn._raw, on_execute)
        return conn

    monkeypatch.setattr(db_state, "_connect_libsql", connect)


def _sql_head(sql: str) -> str:
    return sql.lstrip().upper()


def test_bootstrap_skips_create_when_staff_table_exists(lib_db, monkeypatch):
    """init_db already made staff_users. A logged-out open must not CREATE or ALTER."""
    from modules import auth
    from modules.auth import _bootstrap_admin

    seen = []

    def reject(sql):
        # Hosted Turso raises ValueError for a statement tail. Embedded libSQL does not.
        if _has_statement_tail(sql):
            raise ValueError("SQL string contains more than one statement")

    _install_sql_probe(monkeypatch, seen, reject)
    _drain_pool()
    try:
        _bootstrap_admin()
        assert seen, "bootstrap did not execute any SQL"
        assert not any(_sql_head(sql).startswith("CREATE TABLE") for sql in seen)
        assert not any(_sql_head(sql).startswith("ALTER TABLE") for sql in seen)
        assert not any("sqlite_master" in sql.lower() for sql in seen)
        assert all(not _has_statement_tail(sql) for sql in seen)
        conn = db_state.get_connection()
        row = conn.execute(
            "SELECT username, role FROM staff_users WHERE username = ?",
            ("skramer",),
        ).fetchone()
        conn.close()
        assert row["username"] == "skramer"
        assert row["role"] == "admin"
        assert auth.authenticate("skramer", "Gussierocks1")["role"] == "admin"

        # The row is there. Another anonymous open is a read, not a rehash or UPDATE.
        seen.clear()
        hashed = []
        real_hash = auth.hash_password

        def note_hash(password):
            hashed.append(password)
            return real_hash(password)

        monkeypatch.setattr(auth, "hash_password", note_hash)
        _bootstrap_admin()
        assert hashed == []
        assert seen, "a later open did not read staff_users"
        assert all(_sql_head(sql).startswith("SELECT") for sql in seen)
        monkeypatch.setattr(auth, "hash_password", real_hash)

        seen.clear()
        conn = db_state.get_connection()
        conn.execute("DROP TABLE staff_users")
        conn.commit()
        conn.close()
        _bootstrap_admin()
        creates = [sql for sql in seen if _sql_head(sql).startswith("CREATE TABLE")]
        assert len(creates) == 1
        assert creates[0].lstrip().startswith("CREATE TABLE IF NOT EXISTS staff_users")
        assert creates[0].rstrip().endswith(")")
        assert ";" not in creates[0]
        assert all(not _has_statement_tail(sql) for sql in seen)
        conn = db_state.get_connection()
        row = conn.execute(
            "SELECT username, role FROM staff_users WHERE username = ?",
            ("skramer",),
        ).fetchone()
        conn.close()
        assert row["role"] == "admin"
    finally:
        _drain_pool()


def test_bootstrap_logs_prepare_error_and_tries_again(lib_db, monkeypatch, caplog):
    """A Turso prepare failure must not raise, and must not stick for the next open."""
    from modules.auth import _bootstrap_admin

    seen = []
    state = {"fail": True}

    def reject(sql):
        if state["fail"] and "staff_users" in sql.lower():
            raise ValueError("SQL string contains more than one statement")

    _install_sql_probe(monkeypatch, seen, reject)
    _drain_pool()
    try:
        with caplog.at_level(logging.ERROR, logger="modules.auth"):
            _bootstrap_admin()
        assert "more than one statement" in caplog.text
        first = len(seen)
        assert first >= 1
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="modules.auth"):
            _bootstrap_admin()
        assert len(seen) > first
        assert "more than one statement" in caplog.text

        state["fail"] = False
        _bootstrap_admin()
        conn = db_state.get_connection()
        row = conn.execute(
            "SELECT role FROM staff_users WHERE username = ?",
            ("skramer",),
        ).fetchone()
        conn.close()
        assert row["role"] == "admin"
    finally:
        _drain_pool()


def test_bootstrap_create_failure_is_retried_when_the_table_is_missing(lib_db, monkeypatch, caplog):
    from modules.auth import _bootstrap_admin

    seen = []
    state = {"fail_create": True}

    def reject(sql):
        if state["fail_create"] and _sql_head(sql).startswith("CREATE TABLE"):
            raise ValueError("SQL string contains more than one statement")

    _install_sql_probe(monkeypatch, seen, reject)
    _drain_pool()
    try:
        conn = db_state.get_connection()
        conn.execute("DROP TABLE staff_users")
        conn.commit()
        conn.close()
        seen.clear()
        with caplog.at_level(logging.ERROR, logger="modules.auth"):
            _bootstrap_admin()
        assert "more than one statement" in caplog.text
        assert sum(_sql_head(sql).startswith("CREATE TABLE") for sql in seen) == 1
        conn = db_state.get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'staff_users'"
        ).fetchone()
        conn.close()
        assert tables is None

        state["fail_create"] = False
        seen.clear()
        _bootstrap_admin()
        assert sum(_sql_head(sql).startswith("CREATE TABLE") for sql in seen) == 1
        conn = db_state.get_connection()
        row = conn.execute(
            "SELECT username, role FROM staff_users WHERE username = ?",
            ("skramer",),
        ).fetchone()
        conn.close()
        assert row["role"] == "admin"
    finally:
        _drain_pool()


def test_bootstrap_repairs_missing_columns_without_a_leading_semicolon(lib_db):
    from modules.auth import _bootstrap_admin

    _drain_pool()
    conn = db_state.get_connection()
    conn.execute("DROP TABLE staff_users")
    conn.execute(
        "CREATE TABLE staff_users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT UNIQUE NOT NULL, "
        "password_hash TEXT NOT NULL, "
        "display_name TEXT NOT NULL, "
        "role TEXT NOT NULL DEFAULT 'td')"
    )
    conn.commit()
    conn.close()
    _bootstrap_admin()
    conn = db_state.get_connection()
    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(staff_users)")]
        row = conn.execute(
            "SELECT role, center_affiliation FROM staff_users WHERE username = ?",
            ("skramer",),
        ).fetchone()
    finally:
        conn.close()
    assert "center_affiliation" in cols and "email" in cols
    assert row["role"] == "admin"
    assert row["center_affiliation"] == "CHUSBC"


def test_login_form_renders_when_bootstrap_cannot_prepare(tmp_path):
    """The redacted OperationalError used to replace the Staff Sign In card."""
    streamlit_testing = pytest.importorskip("streamlit.testing.v1")
    from modules import auth
    original = auth._ensure_default_admin
    script = f"""
import sqlite3
from pathlib import Path
from modules import auth, db_state
db_state.DB_PATH = Path({str(tmp_path / "desk.db")!r})

def broken():
    raise sqlite3.OperationalError("SQL string contains more than one statement")

auth._ensure_default_admin = broken
auth.render_login_screen()
"""
    app = streamlit_testing.AppTest.from_string(script, default_timeout=30)
    try:
        app.run()
    finally:
        auth._ensure_default_admin = original
    assert not app.exception, app.exception
    assert any(button.label == "Sign In" for button in app.button)
    assert any(field.label == "Username" for field in app.text_input)


def test_login_form_renders_after_real_bootstrap(tmp_path, monkeypatch):
    streamlit_testing = pytest.importorskip("streamlit.testing.v1")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PRISM_DB_ENGINE", raising=False)
    script = f"""
from pathlib import Path
from modules import db_state
db_state.DB_PATH = Path({str(tmp_path / "desk.db")!r})
db_state.init_db()
from modules.auth import render_login_screen
render_login_screen()
"""
    app = streamlit_testing.AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception, app.exception
    username = next(field for field in app.text_input if field.label == "Username")
    password = next(field for field in app.text_input if field.label == "Password")
    username.set_value("skramer")
    password.set_value("Gussierocks1")
    sign_in = next(button for button in app.button if button.label == "Sign In")
    app = sign_in.click().run()
    assert not app.exception, app.exception
    assert app.session_state["user"]["username"] == "skramer"
    assert app.session_state["user"]["role"] == "admin"


def test_commit_without_a_transaction_matches_sqlite(lib_db):
    """Hosted Turso raises this from with-block commit. sqlite3 does not."""
    _drain_pool()
    conn = db_state.get_connection()

    class _CommitProxy:
        def __init__(self, raw):
            self._raw = raw

        def commit(self):
            raise ValueError(
                "Hrana: stream error: SQLite error: cannot commit - no transaction is active"
            )

        def __getattr__(self, name):
            return getattr(self._raw, name)

    conn._raw = _CommitProxy(conn._raw)
    try:
        conn.commit()
        with conn:
            conn.execute("SELECT 1")
    finally:
        conn.close()
        _drain_pool()


def test_commit_still_raises_a_real_libsql_error(lib_db):
    _drain_pool()
    conn = db_state.get_connection()

    class _CommitProxy:
        def __init__(self, raw):
            self._raw = raw

        def commit(self):
            raise ValueError("SQL string contains more than one statement")

        def __getattr__(self, name):
            return getattr(self._raw, name)

    conn._raw = _CommitProxy(conn._raw)
    try:
        with pytest.raises(sqlite3.OperationalError, match="more than one statement"):
            conn.commit()
    finally:
        conn.close()
        _drain_pool()


def test_dead_stream_matches_baton_and_closed_messages():
    assert db_state._dead_stream(ValueError(
        'Hrana: api error: {"message":"The stream has expired due to inactivity","code":"STREAM_EXPIRED"}'
    ))
    assert db_state._dead_stream(ValueError("stream closed: reset by peer"))
    assert db_state._dead_stream(ValueError("Stream handle 7 was not found"))
    assert db_state._dead_stream(ValueError("stream not found"))
    try:
        raise sqlite3.OperationalError("turso request failed") from ValueError(
            "Stream handle abc was not found"
        )
    except sqlite3.OperationalError as exc:
        assert db_state._dead_stream(exc)
    assert not db_state._dead_stream(ValueError("no such table: staff_users"))
    assert not db_state._dead_stream(ValueError("SQL string contains more than one statement"))


def test_missing_stream_is_reopened_for_the_same_call(lib_db):
    _drain_pool()
    conn = db_state.get_connection()
    state = {"n": 0}

    def on_execute(sql):
        state["n"] += 1
        if state["n"] == 1:
            raise ValueError("Stream handle 19 was not found")

    conn._raw = _RawProxy(conn._raw, on_execute)
    try:
        conn.execute("SELECT 1")
        assert state["n"] == 1  # dead stream failed; the retry used a new connection
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()
        _drain_pool()


def test_idle_libsql_connection_is_dropped_before_turso_expires_it(lib_db):
    _drain_pool()
    a = db_state.get_connection()
    a.execute("SELECT 1")
    a.close()
    a._prism_idle_at = 0  # older than Turso's 10s stream expiry
    try:
        b = db_state.get_connection()
        assert b is not a
        assert b.execute("SELECT 1").fetchone()[0] == 1
        b.close()
    finally:
        _drain_pool()


def test_executescript_error_is_not_swallowed(lib_db):
    conn = db_state.get_connection()
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.executescript("SELECT nope FROM tournaments;")
    finally:
        conn.close()


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
