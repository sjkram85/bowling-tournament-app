"""5-Seed Stepladder Finals Progression & Roll-Off Engine."""

from typing import List, Dict, Any, Optional
from modules.db_state import get_connection, log_desk_action


def init_stepladder_tables() -> None:
    """Ensure stepladder tables exist in SQLite."""
    conn = get_connection()
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS stepladder_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    match_number INTEGER NOT NULL, -- 1: (#5 vs #4), 2: (W1 vs #3), 3: (W2 vs #2), 4: (W3 vs #1)
                    match_name TEXT NOT NULL,
                    bowler_low_id INTEGER,
                    bowler_high_id INTEGER,
                    score_low INTEGER,
                    score_high INTEGER,
                    rolloff_low INTEGER,
                    rolloff_high INTEGER,
                    winner_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'active', 'completed'
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
                    FOREIGN KEY(bowler_low_id) REFERENCES bowlers(id) ON DELETE SET NULL,
                    FOREIGN KEY(bowler_high_id) REFERENCES bowlers(id) ON DELETE SET NULL,
                    FOREIGN KEY(winner_id) REFERENCES bowlers(id) ON DELETE SET NULL
                );
                """
            )
    finally:
        conn.close()


def initialize_stepladder(tournament_id: int) -> bool:
    """Pulls top 5 seeds from active squad standings and generates the 4 stepladder matches."""
    init_stepladder_tables()
    conn = get_connection()
    try:
        # Check if already seeded
        existing = conn.execute(
            "SELECT COUNT(*) as count FROM stepladder_matches WHERE tournament_id = ?",
            (tournament_id,),
        ).fetchone()["count"]
        if existing > 0:
            return True

        # Fetch top 5 qualifiers (scratch or total based on tournament)
        query = """
            SELECT b.id, b.name, b.is_youth,
                   COALESCE(SUM(s.total_score), 0) as grand_total,
                   COALESCE(SUM(s.scratch_score), 0) as total_scratch
            FROM bowlers b
            LEFT JOIN scores s ON b.id = s.bowler_id
            WHERE b.tournament_id = ? AND b.is_pacer = 0
            GROUP BY b.id
            ORDER BY grand_total DESC, total_scratch DESC
            LIMIT 5
        """
        top5 = conn.execute(query, (tournament_id,)).fetchall()
        if len(top5) < 5:
            return False

        seed1, seed2, seed3, seed4, seed5 = top5[0], top5[1], top5[2], top5[3], top5[4]

        with conn:
            # Match 1: #5 vs #4
            conn.execute(
                """
                INSERT INTO stepladder_matches 
                (tournament_id, match_number, match_name, bowler_low_id, bowler_high_id, status)
                VALUES (?, 1, 'Match 1 (#5 Seed vs #4 Seed)', ?, ?, 'active')
                """,
                (tournament_id, seed5["id"], seed4["id"]),
            )
            # Match 2: Winner M1 vs #3
            conn.execute(
                """
                INSERT INTO stepladder_matches 
                (tournament_id, match_number, match_name, bowler_low_id, bowler_high_id, status)
                VALUES (?, 2, 'Match 2 (Winner M1 vs #3 Seed)', NULL, ?, 'pending')
                """,
                (tournament_id, seed3["id"]),
            )
            # Match 3: Winner M2 vs #2 (Semi-Final)
            conn.execute(
                """
                INSERT INTO stepladder_matches 
                (tournament_id, match_number, match_name, bowler_low_id, bowler_high_id, status)
                VALUES (?, 3, 'Semi-Final Match (Winner M2 vs #2 Seed)', NULL, ?, 'pending')
                """,
                (tournament_id, seed2["id"]),
            )
            # Match 4: Winner M3 vs #1 (Championship)
            conn.execute(
                """
                INSERT INTO stepladder_matches 
                (tournament_id, match_number, match_name, bowler_low_id, bowler_high_id, status)
                VALUES (?, 4, 'Championship Match (Winner Semi-Final vs #1 Seed)', NULL, ?, 'pending')
                """,
                (tournament_id, seed1["id"]),
            )

            log_desk_action(
                "Desk Admin",
                "admin",
                f"Initialized 5-Seed Stepladder Finals for tournament #{tournament_id} (Seeds: 1:{seed1['name']}, 2:{seed2['name']}, 3:{seed3['name']}, 4:{seed4['name']}, 5:{seed5['name']})",
            )
        return True
    finally:
        conn.close()


def record_stepladder_score(
    match_id: int,
    score_low: int,
    score_high: int,
    rolloff_low: Optional[int] = None,
    rolloff_high: Optional[int] = None,
) -> bool:
    """Records scores for a stepladder match, handles roll-offs on ties, and advances the winner."""
    init_stepladder_tables()
    conn = get_connection()
    try:
        match = conn.execute("SELECT * FROM stepladder_matches WHERE id = ?", (match_id,)).fetchone()
        if not match:
            return False

        winner_id = None
        if score_low > score_high:
            winner_id = match["bowler_low_id"]
        elif score_high > score_low:
            winner_id = match["bowler_high_id"]
        else:
            # Tie detected - requires roll-off score
            if rolloff_low is not None and rolloff_high is not None and rolloff_low != rolloff_high:
                winner_id = match["bowler_low_id"] if rolloff_low > rolloff_high else match["bowler_high_id"]
            else:
                return False  # Pending tiebreak resolution

        next_match_num = match["match_number"] + 1

        with conn:
            conn.execute(
                """
                UPDATE stepladder_matches 
                SET score_low = ?, score_high = ?, rolloff_low = ?, rolloff_high = ?, winner_id = ?, status = 'completed'
                WHERE id = ?
                """,
                (score_low, score_high, rolloff_low, rolloff_high, winner_id, match_id),
            )

            # Advance winner to the low slot of the next match
            if next_match_num <= 4:
                conn.execute(
                    """
                    UPDATE stepladder_matches 
                    SET bowler_low_id = ?, status = 'active'
                    WHERE tournament_id = ? AND match_number = ?
                    """,
                    (winner_id, match["tournament_id"], next_match_num),
                )

            log_desk_action(
                "Desk Admin",
                "admin",
                f"Recorded Match {match['match_number']} Result: Winner Bowler ID {winner_id}",
            )
        return True
    finally:
        conn.close()


def get_stepladder_state(tournament_id: int) -> List[Dict[str, Any]]:
    """Returns the current state and roster details for all 4 stepladder matches."""
    init_stepladder_tables()
    conn = get_connection()
    try:
        query = """
            SELECT m.*, 
                   b_low.name as low_name, b_low.handicap as low_hdcp, b_low.is_youth as low_is_youth,
                   b_high.name as high_name, b_high.handicap as high_hdcp, b_high.is_youth as high_is_youth,
                   w.name as winner_name
            FROM stepladder_matches m
            LEFT JOIN bowlers b_low ON m.bowler_low_id = b_low.id
            LEFT JOIN bowlers b_high ON m.bowler_high_id = b_high.id
            LEFT JOIN bowlers w ON m.winner_id = w.id
            WHERE m.tournament_id = ?
            ORDER BY m.match_number ASC
        """
        rows = conn.execute(query, (tournament_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()