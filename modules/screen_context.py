"""Small, plain summary of what's on the director's screen, sent to Prism A.I. for everyday tips.

Kept deliberately short (counts and warnings only, no names or rulebook) so requests stay fast and cheap.
"""

from __future__ import annotations

from modules.db_state import get_connection

MAX_CONTEXT_CHARS = 900


def _parse_per_game(raw) -> dict:
    per: dict[int, int] = {}
    for part in str(raw or "").split(","):
        if ":" not in part:
            continue
        g, c = part.split(":", 1)
        per[int(g)] = int(c)
    return per


def build_screen_context(view: str, tournament_id: int | None) -> dict:
    ctx: dict = {"page": view}
    if not tournament_id:
        ctx["tournament"] = "none open"
        ctx["warnings"] = ["No tournament is open yet."]
        return ctx
    warnings: list[str] = []
    try:
        conn = get_connection()
        try:
            # One round trip for the tournament plus every count. Missing lanes need the
            # current game, which is computed from those counts, so they are a second trip.
            t = conn.execute(
                """
                SELECT name, squad_format, game_count, pin_verifier, status,
                  (SELECT COUNT(*) FROM bowlers WHERE tournament_id = t.id) AS n,
                  (SELECT COUNT(*) FROM bowlers WHERE tournament_id = t.id AND checked_in = 1) AS checked,
                  (SELECT COUNT(*) FROM bowlers WHERE tournament_id = t.id AND COALESCE(paid_status,'') NOT IN ('paid','Paid','PAID')) AS unpaid,
                  (SELECT COUNT(*) FROM bowlers WHERE tournament_id = t.id AND COALESCE(entering_avg,0) <= 0) AS no_avg,
                  (SELECT COUNT(*) FROM bowlers WHERE tournament_id = t.id AND is_youth = 1 AND COALESCE(smart_account_id,'') = '') AS youth_no_smart,
                  (SELECT COUNT(*) FROM (SELECT lane_assignment, lineup_position FROM bowlers WHERE tournament_id = t.id GROUP BY 1, 2 HAVING COUNT(*) > 1)) AS dup_spots,
                  (SELECT COUNT(*) FROM scores WHERE tournament_id = t.id AND COALESCE(verified,0) = 0) AS unverified,
                  (SELECT group_concat(game_number || ':' || c) FROM (
                      SELECT game_number, COUNT(*) AS c FROM scores WHERE tournament_id = t.id GROUP BY game_number
                  )) AS per_game
                FROM tournaments t WHERE t.id = ?
                """,
                (tournament_id,),
            ).fetchone()
            if t is None:
                return {"page": view, "tournament": "not found", "warnings": ["The open tournament could not be found."]}
            name, fmt, games, pin, status = t[0], t[1], int(t[2] or 0), t[3], t[4]
            n = int(t["n"] or 0)
            checked = int(t["checked"] or 0)
            unpaid = int(t["unpaid"] or 0)
            no_avg = int(t["no_avg"] or 0)
            youth_no_smart = int(t["youth_no_smart"] or 0)
            dup_spots = int(t["dup_spots"] or 0)
            unverified = int(t["unverified"] or 0)
            per_game = _parse_per_game(t["per_game"])
            game = next((g for g in range(1, games + 1) if per_game.get(g, 0) < n), games) if games else 0
            missing_lanes = [r[0] for r in conn.execute(
                "SELECT DISTINCT b.lane_assignment FROM bowlers b LEFT JOIN scores s ON s.bowler_id = b.id AND s.game_number = ? "
                "WHERE b.tournament_id = ? AND s.id IS NULL ORDER BY 1", (game, tournament_id)).fetchall()]
        finally:
            conn.close()
    except Exception:
        return {"page": view, "tournament": "unknown", "warnings": ["Could not read the tournament data right now."]}

    ctx.update({
        "tournament": f"{name} ({fmt}, {games} games, {status})",
        "bowlers": n,
        "checked_in": f"{checked} of {n}",
        "current_game": game,
        "scores_in_this_game": f"{per_game.get(game, 0)} of {n}",
    })
    if n == 0:
        warnings.append("No bowlers on the roster yet.")
    if n and checked < n:
        warnings.append(f"{n - checked} bowler(s) not checked in.")
    if unpaid:
        warnings.append(f"{unpaid} bowler(s) not marked paid.")
    if no_avg:
        warnings.append(f"{no_avg} bowler(s) missing an entering average.")
    if youth_no_smart:
        warnings.append(f"{youth_no_smart} youth bowler(s) missing a SMART account number.")
    if dup_spots:
        warnings.append(f"{dup_spots} lane spot(s) have two bowlers in the same lineup position.")
    if n and missing_lanes:
        shown = ", ".join(str(x) for x in missing_lanes[:8]) + (" …" if len(missing_lanes) > 8 else "")
        warnings.append(f"Lanes still missing game {game} scores: {shown}.")
    if unverified:
        warnings.append(f"{unverified} score(s) not yet verified.")
    if str(pin) == "6199":
        warnings.append("Floor scorer PIN is still the default.")
    ctx["warnings"] = warnings[:8]
    return ctx


def context_to_text(ctx: dict) -> str:
    lines = [f"{k.replace('_', ' ').title()}: {v}" for k, v in ctx.items() if k != "warnings"]
    warns = ctx.get("warnings") or []
    lines.append("Warnings: " + (" ".join(warns) if warns else "none"))
    text = "\n".join(lines)
    return text[:MAX_CONTEXT_CHARS]
