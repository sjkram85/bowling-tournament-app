"""Weekend dry run of the real Rose Murphy youth preset.

Creates the tournament with create_tournament_from_template(ROSE_MURPHY_KEY),
seeds 40 fictional youth, scores 3 games, ranks each division × gender group,
and plays every stepladder through a champion.

The database is a temporary SQLite file (modules.db_state.DB_PATH). The desk
file tournament.db is not used. Practice Mode is not used.

    python scripts/rose_murphy_dry_run.py

Writes artifacts/rose_murphy_dry_run_standings.md (and a qualifying CSV).
The random seed is fixed so a second run reprints the same report.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep the mailbox vaults off before Prism opens a database.
os.environ["PRISM_STAFF_VAULT"] = "off"
os.environ["PRISM_TOURNAMENT_VAULT"] = "off"

from modules import db_state, rolloff, standings, stepladder  # noqa: E402
from modules import divisions as dv  # noqa: E402
from modules.constants import HOST_CENTERS  # noqa: E402
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template  # noqa: E402

SEED = 20261206
FIELD_SIZE = 40
TD_NAME = "Scott"
# Entries are checked as of this afternoon, before the Nov 29, 2026 deadline.
ENTRY_AS_OF = datetime(2026, 11, 1, 12, 0)
REPORT_NAME = "rose_murphy_dry_run_standings.md"
QUALIFYING_CSV = "rose_murphy_dry_run_qualifying.csv"
STEPLADDER_CSV = "rose_murphy_dry_run_stepladder.csv"

# Age as of July 31, 2026 spans Preps, Juniors, and Majors. Ranking does not use age.
# Birth dates are chosen so age groups (as of July 31, 2026) are realistic for the average.
# Higher averages are older youth. Ranking does not use age.
_BIRTH_BY_BAND = {
    "high": ("2010-09-08", "2009-02-14", "2008-04-04"),       # Majors
    "mid": ("2013-06-15", "2012-01-20", "2011-05-02", "2010-09-08"),  # Juniors / Majors
    "low": ("2016-03-12", "2015-08-19", "2014-11-02", "2013-06-15"),  # Preps / Juniors
}

# (division, gender, [(name, entering average), ...])
# Division 2 Boys is the large group so finalists_count returns top 5 (>25).
# Every other division × gender group is 25 or fewer, so the preset uses top 3.
SLOTS: list[tuple[str, str, list[tuple[str, int]]]] = [
    ("Division 2", "Boys", [
        ("Caleb Brennan", 126), ("Mason Hale", 128), ("Ethan Brooks", 130),
        ("Noah Keller", 132), ("Liam Hart", 134), ("Owen Price", 136),
        ("Jacob Nguyen", 138), ("Lucas Bennett", 140), ("Aiden Walsh", 142),
        ("Eli Carter", 144), ("Gavin Moore", 146), ("Henry Diaz", 148),
        ("Jack Sullivan", 150), ("Leo Park", 151), ("Miles Grant", 152),
        ("Nathan Cole", 153), ("Parker Reid", 154), ("Ryan Foster", 155),
        ("Samuel Ortiz", 156), ("Tyler Jennings", 157), ("Wyatt Lang", 158),
        ("Zachary Pitt", 159), ("Connor Blake", 133), ("Dylan Shaw", 141),
        ("Finn Harper", 147), ("Grayson Holt", 137),
    ]),
    ("Division 1", "Boys", [
        ("Hunter Ellis", 168), ("Isaac Romero", 185), ("Kai Moreno", 201),
    ]),
    ("Division 1", "Girls", [
        ("Ava Sinclair", 162), ("Chloe Bennett", 176), ("Emma Ruiz", 194),
    ]),
    ("Division 2", "Girls", [
        ("Grace Patel", 129), ("Hannah Kim", 143), ("Isla Donovan", 157),
    ]),
    ("Division 3", "Boys", [
        ("Logan Pierce", 98), ("Marcus Webb", 112), ("Nolan Briggs", 124),
    ]),
    ("Division 3", "Girls", [
        ("Maya Chen", 87), ("Sophia Alvarez", 119),
    ]),
]


def _birth_date(avg: int, index: int) -> str:
    band = "high" if avg >= 170 else ("mid" if avg >= 140 else "low")
    choices = _BIRTH_BY_BAND[band]
    return choices[index % len(choices)]


def build_roster() -> list[dict]:
    """Fictional youth field: USBC, SMART, birth date, gender, average, paid, same-pair lane."""
    roster = []
    index = 0
    for division, gender, people in SLOTS:
        for name, avg in people:
            index += 1
            lane = (index - 1) // 2 + 1
            roster.append({
                "name": name,
                "division_name": division,
                "gender": gender,
                "entering_avg": avg,
                "usbc_id": f"17-{10000 + index}",
                "smart_account_id": str(5512000 + index),
                "birth_date": _birth_date(avg, index),
                "lane_assignment": lane,
                "lineup_position": (index - 1) % 2 + 1,
                "is_youth": 1,
                "paid_status": "paid",
                "bowls_scratch": 0,
            })
    if len(roster) != FIELD_SIZE:
        raise RuntimeError(f"Roster has {len(roster)} bowlers; expected {FIELD_SIZE}.")
    if len({r["name"] for r in roster}) != FIELD_SIZE:
        raise RuntimeError("Roster names are not unique.")
    return roster


def _scratch_near(avg: int, rng: random.Random, spread: int) -> int:
    """One youth game around the entering average. Scratch only; handicap is applied later."""
    return max(40, min(279, avg + rng.randint(-spread, spread)))


def _use_database(path: Path) -> tuple[Path, Path]:
    previous = db_state.DB_PATH
    previous_file = db_state.DB_FILE
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for extra in ("", "-wal", "-shm"):
        candidate = Path(str(path) + extra) if extra else path
        if candidate.exists():
            candidate.unlink()
    db_state.DB_PATH = path
    db_state.DB_FILE = path
    return previous, previous_file


def _restore_database(previous: Path, previous_file: Path) -> None:
    db_state.DB_PATH = previous
    db_state.DB_FILE = previous_file


def _insert_roster(tournament_id: int, tournament: dict, roster: list[dict]) -> None:
    conn = db_state.get_connection()
    try:
        with conn:
            for row in roster:
                problems = dv.entry_problems(tournament, row, ENTRY_AS_OF)
                if problems:
                    raise RuntimeError(f"{row['name']} was rejected: {problems}")
                hdcp = dv.entry_handicap(tournament, row["entering_avg"], False)
                if hdcp is None:
                    raise RuntimeError(f"{row['name']} has no handicap from entry_handicap.")
                cur = conn.execute(
                    """
                    INSERT INTO bowlers (
                        tournament_id, name, usbc_id, email, entering_avg, handicap,
                        lane_assignment, lineup_position, is_youth, smart_account_id, paid_status,
                        gender, birth_date, bowls_scratch, checked_in
                    ) VALUES (?, ?, ?, '', ?, ?, ?, ?, 1, ?, 'paid', ?, ?, 0, 1)
                    """,
                    (tournament_id, row["name"], row["usbc_id"], row["entering_avg"], int(hdcp),
                     row["lane_assignment"], row["lineup_position"], row["smart_account_id"],
                     row["gender"], dv.normalize_birth(row["birth_date"])),
                )
                conn.execute(
                    """
                    INSERT INTO bowler_events (bowler_id, tournament_id, event_type, event_fee, paid_status)
                    VALUES (?, ?, 'Singles', 0, 'paid')
                    """,
                    (cur.lastrowid, tournament_id),
                )
    finally:
        conn.close()
    dv.assign_all(tournament_id)


def _record_game(tournament_id: int, bowler_id: int, game_number: int, scratch: int, hdcp: int) -> None:
    """Desk-shaped score write: total = scratch + the bowler's stored per-game handicap.

    The handicap number is the one assign_all wrote. This function does not compute 90% of 220.
    """
    total = int(scratch) + int(hdcp)
    conn = db_state.get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO scores (
                    tournament_id, bowler_id, game_number, scratch_score, hdcp_score, total_score,
                    recorded_by, verified, verified_by, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tournament_id, bowler_id, game_number) DO UPDATE SET
                    scratch_score = excluded.scratch_score,
                    hdcp_score = excluded.hdcp_score,
                    total_score = excluded.total_score,
                    recorded_by = excluded.recorded_by,
                    verified = 1,
                    verified_by = excluded.verified_by,
                    verified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (tournament_id, bowler_id, game_number, int(scratch), int(hdcp), total, TD_NAME, TD_NAME),
            )
    finally:
        conn.close()
    db_state.log_desk_action(
        TD_NAME, "td",
        f"Dry run Game {game_number} score {scratch} (HDCP +{hdcp}) for Bowler #{bowler_id}",
    )


def _score_qualifying(tournament_id: int, roster_ids: list[int], by_id: dict[int, dict], rng: random.Random) -> None:
    for bowler_id in roster_ids:
        bowler = by_id[bowler_id]
        hdcp = int(bowler["handicap"])
        for game in (1, 2, 3):
            scratch = _scratch_near(int(bowler["entering_avg"]), rng, 22)
            _record_game(tournament_id, bowler_id, game, scratch, hdcp)


def _one_game_total(bowler: dict, rng: random.Random) -> int:
    """One stepladder game: scratch near average, plus the bowler's stored handicap."""
    scratch = _scratch_near(int(bowler["entering_avg"]), rng, 32)
    return scratch + int(bowler["handicap"])


