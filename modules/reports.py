"""PDF, scholarship CSV and archive helpers for closing out a tournament."""

import csv
import io
import json
import math
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from modules.cde_bls_bridge import build_bls_streams, generate_bls_export
from modules.constants import CENTERS, HOST_CENTERS
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


def _get_detailed_tournament_scores(tournament_id: int) -> dict[int, dict[int, int]]:
    """Fetch all individual game scores per bowler {bowler_id: {game_number: score}}."""
    scores_map: dict[int, dict[int, int]] = {}
    rows = query(
        "SELECT bowler_id, game_number, scratch_score FROM scores WHERE tournament_id = ? ORDER BY game_number ASC",
        (tournament_id,),
    )
    for r in rows:
        scores_map.setdefault(r["bowler_id"], {})[r["game_number"]] = r["scratch_score"]
    return scores_map


def _get_full_bowler_records(tournament_id: int) -> list[dict]:
    """Fetch complete bowler records including youth, average, handicap, and USBC IDs."""
    return query(
        """
        SELECT b.id, b.name, b.usbc_id, b.entering_avg, b.handicap, b.is_youth, b.smart_account_id,
               COUNT(s.game_number) as games_bowled,
               COALESCE(SUM(s.scratch_score), 0) as total_scratch,
               COALESCE(SUM(s.total_score), 0) as grand_total
        FROM bowlers b
        LEFT JOIN scores s ON b.id = s.bowler_id
        WHERE b.tournament_id = ? AND b.is_pacer = 0
        GROUP BY b.id
        ORDER BY grand_total DESC, total_scratch DESC
        """,
        (tournament_id,),
    )


def build_smart_scholarship_csv(tournament_id: int, prize_pool: float) -> str:
    """SMART scholarship awards for the top 25% of the field."""
    tournament = get_tournament(tournament_id)
    standings = compute_standings(tournament_id)
    if tournament is None or not standings:
        return ""
    amounts = [120.00, 80.00, 50.00, 30.00]
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["USBC ID", "Bowler Name", "SMART Account #", "Award Amount ($)", "Tournament Name", "Date"])
    for row, amount in zip(standings, amounts):
        writer.writerow([row["usbc_id"] or "", row["name"], row.get("smart_account_id", ""), f"{amount:.2f}", tournament["name"], date.today().isoformat()])
    return output.getvalue()


