"""Mystery doubles draw: randomly pair opted-in bowlers and score the pairs."""

import secrets
import sqlite3

from modules.db_state import get_connection


def _pair_totals(connection: sqlite3.Connection, tournament_id: int, first: int, second: int) -> tuple[int, int, int]:
    """Return (scratch, handicap, total) pinfall for a pair across the games scored so far."""
    scratch = handicap = 0
    for bowler_id in (first, second):
        row = connection.execute(
            "SELECT COALESCE(SUM(s.scratch_score), 0) AS scratch, COUNT(s.id) AS games, "
            "COALESCE(b.handicap, 0) AS handicap "
            "FROM bowlers b LEFT JOIN bowler_scores s "
            "ON s.bowler_id = b.id AND s.tournament_id = ? WHERE b.id = ?",
            (tournament_id, bowler_id),
        ).fetchone()
        scratch += row["scratch"]
        handicap += row["handicap"] * row["games"]
    return scratch, handicap, scratch + handicap


def generate_mystery_doubles_draw(tournament_id: int) -> list[dict]:
    """Draw and persist mystery doubles pairs for a tournament.

    Replaces any existing draw. Bowlers are shuffled with ``secrets.SystemRandom``.
    With an odd entrant count, one random existing entrant is drawn a second time so
    everyone has a partner. Returns the stored pairs (empty if fewer than 2 entrants).
    """
    rng = secrets.SystemRandom()
    connection = get_connection()
    try:
        with connection:
            order = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM bowlers WHERE tournament_id = ? AND mystery_doubles_opt_in = 1",
                    (tournament_id,),
                )
            ]
            connection.execute("DELETE FROM mystery_doubles_pairs WHERE tournament_id = ?", (tournament_id,))
            if len(order) < 2:
                return []

            rng.shuffle(order)
            if len(order) % 2:
                # Partner for the unpaired last bowler: any other entrant.
                order.append(rng.choice(order[:-1]))

            for first, second in zip(order[0::2], order[1::2]):
                scratch, handicap, total = _pair_totals(connection, tournament_id, first, second)
                connection.execute(
                    "INSERT INTO mystery_doubles_pairs "
                    "(tournament_id, bowler_1_id, bowler_2_id, combined_scratch, combined_handicap, combined_total) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (tournament_id, first, second, scratch, handicap, total),
                )
            rows = connection.execute(
                "SELECT * FROM mystery_doubles_pairs WHERE tournament_id = ? ORDER BY id", (tournament_id,)
            ).fetchall()
            return [dict(row) for row in rows]
    finally:
        connection.close()


def update_mystery_doubles_scores(tournament_id: int) -> list[dict]:
    """Recompute combined scratch, handicap and total pinfall for every pair.

    Handicap is each bowler's handicap times the games they have scored.
    Returns the updated pairs, highest combined total first.
    """
    connection = get_connection()
    try:
        with connection:
            pairs = connection.execute(
                "SELECT id, bowler_1_id, bowler_2_id FROM mystery_doubles_pairs WHERE tournament_id = ?",
                (tournament_id,),
            ).fetchall()
            for pair in pairs:
                scratch, handicap, total = _pair_totals(
                    connection, tournament_id, pair["bowler_1_id"], pair["bowler_2_id"]
                )
                connection.execute(
                    "UPDATE mystery_doubles_pairs "
                    "SET combined_scratch = ?, combined_handicap = ?, combined_total = ? WHERE id = ?",
                    (scratch, handicap, total, pair["id"]),
                )
            rows = connection.execute(
                "SELECT * FROM mystery_doubles_pairs WHERE tournament_id = ? ORDER BY combined_total DESC, id",
                (tournament_id,),
            ).fetchall()
            return [dict(row) for row in rows]
    finally:
        connection.close()
