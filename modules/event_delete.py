"""Delete an event and everything attached to it (admin only, Finals Closeout).

Allowed: practice events (any status) and cancelled real events.
Never: real events that are active, closed/certified, or archived.
Uses only plain conn.execute calls so it works on local SQLite and the Turso adapter.
"""

from __future__ import annotations

from modules.db_state import get_connection, log_desk_action

# Child tables keyed by another parent id rather than tournament_id / bowler_id.
_INDIRECT = {"bracket_entries": ("bracket_id", "brackets")}


def _event(conn, tournament_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,)).fetchone()
    return dict(row) if row else None


def delete_block_reason(tournament_id: int) -> str | None:
    """None when the event may be deleted, else a plain-English reason."""
    conn = get_connection()
    try:
        t = _event(conn, tournament_id)
        if not t:
            return "That event no longer exists."
        if t.get("is_practice"):
            return None
        archived = conn.execute("SELECT 1 FROM tournament_archives WHERE tournament_id = ? LIMIT 1",
                                (tournament_id,)).fetchone()
        if archived:
            return "Archived events are permanent records and can't be deleted."
        if (t.get("status") or "").lower() != "cancelled":
            return "Only practice events and cancelled events can be deleted. Completed or certified events are permanent."
        return None
    finally:
        conn.close()


def can_delete(tournament_id: int) -> bool:
    return delete_block_reason(tournament_id) is None


def _tables(conn) -> dict[str, list[str]]:
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    return {n: [c[1] for c in conn.execute(f"PRAGMA table_info({n})").fetchall()] for n in names}


def delete_event(tournament_id: int, td_name: str) -> bool:
    """Delete the event and all child rows. Returns False (and deletes nothing) if not allowed."""
    if not can_delete(tournament_id):
        return False
    conn = get_connection()
    try:
        t = _event(conn, tournament_id) or {}
        tables = _tables(conn)
        with conn:
            bowler_ids = [r[0] for r in conn.execute("SELECT id FROM bowlers WHERE tournament_id = ?", (tournament_id,)).fetchall()]
            for child, (fk, parent) in _INDIRECT.items():
                if child in tables and parent in tables and "tournament_id" in tables[parent]:
                    conn.execute(f"DELETE FROM {child} WHERE {fk} IN (SELECT id FROM {parent} WHERE tournament_id = ?)",
                                 (tournament_id,))
            for name, cols in tables.items():
                if name in ("bowlers", "tournaments") or "bowler_id" not in cols or not bowler_ids:
                    continue
                for i in range(0, len(bowler_ids), 500):
                    chunk = bowler_ids[i:i + 500]
                    conn.execute(f"DELETE FROM {name} WHERE bowler_id IN ({','.join('?' * len(chunk))})", chunk)
            for name, cols in tables.items():
                if name != "tournaments" and "tournament_id" in cols:
                    conn.execute(f"DELETE FROM {name} WHERE tournament_id = ?", (tournament_id,))
            conn.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))
    finally:
        conn.close()
    log_desk_action(td_name, "admin", f"Deleted event #{tournament_id} ({t.get('name', '')}, "
                    f"{'practice' if t.get('is_practice') else t.get('status', '')})")
    return True


def hide_in_closeout(t: dict) -> bool:
    """Cancelled practice events don't belong in the Finals Closeout picker."""
    return bool(t.get("is_practice")) and (t.get("status") or "").lower() == "cancelled"