def _resolve_cut_ties(tournament_id: int, by_id: dict[int, dict], rng: random.Random) -> list[dict]:
    """One-game roll-off where grouped_results still has a tie at the last finalist spot."""
    notes = []
    for _ in range(8):
        pending = [g for g in dv.grouped_results(tournament_id) if g.get("rolloff")]
        if not pending:
            return notes
        for group in pending:
            info = group["rolloff"]
            spots = int(info["spots"])
            tied = list(info["bowlers"])
            decided = None
            for _try in range(40):
                scored = []
                for row in tied:
                    bowler = by_id[row["id"]]
                    total = _one_game_total(bowler, rng)
                    scored.append({"id": row["id"], "name": row["name"], "qualifying": row["total"], "rolloff": total})
                scored.sort(key=lambda item: (-item["rolloff"], item["name"]))
                if spots < len(scored) and scored[spots - 1]["rolloff"] == scored[spots]["rolloff"]:
                    continue
                decided = scored
                break
            if decided is None:
                raise RuntimeError(f"Roll-off in {group['group']} stayed tied.")
            for item in decided[:spots]:
                if not rolloff.record_winner(
                    tournament_id, group["group"], item["id"], int(item["qualifying"]), TD_NAME,
                    rolloff_score=int(item["rolloff"]),
                ):
                    raise RuntimeError(f"Could not record roll-off winner {item['name']}.")
            notes.append({"group": group["group"], "spots": spots, "scores": decided, "advanced": spots})
    if any(g.get("rolloff") for g in dv.grouped_results(tournament_id)):
        raise RuntimeError("A finalist cut is still tied after roll-offs.")
    return notes


