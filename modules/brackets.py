"""8-Person Single-Elimination Bracket and Side Pot Management for CHUSBC Tournaments."""

import math
import random
import sqlite3
from modules.db_state import get_connection, log_desk_action, init_db


def init_bracket_tables() -> None:
    """Ensure core tables, bracket, and side pot tables exist in SQLite."""
    init_db()
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
                """
            )
    finally:
        conn.close()


def generate_eight_person_brackets(tournament_id: int, bracket_type: str = "handicap") -> int:
    """
    Pulls paid, eligible bowlers and forms balanced 8-person single-elimination brackets.
    Returns the count of created brackets.
    """
    init_bracket_tables()
    conn = get_connection()
    try:
        cur = conn.cursor()
        bowlers = cur.execute(
            """
            SELECT id, name, handicap 
            FROM bowlers 
            WHERE tournament_id = ? AND paid_status = 'paid' AND is_pacer = 0
            """,
            (tournament_id,),
        ).fetchall()

        if len(bowlers) < 8:
            return 0

        num_brackets = len(bowlers) // 8
        cur.execute("DELETE FROM brackets WHERE tournament_id = ? AND bracket_type = ?", (tournament_id, bracket_type))

        all_bowler_ids = [b["id"] for b in bowlers]
        random.shuffle(all_bowler_ids)

        for b_idx in range(num_brackets):
            cur.execute(
                "INSERT INTO brackets (tournament_id, bracket_number, bracket_type) VALUES (?, ?, ?)",
                (tournament_id, b_idx + 1, bracket_type),
            )
            bracket_id = cur.lastrowid

            squad_slice = all_bowler_ids[b_idx * 8 : (b_idx + 1) * 8]
            for seed, bowler_id in enumerate(squad_slice, start=1):
                cur.execute(
                    """
                    INSERT INTO bracket_entries (bracket_id, bowler_id, seed_position)
                    VALUES (?, ?, ?)
                    """,
                    (bracket_id, bowler_id, seed),
                )

        conn.commit()
        log_desk_action(
            "Desk Admin",
            "admin",
            f"Generated {num_brackets} {bracket_type} 8-person brackets for tournament #{tournament_id}",
        )
        return num_brackets
    finally:
        conn.close()


def score_bracket_round(tournament_id: int, game_number: int) -> None:
    """
    Evaluates matches for Round 1 (Game 1), Round 2 (Game 2), or Round 3 (Game 3 Finals).
    Determines winners and allocates 1st ($25) and 2nd ($10) place payouts on completion.
    """
    init_bracket_tables()
    conn = get_connection()
    try:
        cur = conn.cursor()
        brackets = cur.execute(
            "SELECT id, bracket_type FROM brackets WHERE tournament_id = ? AND status = 'active'",
            (tournament_id,),
        ).fetchall()

        for br in brackets:
            bracket_id = br["id"]
            is_hdcp = br["bracket_type"] == "handicap"

            entries = cur.execute(
                """
                SELECT be.id, be.bowler_id, be.seed_position, b.handicap,
                       COALESCE(bs.scratch_score, 0) as scratch
                FROM bracket_entries be
                JOIN bowlers b ON be.bowler_id = b.id
                LEFT JOIN bowler_scores bs ON b.id = bs.bowler_id AND bs.game_number = ?
                WHERE be.bracket_id = ?
                ORDER BY be.seed_position ASC
                """,
                (game_number, bracket_id),
            ).fetchall()

            if len(entries) != 8:
                continue

            def get_total(entry):
                hdcp = entry["handicap"] if is_hdcp else 0
                return entry["scratch"] + hdcp

            if game_number == 1:
                # Round 1: 1v2, 3v4, 5v6, 7v8
                for i in range(0, 8, 2):
                    e1, e2 = entries[i], entries[i + 1]
                    s1, s2 = get_total(e1), get_total(e2)
                    w_id = e1["id"] if s1 >= s2 else e2["id"]
                    cur.execute("UPDATE bracket_entries SET r1_score = ?, r1_advances = ? WHERE id = ?", (s1, 1 if w_id == e1["id"] else 0, e1["id"]))
                    cur.execute("UPDATE bracket_entries SET r1_score = ?, r1_advances = ? WHERE id = ?", (s2, 1 if w_id == e2["id"] else 0, e2["id"]))

            elif game_number == 2:
                # Semi-Finals: Winner (1v2) vs Winner (3v4), Winner (5v6) vs Winner (7v8)
                r1_winners = [e for e in entries if cur.execute("SELECT r1_advances FROM bracket_entries WHERE id = ?", (e["id"],)).fetchone()[0] == 1]
                if len(r1_winners) == 4:
                    for i in range(0, 4, 2):
                        e1, e2 = r1_winners[i], r1_winners[i + 1]
                        s1, s2 = get_total(e1), get_total(e2)
                        w_id = e1["id"] if s1 >= s2 else e2["id"]
                        cur.execute("UPDATE bracket_entries SET r2_score = ?, r2_advances = ? WHERE id = ?", (s1, 1 if w_id == e1["id"] else 0, e1["id"]))
                        cur.execute("UPDATE bracket_entries SET r2_score = ?, r2_advances = ? WHERE id = ?", (s2, 1 if w_id == e2["id"] else 0, e2["id"]))

            elif game_number == 3:
                # Championship Match: Winner Match A vs Winner Match B
                r2_winners = [e for e in entries if cur.execute("SELECT r2_advances FROM bracket_entries WHERE id = ?", (e["id"],)).fetchone()[0] == 1]
                if len(r2_winners) == 2:
                    e1, e2 = r2_winners[0], r2_winners[1]
                    s1, s2 = get_total(e1), get_total(e2)
                    champ_id = e1["id"] if s1 >= s2 else e2["id"]
                    runner_id = e2["id"] if s1 >= s2 else e1["id"]

                    cur.execute("UPDATE bracket_entries SET r3_score = ?, r3_advances = 1, payout_amount = 25.0 WHERE id = ?", (s1 if champ_id == e1["id"] else s2, champ_id))
                    cur.execute("UPDATE bracket_entries SET r3_score = ?, r3_advances = 0, payout_amount = 10.0 WHERE id = ?", (s2 if champ_id == e1["id"] else s1, runner_id))
                    cur.execute("UPDATE brackets SET status = 'completed' WHERE id = ?", (bracket_id,))

        conn.commit()
    finally:
        conn.close()