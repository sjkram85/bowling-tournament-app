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
