"""Database connection management, schema initialization, checkpointing, and audit logging."""

import os
from pathlib import Path
import sqlite3
import streamlit as st

# Keep the original database file name so existing tournament data is still found.
DB_PATH = Path(__file__).resolve().parent.parent / "tournament.db"
DB_FILE = DB_PATH  # alias used by newer code


# --- Storage backend -------------------------------------------------------------------------
# Turso (hosted libSQL) when TURSO_DATABASE_URL + TURSO_AUTH_TOKEN are set (Streamlit secrets or env),
# otherwise the local tournament.db file. Turso survives Streamlit Cloud reboots; the local file does not.
# PRISM_DB_ENGINE=libsql-file runs the libSQL adapter against the local file (used by tests).


def _setting(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        try:
            val = st.secrets.get(name, "") or ""
        except Exception:
            val = ""
    return str(val).strip()


def turso_config() -> tuple[str, str] | None:
    url, token = _setting("TURSO_DATABASE_URL"), _setting("TURSO_AUTH_TOKEN")
    return (url, token) if url and token else None


def using_turso() -> bool:
    return turso_config() is not None


def storage_label() -> str:
    return "Data: Turso (permanent)" if using_turso() else "Data: local (temporary)"


def _translate(exc: Exception) -> Exception:
    """libsql raises ValueError; turn it into the sqlite3 errors the rest of the app already catches."""
    msg = str(exc)
    if "constraint" in msg.lower():
        return sqlite3.IntegrityError(msg)
    return sqlite3.OperationalError(msg)


class LibsqlRow:
    """Behaves like sqlite3.Row: row[0], row['name'], keys(), dict(row), iteration, len()."""

    __slots__ = ("_cols", "_vals", "_idx")

    def __init__(self, cols: tuple, vals: tuple, idx: dict):
        self._cols, self._vals, self._idx = cols, tuple(vals), idx

    def keys(self) -> list[str]:
        return list(self._cols)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._vals[self._idx[key]]
            except KeyError:
                low = {k.lower(): i for k, i in self._idx.items()}
                if key.lower() in low:
                    return self._vals[low[key.lower()]]
                raise IndexError(f"No item with that key: {key}")
        return self._vals[key]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self) -> int:
        return len(self._vals)

    def __eq__(self, other):
        if isinstance(other, LibsqlRow):
            return self._cols == other._cols and self._vals == other._vals
        return NotImplemented

    def __hash__(self):
        return hash((self._cols, self._vals))

    def __repr__(self) -> str:
        return f"LibsqlRow({dict(zip(self._cols, self._vals))!r})"


class LibsqlCursor:
    def __init__(self, cur):
        self._cur = cur

    def _row(self, vals):
        if vals is None:
            return None
        desc = self._cur.description or ()
        cols = tuple(d[0] for d in desc)
        return LibsqlRow(cols, vals, {c: i for i, c in enumerate(cols)})

    def execute(self, sql, params=()):
        try:
            self._cur.execute(sql, tuple(params) if not isinstance(params, dict) else params)
        except ValueError as exc:
            raise _translate(exc) from exc
        return self

    def executemany(self, sql, seq):
        try:
            self._cur.executemany(sql, [tuple(p) for p in seq])
        except ValueError as exc:
            raise _translate(exc) from exc
        return self

    def fetchone(self):
        return self._row(self._cur.fetchone())

    def fetchall(self):
        return [self._row(r) for r in self._cur.fetchall()]

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size) if size else self._cur.fetchmany()
        return [self._row(r) for r in rows]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass


class LibsqlConnection:
    """Enough of sqlite3.Connection for this app: execute, executescript, `with conn:` transactions."""

    is_libsql = True

    def __init__(self, raw):
        self._raw = raw
        self.row_factory = None  # accepted and ignored; rows always support row['name']

    def cursor(self):
        return LibsqlCursor(self._raw.cursor())

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq):
        return self.cursor().executemany(sql, seq)

    def executescript(self, script):
        try:
            self._raw.executescript(script)
        except ValueError as exc:
            raise _translate(exc) from exc
        return self

    def commit(self):
        try:
            self._raw.commit()
        except ValueError as exc:
            raise _translate(exc) from exc

    def rollback(self):
        try:
            self._raw.rollback()
        except ValueError:
            pass

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def _libsql():
    import libsql  # only needed when Turso is configured (or in adapter tests)
    return libsql


