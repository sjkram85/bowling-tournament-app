import os
import io
import time
import math
import json
import base64
import random
import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd
import qrcode
from PIL import Image
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# ReportLab components for championship summaries
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Image as RLImage, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Document builders
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ---------------------------------------------------------
# ASSET RESOLUTION (CASE-INSENSITIVE & RECURSIVE)
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

def find_logo_path(target_stem: str = "logo_chusbc") -> str | None:
    search_dirs = [BASE_DIR, BASE_DIR / "assets", Path.cwd(), Path.cwd() / "assets"]
    extensions = [".png", ".PNG", ".jpg", ".jpeg", ".webp"]
    
    # Direct candidate search
    for d in search_dirs:
        if d.exists():
            for ext in extensions:
                p = d / f"{target_stem}{ext}"
                if p.is_file():
                    return str(p)
                    
    # Recursive case-insensitive walk
    for root_dir in [BASE_DIR, Path.cwd()]:
        if root_dir.exists():
            for path in root_dir.rglob("*"):
                if path.is_file() and target_stem.lower() in path.stem.lower() and path.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
                    return str(path)
    return None

_chusbc_found = find_logo_path("logo_chusbc") or find_logo_path("chusbc")
LOGO_CHUSBC_PATH = _chusbc_found if _chusbc_found else str(BASE_DIR / "assets" / "logo_chusbc.png")
HAS_CHUSBC_LOGO = _chusbc_found is not None

_fh_found = find_logo_path("logo_forest_hill") or find_logo_path("forest_hill")
LOGO_FOREST_HILL_PATH = _fh_found if _fh_found else str(BASE_DIR / "assets" / "logo_forest_hill.png")
HAS_FOREST_HILL_LOGO = _fh_found is not None

KIOSK_FILE_PATH = "kiosk_state.json"
SQLITE_DB_PATH = "prism_operational.db"

ph = PasswordHasher()

def hash_secret(secret_text: str) -> str:
    return ph.hash(secret_text)

def verify_secret(hashed_value: str, plain_text: str) -> tuple[bool, bool]:
    try:
        ph.verify(hashed_value, plain_text)
        return True, ph.check_needs_rehash(hashed_value)
    except (VerifyMismatchError, Exception):
        return False, False

