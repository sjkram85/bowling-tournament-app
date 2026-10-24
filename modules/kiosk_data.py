"""Data for the public kiosk screen. Pure functions, no Streamlit; every query is guarded."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
ROWS_PER_PAGE = 20


def parse_tournament_id(params) -> int | None:
    raw = params.get("t") or params.get("tournament")
    raw = str(raw or "").strip()
    return int(raw) if raw.isdigit() else None


def eastern_now(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M:%S %p ET")


def _row(r: dict, rank: int, finalist: bool = False) -> dict:
    # Only public fields: never fees, paid status, emails, USBC ids, SMART ids.
    return {"rank": rank, "name": r.get("name") or "", "games": int(r.get("games") or r.get("games_bowled") or 0),
            "total": int(r.get("total") or r.get("handicap_total") or 0), "finalist": bool(finalist)}


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
                           "rows": [_row(r, r["rank"], r.get("finalist")) for r in g["rows"]]})
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
    return {"name": t.get("name") or "Tournament", "center": t.get("host_center") or "",
            "practice": bool(t.get("is_practice")), "groups": groups}


def paginate(groups: list[dict], rows_per_page: int = ROWS_PER_PAGE) -> list[list[dict]]:
    """Pack groups onto pages; a group longer than a page is split into parts."""
    pages, page, used = [], [], 0
    for g in groups:
        rows = g["rows"] or []
        chunks = [rows[i:i + rows_per_page] for i in range(0, len(rows), rows_per_page)] or [[]]
        for n, chunk in enumerate(chunks):
            label = g["label"] + (f" (cont.)" if n else "")
            need = max(len(chunk), 1) + 2  # heading space
            if page and used + need > rows_per_page + 4:
                pages.append(page); page, used = [], 0
            page.append({"label": label, "rows": chunk}); used += need
    if page:
        pages.append(page)
    return pages or [[]]
