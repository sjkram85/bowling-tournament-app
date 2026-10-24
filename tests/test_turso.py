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
