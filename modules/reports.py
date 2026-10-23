"""PDF, scholarship CSV and archive helpers for closing out a tournament."""

import csv
import io
import json
import math
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from modules.cde_bls_bridge import build_bls_streams, generate_bls_export
from modules.db_state import checkpoint_db, get_connection
from modules.standings import (
    CUT_SEED,
    MAX_GAME_SCORE,
    compute_standings,
    get_tournament,
    now_iso,
    query,
)

LADDER_PAYOUT_WEIGHTS = [0.40, 0.25, 0.15]


def stepladder_matches(tournament_id: int) -> list[dict]:
    """Retrieve stepladder matches with low/high bowler names, safely handling pending slots."""
    try:
        return query(
            """
            SELECT m.*, 
                   COALESCE(a.name, 'TBD') AS name_a, 
                   COALESCE(b.name, 'TBD') AS name_b, 
                   COALESCE(w.name, 'Pending') AS winner_name
            FROM stepladder_matches m
            LEFT JOIN bowlers a ON a.id = m.bowler_low_id
            LEFT JOIN bowlers b ON b.id = m.bowler_high_id
            LEFT JOIN bowlers w ON w.id = m.winner_id
            WHERE m.tournament_id = ?
            ORDER BY m.match_number
            """,
            (tournament_id,),
        )
    except Exception:
        return []


def ladder_size(standings: list[dict]) -> int:
    return min(CUT_SEED, len(standings))


def final_places(tournament_id: int) -> dict[int, str]:
    """Final finish label per bowler id: ladder finish for seeds, otherwise overall rank."""
    standings = compute_standings(tournament_id)
    size = ladder_size(standings)
    matches = stepladder_matches(tournament_id)
    places = {row["id"]: f"Rank {row['rank']}" for row in standings}
    
    completed_matches = [m for m in matches if m.get("status") == "completed" and m.get("winner_id")]
    if size >= 2 and len(completed_matches) >= 1:
        order = []
        for match in reversed(completed_matches):
            loser = match["bowler_low_id"] if match["winner_id"] == match["bowler_high_id"] else match["bowler_high_id"]
            if loser and loser not in order:
                order.append(loser)
        champion = completed_matches[-1]["winner_id"]
        if champion:
            order.insert(0, champion)
        suffix = {1: "Champion", 2: "2nd place", 3: "3rd place"}
        for place, bowler_id in enumerate(order, start=1):
            if bowler_id:
                places[bowler_id] = suffix.get(place, f"{place}th place") + " (stepladder)"
    return places


def scholarship_amounts(field_size: int, prize_pool: float) -> list[float]:
    """SMART award per place for the top 25% of the field (40/25/15, remainder split)."""
    if field_size < 1 or prize_pool <= 0:
        return []
    award_count = max(1, math.ceil(field_size * 0.25))
    if award_count < 3:
        weights = LADDER_PAYOUT_WEIGHTS[:award_count]
        weights = [w / sum(weights) for w in weights]
    else:
        weights = LADDER_PAYOUT_WEIGHTS + [0.20 / (award_count - 3)] * (award_count - 3)
    amounts = [round(prize_pool * w, 2) for w in weights]
    amounts[-1] = round(prize_pool - sum(amounts[:-1]), 2)
    return amounts


def payout_equity(tournament: dict, standings: list[dict], bowler_id: int) -> dict:
    """Projected and guaranteed SMART award for a bowler."""
    amounts = scholarship_amounts(len(standings), tournament.get("smart_pool") or 0)
    me = next((row for row in standings if row["id"] == bowler_id), None)
    if not me:
        return {"pool": 0, "paid_places": 0, "projected": 0.0, "guaranteed": 0.0, "worst_rank": 0}
        
    floor = me["handicap_total"]
    worst_rank = 1 + sum(
        1
        for other in standings
        if other["id"] != bowler_id
        and other["handicap_total"]
        + (MAX_GAME_SCORE + (other["handicap"] or 0)) * (tournament["game_count"] - other["games_bowled"])
        > floor
    )

    def award(rank: int) -> float:
        return amounts[rank - 1] if rank <= len(amounts) else 0.0

    return {
        "pool": tournament.get("smart_pool") or 0,
        "paid_places": len(amounts),
        "projected": award(me["rank"]),
        "guaranteed": award(worst_rank),
        "worst_rank": worst_rank,
    }


def build_smart_scholarship_csv(tournament_id: int, prize_pool: float) -> str:
    """SMART scholarship awards for the top 25% of the field (40/25/15, remainder split)."""
    tournament = get_tournament(tournament_id)
    standings = compute_standings(tournament_id)
    if tournament is None or not standings:
        return ""
    amounts = scholarship_amounts(len(standings), prize_pool)
    if not amounts:
        return ""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["USBC ID", "Bowler Name", "SMART Account #", "Award Amount ($)", "Tournament Name", "Date"])
    for row, amount in zip(standings, amounts):
        writer.writerow([row["usbc_id"] or "", row["name"], "", f"{amount:.2f}", tournament["name"], date.today().isoformat()])
    return output.getvalue()


