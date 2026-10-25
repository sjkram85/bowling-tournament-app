"""One-game stepladder finals, seeded per group (division x gender) or overall.

Lowest seed bowls the next-lowest seed; the winner moves up to face the next seed, until #1.
With N seeds there are N-1 matches. Match k: low = seed N (k=1) or winner of match k-1, high = seed N-k.
"""

import logging
from typing import Any, Dict, List, Optional

from modules.db_state import get_connection, log_desk_action

log = logging.getLogger(__name__)
OVERALL = ""  # group_name used for events without divisions
OVERALL_SEEDS = 5


def init_stepladder_tables() -> None:
    """Create the table (and add group_name to old databases). Never raises."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS stepladder_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    group_name TEXT NOT NULL DEFAULT '',
                    match_number INTEGER NOT NULL,
                    match_name TEXT NOT NULL,
                    bowler_low_id INTEGER,
                    bowler_high_id INTEGER,
                    score_low INTEGER,
                    score_high INTEGER,
                    rolloff_low INTEGER,
                    rolloff_high INTEGER,
                    winner_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending'
                )"""
            )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(stepladder_matches)")}
        if "group_name" not in cols:
            with conn:
                conn.execute("ALTER TABLE stepladder_matches ADD COLUMN group_name TEXT NOT NULL DEFAULT ''")
    except Exception as exc:
        log.warning("stepladder table setup failed: %s", exc)
    finally:
        conn.close()


def seeds(tournament_id: int) -> Dict[str, Dict[str, Any]]:
    """{group: {'label', 'seeds': [rows best-first], 'ready': bool, 'reason'}}.

    Grouped events use the same finalist logic as the standings (top 3, top 5 if >25, roll-off winners).
    A group with an unresolved roll-off is not ready.
    """
    from modules.divisions import grouped_results
    from modules.standings import query

    out: Dict[str, Dict[str, Any]] = {}
    groups = grouped_results(tournament_id)
    if groups:
        for g in groups:
            fin = sorted((r for r in g["rows"] if r["finalist"]), key=lambda r: r["rank"])
            reason = ""
            if g.get("rolloff"):
                reason = "Roll-off for the last finals spot not recorded yet."
            elif len(fin) < 2:
                reason = "Not enough finalists yet."
            out[g["group"]] = {"label": g["label"], "seeds": fin, "ready": not reason, "reason": reason}
        return out
    rows = query(
        """SELECT b.id, b.name, COALESCE(SUM(s.total_score), 0) AS grand_total,
                  COALESCE(SUM(s.scratch_score), 0) AS total_scratch, COUNT(s.id) AS games
           FROM bowlers b LEFT JOIN scores s ON b.id = s.bowler_id AND s.tournament_id = b.tournament_id
           WHERE b.tournament_id = ? AND COALESCE(b.is_pacer, 0) = 0
           GROUP BY b.id HAVING games > 0
           ORDER BY grand_total DESC, total_scratch DESC LIMIT ?""",
        (tournament_id, OVERALL_SEEDS),
    )
    ready = len(rows) >= OVERALL_SEEDS
    out[OVERALL] = {"label": "Overall", "seeds": [dict(r) for r in rows], "ready": ready,
                    "reason": "" if ready else "Not enough bowlers with scores yet."}
    return out


def _match_name(k: int, n: int) -> str:
    if k == n - 1:
        return "Championship (vs #1 seed)"
    return f"Match {k} (#{n} seed vs #{n - 1} seed)" if k == 1 else f"Match {k} (winner vs #{n - k} seed)"


def initialize_stepladder(tournament_id: int, group: Optional[str] = None, td_name: str = "Desk Admin") -> bool:
    """Seed one group's ladder (or every ready group when group is None). True if a ladder exists afterwards."""
    init_stepladder_tables()
    info = seeds(tournament_id)
    targets = list(info) if group is None else [group]
    made_any = False
    for gname in targets:
        g = info.get(gname)
        if not g:
            continue
        if get_stepladder_state(tournament_id, gname):
            made_any = True
            continue
        if not g["ready"]:
            continue
        s = g["seeds"]
        n = len(s)
        conn = get_connection()
        try:
            with conn:
                for k in range(1, n):
                    conn.execute(
                        """INSERT INTO stepladder_matches (tournament_id, group_name, match_number, match_name,
                           bowler_low_id, bowler_high_id, status) VALUES (?,?,?,?,?,?,?)""",
                        (tournament_id, gname, k, _match_name(k, n), s[n - 1]["id"] if k == 1 else None,
                         s[n - 1 - k]["id"], "active" if k == 1 else "pending"),
                    )
        finally:
            conn.close()
        # Logged only after the write transaction is closed (avoids 'database is locked').
        log_desk_action(td_name, "admin", f"Started stepladder for tournament #{tournament_id} {g['label']}: "
                        + ", ".join(f"{i + 1}:{r['name']}" for i, r in enumerate(s)))
        made_any = True
    return made_any


