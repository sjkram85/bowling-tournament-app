"""Practice tournament: a throw-away sandbox with obviously fake bowlers for learning the app.

Practice data is flagged tournaments.is_practice = 1 and is kept out of archives, exports,
emails, public screens and real standings lists. "End & Delete" removes every row it created.
"""

from __future__ import annotations
import sqlite3

from modules.db_state import get_connection

PRACTICE_NAME = "PRACTICE - Not Real"
FAKE_BOWLERS = [
    "Practice Pat", "Sample Sam", "Demo Dana", "Test Terry", "Pretend Pam", "Mock Mike",
    "Trial Tina", "Fake Frank", "Dummy Doug", "Example Ellen", "Pinny McPinface", "Gutter Gary",
]


class PracticeBlocked(Exception):
    """Raised when someone tries to archive, export or send practice data."""


def is_practice(tournament_id) -> bool:
    if not tournament_id:
        return False
    conn = get_connection()
    try:
        try:
            row = conn.execute("SELECT COALESCE(is_practice, 0) FROM tournaments WHERE id = ?", (tournament_id,)).fetchone()
        except sqlite3.OperationalError:
            return False  # older database without practice columns yet
        return bool(row and row[0])
    finally:
        conn.close()


def block_if_practice(tournament_id, action: str = "used") -> None:
    if is_practice(tournament_id):
        raise PracticeBlocked(f"This is a practice tournament, so it can't be {action}. Practice data is never saved or sent anywhere.")


def active_practice_id() -> int | None:
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                "SELECT id FROM tournaments WHERE COALESCE(is_practice, 0) = 1 AND status = 'active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # older database without practice columns yet
        return row[0] if row else None
    finally:
        conn.close()


def create_practice_tournament() -> int:
    """Create the sandbox (or return the one already running)."""
    existing = active_practice_id()
    if existing:
        return existing
    conn = get_connection()
    try:
        with conn:
            t_id = conn.execute(
                "INSERT INTO tournaments (name, host_center, squad_format, game_count, pin_verifier, status, is_practice) "
                "VALUES (?, 'Practice Lanes', 'Singles', 3, '0000', 'active', 1)",
                (PRACTICE_NAME,),
            ).lastrowid
            for i, name in enumerate(FAKE_BOWLERS):
                lane, pos = 1 + i // 3, 1 + i % 3          # 4 lanes, 3 bowlers each
                avg = 140 + (i * 7) % 70
                hdcp = max(0, int((220 - avg) * 0.9))
                paid = "unpaid" if i in (4, 9) else "paid"
                checked = 0 if i == 11 else 1
                b_id = conn.execute(
                    "INSERT INTO bowlers (tournament_id, name, usbc_id, email, entering_avg, handicap, lane_assignment, "
                    "lineup_position, is_youth, paid_status, checked_in) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)",
                    (t_id, name, f"PRACTICE-{i + 1:03d}", avg, hdcp, lane, pos, int(i == 7), paid, checked),
                ).lastrowid
                # Game 1 is in for lanes 1-3; lane 4 still needs scores.
                if lane <= 3:
                    scratch = avg + (i * 13) % 40 - 15
                    conn.execute(
                        "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, hdcp_score, total_score, recorded_by) "
                        "VALUES (?, ?, 1, ?, ?, ?, 'practice')",
                        (t_id, b_id, scratch, hdcp, scratch + hdcp),
                    )
        return t_id
    finally:
        conn.close()


def delete_practice_tournament(tournament_id: int) -> bool:
    """Remove a practice tournament and everything attached to it. Refuses real tournaments."""
    if not is_practice(tournament_id):
        return False
    conn = get_connection()
    try:
        with conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            bowler_ids = [r[0] for r in conn.execute("SELECT id FROM bowlers WHERE tournament_id = ?", (tournament_id,))]
            for table in tables:
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
                if "bowler_id" in cols and bowler_ids:
                    marks = ",".join("?" * len(bowler_ids))
                    conn.execute(f"DELETE FROM {table} WHERE bowler_id IN ({marks})", bowler_ids)
            for table in tables:
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
                if "tournament_id" in cols:
                    conn.execute(f"DELETE FROM {table} WHERE tournament_id = ?", (tournament_id,))
            conn.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))
        return True
    finally:
        conn.close()
