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


def center_name(code: str) -> str:
    try:
        from modules.constants import CENTERS
        return CENTERS.get(code or "", {}).get("name") or code or ""
    except Exception:
        return code or ""
