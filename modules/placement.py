"""Final placement per group: one source of truth for the certified PDF and the SMART export.

Order: stepladder champion, then stepladder finish order, then any remaining finalists,
then non-finalists by qualifying rank. With no stepladder played, qualifying order is used.
"""

from __future__ import annotations

import re

STATUS_FINAL = "final"            # stepladder finished
STATUS_QUALIFYING = "qualifying"  # no stepladder played: qualifying order counts
STATUS_LADDER_PENDING = "ladder_pending"
STATUS_ROLLOFF_PENDING = "rolloff_pending"


def event_slug(name: str | None) -> str:
    """File-name-safe event name, e.g. '2nd Annual Rose Murphy' -> '2nd_Annual_Rose_Murphy'."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_")
    return slug or "tournament"


def ladder_order(matches: list[dict]) -> list[int]:
    """Bowler ids best-first from a completed ladder: champion, loser of the last match, and so on."""
    if not matches:
        return []
    order = [matches[-1]["winner_id"]]
    for m in reversed(matches):
        loser = m["bowler_high_id"] if m["winner_id"] == m["bowler_low_id"] else m["bowler_low_id"]
        if loser is not None and loser not in order:
            order.append(loser)
    return order


def group_placement(tournament_id: int, group: dict) -> dict:
    """{'status', 'order': rows best-first with r['place'] set, 'matches', 'champion', 'awards_ok'}.

    awards_ok is False while a roll-off or a started stepladder is unfinished (no money shown yet).
    """
    from modules.stepladder import get_stepladder_state

    rows = [r for r in group["rows"] if r.get("games") or r.get("games_bowled")]
    rows = sorted(rows, key=lambda r: r["rank"])
    finalists = [r for r in rows if r.get("finalist")]
    others = [r for r in rows if not r.get("finalist")]
    matches = get_stepladder_state(tournament_id, group["group"])
    if group.get("rolloff"):
        status = STATUS_ROLLOFF_PENDING
    elif matches and any(m["status"] != "completed" for m in matches):
        status = STATUS_LADDER_PENDING
    elif matches:
        status = STATUS_FINAL
    else:
        status = STATUS_QUALIFYING
    if status == STATUS_FINAL:
        by_id = {r["id"]: r for r in finalists}
        top = [by_id[i] for i in ladder_order(matches) if i in by_id]
        top += [r for r in finalists if r not in top]
    else:
        top = finalists
    order = top + others
    for i, r in enumerate(order, start=1):
        r["place"] = i
    champ = order[0]["name"] if status == STATUS_FINAL and order else None
    return {"status": status, "order": order, "finalists": top, "matches": matches, "champion": champ,
            "awards_ok": status in (STATUS_FINAL, STATUS_QUALIFYING)}


def hold_reason(status: str) -> str:
    """Why awards are blank. Same situations the certified PDF refuses to price."""
    if status == STATUS_ROLLOFF_PENDING:
        return "Roll-off not recorded yet — no awards shown."
    if status == STATUS_LADDER_PENDING:
        return "Finals not finished — no awards shown."
    return ""


def _closeout_row(r: dict, group: dict, status: str, place: int | None, prize: float,
                  withheld: str, champ_id) -> dict:
    return {
        "id": r.get("id"),
        "place": place,
        "qual_rank": r.get("rank"),
        "name": r.get("name") or "",
        "usbc_id": r.get("usbc_id"),
        "grand_total": r.get("grand_total") if r.get("grand_total") is not None else (r.get("total") or 0),
        "total_scratch": r.get("total_scratch") or 0,
        "group": group.get("group") or "",
        "group_label": group.get("label") or group.get("group") or "",
        "prize": float(prize or 0),
        "is_youth": bool(r.get("is_youth")),
        "finalist": bool(r.get("finalist")),
        "rolloff": bool(r.get("rolloff")),
        "champion": bool(champ_id and r.get("id") == champ_id),
        "status": status,
        "withheld": withheld,
    }


def _priced_rows(group: dict, plc: dict, amounts: dict[int, float]) -> tuple[list[dict], str]:
    reason = hold_reason(plc["status"])
    show_place = plc["status"] in (STATUS_FINAL, STATUS_QUALIFYING)
    champ_id = None
    if plc["status"] == STATUS_FINAL and plc.get("matches"):
        champ_id = plc["matches"][-1].get("winner_id")
    ordered = list(plc["order"])
    seen = {r.get("id") for r in ordered}
    ordered += [r for r in group.get("rows") or [] if r.get("id") not in seen]
    rows = []
    for r in ordered:
        place = r.get("place") if show_place else None
        prize = float(amounts.get(place, 0) or 0) if plc["awards_ok"] and place else 0.0
        played = bool(r.get("games") or r.get("games_bowled"))
        withheld = reason if reason and played else ""
        rows.append(_closeout_row(r, group, plc["status"], place, prize, withheld, champ_id))
    return rows, reason


def closeout_standings(tournament_id: int) -> dict:
    """Finals Closeout rows using the same placement as the certified PDF and the SMART export.

    Stepladder champion is 1st once the ladder is finished. While a roll-off or ladder is
    unfinished, prizes are 0 and warnings say why.
    """
    from modules.divisions import get_divisions, grouped_results
    from modules.smart_export import place_amounts
    from modules.standings import get_tournament, query

    warnings: list[str] = []
    rows: list[dict] = []
    groups = grouped_results(tournament_id)
    if groups:
        t = get_tournament(tournament_id) or {}
        divs = {d["name"]: d for d in get_divisions(t)}
        for g in groups:
            plc = group_placement(tournament_id, g)
            base = (g.get("group") or "").partition(" – ")[0]
            built, reason = _priced_rows(g, plc, place_amounts(divs.get(base, {})))
            if reason and any(r.get("games") or r.get("games_bowled") for r in g.get("rows") or []):
                warnings.append(f"{g.get('label') or g.get('group')}: {reason}")
            rows.extend(built)
    else:
        rows, warnings = _overall_closeout(tournament_id, query)
    smart = cash = 0.0
    for r in rows:
        if r["prize"] <= 0:
            continue
        if r["is_youth"]:
            smart += r["prize"]
        else:
            cash += r["prize"]
    return {"rows": rows, "warnings": warnings, "smart_total": smart, "cash_total": cash}


_OVERALL_PRIZES = [120.0, 80.0, 50.0, 30.0]


def _overall_closeout(tournament_id: int, query) -> tuple[list[dict], list[str]]:
    from modules.stepladder import OVERALL, get_stepladder_state

    raw = query(
        """SELECT b.id, b.name, b.usbc_id, b.is_youth, b.entering_avg, b.handicap,
                  COUNT(s.game_number) AS games_bowled,
                  COALESCE(SUM(s.scratch_score), 0) AS total_scratch,
                  COALESCE(SUM(s.total_score), 0) AS grand_total
           FROM bowlers b LEFT JOIN scores s ON b.id = s.bowler_id
           WHERE b.tournament_id = ? AND COALESCE(b.is_pacer, 0) = 0
           GROUP BY b.id
           ORDER BY grand_total DESC, total_scratch DESC""",
        (tournament_id,),
    )
    if not raw:
        return [], []
    matches = get_stepladder_state(tournament_id, OVERALL)
    ladder_ids = {m.get(k) for m in matches for k in ("bowler_low_id", "bowler_high_id", "winner_id") if m.get(k)}
    members = []
    for i, r in enumerate(raw, start=1):
        item = dict(r)
        item["rank"] = i
        item["total"] = item["grand_total"]
        item["games"] = item["games_bowled"]
        item["finalist"] = item["id"] in ladder_ids
        item["rolloff"] = False
        members.append(item)
    group = {"group": OVERALL, "label": "Overall", "rows": members, "rolloff": None}
    plc = group_placement(tournament_id, group)
    amounts = {i: _OVERALL_PRIZES[i - 1] for i in range(1, len(_OVERALL_PRIZES) + 1)}
    built, reason = _priced_rows(group, plc, amounts)
    warnings = [f"Overall: {reason}"] if reason else []
    return built, warnings