def _play_stepladder(tournament_id: int, by_id: dict[int, dict], rng: random.Random, cap: int) -> None:
    info = stepladder.seeds(tournament_id)
    blocked = {name: row["reason"] for name, row in info.items() if not row["ready"]}
    if blocked:
        raise RuntimeError(f"Stepladder is not ready: {blocked}")
    if not stepladder.initialize_stepladder(tournament_id, td_name=TD_NAME):
        raise RuntimeError("initialize_stepladder did not start a ladder.")
    for group in info:
        guard = 0
        while True:
            state = stepladder.get_stepladder_state(tournament_id, group)
            active = [m for m in state if m["status"] == "active"]
            if not active:
                if any(m["status"] != "completed" for m in state):
                    raise RuntimeError(f"{group} stopped before the championship.")
                break
            if len(active) != 1:
                raise RuntimeError(f"{group} has {len(active)} active matches.")
            match = active[0]
            guard += 1
            if guard > 8:
                raise RuntimeError(f"{group} did not finish.")
            low = by_id[match["bowler_low_id"]]
            high = by_id[match["bowler_high_id"]]
            score_low = _one_game_total(low, rng)
            score_high = _one_game_total(high, rng)
            roll_low = roll_high = None
            if score_low == score_high:
                for _ in range(50):
                    roll_low = _one_game_total(low, rng)
                    roll_high = _one_game_total(high, rng)
                    if roll_low != roll_high:
                        break
                else:
                    raise RuntimeError(f"Stepladder roll-off stayed tied in {group}.")
            for value in (score_low, score_high, roll_low, roll_high):
                if value is not None and (value < 0 or value > cap):
                    raise RuntimeError(f"Match score {value} is outside 0..{cap}.")
            if not stepladder.record_stepladder_score(
                match["id"], score_low, score_high, roll_low, roll_high, TD_NAME
            ):
                raise RuntimeError(f"Could not save match {match['match_number']} in {group}.")
        champion = stepladder.champion(tournament_id, group)
        if not champion:
            raise RuntimeError(f"{group} has no champion.")