def record_stepladder_score(match_id: int, score_low: int, score_high: int, rolloff_low: Optional[int] = None,
                            rolloff_high: Optional[int] = None, td_name: str = "Desk Admin") -> bool:
    """Record a match; on a tie a roll-off score is needed. The winner moves up to the next match."""
    init_stepladder_tables()
    conn = get_connection()
    try:
        match = conn.execute("SELECT * FROM stepladder_matches WHERE id = ?", (match_id,)).fetchone()
        if not match or match["status"] != "active" or not match["bowler_low_id"]:
            return False
        if score_low != score_high:
            winner_id = match["bowler_low_id"] if score_low > score_high else match["bowler_high_id"]
        elif rolloff_low is not None and rolloff_high is not None and rolloff_low != rolloff_high:
            winner_id = match["bowler_low_id"] if rolloff_low > rolloff_high else match["bowler_high_id"]
        else:
            return False  # tie needs a roll-off
        with conn:
            conn.execute(
                """UPDATE stepladder_matches SET score_low=?, score_high=?, rolloff_low=?, rolloff_high=?,
                   winner_id=?, status='completed' WHERE id=?""",
                (score_low, score_high, rolloff_low, rolloff_high, winner_id, match_id),
            )
            conn.execute(
                """UPDATE stepladder_matches SET bowler_low_id=?, status='active'
                   WHERE tournament_id=? AND COALESCE(group_name,'')=? AND match_number=?""",
                (winner_id, match["tournament_id"], match["group_name"] or "", match["match_number"] + 1),
            )
    finally:
        conn.close()
    log_desk_action(td_name, "admin", f"Stepladder match {match['match_number']} ({match['group_name'] or 'Overall'}): "
                    f"{score_low}-{score_high}, winner bowler #{winner_id}")
    return True


def matches_by_group(tournament_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Every stepladder match for one event, keyed by group name. No table setup.

    A missing table means no ladder has been started. Display code uses this so a
    standings refresh does not run CREATE TABLE / PRAGMA on every click.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM stepladder_matches WHERE tournament_id = ?
               ORDER BY group_name, match_number""",
            (tournament_id,),
        ).fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r["group_name"] or "", []).append(dict(r))
    return out


def get_stepladder_state(tournament_id: int, group: Optional[str] = None) -> List[Dict[str, Any]]:
    """Matches with names, in order. group=None returns every group."""
    init_stepladder_tables()
    conn = get_connection()
    try:
        sql = """SELECT m.*, b_low.name AS low_name, b_high.name AS high_name, w.name AS winner_name
                 FROM stepladder_matches m
                 LEFT JOIN bowlers b_low ON m.bowler_low_id = b_low.id
                 LEFT JOIN bowlers b_high ON m.bowler_high_id = b_high.id
                 LEFT JOIN bowlers w ON m.winner_id = w.id
                 WHERE m.tournament_id = ?"""
        args: list = [tournament_id]
        if group is not None:
            sql += " AND COALESCE(m.group_name,'') = ?"
            args.append(group)
        return [dict(r) for r in conn.execute(sql + " ORDER BY m.group_name, m.match_number", args).fetchall()]
    except Exception as exc:
        log.warning("get_stepladder_state failed: %s", exc)
        return []
    finally:
        conn.close()


def uses_handicap(tournament: Optional[dict]) -> bool:
    """True when this event's preset scores the stepladder with handicap, not scratch."""
    t = tournament or {}
    try:
        return int(t.get("handicap_pct") or 0) > 0 and int(t.get("handicap_base") or 0) > 0
    except (TypeError, ValueError):
        return False


def max_match_score(tournament: Optional[dict]) -> int:
    """One-game ceiling. Handicap events accept scratch + handicap, not a 300 scratch cap."""
    if not uses_handicap(tournament):
        return 300
    t = tournament or {}
    base, pct = int(t.get("handicap_base") or 0), int(t.get("handicap_pct") or 0)
    return 300 + max(0, int(base * pct / 100))


def clear_stepladder(tournament_id: int, group: str = OVERALL, td_name: str = "Desk Admin",
                     force: bool = False) -> Dict[str, Any]:
    """Remove one group's ladder so it can be seeded again. Qualifying scores are not touched.

    Refuses once a match has a score unless force is True (the TD confirmed).
    """
    init_stepladder_tables()
    group = group or ""
    matches = get_stepladder_state(tournament_id, group)
    if not matches:
        return {"ok": False, "removed": 0, "reason": "No stepladder to clear."}
    scored = any(m.get("status") == "completed" or m.get("score_low") is not None for m in matches)
    if scored and not force:
        return {"ok": False, "removed": 0, "needs_force": True,
                "reason": "Match scores have been entered. Confirm to clear them. Qualifying scores are kept."}
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM stepladder_matches WHERE tournament_id = ? AND COALESCE(group_name, '') = ?",
                (tournament_id, group),
            )
            removed = cur.rowcount
    finally:
        conn.close()
    log_desk_action(td_name, "admin",
                    f"Cleared stepladder for tournament #{tournament_id} ({group or 'Overall'}): "
                    f"{removed} match(es). Qualifying scores kept.")
    return {"ok": True, "removed": removed, "reason": ""}


def champion(tournament_id: int, group: str = OVERALL) -> Optional[str]:
    """Name of the champion once the last match is done, else None."""
    ms = get_stepladder_state(tournament_id, group)
    if ms and ms[-1]["status"] == "completed":
        return ms[-1]["winner_name"]
    return None
