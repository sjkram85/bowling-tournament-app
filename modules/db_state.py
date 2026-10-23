"""Database connection management, schema initialization, checkpointing, and audit logging."""

import os
from pathlib import Path
import sqlite3
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "tournament.db"


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
    """Initialize core tables, audit log, and schema dependencies."""
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
                    role TEXT NOT NULL DEFAULT 'td',
                    center_affiliation TEXT,
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

                CREATE TABLE IF NOT EXISTS scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    bowler_id INTEGER NOT NULL,
                    game_number INTEGER NOT NULL,
                    scratch_score INTEGER NOT NULL DEFAULT 0,
                    total_score INTEGER NOT NULL DEFAULT 0,
                    verified INTEGER DEFAULT 0,
                    verified_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
                    FOREIGN KEY(bowler_id) REFERENCES bowlers(id) ON DELETE CASCADE,
                    UNIQUE(tournament_id, bowler_id, game_number)
                );

                CREATE TABLE IF NOT EXISTS bowler_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    bowler_id INTEGER NOT NULL,
                    game_number INTEGER NOT NULL,
                    scratch_score INTEGER NOT NULL DEFAULT 0,
                    verified INTEGER DEFAULT 0,
                    verified_by TEXT,
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

                CREATE TABLE IF NOT EXISTS mystery_doubles_pairs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    bowler_1_id INTEGER NOT NULL,
                    bowler_2_id INTEGER NOT NULL,
                    combined_scratch INTEGER DEFAULT 0,
                    combined_handicap INTEGER DEFAULT 0,
                    combined_total INTEGER DEFAULT 0,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
                    FOREIGN KEY(bowler_1_id) REFERENCES bowlers(id) ON DELETE CASCADE,
                    FOREIGN KEY(bowler_2_id) REFERENCES bowlers(id) ON DELETE CASCADE
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