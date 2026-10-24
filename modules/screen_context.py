"""Small, plain summary of what's on the director's screen, sent to Prism A.I. for everyday tips.

Kept deliberately short (counts and warnings only, no names or rulebook) so requests stay fast and cheap.
"""

from __future__ import annotations

from modules.db_state import get_connection

MAX_CONTEXT_CHARS = 900


def _one(conn, sql, args=()):
    row = conn.execute(sql, args).fetchone()
    return row[0] if row else None


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
            t = conn.execute(
                "SELECT name, squad_format, game_count, pin_verifier, status FROM tournaments WHERE id = ?",
                (tournament_id,),
            ).fetchone()
            if t is None:
                return {"page": view, "tournament": "not found", "warnings": ["The open tournament could not be found."]}
            name, fmt, games, pin, status = t[0], t[1], int(t[2] or 0), t[3], t[4]
            n = _one(conn, "SELECT COUNT(*) FROM bowlers WHERE tournament_id = ?", (tournament_id,)) or 0
            checked = _one(conn, "SELECT COUNT(*) FROM bowlers WHERE tournament_id = ? AND checked_in = 1", (tournament_id,)) or 0
            unpaid = _one(conn, "SELECT COUNT(*) FROM bowlers WHERE tournament_id = ? AND COALESCE(paid_status,'') NOT IN ('paid','Paid','PAID')", (tournament_id,)) or 0
            no_avg = _one(conn, "SELECT COUNT(*) FROM bowlers WHERE tournament_id = ? AND COALESCE(entering_avg,0) <= 0", (tournament_id,)) or 0
            youth_no_smart = _one(conn, "SELECT COUNT(*) FROM bowlers WHERE tournament_id = ? AND is_youth = 1 AND COALESCE(smart_account_id,'') = ''", (tournament_id,)) or 0
            dup_spots = _one(conn, "SELECT COUNT(*) FROM (SELECT lane_assignment, lineup_position FROM bowlers WHERE tournament_id = ? GROUP BY 1,2 HAVING COUNT(*) > 1)", (tournament_id,)) or 0
            per_game = dict(conn.execute("SELECT game_number, COUNT(*) FROM scores WHERE tournament_id = ? GROUP BY game_number", (tournament_id,)).fetchall())
            game = next((g for g in range(1, games + 1) if per_game.get(g, 0) < n), games) if games else 0
            missing_lanes = [r[0] for r in conn.execute(
                "SELECT DISTINCT b.lane_assignment FROM bowlers b LEFT JOIN scores s ON s.bowler_id = b.id AND s.game_number = ? "
                "WHERE b.tournament_id = ? AND s.id IS NULL ORDER BY 1", (game, tournament_id)).fetchall()]
            unverified = _one(conn, "SELECT COUNT(*) FROM scores WHERE tournament_id = ? AND COALESCE(verified,0) = 0", (tournament_id,)) or 0
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
