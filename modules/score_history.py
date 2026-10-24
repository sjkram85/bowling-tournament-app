"""Small per-event history of score changes, so a TD (or the floor phone that made it) can undo one."""

import logging

from modules.db_state import get_connection, log_desk_action

log = logging.getLogger(__name__)
SOURCES = ("desk", "floor", "verify-fix", "photo")


def ensure_history_table(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS score_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL,
            bowler_id INTEGER NOT NULL,
            game_number INTEGER NOT NULL,
            old_scratch INTEGER, old_hdcp INTEGER, old_total INTEGER, old_verified INTEGER,
            new_scratch INTEGER,
            source TEXT NOT NULL,
            changed_by TEXT,
            device TEXT,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            undone_at TIMESTAMP,
            undone_by TEXT
        )"""
    )
    conn.commit()


def current(tournament_id: int, bowler_id: int, game: int) -> dict | None:
    """The score row as it is now (call before a write to remember the old value)."""
    conn = get_connection()
    try:
        r = conn.execute("SELECT scratch_score, hdcp_score, total_score, verified FROM scores"
                         " WHERE tournament_id=? AND bowler_id=? AND game_number=?",
                         (tournament_id, bowler_id, game)).fetchone()
        return dict(r) if r else None
    except Exception:
        return None
    finally:
        conn.close()


def log_change(tournament_id: int, bowler_id: int, game: int, before: dict | None, new_scratch: int,
               source: str, changed_by: str, device: str | None = None) -> int | None:
    """Record one change (no-op if the value didn't change). Returns the history id. Never raises."""
    if before and before.get("scratch_score") == new_scratch:
        return None
    b = before or {}
    conn = get_connection()
    try:
        ensure_history_table(conn)
        with conn:
            cur = conn.execute(
                """INSERT INTO score_history (tournament_id, bowler_id, game_number, old_scratch, old_hdcp,
                   old_total, old_verified, new_scratch, source, changed_by, device) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (tournament_id, bowler_id, game, b.get("scratch_score"), b.get("hdcp_score"), b.get("total_score"),
                 b.get("verified"), new_scratch, source, changed_by, device))
        return cur.lastrowid
    except Exception as exc:
        log.warning("score history not saved: %s", exc)
        return None
    finally:
        conn.close()


def recent(tournament_id: int, limit: int = 5) -> list[dict]:
    """Latest changes for this event that can still be undone, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT h.*, b.name FROM score_history h JOIN bowlers b ON b.id = h.bowler_id
               WHERE h.tournament_id = ? AND h.undone_at IS NULL ORDER BY h.id DESC LIMIT ?""",
            (tournament_id, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def undo(change_id: int, by: str, device: str | None = None) -> tuple[bool, str]:
    """Put the old value back (or remove a new score). Floor phones pass device: only their own last change.

    The restored score goes back into the verify queue. Returns (ok, plain message).
    """
    conn = get_connection()
    try:
        h = conn.execute("SELECT * FROM score_history WHERE id=?", (change_id,)).fetchone()
        if not h or h["undone_at"]:
            return False, "That change was already undone."
        if device is not None:
            last = conn.execute("SELECT MAX(id) FROM score_history WHERE tournament_id=? AND device=? AND undone_at IS NULL",
                                (h["tournament_id"], device)).fetchone()[0]
            if h["device"] != device or last != change_id:
                return False, "This phone can only undo its own last change."
        now = conn.execute("SELECT scratch_score FROM scores WHERE tournament_id=? AND bowler_id=? AND game_number=?",
                           (h["tournament_id"], h["bowler_id"], h["game_number"])).fetchone()
        if (now["scratch_score"] if now else None) != h["new_scratch"]:
            return False, "This score was changed again since. Please fix it directly."
        key = (h["tournament_id"], h["bowler_id"], h["game_number"])
        with conn:
            if h["old_scratch"] is None:
                conn.execute("DELETE FROM scores WHERE tournament_id=? AND bowler_id=? AND game_number=?", key)
            else:
                total = h["old_total"] if h["old_total"] is not None else h["old_scratch"] + (h["old_hdcp"] or 0)
                conn.execute(
                    """UPDATE scores SET scratch_score=?, total_score=?, verified=0, verified_by=NULL,
                       verified_at=NULL, updated_at=CURRENT_TIMESTAMP
                       WHERE tournament_id=? AND bowler_id=? AND game_number=?""",
                    (h["old_scratch"], total) + key)
            conn.execute("UPDATE score_history SET undone_at=CURRENT_TIMESTAMP, undone_by=? WHERE id=?", (by, change_id))
    except Exception as exc:
        log.warning("undo failed: %s", exc)
        return False, "Could not undo. Please try again."
    finally:
        conn.close()
    old = "removed" if h["old_scratch"] is None else f"back to {h['old_scratch']}"
    log_desk_action(by, "td", f"Undid score change #{change_id}: bowler #{h['bowler_id']} game {h['game_number']} "
                    f"{h['new_scratch']} -> {old}")
    return True, f"Undone: game {h['game_number']} score {old}."
