"""Average-based divisions and locked preset rules (e.g. youth scholarship events).

A tournament may store divisions as JSON in tournaments.divisions_json:
    [{"name": "Division 1", "min_avg": 160, "max_avg": null, "first_place": 500}, ...]
Bowlers are placed by entering average; standings are ranked separately inside each division.
"""

from __future__ import annotations

import json
from datetime import datetime

from modules.db_state import get_connection

UNASSIGNED = "No division (check average)"


def get_divisions(tournament: dict | None) -> list[dict]:
    if not tournament:
        return []
    try:
        divs = json.loads(tournament.get("divisions_json") or "[]")
    except (TypeError, ValueError):
        return []
    return [d for d in divs if isinstance(d, dict) and d.get("name")]


def division_for(avg, divisions: list[dict]) -> str | None:
    if not divisions:
        return None
    try:
        avg = int(avg)
    except (TypeError, ValueError):
        return UNASSIGNED
    for d in divisions:
        lo = d.get("min_avg")
        hi = d.get("max_avg")
        if (lo is None or avg >= int(lo)) and (hi is None or avg <= int(hi)):
            return d["name"]
    return UNASSIGNED


# Competition grouping is ONE setting (tournaments.grouping) so it is easy to switch:
#   "division"         average division only
#   "division_gender"  average division x Boys/Girls   (Rose Murphy: confirmed by Scott)
#   "age_gender"       age group x Boys/Girls
GROUPINGS = {"division": "Average division", "division_gender": "Average division x Boys/Girls",
             "age_gender": "Age group x Boys/Girls"}


def normalize_birth(value) -> str | None:
    """Accept MM/DD/YYYY, YYYY-MM-DD, etc.; return YYYY-MM-DD or None."""
    s = str(value or "").strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def age_on(birth: str | None, cutoff: str | None) -> int | None:
    b, c = normalize_birth(birth), normalize_birth(cutoff)
    if not b or not c:
        return None
    b, c = datetime.strptime(b, "%Y-%m-%d"), datetime.strptime(c, "%Y-%m-%d")
    return c.year - b.year - ((c.month, c.day) < (b.month, b.day))


def age_group_for(birth, tournament: dict) -> str | None:
    try:
        groups = json.loads(tournament.get("age_groups_json") or "[]")
    except (TypeError, ValueError):
        return None
    age = age_on(birth, tournament.get("age_cutoff"))
    if not groups or age is None:
        return None
    for g in groups:
        if (g.get("min_age") is None or age >= g["min_age"]) and (g.get("max_age") is None or age <= g["max_age"]):
            return g["name"]
    return f"Age {age} (outside age groups)"


def group_for(bowler: dict, tournament: dict) -> str | None:
    divs = get_divisions(tournament)
    grouping = tournament.get("grouping") or "division"
    gender = bowler.get("gender") or "Boys/Girls not set"
    if grouping == "age_gender":
        return f"{bowler.get('age_group') or age_group_for(bowler.get('birth_date'), tournament) or 'Age not set'} – {gender}"
    div = division_for(bowler.get("entering_avg"), divs)
    if div is None:
        return None
    return f"{div} – {gender}" if grouping == "division_gender" else div


def group_order(tournament: dict) -> list[str]:
    divs = [d["name"] for d in get_divisions(tournament)]
    grouping = tournament.get("grouping") or "division"
    if grouping == "division_gender":
        return [f"{d} – {g}" for d in divs for g in ("Boys", "Girls")]
    if grouping == "age_gender":
        try:
            ages = [g["name"] for g in json.loads(tournament.get("age_groups_json") or "[]")]
        except (TypeError, ValueError):
            ages = []
        return [f"{a} – {g}" for a in ages for g in ("Boys", "Girls")]
    return divs


def handicap_for(avg, tournament: dict, bowls_scratch: bool = False) -> int | None:
    """Handicap = pct% of (base - average), never below 0. Scratch bowlers get 0."""
    pct, base = tournament.get("handicap_pct"), tournament.get("handicap_base")
    if bowls_scratch:
        return 0
    try:
        return max(0, int((int(base) - int(avg)) * int(pct) / 100))
    except (TypeError, ValueError):
        return None


def finalists_count(field_size: int) -> int:
    """Rose Murphy rule 7: top 5 if MORE than 25 in the group, otherwise top 3."""
    return 5 if field_size > 25 else 3


