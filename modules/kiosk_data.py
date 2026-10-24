"""Data for the public kiosk screen. Pure functions, no Streamlit; every query is guarded."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
ROWS_PER_PAGE = 8   # rows per group block; fits an 800px-tall laptop
GROUPS_PER_PAGE = 2  # one row of two side-by-side tables


def parse_tournament_id(params) -> int | None:
    raw = params.get("t") or params.get("tournament")
    raw = str(raw or "").strip()
    return int(raw) if raw.isdigit() else None


def eastern_now(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M:%S %p ET")


def _row(r: dict, rank: int, finalist: bool = False, tied: bool = False, rolloff: bool = False) -> dict:
    # Only public fields: never fees, paid status, emails, USBC ids, SMART ids.
    return {"rank": rank, "name": r.get("name") or "", "games": int(r.get("games") or r.get("games_bowled") or 0),
            "total": int(r.get("total") or r.get("handicap_total") or 0), "finalist": bool(finalist),
            "tied": bool(tied), "rolloff": bool(rolloff)}


def load_board(tournament_id: int) -> dict | None:
    """{name, center, practice, groups:[{label, rows}]} or None if the tournament isn't found."""
    from modules.standings import get_tournament
    try:
        t = get_tournament(tournament_id)
    except Exception as exc:
        log.warning("kiosk tournament lookup failed: %s", exc)
        return None
    if not t:
        return None
    groups = []
    try:
        from modules.divisions import grouped_results
        for g in grouped_results(tournament_id):
            groups.append({"label": g.get("label") or g.get("group") or "",
                           "rows": [_row(r, r["rank"], r.get("finalist"), r.get("tied"), r.get("rolloff")) for r in g["rows"]]})
    except Exception as exc:
        log.warning("kiosk grouped results failed: %s", exc)
    if not groups:
        try:
            from modules.standings import compute_standings
            rows = [_row(r, r["rank"]) for r in compute_standings(tournament_id)]
        except Exception as exc:
            log.warning("kiosk standings failed: %s", exc)
            rows = []
        groups = [{"label": "Standings", "rows": rows}]
    from modules.events import center_name
    return {"name": t.get("name") or "Tournament", "center": center_name(t.get("host_center") or ""),
            "practice": bool(t.get("is_practice")), "groups": groups}


def paginate(groups: list[dict], rows_per_page: int = ROWS_PER_PAGE,
             groups_per_page: int = GROUPS_PER_PAGE) -> list[list[dict]]:
    """Split groups into blocks of <= rows_per_page rows, then put <= groups_per_page blocks on a page."""
    blocks = []
    for g in groups:
        rows = g["rows"] or []
        chunks = [rows[i:i + rows_per_page] for i in range(0, len(rows), rows_per_page)] or [[]]
        for n, chunk in enumerate(chunks):
            blocks.append({"label": g["label"] + (" (cont.)" if n else ""), "rows": chunk})
    pages = [blocks[i:i + groups_per_page] for i in range(0, len(blocks), groups_per_page)]
    return pages or [[]]