def _connect_libsql(target: str, token: str | None = None) -> LibsqlConnection:
    lib = _libsql()
    raw = lib.connect(target, auth_token=token) if token is not None else lib.connect(target)
    return LibsqlConnection(raw)


def _connect_sqlite(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_connection():
    """Connection to the tournament database: Turso when configured, else the local SQLite file.

    Both kinds support conn.execute(...), row['name'], cur.lastrowid, executescript and `with conn:`.
    """
    cfg = turso_config()
    if cfg:
        conn = _connect_libsql(cfg[0], cfg[1])
    elif os.environ.get("PRISM_DB_ENGINE") == "libsql-file":
        conn = _connect_libsql(str(DB_PATH))
    else:
        return _connect_sqlite(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    return conn


def checkpoint_db() -> None:
    """Forces SQLite WAL journal checkpoint to ensure changes are flushed cleanly to disk."""
    conn = get_connection()
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL);")
    except Exception:
        pass
    finally:
        conn.close()


def init_db() -> None:
    """Initialize core tables, audit log, multi-event package tracking, and schema dependencies."""
    auto_migrate_to_turso()
    conn = get_connection()
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action_description TEXT NOT NULL
                );

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

                CREATE TABLE IF NOT EXISTS tournaments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    host_center TEXT NOT NULL,
                    squad_format TEXT NOT NULL DEFAULT 'Singles',
                    game_count INTEGER NOT NULL DEFAULT 3,
                    pin_verifier TEXT NOT NULL DEFAULT '6199',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS bowlers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    usbc_id TEXT,
                    email TEXT,
                    entering_avg INTEGER DEFAULT 200,
                    handicap INTEGER DEFAULT 0,
                    lane_assignment INTEGER DEFAULT 1,
                    lineup_position INTEGER DEFAULT 1,
                    is_pacer INTEGER DEFAULT 0,
                    is_youth INTEGER DEFAULT 0,
                    smart_account_id TEXT,
                    paid_status TEXT DEFAULT 'paid',
                    checked_in INTEGER DEFAULT 0,
                    checked_in_at TIMESTAMP,
                    mystery_doubles_opt_in INTEGER DEFAULT 0,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS bowler_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bowler_id INTEGER NOT NULL,
                    tournament_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_fee REAL DEFAULT 25.0,
                    paid_status TEXT DEFAULT 'paid',
                    FOREIGN KEY(bowler_id) REFERENCES bowlers(id) ON DELETE CASCADE,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
                    UNIQUE(bowler_id, event_type)
                );

                CREATE TABLE IF NOT EXISTS scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    bowler_id INTEGER NOT NULL,
                    game_number INTEGER NOT NULL,
                    scratch_score INTEGER NOT NULL DEFAULT 0,
                    hdcp_score INTEGER NOT NULL DEFAULT 0,
                    total_score INTEGER NOT NULL DEFAULT 0,
                    verified INTEGER DEFAULT 0,
                    verified_by TEXT,
                    recorded_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
                    FOREIGN KEY(bowler_id) REFERENCES bowlers(id) ON DELETE CASCADE,
                    UNIQUE(tournament_id, bowler_id, game_number)
                );

                CREATE TABLE IF NOT EXISTS brackets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    bracket_number INTEGER NOT NULL,
                    bracket_type TEXT NOT NULL DEFAULT 'handicap',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS bracket_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bracket_id INTEGER NOT NULL,
                    bowler_id INTEGER NOT NULL,
                    seed_position INTEGER NOT NULL,
                    r1_score INTEGER,
                    r2_score INTEGER,
                    r3_score INTEGER,
                    r1_advances INTEGER DEFAULT 0,
                    r2_advances INTEGER DEFAULT 0,
                    r3_advances INTEGER DEFAULT 0,
                    payout_amount REAL DEFAULT 0.0,
                    FOREIGN KEY(bracket_id) REFERENCES brackets(id) ON DELETE CASCADE,
                    FOREIGN KEY(bowler_id) REFERENCES bowlers(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS side_pots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    pot_type TEXT NOT NULL,
                    game_number INTEGER,
                    entry_fee REAL NOT NULL DEFAULT 5.0,
                    total_collected REAL NOT NULL DEFAULT 0.0,
                    payout_amount REAL NOT NULL DEFAULT 0.0,
                    winner_bowler_id INTEGER,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tournament_archives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    archived_by TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    certified_pdf BLOB NOT NULL,
                    smart_csv TEXT NOT NULL,
                    bls_bits_csv TEXT,
                    bls_autoscoring_dat TEXT,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );
                """
            )

        # Auto-migrate columns if tables existed from an earlier schema version
        staff_cols = [r[1] for r in conn.execute("PRAGMA table_info(staff_users);").fetchall()]
        if "email" not in staff_cols:
            conn.execute("ALTER TABLE staff_users ADD COLUMN email TEXT DEFAULT '';")
        if "is_approved" not in staff_cols:
            conn.execute("ALTER TABLE staff_users ADD COLUMN is_approved INTEGER DEFAULT 1;")
        if "center_affiliation" not in staff_cols:
            conn.execute("ALTER TABLE staff_users ADD COLUMN center_affiliation TEXT DEFAULT 'CHUSBC';")
        if "is_active" not in staff_cols:
            conn.execute("ALTER TABLE staff_users ADD COLUMN is_active INTEGER DEFAULT 1;")

        score_cols = [r[1] for r in conn.execute("PRAGMA table_info(scores);").fetchall()]
        if "hdcp_score" not in score_cols:
            conn.execute("ALTER TABLE scores ADD COLUMN hdcp_score INTEGER DEFAULT 0;")
        if "total_score" not in score_cols:
            conn.execute("ALTER TABLE scores ADD COLUMN total_score INTEGER DEFAULT 0;")
        if "recorded_by" not in score_cols:
            conn.execute("ALTER TABLE scores ADD COLUMN recorded_by TEXT;")

        # Multi-TD tables/columns (presence, chat, verification). Never let this block startup.
        try:
            from modules.td_team import ensure_team_tables
            ensure_team_tables(conn)
            from modules.rolloff import ensure_rolloff_table
            ensure_rolloff_table(conn)
            from modules.score_history import ensure_history_table
            ensure_history_table(conn)
        except Exception:
            pass

    finally:
        conn.close()

    # New per-tournament rules/fee/handicap columns (added in the dynamic rules update)
    ensure_tournament_config_columns()


def ensure_tournament_config_columns() -> None:
    """Add any missing fee/handicap columns to tournaments (safe on old databases).

    Ensure tournaments table contains dynamic rules, fees, and handicap configuration columns."""
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("PRAGMA table_info(tournaments)")
            cols = [col[1] for col in cursor.fetchall()]

            col_defs = [
                ("handicap_base", "INTEGER DEFAULT 220"),
                ("handicap_pct", "INTEGER DEFAULT 90"),
                ("handicap_max", "INTEGER DEFAULT 300"),
                ("entry_fee", "REAL DEFAULT 35.0"),
                ("prize_fee", "REAL DEFAULT 20.0"),
                ("lineage_fee", "REAL DEFAULT 12.0"),
                ("expense_fee", "REAL DEFAULT 3.0"),
                ("is_practice", "INTEGER DEFAULT 0"),
                ("status", "TEXT DEFAULT 'active'"),
                ("divisions_json", "TEXT"),
                ("preset_key", "TEXT"),
                ("rules_locked", "INTEGER DEFAULT 0"),
                ("youth_only", "INTEGER DEFAULT 0"),
                ("require_smart", "INTEGER DEFAULT 0"),
                ("no_walkins", "INTEGER DEFAULT 0"),
                ("entry_deadline", "TEXT"),
                ("event_start", "TEXT"),
                ("unconfirmed_json", "TEXT"),
                ("flyer_notes", "TEXT"),
                ("fees_at_front_desk", "INTEGER DEFAULT 0"),
                ("grouping", "TEXT"),
                ("require_gender", "INTEGER DEFAULT 0"),
                ("require_birthdate", "INTEGER DEFAULT 0"),
                ("require_usbc", "INTEGER DEFAULT 0"),
                ("age_groups_json", "TEXT"),
                ("age_cutoff", "TEXT"),
                ("rules_text", "TEXT"),
                ("event_end_date", "TEXT"),
                ("cert_number", "TEXT"),
                ("partner_name", "TEXT"),
            ]
            for col_name, col_type in col_defs:
                if col_name not in cols:
                    conn.execute(f"ALTER TABLE tournaments ADD COLUMN {col_name} {col_type}")
            bowler_cols = [c[1] for c in conn.execute("PRAGMA table_info(bowlers)")]
            for col_name, col_type in (("division", "TEXT"), ("gender", "TEXT"), ("birth_date", "TEXT"),
                                       ("bowls_scratch", "INTEGER DEFAULT 0"), ("age_group", "TEXT")):
                if col_name not in bowler_cols:
                    conn.execute(f"ALTER TABLE bowlers ADD COLUMN {col_name} {col_type}")
    finally:
        conn.close()


def log_desk_action(user_name: str, role: str, action_description: str) -> None:
    """Record an operational action to the immutable audit log."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action_description TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO audit_log (user_name, role, action_description) VALUES (?, ?, ?)",
                (user_name, role, action_description),
            )
    finally:
        conn.close()