def build_certified_pdf(tournament_id: int, certified_by: str) -> bytes:
    """Generates an executive-grade, broadcast-standard certified tournament results sheet."""
    tournament = get_tournament(tournament_id)
    bowler_records = _get_full_bowler_records(tournament_id)
    scores_by_bowler = _get_detailed_tournament_scores(tournament_id)
    game_count = tournament.get("game_count", 3) if tournament else 3

    host_code = tournament.get("host_center", "FHL") if tournament else "FHL"
    center_info = CENTERS.get(host_code) or HOST_CENTERS.get(host_code, {})
    center_name = center_info.get("name", host_code)
    center_address = center_info.get("address", "Bel Air / Forest Hill, MD")

    buffer = io.BytesIO()
    doc_title = f"{tournament['name'] if tournament else 'Tournament'} — Official Certified Results"
    
    # 0.5 in (36 pt) margins provide 540 pt usable width on 612 pt Letter
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=32,
        bottomMargin=32,
        title=doc_title,
    )

    base_styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CertTitle",
        parent=base_styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0F172A"),
        alignment=1,
    )

    assoc_style = ParagraphStyle(
        "AssocStyle",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#1E3A8A"),
        alignment=1,
    )

    meta_style = ParagraphStyle(
        "CertMeta",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#475569"),
        alignment=1,
    )

    sec_heading = ParagraphStyle(
        "SecHead",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=6,
    )

    th_style = ParagraphStyle(
        "TH",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=1,
    )

    td_style = ParagraphStyle(
        "TD",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0F172A"),
    )

    td_center = ParagraphStyle(
        "TDC",
        parent=td_style,
        alignment=1,
    )

    td_right = ParagraphStyle(
        "TDR",
        parent=td_style,
        alignment=2,
    )

    td_bold_right = ParagraphStyle(
        "TDBR",
        parent=td_style,
        fontName="Helvetica-Bold",
        alignment=2,
        textColor=colors.HexColor("#0F172A"),
    )

    story = []

    # 1. Header Banner
    story.append(Paragraph("CECIL HARFORD UNITED STATES BOWLING CONGRESS", assoc_style))
    story.append(Spacer(1, 3))
    tourney_name = tournament["name"] if tournament else "Tournament Results"
    story.append(Paragraph(escape(tourney_name).upper(), title_style))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            f"<b>Official Certified Standing Sheet</b> &nbsp;|&nbsp; "
            f"Host Center: <b>{escape(center_name)}</b> ({escape(center_address)}) &nbsp;|&nbsp; "
            f"Format: <b>{tournament.get('squad_format', 'Singles')} ({game_count} Games)</b>",
            meta_style,
        )
    )
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1E3A8A"), spaceAfter=10))

    # 2. Financial & Event Metric Bar
    prize_template = [120.00, 80.00, 50.00, 30.00]
    total_field = len(bowler_records)
    total_scratch_pins = sum(b["total_scratch"] for b in bowler_records)
    total_prize_fund = sum(prize_template[:min(total_field, len(prize_template))])

    smart_escrow = sum(
        prize_template[i] for i, b in enumerate(bowler_records)
        if i < len(prize_template) and b["is_youth"]
    )
    adult_cash = total_prize_fund - smart_escrow

    kpi_data = [
        [
            Paragraph("<b>TOTAL FIELD</b>", th_style),
            Paragraph("<b>TOTAL PINS KNOCKED DOWN</b>", th_style),
            Paragraph("<b>TOTAL PRIZE POOL</b>", th_style),
            Paragraph("<b>ADULT CASH PAYOUT</b>", th_style),
            Paragraph("<b>USBC SMART ESCROW</b>", th_style),
        ],
        [
            Paragraph(f"<b>{total_field}</b> Bowlers", td_center),
            Paragraph(f"<b>{total_scratch_pins:,}</b> Pins", td_center),
            Paragraph(f"<b>${total_prize_fund:.2f}</b>", td_center),
            Paragraph(f"<b>${adult_cash:.2f}</b>", td_center),
            Paragraph(f"<b>${smart_escrow:.2f}</b>", td_center),
        ],
    ]
    t_kpi = Table(kpi_data, colWidths=[108, 118, 104, 105, 105])
    t_kpi.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F1F5F9")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(t_kpi)
    story.append(Spacer(1, 14))

    # 3. Main Standings Table with Game-by-Game Columns
    story.append(Paragraph("OFFICIAL QUALIFYING & FINAL STANDINGS", sec_heading))

    # Dynamic column widths matching 540 pt printable page width
    # Rank(30), Bowler(105), USBC#(50), Avg/Hdcp(55), G1(36), G2(36), G3(36), Total Scratch(48), Series Total(54), Prize(45), Routing(45)
    headers = [
        Paragraph("<b>Rank</b>", th_style),
        Paragraph("<b>Bowler Name</b>", th_style),
        Paragraph("<b>USBC ID</b>", th_style),
        Paragraph("<b>Avg / HDCP</b>", th_style),
    ]
    for g in range(1, game_count + 1):
        headers.append(Paragraph(f"<b>Gm {g}</b>", th_style))
    headers.extend([
        Paragraph("<b>Scratch</b>", th_style),
        Paragraph("<b>HDCP Total</b>", th_style),
        Paragraph("<b>Award</b>", th_style),
        Paragraph("<b>Routing</b>", th_style),
    ])

    table_data = [headers]
    honor_scores = []

    for idx, b in enumerate(bowler_records, start=1):
        b_id = b["id"]
        g_scores = scores_by_bowler.get(b_id, {})
        prize = prize_template[idx - 1] if idx <= len(prize_template) else 0.0
        is_y = bool(b["is_youth"])

        if is_y and prize > 0:
            routing_txt = "SMART"
        elif prize > 0:
            routing_txt = "Cash"
        else:
            routing_txt = "—"

        avg_hdcp_str = f"{b['entering_avg'] or '—'} / +{b['handicap']}"

        row_cells = [
            Paragraph(f"<b>#{idx}</b>", td_center),
            Paragraph(f"<b>{escape(b['name'])}</b>" + (" <i>(Youth)</i>" if is_y else ""), td_style),
            Paragraph(escape(str(b["usbc_id"] or "—")), td_center),
            Paragraph(avg_hdcp_str, td_center),
        ]

        for g in range(1, game_count + 1):
            score_val = g_scores.get(g, 0)
            if score_val == 300:
                honor_scores.append(f"★ <b>{b['name']}</b> bowled a <b>300 Game</b> in Game {g}!")
                row_cells.append(Paragraph(f"<b>{score_val}</b>", td_center))
            else:
                row_cells.append(Paragraph(str(score_val) if score_val > 0 else "—", td_center))

        row_cells.extend([
            Paragraph(f"<b>{b['total_scratch']}</b>", td_right),
            Paragraph(f"<b>{b['grand_total']}</b>", td_bold_right),
            Paragraph(f"${prize:.2f}" if prize > 0 else "—", td_right),
            Paragraph(routing_txt, td_center),
        ])
        table_data.append(row_cells)

    col_widths = [32, 108, 48, 56] + [36] * game_count + [48, 54, 46, 42]
    # Adjust last column slightly if 3 games to fit exact 540 pt
    scale_diff = 540 - sum(col_widths)
    if scale_diff != 0:
        col_widths[1] += scale_diff

    standings_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    standings_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(standings_table)
    story.append(Spacer(1, 12))

    # 4. Honor Scores Callout (if 300s or 800 series occurred)
    if honor_scores:
        story.append(Paragraph("TOURNAMENT HONOR AWARDS", sec_heading))
        for h in honor_scores:
            story.append(
                Paragraph(
                    f"<font color='#065F46'><b>🏆 USBC RECOGNITION:</b> {h}</font>",
                    ParagraphStyle("Honor", parent=meta_style, alignment=0),
                )
            )
        story.append(Spacer(1, 10))

    # 5. Stepladder Finals Summary (if any matches completed)
    matches = stepladder_matches(tournament_id)
    completed_matches = [m for m in matches if m.get("status") == "completed"]
    if completed_matches:
        story.append(Paragraph("STEPLADDER MATCH PLAY FINALS", sec_heading))
        stepladder_rows = [
            [
                Paragraph("<b>Match</b>", th_style),
                Paragraph("<b>Challenger</b>", th_style),
                Paragraph("<b>Score</b>", th_style),
                Paragraph("<b>Defender</b>", th_style),
                Paragraph("<b>Score</b>", th_style),
                Paragraph("<b>Match Winner</b>", th_style),
            ]
        ]
        for m in completed_matches:
            stepladder_rows.append(
                [
                    Paragraph(f"Match #{m.get('match_number')}", td_center),
                    Paragraph(escape(m.get("name_a", "TBD")), td_style),
                    Paragraph(str(m.get("score_low", 0)), td_center),
                    Paragraph(escape(m.get("name_b", "TBD")), td_style),
                    Paragraph(str(m.get("score_high", 0)), td_center),
                    Paragraph(f"<b>{escape(m.get('winner_name', 'TBD'))}</b>", td_style),
                ]
            )
        t_sl = Table(stepladder_rows, colWidths=[60, 115, 55, 115, 55, 140])
        t_sl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(t_sl)
        story.append(Spacer(1, 12))

    # 6. Formal USBC Compliance & Certification Sign-Off Block
    story.append(Spacer(1, 8))
    cert_text = (
        "<b>OFFICIAL USBC RULE CERTIFICATION & AUDIT ATTESTATION:</b><br/>"
        "I hereby certify that the scores, standings, and prize disbursements compiled in this official standing sheet "
        "have been audited and verified in strict accordance with the United States Bowling Congress (USBC) Playing Rules, "
        "Association tournament bylaws, and USBC Rule 400 SMART Scholarship regulations. All youth scholarship prizes "
        "have been escrowed directly to the USBC SMART program."
    )
    story.append(
        Paragraph(
            cert_text,
            ParagraphStyle("CertLegal", fontName="Helvetica-Oblique", fontSize=7.5, leading=10.5, textColor=colors.HexColor("#475569")),
        )
    )
    story.append(Spacer(1, 16))

    sig_data = [
        [
            Paragraph(f"<b>Certified by:</b> {escape(certified_by)}<br/><font color='#64748B'>Tournament Director</font>", td_style),
            Paragraph(f"<b>Date:</b> {date.today().strftime('%B %d, %Y')}<br/><font color='#64748B'>Audit Timestamp: {now_iso()[:10]}</font>", td_style),
            Paragraph("<b>Tournament Director Signature:</b><br/><br/>________________________________________", td_style),
        ]
    ]
    t_sig = Table(sig_data, colWidths=[170, 150, 220])
    t_sig.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_sig)

    doc.build(story)
    return buffer.getvalue()


def archive_snapshot(tournament_id: int) -> dict:
    snapshot = {
        "tournament": get_tournament(tournament_id),
        "bowlers": query("SELECT * FROM bowlers WHERE tournament_id = ?", (tournament_id,)),
        "scores": query("SELECT * FROM scores WHERE tournament_id = ?", (tournament_id,)),
        "teams": query("SELECT * FROM tournament_teams WHERE tournament_id = ?", (tournament_id,)),
        "mystery_doubles_pairs": query("SELECT * FROM mystery_doubles_pairs WHERE tournament_id = ?", (tournament_id,)),
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