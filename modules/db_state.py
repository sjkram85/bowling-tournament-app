"""Database connection management, schema initialization, and audit logging."""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_FILE = Path(__file__).resolve().parent.parent / "ptcc_data.db"


def get_connection() -> sqlite3.Connection:
    """Return an active connection with Row row_factory and WAL mode enabled."""
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def checkpoint_db() -> None:
    """Flush SQLite WAL journal to disk."""
    conn = get_connection()
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
    finally:
        conn.close()


def ensure_tournament_config_columns() -> None:
    """Ensure tournaments table contains dynamic rules, fees, and handicap configuration columns."""
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
            ]
            for col_name, col_type in col_defs:
                if col_name not in cols:
                    conn.execute(f"ALTER TABLE tournaments ADD COLUMN {col_name} {col_type}")
    finally:
        conn.close()


def log_desk_action(operator_name: str, role: str, action_description: str) -> None:
    """Write an immutable audit entry for any desk action or state change."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO audit_logs (timestamp, operator_name, role, action_description)
                VALUES (?, ?, ?, ?)
                """,
                (datetime.now().isoformat(), operator_name, role, action_description),
            )
        checkpoint_db()
    finally:
        conn.close()


# Ensure tables and config columns exist at module import
ensure_tournament_config_columns()