def build_certified_pdf(tournament_id: int, certified_by: str) -> bytes:
    """Certified results sheet: final standings, stepladder results and TD certification."""
    tournament = get_tournament(tournament_id)
    standings = compute_standings(tournament_id)
    matches = stepladder_matches(tournament_id)
    places = final_places(tournament_id)
    styles = getSampleStyleSheet()

    buffer = io.BytesIO()
    doc_title = f"{tournament['name'] if tournament else 'Tournament'} Certified Results"
    document = SimpleDocTemplate(buffer, pagesize=letter, title=doc_title)
    
    t_name = tournament["name"] if tournament else "Tournament"
    t_center = tournament.get("host_center", "Center") if tournament else "Center"
    t_format = tournament.get("squad_format", "Singles") if tournament else "Singles"
    t_games = tournament.get("game_count", 3) if tournament else 3

    story = [
        Paragraph(escape(t_name), styles["Title"]),
        Paragraph(
            f"Host center: {escape(t_center)} &nbsp;|&nbsp; "
            f"{escape(t_format)} &nbsp;|&nbsp; {t_games} games &nbsp;|&nbsp; "
            f"{date.today().isoformat()}",
            styles["Normal"],
        ),
        Spacer(1, 14),
        Paragraph("Final Standings", styles["Heading2"]),
    ]
    
    table_rows = [["Rank", "Bowler", "Scratch", "Hdcp", "Total", "Finish"]]
    for row in standings:
        table_rows.append(
            [
                row["rank"],
                row["name"],
                row["scratch_total"],
                row["handicap"] or 0,
                row["handicap_total"],
                places.get(row["id"], ""),
            ]
        )
    table = Table(table_rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ]
        )
    )
    story.append(table)

    completed_matches = [m for m in matches if m.get("status") == "completed"]
    if completed_matches:
        story += [Spacer(1, 14), Paragraph("Stepladder Finals", styles["Heading2"])]
        for match in completed_matches:
            story.append(
                Paragraph(
                    f"Match {match.get('match_number')}: {escape(match.get('name_a', 'TBD'))} {match.get('score_low', 0)} vs "
                    f"{escape(match.get('name_b', 'TBD'))} {match.get('score_high', 0)} - Winner: {escape(match.get('winner_name', 'TBD'))}",
                    styles["Normal"],
                )
            )

    story += [
        Spacer(1, 28),
        Paragraph(
            f"Certified by: {escape(certified_by)} &nbsp;&nbsp; Date: {date.today().isoformat()}",
            styles["Normal"],
        ),
        Paragraph("Tournament Director signature: ____________________________", styles["Normal"]),
    ]
    document.build(story)
    return buffer.getvalue()


def archive_snapshot(tournament_id: int) -> dict:
    scores = query("SELECT * FROM scores WHERE tournament_id = ?", (tournament_id,))
    snapshot = {
        "tournament": get_tournament(tournament_id),
        "bowlers": query("SELECT * FROM bowlers WHERE tournament_id = ?", (tournament_id,)),
        "scores": scores,
        "teams": query("SELECT * FROM tournament_teams WHERE tournament_id = ?", (tournament_id,)),
        "mystery_doubles_pairs": query(
            "SELECT * FROM mystery_doubles_pairs WHERE tournament_id = ?", (tournament_id,)
        ),
        "tiebreak_roll_offs": query("SELECT * FROM tiebreak_roll_offs WHERE tournament_id = ?", (tournament_id,)),
        "stepladder_matches": query("SELECT * FROM stepladder_matches WHERE tournament_id = ?", (tournament_id,)),
        "final_standings": [
            {k: v for k, v in row.items() if k not in ("game_scores", "tiebreak_key")}
            for row in compute_standings(tournament_id)
        ],
    }
    return snapshot


def freeze_tournament(tournament_id: int, archived_by: str, pdf: bytes, smart_csv: str) -> None:
    """Write the read-only archive row and mark the tournament completed, atomically."""
    export = build_bls_streams(tournament_id)
    snapshot = json.dumps(archive_snapshot(tournament_id), default=str)
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO tournament_archives (tournament_id, archived_at, archived_by, snapshot_json, "
                "certified_pdf, smart_csv, bls_bits_csv, bls_autoscoring_dat) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tournament_id,
                    now_iso(),
                    archived_by,
                    snapshot,
                    pdf,
                    smart_csv,
                    export["bits_csv"],
                    generate_bls_export(tournament_id),
                ),
            )
            connection.execute("UPDATE tournaments SET status = 'completed' WHERE id = ?", (tournament_id,))
    finally:
        connection.close()
    checkpoint_db()


def get_archive(tournament_id: int) -> dict | None:
    rows = query("SELECT * FROM tournament_archives WHERE tournament_id = ?", (tournament_id,))
    return rows[0] if rows else None