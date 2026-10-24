"""Database connection management, schema initialization, checkpointing, and audit logging."""

import os
from pathlib import Path
import sqlite3
import streamlit as st

# Keep the original database file name so existing tournament data is still found.
DB_PATH = Path(__file__).resolve().parent.parent / "tournament.db"
DB_FILE = DB_PATH  # alias used by newer code


def get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite tournament database with row factory enabled."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
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


def _snapshot_to(path: Path) -> None:
    """Consistent copy of the live database into a file, via the SQLite backup API."""
    src = get_connection()
    dst = sqlite3.connect(str(path))
    try:
        src.backup(dst)
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
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    init_db()  # bring older backups up to the current schema
    log_desk_action("Admin", "admin", f"Restored database from backup (safety copy: {safety.name})")
    return safety
