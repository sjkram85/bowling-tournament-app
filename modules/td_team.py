"""Multi-TD helpers: who's on duty, score verification queue, and TD chat.

Every function is wrapped so a missing table/column on an old database never crashes the app.
"""

import logging

from modules.db_state import get_connection

log = logging.getLogger(__name__)
ONLINE_SECONDS = 60


def ensure_team_tables(conn) -> None:
    """Create/upgrade the tables this feature needs. Called from init_db; safe to call repeatedly."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS td_presence (
            username TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            tournament_id INTEGER,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS td_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL,
            user TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cols = [r[1] for r in conn.execute("PRAGMA table_info(scores)")]
    for name, ctype in (("verified", "INTEGER DEFAULT 0"), ("verified_by", "TEXT"),
                        ("verified_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP")):
        if name not in cols:
            conn.execute(f"ALTER TABLE scores ADD COLUMN {name} {ctype}")
    conn.commit()


def _safe(default):
    def wrap(fn):
        def inner(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as exc:  # never let this feature break login or a screen
                log.warning("td_team.%s failed: %s", fn.__name__, exc)
                return default
        inner.__name__ = fn.__name__
        return inner
    return wrap


# ---------- TDs on duty ----------
@_safe(None)
def heartbeat(username: str, display_name: str, tournament_id) -> None:
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """INSERT INTO td_presence (username, display_name, tournament_id, last_seen)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(username) DO UPDATE SET display_name=excluded.display_name,
                   tournament_id=excluded.tournament_id, last_seen=CURRENT_TIMESTAMP""",
                (username, display_name, tournament_id),
            )
    finally:
        conn.close()


@_safe([])
def tds_on_duty(tournament_id: int) -> list[dict]:
    """Staff on this tournament seen in the last 10 minutes; 'online' is True if seen in the last 60 seconds."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT display_name, last_seen,
                      CAST(strftime('%s','now') - strftime('%s', last_seen) AS INTEGER) AS secs
               FROM td_presence WHERE tournament_id = ?
                 AND datetime(last_seen) >= datetime('now','-10 minutes')
               ORDER BY last_seen DESC""",
            (tournament_id,),
        ).fetchall()
        return [dict(r, online=r["secs"] < ONLINE_SECONDS) for r in rows]
    finally:
        conn.close()


# ---------- Score verification ----------
@_safe([])
def needs_verifying(tournament_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT s.id, s.game_number, s.scratch_score, s.hdcp_score, s.recorded_by,
                      b.name, b.lane_assignment
               FROM scores s JOIN bowlers b ON b.id = s.bowler_id
               WHERE s.tournament_id = ? AND COALESCE(s.verified, 0) = 0
               ORDER BY b.lane_assignment, b.name, s.game_number""",
            (tournament_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@_safe([])
def recently_verified(tournament_id: int, limit: int = 5) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT s.game_number, s.scratch_score, s.verified_by, s.verified_at, b.name
               FROM scores s JOIN bowlers b ON b.id = s.bowler_id
               WHERE s.tournament_id = ? AND s.verified = 1 AND s.verified_by IS NOT NULL
               ORDER BY s.verified_at DESC LIMIT ?""",
            (tournament_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@_safe(False)
def verify_score(score_id: int, td_name: str, new_scratch: int | None = None) -> bool:
    """Mark a score verified. If new_scratch is given, fix the number first (handicap is kept)."""
    conn = get_connection()
    try:
        with conn:
            if new_scratch is not None:
                conn.execute(
                    """UPDATE scores SET scratch_score = ?, total_score = ? + COALESCE(hdcp_score, 0),
                       updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                    (int(new_scratch), int(new_scratch), score_id),
                )
            cur = conn.execute(
                """UPDATE scores SET verified = 1, verified_by = ?, verified_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (td_name, score_id),
            )
        return cur.rowcount == 1
    finally:
        conn.close()


# ---------- TD chat ----------
@_safe([])
def get_messages(tournament_id: int, limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, user, text, created_at FROM td_messages WHERE tournament_id = ? ORDER BY id DESC LIMIT ?",
            (tournament_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


@_safe(False)
def send_message(tournament_id: int, user: str, text: str) -> bool:
    text = (text or "").strip()[:500]
    if not text or not tournament_id:
        return False
    conn = get_connection()
    try:
        with conn:
            conn.execute("INSERT INTO td_messages (tournament_id, user, text) VALUES (?, ?, ?)",
                         (tournament_id, user, text))
        return True
    finally:
        conn.close()


def to_eastern(ts: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' UTC from SQLite -> '9:05 PM' Eastern."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p")
    except Exception:
        return ""


def unread_count(messages: list[dict], last_read_id: int, me: str) -> int:
    return sum(1 for m in messages if m["id"] > last_read_id and m["user"] != me)