def _load_bowlers(tournament_id: int) -> dict[int, dict]:
    rows = standings.query("SELECT * FROM bowlers WHERE tournament_id = ? ORDER BY id", (tournament_id,))
    return {row["id"]: row for row in rows}


def _load_games(tournament_id: int) -> dict[int, dict[int, dict]]:
    games: dict[int, dict[int, dict]] = {}
    for row in standings.query(
        "SELECT bowler_id, game_number, scratch_score, hdcp_score, total_score FROM scores WHERE tournament_id = ?",
        (tournament_id,),
    ):
        games.setdefault(row["bowler_id"], {})[row["game_number"]] = row
    return games


def _check_field(tournament: dict, by_id: dict[int, dict], games: dict) -> None:
    if len(by_id) != FIELD_SIZE:
        raise RuntimeError(f"Field size is {len(by_id)}, expected {FIELD_SIZE}.")
    if tournament.get("preset_key") != ROSE_MURPHY_KEY:
        raise RuntimeError("Tournament was not created from the Rose Murphy preset.")
    if int(tournament.get("is_practice") or 0):
        raise RuntimeError("Practice Mode is on. This dry run must use the real preset.")
    if tournament.get("host_center") != "FHL":
        raise RuntimeError(f"Host is {tournament.get('host_center')}, expected FHL.")
    if int(tournament.get("fees_at_front_desk") or 0) != 1:
        raise RuntimeError("fees_at_front_desk is not set.")
    if int(tournament.get("game_count") or 0) != 3:
        raise RuntimeError("Game count is not 3.")
    if int(tournament.get("handicap_pct") or 0) != 90 or int(tournament.get("handicap_base") or 0) != 220:
        raise RuntimeError("Handicap rule is not 90% of 220.")
    if tournament.get("grouping") != "division_gender":
        raise RuntimeError("Grouping is not division × gender.")
    if standings.event_lane_pattern(tournament) != "same_pair":
        raise RuntimeError("Lane pattern is not same_pair.")
    pattern = standings.event_lane_pattern(tournament)
    lanes = standings.lane_count(tournament, list(by_id.values()))
    divs = dv.get_divisions(tournament)
    expected = {}
    for division, gender, people in SLOTS:
        sample = people[0][1]
        key = dv.group_for({"entering_avg": sample, "gender": gender}, tournament)
        if dv.division_for(sample, divs) != division:
            raise RuntimeError(f"{sample} did not land in {division}.")
        expected[key] = len(people)
    counts = {}
    ages = set()
    for bowler in by_id.values():
        if int(bowler.get("is_youth") or 0) != 1:
            raise RuntimeError(f"{bowler['name']} is not marked youth.")
        if bowler.get("paid_status") != "paid":
            raise RuntimeError(f"{bowler['name']} is not paid.")
        if not str(bowler.get("usbc_id") or "").strip() or not str(bowler.get("smart_account_id") or "").strip():
            raise RuntimeError(f"{bowler['name']} is missing USBC or SMART.")
        if bowler.get("gender") not in ("Boys", "Girls"):
            raise RuntimeError(f"{bowler['name']} has no Boys/Girls value.")
        group = dv.group_for(bowler, tournament)
        if bowler.get("division") != group:
            raise RuntimeError(f"{bowler['name']} division is {bowler.get('division')}, expected {group}.")
        counts[group] = counts.get(group, 0) + 1
        hdcp = dv.handicap_for(bowler.get("entering_avg"), tournament, bool(bowler.get("bowls_scratch")))
        if int(bowler.get("handicap") or -1) != hdcp:
            raise RuntimeError(f"{bowler['name']} handicap {bowler.get('handicap')} != handicap_for {hdcp}.")
        ages.add(bowler.get("age_group"))
        own = games.get(bowler["id"], {})
        if set(own) != {1, 2, 3}:
            raise RuntimeError(f"{bowler['name']} does not have 3 games.")
        for game, score in own.items():
            if int(score["hdcp_score"]) != int(bowler["handicap"]):
                raise RuntimeError(f"{bowler['name']} game {game} did not store the bowler's handicap.")
            if int(score["total_score"]) != int(score["scratch_score"]) + int(score["hdcp_score"]):
                raise RuntimeError(f"{bowler['name']} game {game} total is not scratch + handicap.")
            if not 0 <= int(score["scratch_score"]) <= 300:
                raise RuntimeError(f"{bowler['name']} game {game} scratch is out of range.")
        start = int(bowler["lane_assignment"])
        for game in (1, 2, 3):
            if standings.lane_for_game(start, game, lanes, pattern) != start:
                raise RuntimeError(f"{bowler['name']} left lane {start} on game {game}.")
    if counts != expected:
        raise RuntimeError(f"Group sizes {counts} do not match the plan {expected}.")
    if not {"Preps", "Juniors", "Majors"} <= ages:
        raise RuntimeError(f"Age groups assigned: {ages}.")
    # Known truncation case from the youth preset tests: 90% of (220 - 151) = 62.1 → 62.
    leo = next(b for b in by_id.values() if b["name"] == "Leo Park")
    if int(leo["entering_avg"]) != 151 or int(leo["handicap"]) != 62:
        raise RuntimeError(f"Leo Park should be 151 average / 62 handicap, got {leo['entering_avg']} / {leo['handicap']}.")