# --- Backup & restore (all callers go through these helpers so the storage backend can change) ---
BACKUP_REQUIRED_TABLES = ("tournaments", "bowlers", "scores", "staff_users")
SAFETY_DIR_NAME = "backups"


def backup_filename(now=None) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo("America/New_York"))
    return f"prism-backup-{now.strftime('%Y-%m-%d-%H%M')}-ET.db"


def _user_objects(conn) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, rowid").fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _row_count(conn, table: str) -> int:
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except Exception:
        return 0


def copy_database(src, dst) -> dict:
    """Table-by-table copy of everything in src into dst (dst's own tables are dropped first).

    Works for any mix of sqlite3 / Turso connections. Rows go in multi-row INSERTs so a remote copy
    takes a few round trips per table, not one per row. Runs in one transaction on dst.
    Returns {table: rows copied}.
    """
    objects = _user_objects(src)
    tables = [(n, sql) for t, n, sql in objects if t == "table"]
    copied = {}
    try:
        dst.execute("PRAGMA foreign_keys = OFF")
    except Exception:
        pass
    try:
        for t, n, _ in reversed(_user_objects(dst)):
            if t in ("table", "view", "trigger"):
                dst.execute(f'DROP {t.upper()} IF EXISTS "{n}"')
        for name, sql in tables:
            dst.execute(sql)
            cur = src.execute(f'SELECT * FROM "{name}"')
            cols = [d[0] for d in cur.description]
            rows = [tuple(r) for r in cur.fetchall()]
            per = max(1, 900 // max(1, len(cols)))
            col_sql = ", ".join(f'"{c}"' for c in cols)
            one = "(" + ", ".join("?" * len(cols)) + ")"
            for i in range(0, len(rows), per):
                chunk = rows[i:i + per]
                dst.execute(f'INSERT INTO "{name}" ({col_sql}) VALUES ' + ", ".join([one] * len(chunk)),
                            [v for r in chunk for v in r])
            copied[name] = len(rows)
        for t, n, sql in objects:
            if t != "table":
                dst.execute(sql)
        try:
            seq = [tuple(r) for r in src.execute("SELECT name, seq FROM sqlite_sequence").fetchall()]
        except Exception:
            seq = []
        if seq:
            try:
                dst.execute("DELETE FROM sqlite_sequence")
                for n, v in seq:
                    dst.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (n, v))
            except Exception:
                pass
        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        try:
            dst.execute("PRAGMA foreign_keys = ON")
        except Exception:
            pass
    return copied


