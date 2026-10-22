"""Standings, lane movement and bracket helpers shared by the hub and bowler views."""

from datetime import datetime, timezone

from modules.constants import HOST_CENTERS
from modules.db_state import get_connection

CUT_SEED = 5
TIEBREAK_FINAL_GAME = "high_final_game"
TIEBREAK_ROLL_OFF = "roll_off"
MAX_GAME_SCORE = 300


def query(sql: str, params: tuple = ()) -> list[dict]:
    connection = get_connection()
    try:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def get_tournament(tournament_id: int) -> dict | None:
    rows = query("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
    return rows[0] if rows else None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_action(user_name: str, role: str, description: str) -> None:
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO audit_log (user_name, role, action_description) VALUES (?, ?, ?)",
                (user_name, role, description),
            )
    finally:
        connection.close()


def commit_scores(
    tournament_id: int, game_number: int, scores: dict[int, int], verified_by: str, role: str
) -> None:
    """Upsert scratch scores for one game, stamped with who verified them and when."""
    verified_at = now_iso()
    connection = get_connection()
    try:
        with connection:
            for bowler_id, score in scores.items():
                connection.execute(
                    "INSERT INTO bowler_scores (bowler_id, tournament_id, game_number, scratch_score, "
                    "verified_by, verified_at) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (bowler_id, game_number) DO UPDATE SET "
                    "scratch_score = excluded.scratch_score, verified_by = excluded.verified_by, "
                    "verified_at = excluded.verified_at",
                    (bowler_id, tournament_id, game_number, score, verified_by, verified_at),
                )
            connection.execute(
                "INSERT INTO audit_log (user_name, role, action_description) VALUES (?, ?, ?)",
                (
                    verified_by,
                    role,
                    f"Committed {len(scores)} scores for game {game_number} (tournament {tournament_id})",
                ),
            )
    finally:
        connection.close()


# ---------------------------------------------------------------- lane movement

def pair_of_lane(lane: int) -> int:
    return (lane + 1) // 2


def lane_count(tournament: dict, bowlers: list[dict]) -> int:
    """Lanes in play: the highest assigned lane rounded up to a full pair, capped at host capacity."""
    highest = max((b["lane_assignment"] or 0 for b in bowlers), default=0)
    in_play = highest + (highest % 2)
    capacity = HOST_CENTERS.get(tournament["host_center"], {}).get("capacity_lanes")
    return max(2, min(in_play, capacity) if capacity else in_play)


def lane_for_game(start_lane: int, game_number: int, lanes: int) -> int:
    """Move right one pair (+2 lanes) after every game, wrapping at the last pair."""
    return (start_lane - 1 + 2 * (game_number - 1)) % lanes + 1


# ------------------------------------------------------------------- standings

def compute_standings(tournament_id: int) -> list[dict]:
    """Rank bowlers by handicap total (scratch + handicap per game bowled), applying tiebreaks."""
    tournament = get_tournament(tournament_id)
    if tournament is None:
        return []
    bowlers = query(
        "SELECT id, name, usbc_id, handicap, lane_assignment, mystery_doubles_opt_in "
        "FROM bowlers WHERE tournament_id = ?",
        (tournament_id,),
    )
    scores: dict[int, dict[int, int]] = {}
    for row in query(
        "SELECT bowler_id, game_number, scratch_score FROM bowler_scores WHERE tournament_id = ?",
        (tournament_id,),
    ):
        scores.setdefault(row["bowler_id"], {})[row["game_number"]] = row["scratch_score"]
    roll_offs = {
        row["bowler_id"]: row["roll_off_total"]
        for row in query(
            "SELECT bowler_id, roll_off_total FROM tiebreak_roll_offs WHERE tournament_id = ? ORDER BY id",
            (tournament_id,),
        )
    }

    roll_first = tournament["tiebreak_type"] == TIEBREAK_ROLL_OFF
    rows = []
    for bowler in bowlers:
        games = scores.get(bowler["id"], {})
        handicap = bowler["handicap"] or 0
        scratch = sum(games.values())
        final_game = games.get(tournament["game_count"], 0)
        roll_off = roll_offs.get(bowler["id"], -1)
        rows.append(
            {
                **bowler,
                "games_bowled": len(games),
                "game_scores": games,
                "scratch_total": scratch,
                "handicap_total": scratch + handicap * len(games),
                "high_game": max(games.values(), default=0),
                "final_game": final_game,
                "roll_off_total": roll_off,
                "tiebreak_key": (roll_off, final_game) if roll_first else (final_game, roll_off),
            }
        )

    rows.sort(key=lambda r: (-r["handicap_total"], tuple(-v for v in r["tiebreak_key"]), r["name"]))
    totals: dict[int, int] = {}
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        totals[row["handicap_total"]] = totals.get(row["handicap_total"], 0) + 1
    for row in rows:
        row["tied"] = row["games_bowled"] > 0 and totals[row["handicap_total"]] > 1
    return rows


def tie_groups(standings: list[dict], cut: int = CUT_SEED) -> list[dict]:
    """Groups of bowlers tied on total whose positions touch the finals seeds."""
    groups: dict[int, list[dict]] = {}
    for row in standings:
        if row["games_bowled"] > 0:
            groups.setdefault(row["handicap_total"], []).append(row)
    result = []
    for total, members in groups.items():
        if len(members) < 2 or members[0]["rank"] > cut:
            continue
        keys = [m["tiebreak_key"] for m in members]
        result.append(
            {
                "total": total,
                "start_rank": members[0]["rank"],
                "members": members,
                "unresolved": len(set(keys)) < len(keys),
            }
        )
    return sorted(result, key=lambda g: g["start_rank"])


# ------------------------------------------------------------------ squad pairs