def assign_all(tournament_id: int) -> None:
    """Re-place every bowler (group, age group, and locked-preset handicap)."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,)).fetchone()
        t = dict(row) if row else {}
        if not get_divisions(t):
            return
        with conn:
            for b in conn.execute("SELECT * FROM bowlers WHERE tournament_id = ?", (tournament_id,)).fetchall():
                b = dict(b)
                b["age_group"] = age_group_for(b.get("birth_date"), t)
                conn.execute("UPDATE bowlers SET division = ?, age_group = ? WHERE id = ?",
                             (group_for(b, t), b["age_group"], b["id"]))
                if t.get("rules_locked") and t.get("preset_key"):
                    h = handicap_for(b.get("entering_avg"), t, bool(b.get("bowls_scratch")))
                    if h is not None:
                        conn.execute("UPDATE bowlers SET handicap = ? WHERE id = ?", (h, b["id"]))
    finally:
        conn.close()


def group_standings(standings: list[dict], tournament: dict) -> list[tuple[str, list[dict]]]:
    """Split overall standings into [(group name, rows re-ranked 1..n)] in group order."""
    if not get_divisions(tournament):
        return [("", standings)]
    names = group_order(tournament)
    groups: dict[str, list[dict]] = {n: [] for n in names}
    for row in standings:
        key = (group_for(row, tournament) if "entering_avg" in row else row.get("division")) or UNASSIGNED
        groups.setdefault(key, []).append(row)
    out = []
    for name, rows in groups.items():
        if not rows and name not in names:
            continue
        out.append((name, [{**r, "rank": i} for i, r in enumerate(rows, start=1)]))
    return out


def division_label(name: str, divisions: list[dict]) -> str:
    base, _, suffix = name.partition(" – ")
    d = next((d for d in divisions if d["name"] == base), None)
    if not d:
        return name
    name = f"{base} {suffix}".strip()
    lo, hi = d.get("min_avg"), d.get("max_avg")
    rng = f"{lo} and above" if hi is None else (f"{hi} and under" if lo is None else f"{lo}–{hi}")
    prize = f" · 1st place: ${d['first_place']:,} SMART scholarship" if d.get("first_place") else ""
    return f"{name} (average {rng}){prize}"


# ------------------------------------------------------------------ locked preset rules

def entry_problems(tournament: dict, bowler: dict, now: datetime | None = None, override: bool = False) -> list[str]:
    """Plain-English reasons a bowler can't be added under this tournament's locked rules."""
    if not tournament or not tournament.get("rules_locked") or override:
        return []
    problems = []
    if tournament.get("youth_only") and not bowler.get("is_youth"):
        problems.append("This is a youth-only tournament. Tick 'Youth' for this bowler (adults can't enter).")
    if tournament.get("require_usbc") and not str(bowler.get("usbc_id") or "").strip():
        problems.append("A USBC ID number is required.")
    if tournament.get("require_gender") and bowler.get("gender") not in ("Boys", "Girls"):
        problems.append("Choose Boys or Girls (boys and girls are ranked separately).")
    if tournament.get("require_birthdate") and not normalize_birth(bowler.get("birth_date")):
        problems.append("A birth date is required (MM/DD/YYYY).")
    if tournament.get("require_smart") and not str(bowler.get("smart_account_id") or "").strip():
        problems.append("A SMART account number is required (prizes are SMART scholarships).")
    if get_divisions(tournament):
        try:
            ok = int(bowler.get("entering_avg") or 0) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok and not bowler.get("bowls_scratch"):
            problems.append("An entering average is required to place the bowler in a division (or tick 'Bowls scratch').")
    if tournament.get("no_walkins") and past_deadline(tournament, now):
        problems.append(f"The entry deadline ({tournament.get('entry_deadline')}) has passed and walk-ins are not allowed.")
    return problems


def past_deadline(tournament: dict, now: datetime | None = None) -> bool:
    raw = tournament.get("entry_deadline")
    if not raw:
        return False
    try:
        deadline = datetime.strptime(raw, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        return False
    return (now or datetime.now()) > deadline


def unconfirmed_items(tournament: dict | None) -> list[str]:
    try:
        return list(json.loads((tournament or {}).get("unconfirmed_json") or "[]"))
    except (TypeError, ValueError):
        return []


def grouped_results(tournament_id: int) -> list[dict]:
    """Per-group results: [{group, label, rows:[{id,name,..., rank, prize, finalist}], finalists}].

    Empty list when the tournament has no divisions. Only 1st place has a stated scholarship;
    other places show 0 here (the committee decides) and can be filled in on the flyer box.
    """
    from modules.standings import query  # local import avoids a cycle

    trow = query("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
    t = trow[0] if trow else None
    divs = get_divisions(t)
    if not divs:
        return []
    rows = query(
        """SELECT b.id, b.name, b.usbc_id, b.entering_avg, b.handicap, b.is_youth, b.smart_account_id,
                  b.division, b.gender, b.age_group,
                  COUNT(s.game_number) AS games_bowled,
                  COALESCE(SUM(s.scratch_score), 0) AS total_scratch,
                  COALESCE(SUM(s.scratch_score), 0) + COUNT(s.game_number) * COALESCE(b.handicap, 0) AS grand_total
           FROM bowlers b LEFT JOIN scores s ON s.bowler_id = b.id
           WHERE b.tournament_id = ? AND COALESCE(b.is_pacer, 0) = 0
           GROUP BY b.id ORDER BY grand_total DESC, total_scratch DESC""",
        (tournament_id,),
    )
    out = []
    for name, members in group_standings(rows, t):
        base = name.partition(" – ")[0]
        first = next((d.get("first_place") or 0 for d in divs if d["name"] == base), 0)
        n_final = finalists_count(len(members))
        for r in members:
            r["prize"] = float(first) if r["rank"] == 1 and r["games_bowled"] else 0.0
            r["finalist"] = r["rank"] <= n_final and r["games_bowled"] > 0
            r["total"] = r["grand_total"]
            r["games"] = r["games_bowled"]
        out.append({"group": name, "label": division_label(name, divs), "rows": members, "finalists": n_final})
    return out
