"""SQLite connection and schema setup for tournament state."""

import os
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(
    os.environ.get(
        "PRISM_DB_PATH",
        Path(__file__).resolve().parent.parent / "prism_operational.db",
    )
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS staff_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT,
    center_affiliation TEXT NOT NULL,
    role TEXT NOT NULL,
    is_approved INTEGER DEFAULT 0,
    approval_token TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    host_center TEXT NOT NULL,
    squad_format TEXT NOT NULL,
    game_count INTEGER NOT NULL,
    handicap_base INTEGER NOT NULL DEFAULT 220,
    handicap_pct REAL NOT NULL DEFAULT 0.90,
    status TEXT NOT NULL,
    logo_path TEXT,
    tiebreak_type TEXT,
    mystery_doubles_enabled INTEGER NOT NULL DEFAULT 0,
    mystery_doubles_fee REAL NOT NULL DEFAULT 5.0,
    pin_verifier TEXT,
    smart_pool REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tournament_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    team_name TEXT NOT NULL,
    starting_pair INTEGER NOT NULL,
    FOREIGN KEY (tournament_id) REFERENCES tournaments (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bowlers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    team_id INTEGER,
    name TEXT NOT NULL,
    usbc_id TEXT,
    email TEXT,
    entering_avg INTEGER,
    handicap INTEGER,
    lane_assignment INTEGER,
    lineup_position INTEGER,
    is_pacer INTEGER NOT NULL DEFAULT 0,
    is_youth INTEGER NOT NULL DEFAULT 0,
    paid_status TEXT NOT NULL DEFAULT 'unpaid',
    mystery_doubles_opt_in INTEGER NOT NULL DEFAULT 0,
    brackets_opt_in INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (tournament_id) REFERENCES tournaments (id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES tournament_teams (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS bowler_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bowler_id INTEGER NOT NULL,
    tournament_id INTEGER NOT NULL,
    game_number INTEGER NOT NULL,
    scratch_score INTEGER NOT NULL,
    verified_by TEXT,
    verified_at TEXT,
    FOREIGN KEY (bowler_id) REFERENCES bowlers (id) ON DELETE CASCADE,
    FOREIGN KEY (tournament_id) REFERENCES tournaments (id) ON DELETE CASCADE,
    UNIQUE (bowler_id, game_number)
);

CREATE TABLE IF NOT EXISTS mystery_doubles_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    bowler_1_id INTEGER NOT NULL,
    bowler_2_id INTEGER NOT NULL,
    combined_scratch INTEGER NOT NULL,
    combined_handicap INTEGER NOT NULL,
    combined_total INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (tournament_id) REFERENCES tournaments (id) ON DELETE CASCADE,
    FOREIGN KEY (bowler_1_id) REFERENCES bowlers (id) ON DELETE CASCADE,
    FOREIGN KEY (bowler_2_id) REFERENCES bowlers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tiebreak_roll_offs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    bowler_id INTEGER NOT NULL,
    target_seed INTEGER NOT NULL,
    frame_9 TEXT,
    frame_10 TEXT,
    roll_off_total INTEGER NOT NULL,
    FOREIGN KEY (tournament_id) REFERENCES tournaments (id) ON DELETE CASCADE,
    FOREIGN KEY (bowler_id) REFERENCES bowlers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_name TEXT NOT NULL,
    role TEXT NOT NULL,
    action_description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stepladder_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    bowler_a_id INTEGER NOT NULL,
    bowler_b_id INTEGER NOT NULL,
    score_a INTEGER NOT NULL,
    score_b INTEGER NOT NULL,
    winner_id INTEGER NOT NULL,
    entered_by TEXT NOT NULL,
    entered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tournament_id) REFERENCES tournaments (id) ON DELETE CASCADE,
    FOREIGN KEY (bowler_a_id) REFERENCES bowlers (id) ON DELETE CASCADE,
    FOREIGN KEY (bowler_b_id) REFERENCES bowlers (id) ON DELETE CASCADE,
    UNIQUE (tournament_id, round_number)
);

CREATE TABLE IF NOT EXISTS tournament_archives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL UNIQUE,
    archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_by TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    certified_pdf BLOB NOT NULL,
    smart_csv TEXT NOT NULL,
    bls_bits_csv TEXT NOT NULL,
    bls_autoscoring_dat TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS tournament_archives_no_update
BEFORE UPDATE ON tournament_archives
BEGIN
    SELECT RAISE(ABORT, 'tournament_archives is read-only');
END;

CREATE TRIGGER IF NOT EXISTS tournament_archives_no_delete
BEFORE DELETE ON tournament_archives
BEGIN
    SELECT RAISE(ABORT, 'tournament_archives is read-only');
END;
"""


def get_connection() -> sqlite3.Connection:
    """Open a configured SQLite connection; the caller is responsible for closing it."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(DATABASE_PATH),
        timeout=30,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


_ADDED_COLUMNS = {
    "staff_users": [
        ("email", "TEXT"),
        ("is_approved", "INTEGER DEFAULT 0"),
        ("approval_token", "TEXT"),
    ],
    "tournaments": [
        ("handicap_base", "INTEGER NOT NULL DEFAULT 220"),
        ("handicap_pct", "REAL NOT NULL DEFAULT 0.90"),
        ("mystery_doubles_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("mystery_doubles_fee", "REAL NOT NULL DEFAULT 5.0"),
        ("pin_verifier", "TEXT"),
        ("smart_pool", "REAL NOT NULL DEFAULT 0"),
    ],
    "bowlers": [
        ("lineup_position", "INTEGER"),
        ("is_youth", "INTEGER NOT NULL DEFAULT 0"),
        ("brackets_opt_in", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "mystery_doubles_pairs": [("combined_total", "INTEGER NOT NULL DEFAULT 0")],
}


def _migrate(connection: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created."""
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns:
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                if (table, name) == ("staff_users", "is_approved"):
                    # Accounts that predate approval keep working.
                    connection.execute("UPDATE staff_users SET is_approved = 1")


def init_db() -> None:
    """Create the tournament tables if they do not already exist."""
    connection = get_connection()
    try:
        connection.executescript(_SCHEMA)
        with connection:
            _migrate(connection)
    finally:
        connection.close()


def log_desk_action(user_name: str, role: str, action: str) -> None:
    """Record a desk action in the audit log."""
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO audit_log (user_name, role, action_description) VALUES (?, ?, ?)",
                (user_name, role, action),
            )
    finally:
        connection.close()