def _series_ok(groups: list[dict], games: dict) -> None:
    for group in groups:
        field = len(group["rows"])
        if group["finalists"] != dv.finalists_count(field):
            raise RuntimeError(f"{group['group']} cut {group['finalists']} does not match finalists_count({field}).")
        for row in group["rows"]:
            own = games[row["id"]]
            scratch = sum(int(own[g]["scratch_score"]) for g in (1, 2, 3))
            total = scratch + int(row["handicap"]) * 3
            if int(row["total_scratch"]) != scratch or int(row["grand_total"]) != total:
                raise RuntimeError(f"{row['name']} standings total does not match scratch + handicap × 3.")


def _cut_label(field: int) -> str:
    return "Top 5" if field > 25 else "Top 3"


def _match_word(count: int) -> str:
    return "1 match" if count == 1 else f"{count} matches"


def _rank_label(row: dict) -> str:
    return f"T{row['rank']}" if row.get("tied") else str(row["rank"])


def _md_table(headers: list[str], rows: list[list]) -> str:
    head = "| " + " | ".join(headers) + " |"
    rule = "|" + "|".join("---" for _ in headers) + "|"
    body = ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def _render_report(tournament: dict, groups: list[dict], games: dict, rolloff_notes: list[dict],
                   seed_info: dict) -> tuple[str, list[dict]]:
    center = HOST_CENTERS["FHL"]
    lines = [
        f"# {tournament['name']}",
        "",
        "Weekend dry-run standings with stepladder champions.",
        "",
        "| | |",
        "|---|---|",
        f"| Event | {tournament['name']} |",
        f"| Preset | {ROSE_MURPHY_KEY} |",
        f"| Host | {center['name']} (FHL), {center['address']} |",
        "| Date | Sunday, December 6, 2026, 10:00 AM |",
        "| Format | Singles, 3 games, same pair |",
        "| Handicap | 90% of 220, fraction dropped (`divisions.handicap_for` / `assign_all`) |",
        f"| Field | {FIELD_SIZE} youth |",
        "| Fees | All 40 marked paid. The $30 entry is collected at the Forest Hill front desk (`fees_at_front_desk`). |",
        "| Ranking | Division × Boys/Girls |",
        "| Finals | Top 5 when the group has more than 25 bowlers; otherwise top 3 (`divisions.finalists_count`) |",
        "| Lanes | Lanes 1–20, two bowlers per lane. `same_pair`: games 2 and 3 stay on the starting lane. |",
        "| Database | Temporary SQLite through `db_state`. Practice Mode is off (`is_practice` = 0). |",
        "",
        "This was a simulated dry run using Prism modules. It is not a live Streamlit Cloud session "
        "and it is not the December 6 tournament. Names, USBC IDs, SMART accounts, birth dates, and "
        f"scores are fictional. Re-run `python scripts/rose_murphy_dry_run.py` (seed {SEED}) to reprint this report.",
        "",
        "Forty bowlers can fill one division × gender group past 25. This field puts 26 bowlers in "
        "Division 2 Boys so the top-5 stepladder runs. Every other group has 25 or fewer bowlers, so "
        "Prism uses top 3. When the field is smaller than that cut, every bowler with scores is a finalist.",
        "",
        "## Stepladder champions",
        "",
    ]
    champion_rows = []
    champions = []
    for group in groups:
        field = len(group["rows"])
        if field == 0:
            continue
        name = stepladder.champion(tournament["id"], group["group"])
        leader = next(row["name"] for row in group["rows"] if row["rank"] == 1)
        rule = _cut_label(field)
        advanced = sum(1 for row in group["rows"] if row["finalist"])
        champion_rows.append([group["group"], field, rule, leader, name])
        champions.append({
            "group": group["group"],
            "label": group["label"],
            "field": field,
            "rule": rule,
            "cut": group["finalists"],
            "advanced": advanced,
            "leader": leader,
            "champion": name,
        })
    lines.append(_md_table(
        ["Group", "Field", "Finals", "Qualifying leader", "Champion"],
        champion_rows,
    ))
    lines.append("")
    lines.append("The champion is the stepladder winner. The qualifying leader is rank 1 on the handicap series before the ladder.")
    lines.append("")
    lines.append("## Finals cut")
    lines.append("")
    lines.append(_md_table(
        ["Group", "Bowlers", "Rule (`finalists_count`)", "In the ladder"],
        [[
            c["group"],
            c["field"],
            f"{c['rule']} (cut {c['cut']})",
            c["advanced"] if c["field"] >= c["cut"] else f"{c['advanced']} (field smaller than the cut)",
        ] for c in champions],
    ))
    lines.append("")
    lines.append("## Qualifying standings")
    lines.append("")
    lines.append(
        "HDCP is pins per game, stored on the bowler by `divisions.assign_all`. "
        "Total = G1 + G2 + G3 + HDCP × 3, which is the `grouped_results` handicap series. "
        "Finalist follows that series and any cut roll-off. "
        "Lane, lineup, USBC ID, SMART account, birth date, and age group are in "
        "`artifacts/rose_murphy_dry_run_qualifying.csv`."
    )
    lines.append("")
    for group in groups:
        if not group["rows"]:
            continue
        field = len(group["rows"])
        advanced = sum(1 for row in group["rows"] if row["finalist"])
        lines.append(f"### {group['label']}")
        lines.append("")
        if field < group["finalists"]:
            who = "both bowlers" if advanced == 2 else f"all {advanced} bowlers"
            lines.append(
                f"{field} bowlers. {_cut_label(field)} (`finalists_count` is {group['finalists']}). "
                f"The field is smaller than the cut, so {who} with scores are finalists."
            )
        else:
            lines.append(f"{field} bowlers. {_cut_label(field)}. {advanced} finalists.")
        lines.append("")
        table = []
        for row in group["rows"]:
            own = games[row["id"]]
            scratch = sum(int(own[g]["scratch_score"]) for g in (1, 2, 3))
            table.append([
                _rank_label(row),
                row["name"],
                row["entering_avg"],
                own[1]["scratch_score"],
                own[2]["scratch_score"],
                own[3]["scratch_score"],
                row["handicap"],
                scratch,
                row["grand_total"],
                "Yes" if row["finalist"] else "No",
            ])
        lines.append(_md_table(
            ["Rank", "Name", "Avg", "G1", "G2", "G3", "HDCP", "Scratch", "Total", "Finalist"],
            table,
        ))
        lines.append("")
    lines.append("## Cut roll-offs")
    lines.append("")
    if not rolloff_notes:
        lines.append("No group tied at the last finalist spot, so no roll-off was required.")
        lines.append("")
    else:
        lines.append(
            "A tie at the last finalist spot was bowled as one game. "
            "The roll-off score is a handicap total (scratch near average + that bowler's stored handicap). "
            "`rolloff.record_winner` advanced the open spots."
        )
        lines.append("")
        for note in rolloff_notes:
            lines.append(f"### {note['group']}")
            lines.append("")
            lines.append(_md_table(
                ["Bowler", "Qualifying total", "Roll-off", "Advanced"],
                [[
                    item["name"], item["qualifying"], item["rolloff"],
                    "Yes" if index < note["advanced"] else "No",
                ] for index, item in enumerate(note["scores"])],
            ))
            lines.append("")
    lines.append("## Stepladder")
    lines.append("")
    lines.append(
        "One game per match. The score entered is the handicap total (scratch near the bowler's average "
        "+ the per-game handicap already stored on the bowler), capped by `stepladder.max_match_score`. "
        "Lowest seed bowls the next seed. The winner moves up. A tied game uses a one-game roll-off."
    )
    lines.append("")
    for group in groups:
        if not group["rows"]:
            continue
        info = seed_info[group["group"]]
        matches = stepladder.get_stepladder_state(tournament["id"], group["group"])
        lines.append(f"### {group['label']}")
        lines.append("")
        lines.append(f"{_cut_label(len(group['rows']))} · {_match_word(len(matches))}.")
        lines.append("")
        lines.append("Seeds (best qualifying first): " + ", ".join(
            f"#{i + 1} {row['name']}" for i, row in enumerate(info["seeds"])
        ) + ".")
        tied_totals: dict[int, list] = {}
        for index, row in enumerate(info["seeds"], start=1):
            tied_totals.setdefault(row["total"], []).append((index, row))
        for total, members in tied_totals.items():
            if len(members) < 2:
                continue
            detail = ", ".join(
                f"#{index} {row['name']} (scratch {row['total_scratch']})" for index, row in members
            )
            lines.append("")
            lines.append(
                f"Tied handicap total {total}: {detail}. "
                "Each of them is inside the cut, so each is a finalist. "
                "The better seed is the higher scratch series."
            )
        lines.append("")
        match_rows = []
        for match in matches:
            extra = ""
            if match.get("rolloff_low") is not None and match.get("rolloff_high") is not None:
                extra = f" Roll-off {match['rolloff_low']}–{match['rolloff_high']}."
            match_rows.append([
                match["match_name"],
                match["low_name"] or "",
                match["score_low"],
                match["high_name"] or "",
                match["score_high"],
                match["winner_name"] or "",
                extra.strip() or "—",
            ])
        lines.append(_md_table(
            ["Match", "Low seed", "Score", "High seed", "Score", "Winner", "Roll-off"],
            match_rows,
        ))
        lines.append("")
        lines.append(f"**Champion: {stepladder.champion(tournament['id'], group['group'])}**")
        lines.append("")
    lines.append("## How this run used Prism")
    lines.append("")
    lines.append(
        f"- Tournament: `create_tournament_from_template` with `{ROSE_MURPHY_KEY}`. "
        "The preset locks Forest Hill Lanes, 3 games, handicap 90% of 220, division × gender, "
        "same-pair lanes, youth-only, USBC, SMART, gender, and birth date."
    )
    lines.append(
        "- Roster: each bowler passed `divisions.entry_problems` (checked November 1, 2026, before the "
        "November 29 deadline) and was placed by `divisions.assign_all`, which calls `handicap_for`."
    )
    lines.append(
        "- Scores: three scratch games near the entering average. Each score row stores that scratch, "
        "the bowler's handicap, and scratch + handicap. Standings come from `divisions.grouped_results` "
        "(group standings plus `finalists_count`)."
    )
    lines.append(
        "- Finals: `stepladder.initialize_stepladder` and `stepladder.record_stepladder_score` through "
        "the last match. Champions are `stepladder.champion`."
    )
    lines.append(
        "- This run did not call Practice Mode. `tournaments.is_practice` is 0. "
        "The database was a temporary SQLite file, not the live Streamlit Cloud desk."
    )
    lines.append("")
    return "\n".join(lines), champions


