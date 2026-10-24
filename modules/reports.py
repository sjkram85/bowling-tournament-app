"""PDF, scholarship CSV and archive helpers for closing out a tournament."""

import csv
from datetime import date
import io
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from modules.cde_bls_bridge import build_bls_streams, generate_bls_export
from modules.constants import CENTERS, HOST_CENTERS
from modules.db_state import checkpoint_db, get_connection
from modules.practice import block_if_practice
from modules.divisions import grouped_results
from modules.placement import STATUS_FINAL, STATUS_LADDER_PENDING, STATUS_ROLLOFF_PENDING, event_slug, group_placement
from modules.standings import (
    CUT_SEED,
    compute_standings,
    get_tournament,
    now_iso,
    query,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHUSBC_LOGO_PATH = ASSETS_DIR / "CHUSBC.jpg"
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


def build_smart_scholarship_csv(tournament_id: int, prize_pool: float | None = None) -> str:
    """SMART recipient CSV from the event's real payout setup (see modules/smart_export).

    prize_pool is ignored (kept so old callers still work); amounts are never invented.
    """
    block_if_practice(tournament_id, "exported")
    from modules.smart_export import build_smart_export, recipients_csv
    if get_tournament(tournament_id) is None:
        return ""
    return recipients_csv(build_smart_export(tournament_id))


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def certified_pdf_filename(tournament: dict | None) -> str:
    """Same naming as the Archive Vault download."""
    return f"{event_slug((tournament or {}).get('name'))}_certified_results.pdf"


def rolloff_details(tournament_id: int) -> dict[str, list[dict]]:
    """{group: [{bowler_id, total, decided_by}]} recorded cut roll-off winners."""
    try:
        rows = query("SELECT group_name, bowler_id, total, decided_by FROM cut_rolloffs WHERE tournament_id = ? ORDER BY id",
                     (tournament_id,))
    except Exception:
        return {}
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["group_name"], []).append(dict(r))
    return out


def _finals_section(tournament_id, groups, placements, sec_heading, th_style, td_style, td_center, small_style) -> list:
    """Per-division stepladder matches, champion and cut roll-off notes."""
    ro = rolloff_details(tournament_id)
    out = [PageBreak(), Paragraph("STEPLADDER FINALS & ROLL-OFFS", sec_heading)]
    for g in groups:
        plc = placements[g["group"]]
        names = {r["id"]: r["name"] for r in g["rows"]}
        block = [Paragraph(f"<b>{escape(g['label'])}</b>", td_style), Spacer(1, 3)]
        won = [w for w in ro.get(g["group"], []) if w["bowler_id"] in names]
        if won or g.get("rolloff"):
            tied_all = [r for r in g["rows"] if r.get("tied") and r["total"] == (won[0]["total"] if won else
                        g["rolloff"]["bowlers"][0]["total"])]
            tie_names = ", ".join(escape(r["name"]) for r in tied_all)
            total = tied_all[0]["total"] if tied_all else ""
            if g.get("rolloff"):
                note = (f"Roll-off for the last finals spot: {tie_names} tied at {total}. "
                        f"Roll-off not recorded yet, so these bowlers are not finalists and no awards are shown.")
            else:
                wn = ", ".join(escape(names[w["bowler_id"]]) for w in won)
                losers = [escape(r["name"]) for r in tied_all if r["id"] not in {w["bowler_id"] for w in won}]
                by = ", ".join(sorted({w["decided_by"] for w in won if w.get("decided_by")}))
                note = (f"Roll-off for the last finals spot: {tie_names} tied at {total} after qualifying. "
                        f"<b>{wn}</b> won the roll-off{f' (recorded by {escape(by)})' if by else ''} and advanced to the finals"
                        + (f"; {', '.join(losers)} did not advance and are ranked by qualifying." if losers else "."))
            block += [Paragraph(note, small_style), Spacer(1, 4)]
        ms = plc["matches"]
        if not ms:
            block.append(Paragraph("No stepladder bowled for this division — awards follow qualifying order.", small_style))
        else:
            data = [[Paragraph(f"<b>{h}</b>", th_style) for h in ("Match", "Bowler", "Score", "Bowler", "Score", "Roll-off", "Winner")]]
            for m in ms:
                done = m["status"] == "completed"
                rl = f"{m['rolloff_low']}–{m['rolloff_high']}" if done and m.get("rolloff_low") is not None and m["score_low"] == m["score_high"] else "—"
                data.append([
                    Paragraph(escape(m.get("match_name") or f"Match {m['match_number']}"), td_style),
                    Paragraph(escape(m.get("low_name") or "TBD"), td_style),
                    Paragraph(str(m["score_low"]) if done else "—", td_center),
                    Paragraph(escape(m.get("high_name") or "TBD"), td_style),
                    Paragraph(str(m["score_high"]) if done else "—", td_center),
                    Paragraph(rl, td_center),
                    Paragraph(f"<b>{escape(m.get('winner_name') or '')}</b>" if done else "Pending", td_style),
                ])
            t = Table(data, colWidths=[130, 100, 40, 100, 40, 40, 90])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            block.append(t)
            block.append(Spacer(1, 3))
            if plc["champion"]:
                order = ", ".join(f"{_ordinal(r['place'])} {escape(r['name'])}" for r in plc["finalists"])
                block.append(Paragraph(f'<font color="#15803D"><b>Champion: {escape(plc["champion"])}</b></font> &nbsp;|&nbsp; Finish: {order}', td_style))
            else:
                block.append(Paragraph("Finals not finished yet — no champion or awards shown.", small_style))
        block.append(Spacer(1, 12))
        out.append(KeepTogether(block))
    return out


