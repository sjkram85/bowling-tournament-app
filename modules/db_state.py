"""Database connection and schema management for PTCC SQLite backend."""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_FILE = Path(os.environ.get("PTCC_DB_PATH", "prism_operational.db"))


def get_connection() -> sqlite3.Connection:
    """Create and return a configured connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Safely apply non-destructive schema migrations."""
    cursor = conn.cursor()
    
    # Audit bowler table columns
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