def _write_qualifying_csv(path: Path, groups: list[dict], games: dict, by_id: dict[int, dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "group", "rank", "tied", "finalist", "name", "gender", "entering_avg", "handicap",
            "g1", "g2", "g3", "scratch_series", "total", "lane", "lineup", "usbc_id",
            "smart_account_id", "birth_date", "age_group", "paid_status",
        ])
        for group in groups:
            for row in group["rows"]:
                bowler = by_id[row["id"]]
                own = games[row["id"]]
                scratch = sum(int(own[g]["scratch_score"]) for g in (1, 2, 3))
                writer.writerow([
                    group["group"], row["rank"], int(bool(row.get("tied"))), int(bool(row["finalist"])),
                    row["name"], bowler.get("gender"), row["entering_avg"], row["handicap"],
                    own[1]["scratch_score"], own[2]["scratch_score"], own[3]["scratch_score"],
                    scratch, row["grand_total"], bowler.get("lane_assignment"), bowler.get("lineup_position"),
                    bowler.get("usbc_id"), bowler.get("smart_account_id"), bowler.get("birth_date"),
                    bowler.get("age_group"), bowler.get("paid_status"),
                ])


def _write_stepladder_csv(path: Path, tournament_id: int, groups: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "group", "match_number", "match_name", "low_name", "score_low", "high_name", "score_high",
            "rolloff_low", "rolloff_high", "winner_name", "status",
        ])
        for group in groups:
            if not group["rows"]:
                continue
            for match in stepladder.get_stepladder_state(tournament_id, group["group"]):
                writer.writerow([
                    group["group"], match["match_number"], match["match_name"], match["low_name"],
                    match["score_low"], match["high_name"], match["score_high"],
                    match.get("rolloff_low"), match.get("rolloff_high"), match["winner_name"], match["status"],
                ])


