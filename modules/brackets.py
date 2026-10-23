"""8-Person Single-Elimination Brackets and Side Pot Financial Engine."""

import math
import random
from typing import List, Dict, Any
from modules.db_state import get_connection, log_desk_action

BRACKET_ENTRY_FEE = 5.0
BRACKET_PAYOUT_1ST = 25.0
BRACKET_PAYOUT_2ND = 10.0
BRACKET_EXPENSE_FEE = 5.0  # 8 * $5 = $40. Payouts: $25 + $10 = $35 + $5 expense = $40.00


def init_bracket_tables() -> None:
    """Ensure bracket and side pot tables exist in SQLite."""
    conn = get_connection()
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS brackets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    bracket_number INTEGER NOT NULL,
                    bracket_type TEXT NOT NULL DEFAULT 'handicap', -- 'handicap' or 'scratch'
                    status TEXT NOT NULL DEFAULT 'active',         -- 'active', 'completed'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS bracket_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bracket_id INTEGER NOT NULL,
                    bowler_id INTEGER NOT NULL,
                    seed_position INTEGER NOT NULL, -- 1 through 8
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
                    pot_type TEXT NOT NULL, -- 'high_game', 'survivor', 'mystery'
                    game_number INTEGER,
                    entry_fee REAL NOT NULL DEFAULT 5.0,
                    total_collected REAL NOT NULL DEFAULT 0.0,
                    payout_amount REAL NOT NULL DEFAULT 0.0,
                    winner_bowler_id INTEGER,
                    FOREIGN KEY(tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );
                """
            )
    finally:
        conn.close()


def generate_eight_person_brackets(tournament_id: int, bracket_type: str = "handicap") -> int:
    """
    Pairs eligible bowlers into 8-person single-elimination brackets.
    Returns the number of brackets generated.
    """
    init_bracket_tables()
    conn = get_connection()
    try:
        # Get bowlers who opted into brackets and are paid
        bowlers = conn.execute(
            "SELECT id, name, handicap, is_youth FROM bowlers "
            "WHERE tournament_id = ? AND paid_status = 'paid' AND is_pacer = 0",
            (tournament_id,),
        ).fetchall()

        eligible_ids = [b["id"] for b in bowlers]
        if len(eligible_ids) < 8:
            return 0

        # Determine how many full 8-person brackets we can create
        num_brackets = len(eligible_ids) // 8
        shuffled = eligible_ids.copy()
        random.shuffle(shuffled)

        with conn:
            for b_idx in range(1, num_brackets + 1):
                cur = conn.execute(
                    "INSERT INTO brackets (tournament_id, bracket_number, bracket_type) VALUES (?, ?, ?)",
                    (tournament_id, b_idx, bracket_type),
                )
                bracket_id = cur.lastrowid

                bracket_entrants = shuffled[(b_idx - 1) * 8 : b_idx * 8]
                for seed, b_id in enumerate(bracket_entrants, start=1):
                    conn.execute(
                        "INSERT INTO bracket_entries (bracket_id, bowler_id, seed_position) VALUES (?, ?, ?)",
                        (bracket_id, b_id, seed),
                    )

            log_desk_action(
                "Desk Admin",
                "admin",
                f"Generated {num_brackets} {bracket_type} 8-person brackets for tournament #{tournament_id}",
            )
        return num_brackets
    finally:
        conn.close()


def score_bracket_round(tournament_id: int, game_round: int) -> None:
    """
    Advances bracket match-ups based on game scores (Game 1 = R1, Game 2 = R2, Game 3 = R3).
    Round 1 Matchups: (1 vs 2), (3 vs 4), (5 vs 6), (7 vs 8).
    Round 2 Matchups: Winner(1-2) vs Winner(3-4), Winner(5-6) vs Winner(7-8).
    Round 3 Finals: Championship Match.
    """
    init_bracket_tables()
    conn = get_connection()
    try:
        with conn:
            brackets = conn.execute(
                "SELECT id, bracket_type FROM brackets WHERE tournament_id = ? AND status = 'active'",
                (tournament_id,),
            ).fetchall()

            for b in brackets:
                b_id = b["id"]
                b_type = b["bracket_type"]
                entries = conn.execute(
                    """
                    SELECT be.id, be.bowler_id, be.seed_position, be.r1_advances, be.r2_advances,
                           b.handicap, b.is_youth,
                           s.scratch_score, s.total_score
                    FROM bracket_entries be
                    JOIN bowlers b ON be.bowler_id = b.id
                    LEFT JOIN scores s ON (b.id = s.bowler_id AND s.game_number = ?)
                    WHERE be.bracket_id = ?
                    ORDER BY be.seed_position
                    """,
                    (game_round, b_id),
                ).fetchall()

                if len(entries) < 8:
                    continue

                if game_round == 1:
                    for i in range(0, 8, 2):
                        p1, p2 = entries[i], entries[i + 1]
                        score1 = p1["total_score"] if b_type == "handicap" else p1["scratch_score"]
                        score2 = p2["total_score"] if b_type == "handicap" else p2["scratch_score"]
                        if score1 is not None and score2 is not None:
                            winner = p1 if score1 >= score2 else p2
                            conn.execute("UPDATE bracket_entries SET r1_score = ?, r1_advances = ? WHERE id = ?", (score1, int(winner["id"] == p1["id"]), p1["id"]))
                            conn.execute("UPDATE bracket_entries SET r1_score = ?, r1_advances = ? WHERE id = ?", (score2, int(winner["id"] == p2["id"]), p2["id"]))

                elif game_round == 2:
                    r1_winners = [e for e in entries if e["r1_advances"] == 1]
                    if len(r1_winners) == 4:
                        for i in range(0, 4, 2):
                            p1, p2 = r1_winners[i], r1_winners[i + 1]
                            score1 = p1["total_score"] if b_type == "handicap" else p1["scratch_score"]
                            score2 = p2["total_score"] if b_type == "handicap" else p2["scratch_score"]
                            if score1 is not None and score2 is not None:
                                winner = p1 if score1 >= score2 else p2
                                conn.execute("UPDATE bracket_entries SET r2_score = ?, r2_advances = ? WHERE id = ?", (score1, int(winner["id"] == p1["id"]), p1["id"]))
                                conn.execute("UPDATE bracket_entries SET r2_score = ?, r2_advances = ? WHERE id = ?", (score2, int(winner["id"] == p2["id"]), p2["id"]))

                elif game_round == 3:
                    finalists = [e for e in entries if e["r2_advances"] == 1]
                    if len(finalists) == 2:
                        p1, p2 = finalists[0], finalists[1]
                        score1 = p1["total_score"] if b_type == "handicap" else p1["scratch_score"]
                        score2 = p2["total_score"] if b_type == "handicap" else p2["scratch_score"]
                        if score1 is not None and score2 is not None:
                            champ = p1 if score1 >= score2 else p2
                            runner_up = p2 if score1 >= score2 else p1

                            conn.execute("UPDATE bracket_entries SET r3_score = ?, r3_advances = 1, payout_amount = ? WHERE id = ?", (score1 if champ["id"] == p1["id"] else score2, BRACKET_PAYOUT_1ST, champ["id"]))
                            conn.execute("UPDATE bracket_entries SET r3_score = ?, r3_advances = 0, payout_amount = ? WHERE id = ?", (score2 if champ["id"] == p1["id"] else score1, BRACKET_PAYOUT_2ND, runner_up["id"]))
                            conn.execute("UPDATE brackets SET status = 'completed' WHERE id = ?", (b_id,))
    finally:
        conn.close()


def get_bracket_financial_ledger(tournament_id: int) -> Dict[str, Any]:
    """Calculate the penny-perfect bracket financial ledger."""
    init_bracket_tables()
    conn = get_connection()
    try:
        brackets = conn.execute("SELECT id FROM brackets WHERE tournament_id = ?", (tournament_id,)).fetchall()
        num_brackets = len(brackets)
        total_collected = num_brackets * 8 * BRACKET_ENTRY_FEE

        # Sum payouts and check youth SMART allocations
        payouts = conn.execute(
            """
            SELECT be.payout_amount, b.is_youth
            FROM bracket_entries be
            JOIN brackets br ON be.bracket_id = br.id
            JOIN bowlers b ON be.bowler_id = b.id
            WHERE br.tournament_id = ? AND be.payout_amount > 0
            """,
            (tournament_id,),
        ).fetchall()

        cash_payouts = sum(r["payout_amount"] for r in payouts if not r["is_youth"])
        smart_payouts = sum(r["payout_amount"] for r in payouts if r["is_youth"])
        total_payouts = cash_payouts + smart_payouts
        admin_expenses = num_brackets * BRACKET_EXPENSE_FEE
        net_balance = total_collected - (total_payouts + admin_expenses)

        return {
            "num_brackets": num_brackets,
            "total_collected": total_collected,
            "cash_payouts": cash_payouts,
            "smart_payouts": smart_payouts,
            "total_payouts": total_payouts,
            "admin_expenses": admin_expenses,
            "net_balance": net_balance,  # Strictly $0.00 when complete
        }
    finally:
        conn.close()