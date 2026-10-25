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


# Rose Murphy: $30 ($15 bowling + $15 scholarships) at the Forest Hill front desk, not Prism.
FRONT_DESK_FEE_COPY = (
    "The $30 entry fee is collected at the Forest Hill Lanes front desk, "
    "not at the tournament desk."
)


def front_desk_fee_copy(tournament: dict | None) -> str | None:
    """Public check-in sentence for events that do not collect fees in Prism. None otherwise."""
    if tournament and tournament.get("fees_at_front_desk"):
        return FRONT_DESK_FEE_COPY
    return None


def mask_usbc_id(usbc: str | None) -> str:
    """Public roster display. Full USBC IDs stay off the check-in screen."""
    digits = "".join(ch for ch in str(usbc or "") if ch.isdigit())
    if not digits:
        return "Not on file"
    if len(digits) <= 4:
        return "••••"
    return "••••" + digits[-4:]


def public_checkin_url(base: str, tournament_id: int) -> str:
    """Check-in link with the event id, same `t=` the hub kiosk QR uses."""
    root = (base or "").rstrip("/")
    return f"{root}/?mode=bowler&action=checkin&t={int(tournament_id)}"


def pick_public_event(events: list[dict], params) -> tuple[dict | None, str | None]:
    """(event, error). A `t=` that is not an open event is an error, not a different roster.

    No `t=` and one open event selects that event. No `t=` and several events returns
    (None, None) so the page can ask which one.
    """
    from modules.kiosk_data import parse_tournament_id
    tid = parse_tournament_id(params)
    if tid is not None:
        match = next((e for e in events if int(e["id"]) == tid), None)
        if match is None:
            return None, "This check-in link does not match an open event. Ask the tournament desk for a new code."
        return match, None
    if len(events) == 1:
        return events[0], None
    return None, None


def entry_package_labels(tournament: dict | None) -> dict:
    """Which Add Bowler tags to offer.

    Standings are one board for the squad. Doubles, Team, and All-Events are labels
    on the entry. They are hidden unless this squad's format names them, because
    checking them does not create those standings. All-Events is never offered:
    no format here builds an All-Events board.
    """
    fmt = str((tournament or {}).get("squad_format") or "")
    low = fmt.lower()
    offer_doubles = "double" in low
    offer_team = "team" in low
    offer_singles = "single" in low or not (offer_doubles or offer_team)
    show_picker = offer_doubles or offer_team
    if show_picker:
        caption = (
            "Tags on this entry. Only events named in the squad format are listed. "
            "Doubles and Team tags do not create a separate standings board. "
            "All-Events is not used."
        )
    else:
        caption = (
            "Singles squad. Doubles, Team, and All-Events are hidden — "
            "they do not create standings."
        )
    return {
        "show_picker": show_picker,
        "offer_singles": offer_singles,
        "offer_doubles": offer_doubles,
        "offer_team": offer_team,
        "offer_all_events": False,
        "caption": caption,
    }


def center_name(code: str) -> str:
    try:
        from modules.constants import CENTERS
        return CENTERS.get(code or "", {}).get("name") or code or ""
    except Exception:
        return code or ""
