"""Which event is this device working on? Supports 2-3 events running at once.

Pure helpers (no Streamlit) so they're easy to test. All queries are guarded.
"""

import logging

from modules.db_state import get_connection

log = logging.getLogger(__name__)


def active_events() -> list[dict]:
    """All active events (real first, practice last). Empty list if anything is missing."""
    conn = get_connection()
    try:
        try:
            rows = conn.execute(
                "SELECT id, name, host_center, COALESCE(is_practice, 0) AS is_practice, pin_verifier, game_count "
                "FROM tournaments WHERE status = 'active' ORDER BY COALESCE(is_practice, 0), id"
            ).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT id, name, host_center, 0 AS is_practice, pin_verifier, game_count "
                "FROM tournaments WHERE status = 'active' ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        log.warning("active_events failed: %s", exc)
        return []
    finally:
        conn.close()


def parse_id(value) -> int | None:
    value = str(value or "").strip()
    return int(value) if value.isdigit() else None


def resolve_event(events: list[dict], *wanted) -> tuple[dict | None, bool]:
    """Pick the event: the first wanted id that is active, else the only active event.

    Returns (event, needs_picker). needs_picker is True when 2+ events are active and none was chosen.
    """
    by_id = {e["id"]: e for e in events}
    for w in wanted:
        w = parse_id(w)
        if w in by_id:
            return by_id[w], False
    if len(events) == 1:
        return events[0], False
    return None, len(events) > 1


def scoring_is_open(tournament_id: int) -> bool:
    """Floor phones and the desk can change scores only while the event is active."""
    try:
        from modules.standings import get_tournament
        t = get_tournament(tournament_id)
    except Exception:
        return False
    return bool(t and str(t.get("status") or "").lower() == "active")


def cancel_tournament(tournament_id: int, by: str) -> None:
    """Mark the squad cancelled. Scores, roster and finals rows stay in the database."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE tournaments SET status = 'cancelled' WHERE id = ?", (tournament_id,))
    finally:
        conn.close()
    try:
        from modules.db_state import log_desk_action
        log_desk_action(by, "td", f"Cancelled tournament #{tournament_id}. Scores were not deleted.")
    except Exception as exc:
        log.warning("cancel audit failed: %s", exc)


def center_name(code: str) -> str:
    try:
        from modules.constants import CENTERS
        return CENTERS.get(code or "", {}).get("name") or code or ""
    except Exception:
        return code or ""
