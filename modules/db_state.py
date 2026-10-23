"""Database connection and schema management for PTCC SQLite backend."""

import os
from pathlib import Path
import shutil
import sqlite3

DB_FILE = Path(os.environ.get("PTCC_DB_PATH", "prism_operational.db"))
BACKUP_DIR = Path("backups")


def get_connection() -> sqlite3.Connection:
    """Create and return a configured connection to the SQLite database with WAL and busy timeout."""
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Safely apply non-destructive schema migrations."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(bowlers)")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    if "checked_in" not in existing_cols:
        cursor.execute("ALTER TABLE bowlers ADD COLUMN checked_in INTEGER DEFAULT 0")
    if "checked_in_at" not in existing_cols:
        cursor.execute("ALTER TABLE bowlers ADD COLUMN checked_in_at TEXT")
    if "is_youth" not in existing_cols:
        cursor.execute("ALTER TABLE bowlers ADD COLUMN is_youth INTEGER DEFAULT 0")
    if "smart_account_id" not in existing_cols:
        cursor.execute("ALTER TABLE bowlers ADD COLUMN smart_account_id TEXT")
    if "email" not in existing_cols:
        cursor.execute("ALTER TABLE bowlers ADD COLUMN email TEXT")


def init_db() -> None:
    """Initialize required tables and apply any schema migrations."""
    conn = get_connection()
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS staff_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    email TEXT,
                    center_affiliation TEXT,
                    role TEXT NOT NULL DEFAULT 'td',
                    is_approved INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tournaments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    host_center TEXT NOT NULL,
                    squad_format TEXT NOT NULL,
                    game_count INTEGER NOT NULL,
                    handicap_base INTEGER NOT NULL DEFAULT 220,
                    handicap_pct REAL NOT NULL DEFAULT 0.90,
                    status TEXT NOT NULL DEFAULT 'active',
                    mystery_doubles_enabled INTEGER NOT NULL DEFAULT 0,
                    mystery_doubles_fee REAL NOT NULL DEFAULT 5.0,
                    pin_verifier TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS bowlers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    usbc_id TEXT,
                    entering_avg INTEGER,
                    handicap INTEGER NOT NULL DEFAULT 0,
                    lane_assignment INTEGER NOT NULL,
                    lineup_position INTEGER NOT NULL,
                    is_pacer INTEGER NOT NULL DEFAULT 0,
                    is_youth INTEGER NOT NULL DEFAULT 0,
                    smart_account_id TEXT,
                    email TEXT,
                    paid_status TEXT NOT NULL DEFAULT 'unpaid',
                    mystery_doubles_opt_in INTEGER NOT NULL DEFAULT 0,
                    checked_in INTEGER NOT NULL DEFAULT 0,
                    checked_in_at TEXT,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    bowler_id INTEGER NOT NULL,
                    game_number INTEGER NOT NULL,
                    scratch_score INTEGER NOT NULL,
                    hdcp_score INTEGER NOT NULL,
                    total_score INTEGER NOT NULL,
                    recorded_by TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
                    FOREIGN KEY(bowler_id) REFERENCES bowlers(id) ON DELETE CASCADE,
                    UNIQUE(bowler_id, game_number)
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action_description TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tournament_archives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    archived_by TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    certified_pdf BLOB,
                    smart_csv TEXT,
                    bls_bits_csv TEXT,
                    bls_autoscoring_dat TEXT,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id)
                );
                """
            )
            _migrate_columns(conn)
    finally:
        conn.close()


def log_desk_action(user_name: str, role: str, action_description: str) -> None:
    """Record an operational action to the immutable audit log."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO audit_log (user_name, role, action_description) VALUES (?, ?, ?)",
                (user_name, role, action_description),
            )
    finally:
        conn.close()


def checkpoint_db(label: str = "manual") -> Path:
    """Create a point-in-time timestamped backup copy of the database file."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_label = "".join(c for c in label if c.isalnum() or c in ("-", "_")).strip() or "checkpoint"
    dest_path = BACKUP_DIR / f"prism_{timestamp}_{sanitized_label}.db"

    if DB_FILE.exists():
        conn = get_connection()
        try:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
    shutil.copy2(DB_FILE, dest_path)
    return dest_path


def revert_to_checkpoint(checkpoint_path: Path | str) -> bool:
    """Restore database from a given checkpoint file."""
    src = Path(checkpoint_path)
    if not src.exists():
        return False
    shutil.copy2(src, DB_FILE)
    return True


def list_checkpoints() -> list[Path]:
    """List all available database checkpoint files sorted newest first."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("prism_*.db"), key=os.path.getmtime, reverse=True)