def squad_pairs(tournament_id: int, game_number: int) -> list[dict]:
    """Pair tiles for one game, using each bowler's lane after movement."""
    tournament = get_tournament(tournament_id)
    if tournament is None:
        return []
    bowlers = query(
        "SELECT id, name, lane_assignment FROM bowlers WHERE tournament_id = ? AND lane_assignment IS NOT NULL",
        (tournament_id,),
    )
    lanes = lane_count(tournament, bowlers)
    scores = {
        row["bowler_id"]: row["scratch_score"]
        for row in query(
            "SELECT bowler_id, scratch_score FROM bowler_scores WHERE tournament_id = ? AND game_number = ?",
            (tournament_id, game_number),
        )
    }
    pairs: dict[int, dict] = {}
    for bowler in bowlers:
        lane = lane_for_game(bowler["lane_assignment"], game_number, lanes)
        pair = pairs.setdefault(
            pair_of_lane(lane), {"pair": pair_of_lane(lane), "bowlers": [], "lanes": (0, 0)}
        )
        pair["bowlers"].append({**bowler, "lane": lane, "score": scores.get(bowler["id"])})
    for pair in pairs.values():
        pair["lanes"] = (pair["pair"] * 2 - 1, pair["pair"] * 2)
        pair["reported"] = sum(b["score"] is not None for b in pair["bowlers"])
        pair["complete"] = pair["reported"] == len(pair["bowlers"])
        pair["bowlers"].sort(key=lambda b: b["lane"])
    return [pairs[key] for key in sorted(pairs)]


def current_game(tournament_id: int, game_count: int) -> int:
    """Lowest game that still has unreported scores, else the last game."""
    bowlers = query("SELECT COUNT(*) AS n FROM bowlers WHERE tournament_id = ?", (tournament_id,))[0]["n"]
    counts = {
        row["game_number"]: row["n"]
        for row in query(
            "SELECT game_number, COUNT(*) AS n FROM bowler_scores WHERE tournament_id = ? GROUP BY game_number",
            (tournament_id,),
        )
    }
    for game in range(1, game_count + 1):
        if counts.get(game, 0) < bowlers:
            return game
    return game_count


# --------------------------------------------------------------------- brackets

def bowler_brackets(tournament_id: int, bowler_id: int) -> list[dict]:
    """Which side events a bowler is still mathematically alive in."""
    tournament = get_tournament(tournament_id)
    standings = compute_standings(tournament_id)
    me = next((row for row in standings if row["id"] == bowler_id), None)
    if tournament is None or me is None:
        return []
    games_left = tournament["game_count"] - me["games_bowled"]
    handicap = me["handicap"] or 0
    brackets = []

    cut_row = standings[CUT_SEED - 1] if len(standings) >= CUT_SEED else None
    threshold = cut_row["handicap_total"] if cut_row else 0
    reach = me["handicap_total"] + (MAX_GAME_SCORE + handicap) * games_left
    brackets.append(
        {
            "name": "Handicap Stepladder",
            "alive": me["rank"] <= CUT_SEED or reach >= threshold,
            "detail": f"Seed #{me['rank']} (top {CUT_SEED} advance)",
        }
    )

    by_scratch = sorted(standings, key=lambda r: -r["scratch_total"])
    scratch_rank = next(i for i, r in enumerate(by_scratch, 1) if r["id"] == bowler_id)
    scratch_cut = by_scratch[CUT_SEED - 1]["scratch_total"] if len(by_scratch) >= CUT_SEED else 0
    brackets.append(
        {
            "name": "Scratch Series",
            "alive": scratch_rank <= CUT_SEED or me["scratch_total"] + MAX_GAME_SCORE * games_left >= scratch_cut,
            "detail": f"Scratch rank #{scratch_rank} (top {CUT_SEED} paid)",
        }
    )

    by_high = sorted(standings, key=lambda r: -r["high_game"])
    high_rank = next(i for i, r in enumerate(by_high, 1) if r["id"] == bowler_id)
    brackets.append(
        {
            "name": "High Game",
            "alive": high_rank <= 3 or games_left > 0,
            "detail": f"Best game {me['high_game']} (rank #{high_rank}, top 3 paid)",
        }
    )

    if me["mystery_doubles_opt_in"]:
        brackets.append(_mystery_bracket(tournament_id, standings, me, games_left))
    return brackets


def _mystery_bracket(tournament_id: int, standings: list[dict], me: dict, games_left: int) -> dict:
    by_id = {row["id"]: row for row in standings}
    pairs = query(
        "SELECT bowler_1_id, bowler_2_id FROM mystery_doubles_pairs WHERE tournament_id = ?",
        (tournament_id,),
    )
    if not pairs:
        return {"name": "$5 Mystery Doubles", "alive": True, "detail": "Draw pending"}

    def total(pair: dict) -> int:
        return sum(by_id[pair[key]]["handicap_total"] for key in ("bowler_1_id", "bowler_2_id") if pair[key] in by_id)

    mine = [p for p in pairs if me["id"] in (p["bowler_1_id"], p["bowler_2_id"])]
    if not mine:
        return {"name": "$5 Mystery Doubles", "alive": True, "detail": "Not yet paired"}
    pair = mine[0]
    partner_id = pair["bowler_2_id"] if pair["bowler_1_id"] == me["id"] else pair["bowler_1_id"]
    partner = by_id.get(partner_id, {}).get("name", "Mystery partner")
    ranked = sorted(pairs, key=total, reverse=True)
    place = ranked.index(pair) + 1
    return {
        "name": "$5 Mystery Doubles",
        "alive": place == 1 or games_left > 0,
        "detail": f"Paired with {partner} (pair rank #{place} of {len(pairs)})",
    }
