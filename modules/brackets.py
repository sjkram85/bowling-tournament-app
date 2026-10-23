"""Advanced bracket pairing, side-pot accounting, and payout distribution logic."""

import pandas as pd
from db_state import get_connection

def create_brackets_for_tournament(tournament_id: int, bracket_type: str = "handicap", entry_fee: float = 10.0) -> int:
    """
    Automatically group available bowlers into 8-person single-elimination brackets 
    based on sign-ups or field size.
    """
    conn = get_connection()
    try:
        bowlers = conn.execute(
            "SELECT id FROM bowlers WHERE tournament_id = ? AND is_pacer = 0 ORDER BY RANDOM()",
            (tournament_id,)
        ).fetchall()
        
        if len(bowlers) < 8:
            return 0  # Not enough bowlers to form an 8-person bracket

        created_count = 0
        bowler_ids = [b["id"] for b in bowlers]
        
        # Form 8-person brackets in chunks
        with conn:
            for i in range(0, len(bowler_ids) // 8 * 8, 8):
                chunk = bowler_ids[i:i+8]
                created_count += 1
                
                # Insert bracket header
                cur = conn.execute(
                    "INSERT INTO brackets (tournament_id, bracket_number, bracket_type, status) VALUES (?, ?, ?, 'active')",
                    (tournament_id, created_count, bracket_type)
                )
                b_id = cur.lastrowid
                
                # Insert 8 entries with seed positions 1 to 8
                for seed_idx, b_id_val in enumerate(chunk, start=1):
                    conn.execute(
                        "INSERT INTO bracket_entries (bracket_id, bowler_id, seed_position) VALUES (?, ?, ?)",
                        (b_id, b_id_val, seed_idx)
                    )
        return created_count
    finally:
        conn.close()

def get_bracket_financial_ledger(tournament_id: int) -> dict:
    """Compute total collected funds and payout liability for brackets and side pots."""
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

        total_bracket_collected = sum(b["entry_count"] * 10.0 for b in brackets) # Assuming $10 per bracket entry
        total_pot_collected = sum(p["total_collected"] for p in side_pots)

        return {
            "brackets": [dict(r) for r in brackets],
            "side_pots": [dict(r) for r in side_pots],
            "total_collected": total_bracket_collected + total_pot_collected,
            "bracket_payout_liability": total_bracket_collected * 0.80, # 80% payout rule typical
            "pot_payout_liability": total_pot_collected
        }
    finally:
        conn.close()