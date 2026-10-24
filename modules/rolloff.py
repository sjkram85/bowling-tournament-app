"""Ties at the finals cut: flag 'TIE – ROLL-OFF' and record roll-off winners (per event, per group)."""

import logging

from modules.db_state import get_connection

log = logging.getLogger(__name__)


def ensure_rolloff_table(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS cut_rolloffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            bowler_id INTEGER NOT NULL,
            total INTEGER NOT NULL,
            decided_by TEXT,
            decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.commit()


def winners(tournament_id: int) -> dict[str, dict[int, int]]:
    """{group_name: {bowler_id: total_when_recorded}}. Empty if the table is missing."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT group_name, bowler_id, total FROM cut_rolloffs WHERE tournament_id = ?",
                            (tournament_id,)).fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    out: dict[str, dict[int, int]] = {}
    for r in rows:
        out.setdefault(r["group_name"], {})[r["bowler_id"]] = r["total"]
    return out


def record_winner(tournament_id: int, group_name: str, bowler_id: int, total: int, td_name: str) -> bool:
    conn = get_connection()
    try:
        ensure_rolloff_table(conn)
        with conn:
            conn.execute("INSERT INTO cut_rolloffs (tournament_id, group_name, bowler_id, total, decided_by) VALUES (?,?,?,?,?)",
                         (tournament_id, group_name, bowler_id, int(total), td_name))
        return True
    except Exception as exc:
        log.warning("record_winner failed: %s", exc)
        return False
    finally:
        conn.close()


def apply_cut(members: list[dict], n_final: int, recorded: dict[int, int] | None = None) -> dict | None:
    """Set finalist / tied / rolloff on each row (rows already sorted best-first, each has rank, total, games).

    Returns {'spots', 'bowlers'} when a roll-off is still needed, else None.
    """
    recorded = recorded or {}
    result = _apply(members, n_final, recorded)
    first: dict[int, int] = {}
    for r in members:  # tied bowlers share the best rank of their tie (T5, T5, T5)
        if r.get("tied"):
            r["rank"] = first.setdefault(r["total"], r["rank"])
    return result


def _apply(members: list[dict], n_final: int, recorded: dict[int, int]) -> dict | None:
    bowled = [r for r in members if r["games"]]
    counts: dict[int, int] = {}
    for r in bowled:
        counts[r["total"]] = counts.get(r["total"], 0) + 1
    for r in members:
        r["tied"] = bool(r["games"]) and counts.get(r["total"], 0) > 1
        r["finalist"] = r["rank"] <= n_final and bool(r["games"])
        r["rolloff"] = False
    if len(bowled) <= n_final:
        return None
    cut_total = bowled[n_final - 1]["total"]
    if bowled[n_final]["total"] != cut_total:
        return None  # nobody outside the cut is tied with the last finalist
    tied = [r for r in bowled if r["total"] == cut_total]
    spots = n_final - sum(1 for r in bowled if r["total"] > cut_total)
    won = [r for r in tied if recorded.get(r["id"]) == r["total"]][:spots]
    for r in tied:
        r["finalist"] = r in won
        r["rolloff"] = len(won) < spots and r not in won
    if len(won) >= spots:
        return None
    return {"spots": spots - len(won), "bowlers": [r for r in tied if r["rolloff"]]}
