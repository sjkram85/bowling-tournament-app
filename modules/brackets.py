"""Advanced bracket pairing, side-pot accounting, and payout distribution logic."""

import pandas as pd
from modules.db_state import get_connection

def init_bracket_tables() -> None:
    """Ensure bracket tables exist in the database."""
    conn = get_connection()
    try:
        with conn:
            conn.executescript(
                """
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
                """
            )
    finally:
        conn.close()

def create_brackets_for_tournament(tournament_id: int, bracket_type: str = "handicap", entry_fee: float = 10.0) -> int:
    """Automatically group available bowlers into 8-person single-elimination brackets."""
    init_bracket_tables()
    conn = get_connection()
    try:
        bowlers = conn.execute(
            "SELECT id FROM bowlers WHERE tournament_id = ? AND is_pacer = 0 ORDER BY RANDOM()",
            (tournament_id,)
        ).fetchall()
        
        if len(bowlers) < 8:
            return 0

        created_count = 0
        bowler_ids = [b["id"] for b in bowlers]
        
        with conn:
            for i in range(0, len(bowler_ids) // 8 * 8, 8):
                chunk = bowler_ids[i:i+8]
                created_count += 1
                
                cur = conn.execute(
                    "INSERT INTO brackets (tournament_id, bracket_number, bracket_type, status) VALUES (?, ?, ?, 'active')",
                    (tournament_id, created_count, bracket_type)
                )
                b_id = cur.lastrowid
                
                for seed_idx, b_id_val in enumerate(chunk, start=1):
                    conn.execute(
                        "INSERT INTO bracket_entries (bracket_id, bowler_id, seed_position) VALUES (?, ?, ?)",
                        (b_id, b_id_val, seed_idx)
                    )
        return created_count
    finally:
        conn.close()

# Alias matching active_squad.py expected function name
def generate_eight_person_brackets(tournament_id: int) -> int:
    return create_brackets_for_tournament(tournament_id)

def score_bracket_round(bracket_id: int, round_number: int) -> None:
    """Placeholder for scoring a specific bracket round."""
    pass

def get_bracket_financial_ledger(tournament_id: int) -> dict:
    """Compute total collected funds and payout liability for brackets and side pots."""
    init_bracket_tables()
    conn = get_connection()
    try:
        brackets = conn.execute(
            """
            SELECT b.id, b.bracket_number, b.bracket_type, b.status,
                   COUNT(be.id) as entry_count
            FROM brackets b
            LEFT JOIN bracket_entries be ON b.id = be.bracket_id
            WHERE b.tournament_id = ?
            GROUP BY b.id
            """,
            (tournament_id,)
        ).fetchall()

        side_pots = conn.execute(
            "SELECT * FROM side_pots WHERE tournament_id = ?",
            (tournament_id,)
        ).fetchall()

        total_bracket_collected = sum(b["entry_count"] * 10.0 for b in brackets)
        total_pot_collected = sum(p["total_collected"] for p in side_pots)

        return {
            "brackets": [dict(r) for r in brackets],
            "side_pots": [dict(r) for r in side_pots],
            "total_collected": total_bracket_collected + total_pot_collected,
            "bracket_payout_liability": total_bracket_collected * 0.80,
            "pot_payout_liability": total_pot_collected
        }
    finally:
        conn.close()