def _snapshot_to(path: Path) -> None:
    """Consistent copy of the live database into a local SQLite file."""
    src = get_connection()
    dst = sqlite3.connect(str(path))
    try:
        if isinstance(src, sqlite3.Connection):
            src.backup(dst)  # SQLite backup API for the local file
        else:
            copy_database(src, dst)  # Turso: table-by-table
    finally:
        dst.close()
        src.close()


def backup_bytes() -> bytes:
    """A consistent snapshot of the whole database as bytes (safe while TDs are scoring)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "snap.db"
        _snapshot_to(p)
        return p.read_bytes()


def inspect_backup(data: bytes) -> dict:
    """Check uploaded bytes are a Prism database. Returns counts; raises ValueError with a plain message."""
    import tempfile
    if not data or not data.startswith(b"SQLite format 3\x00"):
        raise ValueError("This is not a Prism backup file.")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "upload.db"
        p.write_bytes(data)
        conn = sqlite3.connect(str(p))
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("This backup file is damaged.")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = [t for t in BACKUP_REQUIRED_TABLES if t not in tables]
            if missing:
                raise ValueError("This is not a Prism backup file (missing: " + ", ".join(missing) + ").")
            count = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            events = [r[0] for r in conn.execute("SELECT name FROM tournaments ORDER BY id")]
            return {"events": count("tournaments"), "event_names": events, "bowlers": count("bowlers"),
                    "scores": count("scores"), "staff": count("staff_users")}
        except sqlite3.DatabaseError as exc:
            raise ValueError("This is not a Prism backup file.") from exc
        finally:
            conn.close()


def restore_from_bytes(data: bytes) -> Path:
    """Validate, save a safety copy of the current data, replace it with the backup, then migrate.

    Returns the safety-copy path.
    """
    import tempfile
    inspect_backup(data)
    safety_dir = Path(DB_PATH).parent / SAFETY_DIR_NAME
    safety_dir.mkdir(exist_ok=True)
    safety = safety_dir / ("pre-restore-" + backup_filename().removeprefix("prism-backup-"))
    _snapshot_to(safety)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "restore.db"
        p.write_bytes(data)
        src = sqlite3.connect(str(p))
        dst = get_connection()
        try:
            if isinstance(dst, sqlite3.Connection):
                src.backup(dst)
            else:
                copy_database(src, dst)
        finally:
            src.close()
            dst.close()
    init_db()  # bring older backups up to the current schema
    log_desk_action("Admin", "admin", f"Restored database from backup (safety copy: {safety.name})")
    return safety


# --- One-time move of the local file into Turso ------------------------------------------------

def _has_data(conn) -> bool:
    return _row_count(conn, "tournaments") > 0 or _row_count(conn, "staff_users") > 0


def local_data_counts() -> dict | None:
    """Counts in the local tournament.db, or None if there is no local file / no data."""
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    try:
        if not _has_data(conn):
            return None
        return {t: _row_count(conn, t) for t in BACKUP_REQUIRED_TABLES}
    finally:
        conn.close()


def turso_has_data() -> bool:
    if not using_turso():
        return False
    conn = get_connection()
    try:
        return _has_data(conn)
    finally:
        conn.close()


def copy_local_to_turso(replace: bool = False) -> dict:
    """Copy the local tournament.db into Turso. Refuses to overwrite Turso data unless replace=True
    (then a safety copy of Turso's data is saved locally first)."""
    if not using_turso():
        raise ValueError("Turso is not set up (TURSO_DATABASE_URL / TURSO_AUTH_TOKEN missing).")
    if local_data_counts() is None:
        raise ValueError("There is no local data to copy.")
    if turso_has_data():
        if not replace:
            raise ValueError("Turso already has data. Tick 'replace' to overwrite it.")
        safety_dir = Path(DB_PATH).parent / SAFETY_DIR_NAME
        safety_dir.mkdir(exist_ok=True)
        _snapshot_to(safety_dir / ("pre-copy-turso-" + backup_filename().removeprefix("prism-backup-")))
    src = sqlite3.connect(str(DB_PATH))
    dst = get_connection()
    try:
        return copy_database(src, dst)
    finally:
        src.close()
        dst.close()


def auto_migrate_to_turso() -> bool:
    """On startup: if Turso is set up but empty and the local file has data, copy it over (nothing lost)."""
    try:
        if not using_turso() or local_data_counts() is None or turso_has_data():
            return False
        copy_local_to_turso()
        try:
            log_desk_action("System", "admin", "Copied local data to Turso (automatic first-time move)")
        except Exception:
            pass
        return True
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("automatic copy to Turso failed: %s", exc)
        return False