def run(db_path: Path, out_dir: Path, seed: int = SEED) -> dict:
    """Simulate the weekend and write the standings report. Returns a short summary."""
    from modules import staff_vault, tournament_vault

    staff_vault.use_store(None)
    tournament_vault.use_store(None)
    previous, previous_file = _use_database(Path(db_path))
    try:
        db_state.init_db()
        roster = build_roster()
        tournament_id = create_tournament_from_template(ROSE_MURPHY_KEY, "FHL")
        tournament = standings.get_tournament(tournament_id)
        if tournament is None:
            raise RuntimeError("Rose Murphy tournament was not created.")
        _insert_roster(tournament_id, tournament, roster)
        by_id = _load_bowlers(tournament_id)
        roster_ids = [bowler_id for bowler_id, _bowler in sorted(by_id.items(), key=lambda item: item[0])]
        # Registration order matches build_roster order (ids are assigned in that order).
        if [by_id[i]["name"] for i in roster_ids] != [row["name"] for row in roster]:
            raise RuntimeError("Bowler insert order does not match the roster.")
        rng = random.Random(seed)
        _score_qualifying(tournament_id, roster_ids, by_id, rng)
        games = _load_games(tournament_id)
        _check_field(tournament, by_id, games)
        rolloff_notes = _resolve_cut_ties(tournament_id, by_id, rng)
        groups = dv.grouped_results(tournament_id)
        games = _load_games(tournament_id)
        _series_ok(groups, games)
        cap = stepladder.max_match_score(tournament)
        _play_stepladder(tournament_id, by_id, rng, cap)
        groups = dv.grouped_results(tournament_id)
        seed_info = stepladder.seeds(tournament_id)
        report, champions = _render_report(tournament, groups, games, rolloff_notes, seed_info)
        if len(champions) != len(SLOTS):
            raise RuntimeError(f"Expected a champion in {len(SLOTS)} groups, got {len(champions)}.")
        if not any(c["rule"] == "Top 5" and c["field"] > 25 for c in champions):
            raise RuntimeError("No group ran a top-5 stepladder.")
        if not all(c["champion"] for c in champions):
            raise RuntimeError("A group finished without a champion.")
        for champ in champions:
            if champ["rule"] == "Top 5" and champ["cut"] != 5:
                raise RuntimeError(f"{champ['group']} was labeled top 5 with cut {champ['cut']}.")
            if champ["rule"] == "Top 3" and champ["cut"] != 3:
                raise RuntimeError(f"{champ['group']} was labeled top 3 with cut {champ['cut']}.")
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / REPORT_NAME
        report_path.write_text(report, encoding="utf-8")
        _write_qualifying_csv(out_dir / QUALIFYING_CSV, groups, games, by_id)
        _write_stepladder_csv(out_dir / STEPLADDER_CSV, tournament_id, groups)
        return {
            "tournament_id": tournament_id,
            "bowler_count": len(by_id),
            "is_practice": int(tournament.get("is_practice") or 0),
            "champions": champions,
            "rolloffs": len(rolloff_notes),
            "report_path": str(report_path),
            "names": [row["name"] for row in roster],
        }
    finally:
        _restore_database(previous, previous_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rose Murphy weekend dry run (real preset, temporary SQLite).")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts", help="Directory for the standings report.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite file to use. Default: a temporary file.")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed for scores and match games.")
    args = parser.parse_args()
    temporary = args.db is None
    if temporary:
        handle = tempfile.NamedTemporaryFile(prefix="rose_murphy_dry_run_", suffix=".db", delete=False)
        handle.close()
        db_path = Path(handle.name)
    else:
        db_path = args.db
    try:
        result = run(db_path, args.out, args.seed)
    finally:
        if temporary:
            for extra in ("", "-wal", "-shm"):
                candidate = Path(str(db_path) + extra) if extra else db_path
                candidate.unlink(missing_ok=True)
    print(f"Wrote {result['report_path']}")
    print(f"Field: {result['bowler_count']} youth. Practice flag: {result['is_practice']}.")
    for champ in result["champions"]:
        print(f"  {champ['group']}: {champ['rule']} ({champ['field']}) champion {champ['champion']}")


if __name__ == "__main__":
    main()