def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_sqlite_tables():
    conn = get_sqlite_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS live_roster (
            usbc_id TEXT PRIMARY KEY,
            bowler TEXT NOT NULL,
            average INTEGER DEFAULT 200,
            starting_lane INTEGER DEFAULT 1,
            division TEXT DEFAULT 'Open',
            team_name TEXT DEFAULT 'Singles',
            game_1 INTEGER DEFAULT 0,
            game_2 INTEGER DEFAULT 0,
            game_3 INTEGER DEFAULT 0,
            game_4 INTEGER DEFAULT 0,
            game_5 INTEGER DEFAULT 0,
            game_6 INTEGER DEFAULT 0,
            paid INTEGER DEFAULT 0,
            checked_in INTEGER DEFAULT 0,
            is_sub INTEGER DEFAULT 0,
            subbing_for TEXT,
            g1_verified_by TEXT, g1_verified_at TEXT,
            g2_verified_by TEXT, g2_verified_at TEXT,
            g3_verified_by TEXT, g3_verified_at TEXT,
            g4_verified_by TEXT, g4_verified_at TEXT,
            g5_verified_by TEXT, g5_verified_at TEXT,
            g6_verified_by TEXT, g6_verified_at TEXT,
            last_updated_by TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # Defensive schema migration for existing databases
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(live_roster)")
    existing_cols = [row[1] for row in cursor.fetchall()]
    for g in [4, 5, 6]:
        if f"game_{g}" not in existing_cols:
            cursor.execute(f"ALTER TABLE live_roster ADD COLUMN game_{g} INTEGER DEFAULT 0")
        if f"g{g}_verified_by" not in existing_cols:
            cursor.execute(f"ALTER TABLE live_roster ADD COLUMN g{g}_verified_by TEXT")
        if f"g{g}_verified_at" not in existing_cols:
            cursor.execute(f"ALTER TABLE live_roster ADD COLUMN g{g}_verified_at TEXT")
    conn.commit()
    conn.close()

def read_kiosk_state() -> dict:
    if os.path.exists(KIOSK_FILE_PATH):
        try:
            with open(KIOSK_FILE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def write_kiosk_state(data: dict):
    with open(KIOSK_FILE_PATH, "w") as f:
        json.dump(data, f)

def clear_kiosk_state():
    if os.path.exists(KIOSK_FILE_PATH):
        try:
            os.remove(KIOSK_FILE_PATH)
        except Exception:
            pass

def generate_qr_image(url_string: str) -> io.BytesIO:
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(url_string)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

def notify_admin_new_registration(username: str, name: str, email: str, timestamp: str):
    pass

def notify_user_account_approved(email: str, name: str, username: str):
    pass

def parse_active_pairs(lane_range_str: str, max_lanes: int = 40) -> list[tuple[int, int]]:
    pairs = []
    clean_str = lane_range_str.replace(" ", "")
    segments = clean_str.split(",")
    valid_lanes = set()
    for seg in segments:
        if "-" in seg:
            try:
                start, end = map(int, seg.split("-"))
                for l in range(start, end + 1):
                    if 1 <= l <= max_lanes:
                        valid_lanes.add(l)
            except Exception:
                continue
        elif seg.isdigit():
            l = int(seg)
            if 1 <= l <= max_lanes:
                valid_lanes.add(l)

    for odd in range(1, max_lanes + 1, 2):
        even = odd + 1
        if odd in valid_lanes or even in valid_lanes:
            pairs.append((odd, even))
    return sorted(pairs, key=lambda p: p[0])

def get_bowler_lane_for_game(starting_lane: int, game_num: int, movement_rule: str, max_lanes: int = 40) -> int:
    if game_num <= 1 or "Stay on Pair" in movement_rule:
        return starting_lane

    offset = 0
    if "Move Right 1 Pair" in movement_rule:
        offset = 2 * (game_num - 1)
    elif "Move Right 2 Pairs" in movement_rule:
        offset = 4 * (game_num - 1)
    elif "Move Left 1 Pair" in movement_rule:
        offset = -2 * (game_num - 1)

    new_lane = starting_lane + offset
    while new_lane > max_lanes:
        new_lane -= max_lanes
    while new_lane < 1:
        new_lane += max_lanes
    return new_lane

def auto_assign_lanes(roster_df: pd.DataFrame, pairs: list[tuple[int, int]], max_per_pair: int = 5, shuffle: bool = True, group_by_team: bool = True) -> tuple[pd.DataFrame, str]:
    if roster_df.empty:
        return roster_df, "Roster is empty."
    if not pairs:
        return roster_df, "No valid lane pairs specified."

    df = roster_df.copy()
    total_slots = len(pairs) * max_per_pair
    if len(df) > total_slots:
        return df, f"Field size ({len(df)}) exceeds total lane capacity ({total_slots} on {len(pairs)} pairs)."

    pair_allocations = {p: [] for p in pairs}
    pair_cycle = list(pairs)
    if shuffle and not group_by_team:
        random.shuffle(pair_cycle)

    if group_by_team and "Team_Name" in df.columns:
        teams = df["Team_Name"].unique().tolist()
        if shuffle:
            random.shuffle(teams)
        p_idx = 0
        for team in teams:
            t_bowlers = df[df["Team_Name"] == team].to_dict(orient="records")
            placed = False
            for _ in range(len(pairs)):
                target_pair = pair_cycle[p_idx % len(pair_cycle)]
                if len(pair_allocations[target_pair]) + len(t_bowlers) <= max_per_pair:
                    for b in t_bowlers:
                        lead_lane = target_pair[0] if len(pair_allocations[target_pair]) % 2 == 0 else target_pair[1]
                        b["Starting Lane"] = lead_lane
                        pair_allocations[target_pair].append(b)
                    placed = True
                    p_idx += 1
                    break
                p_idx += 1
            if not placed:
                target_pair = min(pair_allocations, key=lambda k: len(pair_allocations[k]))
                for b in t_bowlers:
                    lead_lane = target_pair[0] if len(pair_allocations[target_pair]) % 2 == 0 else target_pair[1]
                    b["Starting Lane"] = lead_lane
                    pair_allocations[target_pair].append(b)
    else:
        bowler_list = df.to_dict(orient="records")
        if shuffle:
            random.shuffle(bowler_list)
        for idx, b in enumerate(bowler_list):
            target_pair = pair_cycle[idx % len(pair_cycle)]
            lead_lane = target_pair[0] if len(pair_allocations[target_pair]) % 2 == 0 else target_pair[1]
            b["Starting Lane"] = lead_lane
            pair_allocations[target_pair].append(b)

    assigned_records = []
    for p in pairs:
        assigned_records.extend(pair_allocations[p])

    return pd.DataFrame(assigned_records), ""

def calculate_handicap(entering_average: int, base: int = 220, percentage: float = 0.90) -> int:
    if entering_average >= base:
        return 0
    return int(math.floor((base - entering_average) * percentage))

def compile_standings(roster_df: pd.DataFrame, config: dict = None) -> pd.DataFrame:
    if roster_df.empty:
        return pd.DataFrame()
    df = roster_df.copy()
    num_games = int(config.get("games_count", 3)) if config else 3
    game_cols = [f"Game {i}" for i in range(1, num_games + 1)]

    for col in game_cols + ["Average"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    base = int(config.get("hdcp_base", 220)) if config else 220
    pct = float(config.get("hdcp_pct", 0.90)) if config else 0.90

    df["HDCP_Per_Game"] = df["Average"].apply(lambda a: calculate_handicap(a, base=base, percentage=pct))
    df["Total_HDCP"] = df["HDCP_Per_Game"] * num_games
    df["Scratch_Total"] = df[game_cols].sum(axis=1)
    df["Grand_Total"] = df["Scratch_Total"] + df["Total_HDCP"]
    df["High_Scratch_Game"] = df[game_cols].max(axis=1)

    df = df.sort_values(by=["Grand_Total", "Scratch_Total"], ascending=[False, False]).reset_index(drop=True)
    df.index += 1
    df.index.name = "Rank"
    return df

def compile_all_events_leaderboard(roster_df: pd.DataFrame, config: dict = None) -> pd.DataFrame:
    if roster_df.empty:
        return pd.DataFrame()
    df = roster_df.copy()
    num_games = int(config.get("games_count", 3)) if config else 3
    game_cols = [f"Game {i}" for i in range(1, num_games + 1)]

    for col in game_cols + ["Average"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    base = int(config.get("hdcp_base", 220)) if config else 220
    pct = float(config.get("hdcp_pct", 0.90)) if config else 0.90

    df["HDCP_Per_Game"] = df["Average"].apply(lambda a: calculate_handicap(a, base=base, percentage=pct))
    group_col = "USBC ID" if "USBC ID" in df.columns else "Bowler"

    agg_rules = {
        "Average": "max",
        "HDCP_Per_Game": "max",
        "Team_Name": lambda x: ", ".join(set([str(v) for v in x if v and str(v) != "Singles"])) or "Singles",
        "Division": "first"
    }
    for gc in game_cols:
        agg_rules[gc] = "sum"

    grouped = df.groupby(group_col).agg(agg_rules).reset_index()

    if group_col == "USBC ID":
        name_map = df.drop_duplicates(subset=["USBC ID"]).set_index("USBC ID")["Bowler"].to_dict()
        grouped["Bowler"] = grouped["USBC ID"].map(name_map)

    grouped["Total_Games_Bowled"] = df.groupby(group_col).apply(
        lambda g: sum((g[gc] > 0).sum() for gc in game_cols)
    ).values

    grouped["Total_HDCP"] = grouped["HDCP_Per_Game"] * grouped["Total_Games_Bowled"]
    grouped["Scratch_Series"] = grouped[game_cols].sum(axis=1)
    grouped["Grand_Total"] = grouped["Scratch_Series"] + grouped["Total_HDCP"]

    grouped = grouped.sort_values(by=["Grand_Total", "Scratch_Series"], ascending=[False, False]).reset_index(drop=True)
    grouped.index += 1
    grouped.index.name = "Rank"
    return grouped

def calculate_financial_summary(roster_df: pd.DataFrame, config: dict) -> dict:
    paid_count = int(roster_df["Paid"].sum()) if ("Paid" in roster_df.columns and not roster_df.empty) else len(roster_df)
    entry_fee = float(config.get("entry_fee", 50.0))
    lineage_rate = float(config.get("lineage_rate", 15.0))
    expenses_rate = float(config.get("expenses_rate", 5.0))

    gross = paid_count * entry_fee
    total_lineage = paid_count * lineage_rate
    total_expenses = paid_count * expenses_rate
    net_prize = max(0.0, gross - total_lineage - total_expenses)

    return {
        "paid_count": paid_count,
        "gross_revenue": gross,
        "total_lineage": total_lineage,
        "total_expenses": total_expenses,
        "net_prize_fund": net_prize
    }

def generate_smart_scholarship_csv(roster_df: pd.DataFrame, prize_pool: float, tournament_name: str) -> str:
    out = io.StringIO()
    out.write("USBC ID,Bowler,Scholarship_Amount,Program,Event\n")
    if not roster_df.empty:
        top_award = prize_pool * 0.50
        second_award = prize_pool * 0.30
        third_award = prize_pool * 0.20
        awards = [top_award, second_award, third_award]
        for idx, row in roster_df.head(3).iterrows():
            amt = awards[idx] if idx < len(awards) else 0.0
            out.write(f"{row.get('USBC ID', 'N/A')},{row.get('Bowler', 'Youth')},{amt:.2f},USBC SMART,{tournament_name}\n")
    return out.getvalue()

def resolve_bracket_match(usbc1: str, usbc2: str, game_col: str, bracket_type: str, roster_df: pd.DataFrame):
    def get_info(uid):
        m = roster_df[roster_df["USBC ID"].astype(str) == str(uid)]
        if m.empty:
            return "Vacant", 0
        b_name = m.iloc[0]["Bowler"]
        score = int(m.iloc[0].get(game_col, 0))
        if bracket_type == "Handicap":
            avg = int(m.iloc[0].get("Average", 200))
            hdcp = calculate_handicap(avg)
            score += hdcp
        return b_name, score

    b1_name, s1 = get_info(usbc1)
    b2_name, s2 = get_info(usbc2)
    winner_uid = usbc1 if s1 >= s2 else usbc2
    return b1_name, s1, b2_name, s2, winner_uid

def export_lane_assignments_pdf(roster_df: pd.DataFrame, config: dict, td_name: str = "TD Staff") -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title = ParagraphStyle("LaneTitle", parent=styles["Heading1"], fontSize=14, leading=16, textColor=colors.HexColor("#0f172a"))
    h_text = f"<b>Cecil Harford USBC — Lane Assignments</b><br/><font size='8' color='#475569'>Event: {config.get('name')} | Center: {config.get('center')} | TD: {td_name}</font>"
    story.append(Paragraph(h_text, title))
    story.append(Spacer(1, 10))

    t_data = [["Lane", "Bowler Name", "USBC ID", "Average", "Division", "Team / Group"]]
    sorted_df = roster_df.sort_values(by=["Starting Lane", "Bowler"])
    for _, r in sorted_df.iterrows():
        t_data.append([
            str(r.get("Starting Lane", 1)), str(r.get("Bowler", "")), str(r.get("USBC ID", "-")),
            str(r.get("Average", 200)), str(r.get("Division", "Open")), str(r.get("Team_Name", "Singles"))
        ])

    table = Table(t_data, colWidths=[36, 170, 70, 48, 80, 136])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def export_standings_pdf(standings_df: pd.DataFrame, config: dict, td_name: str = "TD Staff") -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title = ParagraphStyle("StdTitle", parent=styles["Heading1"], fontSize=14, leading=16, textColor=colors.HexColor("#0f172a"))
    h_text = f"<b>Cecil Harford USBC — Official Standings</b><br/><font size='8' color='#475569'>Event: {config.get('name')} | Center: {config.get('center')} | Date: {datetime.now().strftime('%m/%d/%Y %H:%M')}</font>"
    story.append(Paragraph(h_text, title))
    story.append(Spacer(1, 10))

    num_games = int(config.get("games_count", 3))
    game_headers = [f"G{i}" for i in range(1, num_games + 1)]
    header_row = ["Pos", "Bowler Name", "Lane", "Avg"] + game_headers + ["Scratch", "HDCP", "Total"]
    t_data = [header_row]

    for rank, r in standings_df.reset_index().head(30).iterrows():
        row = [str(r.get("Rank", rank + 1)), str(r.get("Bowler")), str(r.get("Starting Lane", 1)), str(r.get("Average"))]
        for i in range(1, num_games + 1):
            row.append(str(r.get(f"Game {i}", 0)))
        row.extend([str(r.get("Scratch_Total", 0)), str(r.get("Total_HDCP", 0)), str(r.get("Grand_Total"))])
        t_data.append(row)

    table = Table(t_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def export_tournament_summary_pdf(standings_df: pd.DataFrame, config: dict, champion_name: str, stepladder_results: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle("SummaryTitle", parent=styles["Heading1"], fontSize=15, leading=18, textColor=colors.HexColor("#0f172a"), spaceAfter=2)
    h2_style = ParagraphStyle("SummaryH2", parent=styles["Heading2"], fontSize=11, leading=14, textColor=colors.HexColor("#0284c7"), spaceBefore=8, spaceAfter=4)

    header_text = f"""
    <b>Cecil Harford USBC — Official Tournament Summary & Champion Report</b><br/>
    <font size="8" color="#475569">
    Event: {config.get('name')} | Host Center: {config.get('center')} | Division: {config.get('division')}<br/>
    Official Champion: <b>{champion_name}</b> | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')}
    </font>
    """

    logo_path = LOGO_FOREST_HILL_PATH if ("forest hill" in str(config.get("center", "")).lower() and HAS_FOREST_HILL_LOGO) else LOGO_CHUSBC_PATH
    if os.path.exists(logo_path):
        logo_img = RLImage(logo_path, width=50, height=50)
        header_table = Table([[logo_img, Paragraph(header_text, title_style)]], colWidths=[60, 480])
        header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story.append(header_table)
    else:
        story.append(Paragraph(f"Cecil Harford USBC — {config.get('name')}", title_style))

    champ_data = [[Paragraph(f"<b>🏆 OFFICIAL CHAMPION CROWNED: {champion_name}</b><br/><font size='8.5' color='#0f172a'>Adjudicated automatically via USBC handicap grand totals and stepladder finals engine.</font>", styles["Normal"])]]
    ct = Table(champ_data, colWidths=[540])
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#10b98120")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#10b981")),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(ct)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Championship Stepladder Finals Summary", h2_style))
    step_data = [
        ["Match Stage", "Competitors", "Winner & Score"],
        ["Match 1 (4th vs 5th)", f"{stepladder_results.get('m1_p1', '')} vs {stepladder_results.get('m1_p2', '')}", f"{stepladder_results.get('m1_winner', '')} ({stepladder_results.get('m1_score', '')})"],
        ["Match 2 (3rd vs M1 Winner)", f"{stepladder_results.get('m2_p1', '')} vs {stepladder_results.get('m2_winner_prev', '')}", f"{stepladder_results.get('m2_winner', '')} ({stepladder_results.get('m2_score', '')})"],
        ["Semifinal (2nd vs M2 Winner)", f"{stepladder_results.get('semi_p1', '')} vs {stepladder_results.get('semi_winner_prev', '')}", f"{stepladder_results.get('semi_winner', '')} ({stepladder_results.get('semi_score', '')})"],
        ["Championship (1st vs Semifinalist)", f"{stepladder_results.get('champ_p1', '')} vs {stepladder_results.get('champ_winner_prev', '')}", f"<b>{champion_name} ({stepladder_results.get('champ_score', '')})</b>"]
    ]
    st_table = Table(step_data, colWidths=[140, 220, 180])
    st_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0284c7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(st_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Final Official Standings", h2_style))
    num_games = int(config.get("games_count", 3))
    game_headers = [f"G{i}" for i in range(1, num_games + 1)]
    table_data = [["Pos", "Bowler Name", "USBC ID", "Avg", "HDCP"] + game_headers + ["Scratch", "Total"]]

    for rank, row in standings_df.reset_index().head(20).iterrows():
        r_line = [
            str(row["Rank"]), str(row["Bowler"]), str(row.get("USBC ID", "-")),
            str(row["Average"]), str(row.get("Total_HDCP", 0))
        ]
        for i in range(1, num_games + 1):
            r_line.append(str(row.get(f"Game {i}", 0)))
        r_line.extend([str(row.get("Scratch_Total", 0)), str(row["Grand_Total"])])
        table_data.append(r_line)

    t_standings = Table(table_data)
    t_standings.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_standings)
    story.append(Spacer(1, 14))

    sig_data = [
        ["Tournament Director Signature: ___________________________", "Date: ___________________"],
        ["Association Official: _________________________________", "Sanction Verified: [ X ]"]
    ]
    s_table = Table(sig_data, colWidths=[340, 200])
    s_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#475569")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(s_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def generate_sop_docx(config: dict) -> bytes:
    doc = Document()
    doc.add_heading("Cecil-Harford USBC — Tournament Operations SOP", 0)
    p = doc.add_paragraph()
    p.add_run(f"Standard Operating Procedures for: {config.get('name')}\n").bold = True
    p.add_run(f"Host Center: {config.get('center')}\nDivision: {config.get('division')}\n")
    p.add_run(f"Handicap: {int(config.get('hdcp_pct', 0.9)*100)}% of {config.get('hdcp_base', 220)}\n")
    doc.add_heading("1. Tournament Desk Check-In Procedure", level=1)
    doc.add_paragraph("All bowlers must present USBC sanction verification and verify entering book average.")
    doc.add_heading("2. Scoring & Dispute Arbitration", level=1)
    doc.add_paragraph("Protests regarding scoring or eligibility must be arbitrated immediately via official USBC Playing Rules.")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()

def generate_sop_pdf(config: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>Cecil Harford USBC — Tournament Desk SOP</b>", styles["Heading1"]),
        Spacer(1, 10),
        Paragraph(f"Event: {config.get('name')}<br/>Center: {config.get('center')}", styles["Normal"]),
        Spacer(1, 10),
        Paragraph("1. Check-In & Financial Verification: Verify payments, active USBC membership, and assigned lanes.", styles["Normal"]),
        Paragraph("2. On-Lane Score Verification: Two signatures required on paper tally sheets prior to computer lock.", styles["Normal"])
    ]
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