def build_certified_pdf(tournament_id: int, certified_by: str) -> bytes:
    """Generates an executive-grade, broadcast-standard certified tournament results sheet with CHUSBC branding."""
    block_if_practice(tournament_id, "certified or exported")
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

    prize_template = [120.00, 80.00, 50.00, 30.00]
    small_style = ParagraphStyle("Small", parent=td_style, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#475569"))
    story = []

    tourney_name = tournament["name"] if tournament else "Tournament Results"
    groups = grouped_results(tournament_id)
    placements = {g["group"]: group_placement(tournament_id, g) for g in groups}

    logo_left = None
    if CHUSBC_LOGO_PATH.is_file():
        try:
            logo_left = RLImage(str(CHUSBC_LOGO_PATH), width=58, height=58)
        except Exception:
            logo_left = None

    fmt = f"{tournament.get('squad_format', 'Singles') if tournament else 'Singles'} ({game_count} Games)"
    from modules.event_logos import get_logos, partner_heading
    logos = get_logos(tournament_id)
    partner_name = (tournament or {}).get("partner_name") or ""

    def _logo(data: bytes, max_w: float, max_h: float):
        try:
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(io.BytesIO(data)).getSize()
            sc = min(max_w / iw, max_h / ih)
            return RLImage(io.BytesIO(data), width=iw * sc, height=ih * sc)
        except Exception:
            return None

    partner_logo = _logo(logos["partner"], 120, 48) if logos.get("partner") else None
    event_logo = _logo(logos["event"], 170, 70) if logos.get("event") else None
    # Title lines span the full page width so they are truly centered; logos sit in a symmetric row below.
    title_block = [
        Paragraph("CECIL HARFORD UNITED STATES BOWLING CONGRESS", assoc_style),
        Spacer(1, 2),
        Paragraph(escape(tourney_name).upper(), title_style),
        Spacer(1, 4),
    ]
    center_text_flowables = []
    if event_logo:
        center_text_flowables += [event_logo, Spacer(1, 3)]
    meta_block = [
        Paragraph(f"<b>Official Certified Standing Sheet</b> &nbsp;|&nbsp; Format: <b>{escape(fmt)}</b>", meta_style),
        Paragraph(f"Host Center: <b>{escape(center_name)}</b> ({escape(center_address)})", meta_style),
    ]
    if partner_logo:
        header_cells, header_widths = [logo_left or "", center_text_flowables, partner_logo], [135, 270, 135]
    else:
        header_cells, header_widths = [logo_left or "", center_text_flowables or "", ""], [70, 400, 70]
    if not (partner_logo or event_logo):  # no event logos: classic compact header, logo beside a centered title
        header_cells = [logo_left or "", title_block + meta_block, ""]
        title_block, meta_block = [], []
    t_header = Table([header_cells], colWidths=header_widths)
    t_header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story[0:0] = title_block
    story.append(t_header)
    story += meta_block
    if partner_name:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>{escape(partner_heading(partner_name))}</b>", assoc_style))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1E3A8A"), spaceAfter=10))

    # --- awards by FINAL placement (same logic as the SMART export) ---
    awards: dict[int, float] = {}
    places: dict[int, int] = {}
    if groups:
        from modules.divisions import get_divisions
        from modules.smart_export import place_amounts
        divs = {d["name"]: d for d in get_divisions(tournament)}
        for g in groups:
            plc = placements[g["group"]]
            amounts = place_amounts(divs.get(g["group"].partition(" – ")[0], {}))
            for r in plc["order"]:
                if r.get("finalist") and plc["status"] == STATUS_FINAL:
                    places[r["id"]] = r["place"]
                if plc["awards_ok"] and amounts.get(r["place"]):
                    awards[r["id"]] = amounts[r["place"]]
    else:
        for i, b in enumerate(bowler_records):
            if i < len(prize_template):
                awards[b["id"]] = prize_template[i]

    total_field = len(bowler_records)
    total_scratch_pins = sum(b["total_scratch"] for b in bowler_records)
    youth_ids = {b["id"] for b in bowler_records if b["is_youth"]}
    total_prize_fund = sum(awards.values())
    smart_escrow = sum(v for k, v in awards.items() if k in youth_ids)
    adult_cash = total_prize_fund - smart_escrow
    all_youth = bool(bowler_records) and len(youth_ids) == total_field

    kpis = [("FIELD", f"<b>{total_field}</b> Bowlers"), ("TOTAL PINS", f"<b>{total_scratch_pins:,}</b>"),
            ("PRIZE POOL", f"<b>${total_prize_fund:,.2f}</b>")]
    if adult_cash > 0:
        kpis.append(("ADULT CASH", f"<b>${adult_cash:,.2f}</b>"))
    kpis.append(("USBC SMART SCHOLARSHIPS", f"<b>${smart_escrow:,.2f}</b>"))
    w = 540 / len(kpis)
    t_kpi = Table([[Paragraph(f"<b>{k}</b>", th_style) for k, _ in kpis],
                   [Paragraph(v, td_center) for _, v in kpis]], colWidths=[w] * len(kpis))
    t_kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F1F5F9")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t_kpi)
    story.append(Spacer(1, 14))
    story.append(Paragraph("OFFICIAL QUALIFYING & FINAL STANDINGS", sec_heading))
    if groups:
        story.append(Paragraph("<b>Qual</b> = qualifying rank (T = tie). <b>Final</b> = finish in the stepladder finals. "
                               "Awards follow the final finish.", small_style))
        story.append(Spacer(1, 6))

    headers = [Paragraph(f"<b>{h}</b>", th_style) for h in
               ["Qual", "Final", "Bowler Name", "USBC ID", "Avg / HDCP"]
               + [f"Gm {g}" for g in range(1, game_count + 1)] + ["Scratch", "HDCP Total", "Award", "Type"]]
    game_w = 30
    name_w = max(80, 540 - (26 + 30 + 58 + 50 + 38 + 40 + 46 + 34) - game_w * game_count)
    col_widths = [26, 30, name_w, 58, 50] + [game_w] * game_count + [38, 40, 46, 34]

    if groups:
        rec_by_id = {r["id"]: r for r in bowler_records}
        segments = []
        for g in groups:
            plc = placements[g["group"]]
            qual_rows = sorted((r for r in g["rows"]), key=lambda r: r["rank"])
            title = g["label"] + (f" — top {g['finalists']} to stepladder finals" if g["rows"] else "")
            if plc["status"] == STATUS_ROLLOFF_PENDING:
                title += " (roll-off not recorded yet — no awards shown)"
            elif plc["status"] == STATUS_LADDER_PENDING:
                title += " (finals not finished — no awards shown)"
            segments.append((title, [{**rec_by_id.get(r["id"], r), **{k: r[k] for k in ("grand_total", "total_scratch")},
                                      "_finalist": r.get("finalist"), "_rolloff": r.get("rolloff"),
                                      "_tied": r.get("tied"), "_rank": r.get("rank")} for r in qual_rows]))
    else:
        segments = [("", bowler_records)]

    for seg_title, seg_rows in segments:
        block = []
        if seg_title:
            block += [Paragraph(f"<b>{escape(seg_title)}</b>", td_style), Spacer(1, 4)]
        if groups and not seg_rows:
            block += [Paragraph("No bowlers in this group.", td_style), Spacer(1, 10)]
            story.append(KeepTogether(block))
            continue
        table_data = [headers]
        for idx, b in enumerate(seg_rows, start=1):
            g_scores = scores_by_bowler.get(b["id"], {})
            prize = awards.get(b["id"], 0.0)
            is_y = bool(b["is_youth"])
            routing_txt = ("SMART" if is_y else "Cash") if prize > 0 else "—"
            hdcp_val = b["handicap"] or 0
            avg_hdcp_str = f"{b['entering_avg'] or '—'} / +{hdcp_val}" if hdcp_val > 0 else f"{b['entering_avg'] or '—'} (S)"
            if b.get("_rolloff"):
                final_txt = '<font color="#C2410C"><b>RO</b></font>'
            elif b["id"] in places:
                final_txt = f'<font color="#15803D"><b>{_ordinal(places[b["id"]])}</b></font>'
            elif b.get("_finalist"):
                final_txt = '<font color="#15803D"><b>F</b></font>'
            else:
                final_txt = "—"
            name_txt = f"<b>{escape(b['name'])}</b>" + (" <i>(Y)</i>" if is_y and not all_youth else "")
            row_cells = [
                Paragraph(f"<b>{'T' if b.get('_tied') else ''}{b.get('_rank') or idx}</b>", td_center),
                Paragraph(final_txt, td_center),
                Paragraph(name_txt, td_style),
                Paragraph(escape(str(b["usbc_id"] or "—")), td_center),
                Paragraph(avg_hdcp_str, td_center),
            ]
            for g in range(1, game_count + 1):
                v = g_scores.get(g, 0)
                row_cells.append(Paragraph(str(v) if v > 0 else "—", td_center))
            row_cells.extend([
                Paragraph(str(b["total_scratch"]), td_center),
                Paragraph(f"<b>{b['grand_total']}</b>", td_center),
                Paragraph(f"${prize:,.2f}" if prize > 0 else "—", td_center),
                Paragraph(routing_txt, td_center),
            ])
            table_data.append(row_cells)
        t_standings = Table(table_data, colWidths=col_widths, repeatRows=1)
        t_standings.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        block += [t_standings, Spacer(1, 14)]
        story.append(KeepTogether(block))

    if groups:
        story += _finals_section(tournament_id, groups, placements, sec_heading, th_style, td_style, td_center, small_style)

    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"Certified and verified by: <b>{escape(certified_by)}</b>, Tournament Director &nbsp;|&nbsp; "
            f"Generated on {date.today().strftime('%B %d, %Y')} &nbsp;|&nbsp; Cecil Harford USBC PTCC Desk",
            meta_style,
        )
    )

    doc.build(story)
    return buffer.getvalue()


def freeze_tournament(tournament_id: int) -> None:
    """Lock down tournament as frozen/archived."""
    block_if_practice(tournament_id, "archived")
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE tournaments SET status = 'closed' WHERE id = ?", (tournament_id,))
        checkpoint_db()
    finally:
        conn.close()