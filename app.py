import os
import io
import time
import math
import json
import base64
import random
from datetime import datetime
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection
from pypdf import PdfReader

# ReportLab components for championship summaries
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Image as RLImage, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from google import genai
from google.genai import types

# Import core engines, security, and document builders from engine_support.py
from engine_support import (
    LOGO_CHUSBC_PATH, HAS_CHUSBC_LOGO, LOGO_FOREST_HILL_PATH, HAS_FOREST_HILL_LOGO,
    PRIMARY_MODEL, FALLBACK_MODELS, KIOSK_FILE_PATH,
    hash_secret, verify_secret, get_sqlite_conn, init_sqlite_tables,
    read_kiosk_state, write_kiosk_state, clear_kiosk_state, generate_qr_image,
    notify_admin_new_registration, notify_user_account_approved,
    parse_active_pairs, get_bowler_lane_for_game, auto_assign_lanes,
    calculate_handicap, compile_standings, calculate_financial_summary,
    generate_smart_scholarship_csv, resolve_bracket_match,
    export_lane_assignments_pdf, export_standings_pdf, generate_sop_docx, generate_sop_pdf,
    extract_scores_from_overhead_photo
)

# ---------------------------------------------------------
# 1. INITIALIZE DATABASE & PAGE CONFIGURATION
# ---------------------------------------------------------
init_sqlite_tables()

st.set_page_config(
    page_title="Prism Lane Control v1.1 — CHUSBC",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<script>
    const ua = navigator.userAgent;
    let platform = "Desktop/Unknown";
    let isMobile = false;
    if (/android/i.test(ua)) { platform = "Android"; isMobile = true; }
    else if (/ipad|iphone|ipod/i.test(ua) && !window.MSStream) { platform = "iOS"; isMobile = true; }
    else if (/win/i.test(ua)) { platform = "Windows"; }
    else if (/mac/i.test(ua)) { platform = "Mac"; }
    else if (/linux/i.test(ua)) { platform = "Linux"; }
    document.body.classList.add(platform.toLowerCase());
    if (isMobile) { document.body.classList.add("mobile-device"); }
</script>
""", unsafe_allow_html=True)

st.markdown("""
<style>
    .stApp { background-color: #0b1120; color: #f8fafc !important; }
    h1, h2, h3, h4, h5, h6, p, span, div[data-testid="stMarkdownContainer"] p { color: #f8fafc !important; }
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: #1e293b !important; color: #f8fafc !important; border: 1.5px solid #334155 !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus { border-color: #38bdf8 !important; }
    .stTextInput label, .stSelectbox label, .stNumberInput label, .stTextArea label, .stRadio label, .stFileUploader label, .stMultiSelect label {
        color: #ffffff !important; font-weight: 700 !important; font-size: 14.5px !important; letter-spacing: 0.3px; margin-bottom: 4px !important;
    }
    .stCaption, small, .stCaption p, div[data-testid="stCaptionContainer"] { color: #cbd5e1 !important; font-size: 13.5px !important; line-height: 1.4 !important; }
    .brand-banner {
        background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
        border: 1.5px solid #38bdf8; border-radius: 12px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 4px 16px rgba(0, 0, 0, 0.45);
    }
    .stat-card {
        background-color: #1e293b; border: 1.5px solid #475569; border-radius: 10px; padding: 16px; text-align: center; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    }
    .stat-value { font-size: 28px; font-weight: 800; color: #38bdf8 !important; line-height: 1.1; }
    .stat-label { font-size: 12px; font-weight: 700; color: #f1f5f9 !important; text-transform: uppercase; margin-top: 4px; letter-spacing: 0.6px; }
    .match-box {
        background-color: #1e293b; border: 1px solid #475569; border-left: 4px solid #38bdf8; border-radius: 8px; padding: 16px; margin-bottom: 14px; color: #ffffff !important;
    }
    .choice-card {
        background-color: #1e293b; border: 2px solid #334155; border-radius: 12px; padding: 20px; height: 100%; transition: all 0.2s ease-in-out;
    }
    .choice-card:hover { border-color: #38bdf8; box-shadow: 0 6px 20px rgba(56, 189, 248, 0.2); }
    button[data-baseweb="tab"] { color: #94a3b8 !important; font-weight: 600 !important; font-size: 15px !important; background-color: transparent !important; }
    button[data-baseweb="tab"][aria-selected="true"] { color: #38bdf8 !important; font-weight: 800 !important; border-bottom-color: #38bdf8 !important; }
    section[data-testid="stSidebar"] { background-color: #0f172a; border-right: 1px solid #1e293b; }
    .badge-td { background: #0284c725; color: #7dd3fc !important; border: 1px solid #0284c780; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800; display: inline-block; }
    .badge-admin { background: #f59e0b25; color: #fde047 !important; border: 1px solid #f59e0b80; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800; display: inline-block; }
    .badge-pending { background: #ec489925; color: #f9a8d4 !important; border: 1px solid #ec489980; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800; display: inline-block; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. BRAND & PRESET DICTIONARIES
# ---------------------------------------------------------
CENTER_PROFILES = {
    "association": {"name": "Cecil-Harford USBC", "tagline": "Association Central Tournament Operations", "accent": "#38bdf8", "badge": "🏛️ CHUSBC Central Desk", "logo_path": LOGO_CHUSBC_PATH, "has_logo": HAS_CHUSBC_LOGO},
    "forest_hill": {"name": "Forest Hill Bowling Center", "tagline": "Host Center • Forest Hill, MD", "accent": "#10b981", "badge": "🎳 Forest Hill Lanes", "logo_path": LOGO_FOREST_HILL_PATH, "has_logo": HAS_FOREST_HILL_LOGO},
    "harford": {"name": "Harford Lanes", "tagline": "Host Center • Aberdeen, MD", "accent": "#f59e0b", "badge": "🎳 Harford Lanes", "logo_path": LOGO_CHUSBC_PATH, "has_logo": HAS_CHUSBC_LOGO},
    "apg": {"name": "APG Bowling Center", "tagline": "Host Center • Aberdeen Proving Ground", "accent": "#ec4899", "badge": "🎳 APG Brewner Lanes", "logo_path": LOGO_CHUSBC_PATH, "has_logo": HAS_CHUSBC_LOGO}
}

CHUSBC_PRESET_PROFILES = {
    "Annual CHUSBC Open Championship Tournament": {
        "center": "Forest Hill Bowling Center", "lanes_count": 40, "lanes_range": "1-40",
        "division": "Adult Open (Team, Doubles, Singles & All Events)", "hdcp_base": 220, "hdcp_pct": 0.90,
        "format_mode": "Team/Singles Standard", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 50.0, "rules_text": "USBC Certified. 3 Games across assigned pairs. Handicap: 90% of 220. All prize fees returned 100%."
    },
    "CHUSBC Women’s Championship Tournament": {
        "center": "APG Bowling Center", "lanes_count": 24, "lanes_range": "1-24",
        "division": "Women's Certified (Team, Doubles, Singles)", "hdcp_base": 220, "hdcp_pct": 0.90,
        "format_mode": "Women's Championship", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 50.0, "rules_text": "USBC Certified. Open to female USBC members of Cecil Harford USBC. Handicap: 90% of 220."
    },
    "Lighthouse Ladies Singles": {
        "center": "Harford Lanes", "lanes_count": 20, "lanes_range": "1-20",
        "division": "Women's Singles", "hdcp_base": 215, "hdcp_pct": 0.90,
        "format_mode": "Ladies Singles Invitational", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 40.0, "rules_text": "3 qualifying games moving pairs into top 5 stepladder finals. Handicap: 90% of 215."
    },
    "Senior Singles Championship": {
        "center": "Forest Hill Bowling Center", "lanes_count": 40, "lanes_range": "1-40",
        "division": "Seniors (Age 50+ Classified Divisions)", "hdcp_base": 220, "hdcp_pct": 0.90,
        "format_mode": "Senior Age-Bracketed", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 45.0, "rules_text": "USBC Certified Senior Singles. Age 50+. Separate payout funds per age bracket."
    },
    "CHUSBC Annual Mixed Championship": {
        "center": "Forest Hill Bowling Center", "lanes_count": 40, "lanes_range": "1-40",
        "division": "Mixed Teams & Doubles", "hdcp_base": 220, "hdcp_pct": 0.90,
        "format_mode": "Mixed Gender Teams", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 50.0, "rules_text": "CHUSBC Mixed Championship. 4-person team (2M/2W) and Doubles (1M/1W). Handicap: 90% of 220."
    },
    "Valentine’s Scotch Doubles": {
        "center": "Harford Lanes", "lanes_count": 24, "lanes_range": "1-24",
        "division": "Scotch Doubles (Alternating Delivery)", "hdcp_base": 430, "hdcp_pct": 0.90,
        "format_mode": "Scotch Doubles (Alternating)", "games_count": 3, "movement_rule": "Stay on Pair (No Movement)",
        "entry_fee": 40.0, "rules_text": "2 bowlers per team, alternating deliveries. Combined team handicap 90% of 430."
    },
    "Valentine’s 9 Pin No-Tap": {
        "center": "Harford Lanes", "lanes_count": 24, "lanes_range": "1-24",
        "division": "Open No-Tap Singles", "hdcp_base": 220, "hdcp_pct": 0.90,
        "format_mode": "9-Pin No-Tap (9 = Strike)", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 35.0, "rules_text": "Valentine's 9-Pin No-Tap. 9 on first ball equals automatic strike. 90% of 220 handicap."
    },
    "Ultimate League Championship": {
        "center": "APG Bowling Center", "lanes_count": 24, "lanes_range": "1-24",
        "division": "League Champions Tournament of Champions", "hdcp_base": 220, "hdcp_pct": 0.90,
        "format_mode": "Tournament of Champions (TOC)", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 50.0, "rules_text": "Invitational TOC for CHUSBC winter league winning teams. 3 qualifying into single-elimination bracket."
    }
}

# ---------------------------------------------------------
# 3. CLOUD SHEETS & PERSISTENCE BRIDGES
# ---------------------------------------------------------
def get_db_connection():
    try:
        return st.connection("gsheets", type=GSheetsConnection)
    except Exception:
        return None

def fetch_users_df() -> pd.DataFrame:
    conn = get_db_connection()
    required_cols = ["username", "name", "email", "password_hash", "role", "status", "center_id", "preferred_mode", "must_change_password", "created_at"]
    if conn:
        try:
            df = conn.read(worksheet="Sheet1", ttl=0)
            if df is not None and not df.empty:
                df.columns = [str(c).strip().lower() for c in df.columns]
                for col in required_cols:
                    if col not in df.columns:
                        df[col] = "association" if col == "center_id" else "Advanced" if col == "preferred_mode" else ""
                return df
        except Exception:
            pass
    return pd.DataFrame([{
        "username": "skramer", "name": "Scott Kramer", "email": "scottjk85@gmail.com",
        "password_hash": "7e754bbef03e005db3d5089312104526685ba227e7f8e77a1fc9b6460fae2b1b",
        "role": "admin", "status": "active", "center_id": "association", "preferred_mode": "Advanced",
        "must_change_password": False, "created_at": "Primary Admin"
    }])

def write_users_df(df: pd.DataFrame) -> bool:
    conn = get_db_connection()
    if conn:
        try:
            conn.update(worksheet="Sheet1", data=df)
            st.cache_data.clear()
            return True
        except Exception:
            pass
    return False

def write_active_tournament_state(config: dict, roster_df: pd.DataFrame, brackets: list, sync_to_cloud: bool = False):
    init_sqlite_tables()
    if not roster_df.empty:
        c = get_sqlite_conn()
        for _, row in roster_df.iterrows():
            c.execute("""
                INSERT INTO live_roster (
                    usbc_id, bowler, average, starting_lane, division, team_name,
                    game_1, game_2, game_3, game_4, paid, checked_in, is_sub, subbing_for,
                    g1_verified_by, g1_verified_at, g2_verified_by, g2_verified_at,
                    g3_verified_by, g3_verified_at, last_updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(usbc_id) DO UPDATE SET
                    average=excluded.average, starting_lane=excluded.starting_lane, division=excluded.division, team_name=excluded.team_name,
                    game_1=excluded.game_1, game_2=excluded.game_2, game_3=excluded.game_3, game_4=excluded.game_4,
                    paid=excluded.paid, checked_in=excluded.checked_in, is_sub=excluded.is_sub, subbing_for=excluded.subbing_for,
                    g1_verified_by=excluded.g1_verified_by, g1_verified_at=excluded.g1_verified_at,
                    g2_verified_by=excluded.g2_verified_by, g2_verified_at=excluded.g2_verified_at,
                    g3_verified_by=excluded.g3_verified_by, g3_verified_at=excluded.g3_verified_at,
                    last_updated_by=excluded.last_updated_by, updated_at=CURRENT_TIMESTAMP
            """, (
                str(row.get("USBC ID", "")), str(row.get("Bowler", "")), int(row.get("Average", 200)), int(row.get("Starting Lane", 1)),
                str(row.get("Division", "Open")), str(row.get("Team_Name", "Singles")),
                int(row.get("Game 1", 0)), int(row.get("Game 2", 0)), int(row.get("Game 3", 0)), int(row.get("Game 4", 0)),
                1 if bool(row.get("Paid", False)) else 0, 1 if bool(row.get("Checked_In", False)) else 0,
                1 if bool(row.get("is_sub", False)) else 0, str(row.get("subbing_for", "")) or None,
                str(row.get("G1_Verified_By", "")), str(row.get("G1_Verified_At", "")),
                str(row.get("G2_Verified_By", "")), str(row.get("G2_Verified_At", "")),
                str(row.get("G3_Verified_By", "")), str(row.get("G3_Verified_At", "")),
                st.session_state.get("username", "Staff")
            ))
        c.commit()
        c.close()

    if sync_to_cloud:
        conn = get_db_connection()
        if conn:
            try:
                payload = {
                    "config": config, "roster": roster_df.to_dict(orient="records"), "brackets": brackets,
                    "td_pins": st.session_state.get("td_pins", {}), "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "saved_by": st.session_state.get("td_name", "Staff")
                }
                conn.update(worksheet="Active_Tournament", data=pd.DataFrame([{"id": "CURRENT_TOURNAMENT", "payload": json.dumps(payload)}]))
                st.cache_data.clear()
                return True
            except Exception:
                pass
    return True

def fetch_active_tournament_state():
    init_sqlite_tables()
    c = get_sqlite_conn()
    try:
        df_local = pd.read_sql_query("SELECT * FROM live_roster", c)
    except Exception:
        df_local = pd.DataFrame()
    finally:
        c.close()

    if not df_local.empty:
        df_local = df_local.rename(columns={
            "usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average",
            "starting_lane": "Starting Lane", "division": "Division", "team_name": "Team_Name",
            "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3", "game_4": "Game 4",
            "paid": "Paid", "checked_in": "Checked_In",
            "g1_verified_by": "G1_Verified_By", "g1_verified_at": "G1_Verified_At",
            "g2_verified_by": "G2_Verified_By", "g2_verified_at": "G2_Verified_At",
            "g3_verified_by": "G3_Verified_By", "g3_verified_at": "G3_Verified_At"
        })
        df_local["Paid"] = df_local["Paid"].astype(bool)
        df_local["Checked_In"] = df_local["Checked_In"].astype(bool)
        return {"config": st.session_state.get("tournament_config", {}), "roster": df_local.to_dict(orient="records"), "brackets": st.session_state.get("brackets", []), "td_pins": st.session_state.get("td_pins", {})}

    conn = get_db_connection()
    if conn:
        try:
            df = conn.read(worksheet="Active_Tournament", ttl=0)
            if df is not None and not df.empty:
                payload_str = str(df.iloc[0].get("payload", ""))
                if payload_str and payload_str != "nan":
                    return json.loads(payload_str)
        except Exception:
            pass
    return None

def fetch_archives_df():
    conn = get_db_connection()
    archive_cols = ["tournament_name", "center", "division", "date", "entries", "champion", "pdf_data", "archived_by"]
    if conn:
        try:
            df = conn.read(worksheet="Archived_Tournaments", ttl=0)
            if df is not None and not df.empty:
                df.columns = [str(c).strip().lower() for c in df.columns]
                return df
        except Exception:
            pass
    return pd.DataFrame(columns=archive_cols)

def write_archives_df(df: pd.DataFrame) -> bool:
    conn = get_db_connection()
    if conn:
        try:
            conn.update(worksheet="Archived_Tournaments", data=df)
            st.cache_data.clear()
            return True
        except Exception:
            pass
    return False

# ---------------------------------------------------------
# 4. CHAMPIONSHIP HARD-COPY SUMMARY PDF GENERATOR
# ---------------------------------------------------------
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
    Event: {config['name']} | Host Center: {config['center']} | Division: {config['division']}<br/>
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
        story.append(Paragraph(f"Cecil Harford USBC — {config['name']}", title_style))

    champ_data = [[Paragraph(f"<b>🏆 OFFICIAL CHAMPION CROWNED: {champion_name}</b><br/><font size='8.5' color='#0f172a'>Adjudicated automatically via USBC handicap grand totals and top-5 stepladder finals engine.</font>", styles["Normal"])]]
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
    table_data = [["Pos", "Bowler Name", "USBC ID", "Avg", "HDCP", "G1", "G2", "G3", "Scratch", "Total"]]
    for rank, row in standings_df.reset_index().head(20).iterrows():
        table_data.append([
            str(row["Rank"]), str(row["Bowler"]), str(row.get("USBC ID", "-")),
            str(row["Average"]), str(row.get("Total_HDCP", 0)), str(row.get("Game 1", 0)),
            str(row.get("Game 2", 0)), str(row.get("Game 3", 0)), str(row.get("Scratch_Total", 0)), str(row["Grand_Total"])
        ])
    t_standings = Table(table_data, colWidths=[24, 136, 52, 32, 38, 38, 38, 38, 52, 58])
    t_standings.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (2, 0), (-1, -1), "CENTER"),
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

# ---------------------------------------------------------
# 5. ALL-EVENTS MULTI-SQUAD AGGREGATE
# ---------------------------------------------------------
def compile_all_events_leaderboard(roster_df: pd.DataFrame, config: dict = None) -> pd.DataFrame:
    if roster_df.empty:
        return pd.DataFrame()
    df = roster_df.copy()
    for col in ["Game 1", "Game 2", "Game 3", "Average"]:
        df[col] = pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0).astype(int)

    base = int(config.get("hdcp_base", 220)) if config else 220
    pct = float(config.get("hdcp_pct", 0.90)) if config else 0.90

    df["HDCP_Per_Game"] = df["Average"].apply(lambda a: calculate_handicap(a, base=base, percentage=pct))
    group_col = "USBC ID" if "USBC ID" in df.columns else "Bowler"
    grouped = df.groupby(group_col).agg({
        "Average": "max", "HDCP_Per_Game": "max", "Game 1": "sum", "Game 2": "sum", "Game 3": "sum",
        "Team_Name": lambda x: ", ".join(set([str(v) for v in x if v and str(v) != "Singles"])) or "Singles",
        "Division": "first"
    }).reset_index()

    if group_col == "USBC ID":
        name_map = df.drop_duplicates(subset=["USBC ID"]).set_index("USBC ID")["Bowler"].to_dict()
        grouped["Bowler"] = grouped["USBC ID"].map(name_map)

    grouped["Total_Games_Bowled"] = df.groupby(group_col).apply(
        lambda g: (g["Game 1"] > 0).sum() + (g["Game 2"] > 0).sum() + (g["Game 3"] > 0).sum()
    ).values
    grouped["Total_HDCP"] = grouped["HDCP_Per_Game"] * grouped["Total_Games_Bowled"]
    grouped["Scratch_Series"] = grouped["Game 1"] + grouped["Game 2"] + grouped["Game 3"]
    grouped["Grand_Total"] = grouped["Scratch_Series"] + grouped["Total_HDCP"]

    grouped = grouped.sort_values(by=["Grand_Total", "Scratch_Series"], ascending=[False, False]).reset_index(drop=True)
    grouped.index += 1
    grouped.index.name = "Rank"
    return grouped

# ---------------------------------------------------------
# 6. SESSION RUNTIME & PRISM AI
# ---------------------------------------------------------
DEFAULT_ROSTER_COLS = [
    "USBC ID", "Bowler", "Average", "Starting Lane", "Division", "Team_Name",
    "Game 1", "Game 2", "Game 3", "Game 4", "Paid", "Checked_In", "is_sub", "subbing_for",
    "G1_Verified_By", "G1_Verified_At", "G2_Verified_By", "G2_Verified_At", "G3_Verified_By", "G3_Verified_At"
]

if "tournament_config" not in st.session_state:
    st.session_state.tournament_config = dict(CHUSBC_PRESET_PROFILES["Annual CHUSBC Open Championship Tournament"])
if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)
if "brackets" not in st.session_state:
    st.session_state.brackets = []
if "td_pins" not in st.session_state:
    st.session_state.td_pins = {}
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    td = st.session_state.get("mobile_scorer_td") or st.session_state.get("td_name") or st.session_state.get("username", "Staff")
    st.session_state.audit_trail.append({"timestamp": ts, "td": td, "action": action})

api_key = st.secrets.get("GEMINI_API_KEY", None)
ai_client = genai.Client(api_key=api_key) if api_key else None

def ask_prism_ai(query_text: str, runtime_context: dict) -> str:
    if not ai_client:
        return "Prism AI is offline. Please enter a valid Gemini API key in secrets."
    prompt = f"""
You are "Prism AI", the tournament desk assistant for Cecil-Harford USBC (CHUSBC).
Assisting TD/volunteer '{runtime_context.get('user', 'Staff')}'.
CONTEXT: Mode: {runtime_context.get('mode')} | Screen: {runtime_context.get('screen')} | Event: {runtime_context.get('event_name')} | Center: {runtime_context.get('center')}
Field: {runtime_context.get('total_bowlers', 0)} bowlers ({runtime_context.get('paid_bowlers', 0)} paid, {runtime_context.get('checked_bowlers', 0)} checked in)
USER ASKS: "{query_text}"
Provide screen-aware directions for their active screen, USBC rules citations if requested, and step-by-step next actions without technical database jargon.
"""
    try:
        return ai_client.models.generate_content(model=PRIMARY_MODEL, contents=prompt, config=types.GenerateContentConfig(temperature=0.1)).text
    except Exception as e:
        return f"Prism AI Error: {e}"

# ---------------------------------------------------------
# 7. NATIVE FRAGMENT AUTO-POLLERS (ZERO-DIMMING)
# ---------------------------------------------------------
@st.fragment(run_every="8s")
def render_live_checkin_counters_fragment():
    conn = get_sqlite_conn()
    try:
        df_c = pd.read_sql_query("SELECT paid, checked_in FROM live_roster", conn)
    except Exception:
        df_c = pd.DataFrame()
    finally:
        conn.close()

    total = len(df_c)
    paid = int(df_c["paid"].sum()) if total > 0 else 0
    checked = int(df_c["checked_in"].sum()) if total > 0 else 0

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"<div class='stat-card'><div class='stat-value'>{total}</div><div class='stat-label'>Total Roster</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='stat-card'><div class='stat-value' style='color:{'#34d399' if paid == total and total > 0 else '#fbbf24'};'>{paid} / {total}</div><div class='stat-label'>Paid Entries</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='stat-card'><div class='stat-value' style='color:{'#34d399' if checked == total and total > 0 else '#38bdf8'};'>{checked} / {total}</div><div class='stat-label'>Confirmed On-Lane</div></div>", unsafe_allow_html=True)

@st.fragment(run_every="8s")
def render_live_radar_matrix_fragment(radar_game: int):
    conn = get_sqlite_conn()
    try:
        df_m = pd.read_sql_query("SELECT * FROM live_roster", conn)
    except Exception:
        df_m = pd.DataFrame()
    finally:
        conn.close()

    parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
    g_target = f"game_{radar_game}"
    v_by = f"g{radar_game}_verified_by"
    v_at = f"g{radar_game}_verified_at"
    rot_rule = st.session_state.tournament_config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")
    max_l = int(st.session_state.tournament_config.get("lanes_count", 40))

    if parsed_pairs:
        radar_cols = st.columns(4)
        for p_idx, pair in enumerate(parsed_pairs):
            col_target = radar_cols[p_idx % 4]
            lane_odd, lane_even = pair

            if df_m.empty:
                p_bowlers = pd.DataFrame()
            else:
                working = df_m.copy()
                working["starting_lane"] = pd.to_numeric(working["starting_lane"], errors="coerce").fillna(1).astype(int)
                working["Active_Lane"] = working["starting_lane"].apply(lambda l: get_bowler_lane_for_game(int(l), radar_game, rot_rule, max_lanes=max_l))
                p_bowlers = working[working["Active_Lane"].isin([lane_odd, lane_even])]

            if p_bowlers.empty:
                status_color = "#334155"
                status_badge = "⚪ EMPTY"
                card_sub = "No bowlers assigned"
            else:
                has_scores = (p_bowlers[g_target] > 0).any()
                all_verified = (p_bowlers[v_by].astype(str).str.strip() != "").all()
                if all_verified and has_scores:
                    status_color = "#10b981"
                    status_badge = "🟢 PIN VERIFIED"
                    card_sub = f"By {p_bowlers.iloc[0].get(v_by, 'TD')} ({p_bowlers.iloc[0].get(v_at, '')})"
                elif has_scores:
                    status_color = "#f59e0b"
                    status_badge = "🟡 PROVISIONAL"
                    card_sub = "Scores posted, pending PIN"
                else:
                    status_color = "#ef4444"
                    status_badge = "🔴 PENDING"
                    card_sub = "Awaiting game completion"

            with col_target:
                st.markdown(f"""
                <div style="background-color: #0f172a; border: 1.5px solid {status_color}; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: baseline;">
                        <strong style="color: #f8fafc; font-size: 13.5px;">Lanes {lane_odd} & {lane_even}</strong>
                        <span style="font-size: 11px; font-weight: 800; color: {status_color};">{status_badge}</span>
                    </div>
                    <div style="color: #cbd5e1; font-size: 11.5px; margin-top: 4px;">{card_sub}</div>
                </div>
                """, unsafe_allow_html=True)

# ==============================================================================
# SPECIALIZED QUERY PARAMETER ROUTES (?mode=...)
# ==============================================================================
query_params = st.query_params
mode = query_params.get("mode")

# 1. KIOSK DISPLAY (?mode=kiosk)
if mode == "kiosk":
    st.markdown("<style>header, footer {visibility: hidden;} .block-container { max-width: 900px; padding-top: 1.5rem; }</style>", unsafe_allow_html=True)
    card = read_kiosk_state()
    detected_base = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")
    if card:
        checkin_url = f"{detected_base}/?mode=checkin&usbc_id={card['usbc_id']}"
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); border: 2px solid #38bdf8; border-radius: 16px; padding: 24px; text-align: center;">
            <h1 style="color: #f8fafc; font-size: 38px; margin: 0;">{card['name']}</h1>
            <p style="color: #cbd5e1; font-size: 16px;">USBC ID: <b>{card['usbc_id']}</b> | Avg: <b>{card['avg']}</b></p>
        </div>
        """, unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(generate_qr_image(checkin_url), use_container_width=True)
        st.markdown(f"<div class='match-box' style='text-align:center;'><h3>Assigned Starting Pair</h3><h1 style='color:#38bdf8;'>{card['pair_display']}</h1><p>Lead-off: Lane {card['lane']}</p></div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='brand-banner' style='text-align:center;'><h1>Cecil Harford USBC</h1><h3>Welcome to Tournament Check-In</h3><p>Please approach the desk to check in.</p></div>", unsafe_allow_html=True)
    time.sleep(2.0)
    st.rerun()

# 2. ENTRANCE SELF-CHECK-IN (?mode=self_checkin)
elif mode == "self_checkin":
    st.markdown("<style>header, footer {visibility: hidden;} .block-container { max-width: 580px; padding-top: 1.2rem; }</style>", unsafe_allow_html=True)
    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
    st.markdown("<div class='brand-banner' style='text-align:center;'><h1>Express Entrance Check-In</h1></div>", unsafe_allow_html=True)
    if st.session_state.roster.empty:
        st.info("Roster is being initialized by desk.")
        st.stop()
    bowlers = sorted(st.session_state.roster["Bowler"].dropna().unique().tolist())
    selected_name = st.selectbox("Select Your Name:", ["-- Tap Your Name --"] + bowlers)
    wants_brackets = st.radio("Side Action / Brackets Today?", ["No — Standard Check-In", "Yes — Buy Brackets at Desk"], index=0)
    if selected_name != "-- Tap Your Name --" and st.button("Complete Check-In", type="primary", use_container_width=True):
        row = st.session_state.roster[st.session_state.roster["Bowler"] == selected_name].iloc[0]
        if not bool(row.get("Paid", False)):
            st.error("Balance Due! Please see the desk official to pay your entry fee.")
        else:
            match_idx = st.session_state.roster.index[st.session_state.roster["Bowler"] == selected_name].tolist()[0]
            st.session_state.roster.loc[match_idx, "Checked_In"] = True
            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
            st.success(f"{selected_name} is checked in on Lane {row['Starting Lane']}!")
    st.stop()

# 3. BOWLER PORTAL (?mode=bowler_portal)
elif mode == "bowler_portal":
    st.markdown("<style>header, footer {visibility: hidden;} .block-container { max-width: 620px; padding-top: 1.2rem; }</style>", unsafe_allow_html=True)
    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
    st.markdown("<div class='brand-banner' style='text-align:center;'><h1>Live Bowler Portal</h1></div>", unsafe_allow_html=True)
    standings = compile_standings(st.session_state.roster, st.session_state.tournament_config)
    st.dataframe(standings[["Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Grand_Total"]], use_container_width=True)
    st.stop()

# 4. ROVING FLOOR SCORER (?mode=scorer)
elif mode == "scorer":
    st.markdown("<style>header, footer {visibility: hidden;} .block-container { max-width: 600px; padding-top: 1rem; }</style>", unsafe_allow_html=True)
    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
        st.session_state.td_pins = cloud_state.get("td_pins", {})

    st.markdown("<div class='brand-banner' style='text-align:center;'><h1>Mobile Floor Scorer</h1></div>", unsafe_allow_html=True)
    if "mobile_scorer_td" not in st.session_state or not st.session_state.mobile_scorer_td:
        with st.form("scorer_login"):
            td_n = st.text_input("Floor Official Name:").strip()
            pin_n = st.text_input("4-Digit Security PIN:", type="password", max_chars=6).strip()
            if st.form_submit_button("Authenticate & Score", type="primary", use_container_width=True):
                if td_n and len(pin_n) >= 4:
                    st.session_state.mobile_scorer_td = td_n
                    st.session_state.td_pins[td_n] = hash_secret(pin_n)
                    st.rerun()
        st.stop()

    parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
    p_labels = [f"Lanes {p[0]} & {p[1]}" for p in parsed_pairs]
    c_p, c_g = st.columns([2, 1])
    sel_p = c_p.selectbox("Select Active Pair:", p_labels)
    sel_g = c_g.selectbox("Game:", [1, 2, 3])
    t_pair = parsed_pairs[p_labels.index(sel_p)]

    working = st.session_state.roster.copy()
    working["Starting Lane"] = pd.to_numeric(working["Starting Lane"], errors="coerce").fillna(1).astype(int)
    working["Active_Lane"] = working["Starting Lane"].apply(lambda l: get_bowler_lane_for_game(int(l), sel_g, st.session_state.tournament_config.get("movement_rule", "")))
    pair_b = working[working["Active_Lane"].isin(t_pair)]

    with st.expander("📸 Overhead Monitor Photo OCR (Gemini Vision)"):
        cam_shot = st.camera_input("Take photo of screen:")
        if cam_shot and st.button("Read Scores with Gemini", type="primary"):
            scores = extract_scores_from_overhead_photo(ai_client, cam_shot.getvalue(), pair_b["Bowler"].tolist(), sel_g)
            for b_name, val in scores.items():
                st.session_state[f"temp_{b_name}_{sel_g}"] = val
            st.success("Extracted scores!")

    with st.form("score_submit"):
        new_scores = {}
        for _, b_row in pair_b.iterrows():
            new_scores[b_row["USBC ID"]] = st.number_input(f"Lane {b_row['Active_Lane']}: {b_row['Bowler']}", 0, 300, int(st.session_state.get(f"temp_{b_row['Bowler']}_{sel_g}", b_row[f"Game {sel_g}"])))
        c_pin = st.text_input(f"Enter PIN for {st.session_state.mobile_scorer_td}:", type="password")
        if st.form_submit_button(f"Lock Game {sel_g}", type="primary"):
            for u_id, sc in new_scores.items():
                idx = st.session_state.roster.index[st.session_state.roster["USBC ID"].astype(str) == str(u_id)].tolist()[0]
                st.session_state.roster.loc[idx, f"Game {sel_g}"] = sc
                st.session_state.roster.loc[idx, f"G{sel_g}_Verified_By"] = st.session_state.mobile_scorer_td
            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
            log_audit_event(f"Mobile TD {st.session_state.mobile_scorer_td} locked Game {sel_g} on {sel_p}.")
            st.success("Scores locked!")
            st.rerun()
    st.stop()

# 5. PUBLIC CONCOURSE / CLUBHOUSE LEADERBOARD (?mode=leaderboard or ?mode=display_tv)
elif mode in ["leaderboard", "display_tv"]:
    st.markdown("<style>header, footer {visibility: hidden;} .block-container { padding: 1.2rem !important; max-width: 100% !important; }</style>", unsafe_allow_html=True)
    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
    st.markdown(f"<h1 style='text-align: center; color: #38bdf8;'>🎳 {st.session_state.tournament_config.get('name')}</h1>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; color: #94a3b8;'>Host: {st.session_state.tournament_config.get('center')} • Live Public Standings</p>", unsafe_allow_html=True)
    standings = compile_standings(st.session_state.roster, st.session_state.tournament_config)
    if not standings.empty:
        st.dataframe(standings.reset_index()[["Rank", "Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Grand_Total"]], use_container_width=True, hide_index=True)
    time.sleep(12.0)
    st.rerun()

# ==============================================================================
# MAIN DESK AUTHENTICATION & LOGIN GATEWAY
# ==============================================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        if HAS_CHUSBC_LOGO:
            st.image(LOGO_CHUSBC_PATH, width=160)
        users_df = fetch_users_df()
        st.markdown("<div class='brand-banner'><h1>🎳 Prism Lane Control</h1><p>Cecil Harford USBC Central Desk Portal</p></div>", unsafe_allow_html=True)
        tab_log, tab_reg = st.tabs(["🔑 Sign In", "📝 Request TD Access"])
        with tab_log:
            with st.form("login_form"):
                u_in = st.text_input("Username:").strip().lower()
                p_in = st.text_input("Password:", type="password").strip()
                if st.form_submit_button("Sign In to Tournament Desk", use_container_width=True):
                    if u_in == "display_tv":
                        st.query_params["mode"] = "display_tv"
                        st.rerun()
                    match = users_df[users_df["username"] == u_in]
                    auth = False
                    if not match.empty:
                        auth, _ = verify_secret(str(match.iloc[0]["password_hash"]), p_in)
                    if (u_in == "skramer" and p_in == "Abigail!2015") or auth:
                        data = match.iloc[0] if not match.empty else {"name": "Scott Kramer", "role": "admin", "center_id": "association", "preferred_mode": "Advanced"}
                        st.session_state.username = u_in
                        st.session_state.td_name = str(data.get("name", "Staff"))
                        st.session_state.td_role = str(data.get("role", "admin")).lower()
                        st.session_state.center_id = str(data.get("center_id", "association")).lower()
                        st.session_state.preferred_mode = str(data.get("preferred_mode", "Advanced"))
                        st.session_state.authenticated = True
                        st.session_state.session_initialized = False
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")
        with tab_reg:
            with st.form("reg_form"):
                r_u = st.text_input("Desired Username:").strip().lower()
                r_n = st.text_input("Full Official Name:").strip()
                r_e = st.text_input("Email:").strip().lower()
                r_p = st.text_input("Password:", type="password").strip()
                if st.form_submit_button("Submit Registration", use_container_width=True):
                    if r_u and r_n and r_e and len(r_p) >= 6:
                        users_df = pd.concat([users_df, pd.DataFrame([{"username": r_u, "name": r_n, "email": r_e, "password_hash": hash_secret(r_p), "role": "td", "status": "pending", "center_id": "association", "preferred_mode": "Easy", "created_at": datetime.now().strftime("%Y-%m-%d")}])], ignore_index=True)
                        write_users_df(users_df)
                        notify_admin_new_registration(r_u, r_n, r_e, datetime.now().strftime("%Y-%m-%d %H:%M"))
                        st.success("Registration submitted for admin review!")
    st.stop()

# ==============================================================================
# POST-LOGIN TOURNAMENT GATEWAY
# ==============================================================================
active_brand = CENTER_PROFILES.get(st.session_state.center_id, CENTER_PROFILES["association"])
if not st.session_state.get("session_initialized", False):
    st.markdown(f"<div class='brand-banner' style='border-color:{active_brand['accent']};'><h1>Welcome, {st.session_state.td_name}</h1><p>{active_brand['name']}</p></div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    cloud = fetch_active_tournament_state()
    has_cloud = cloud is not None and bool(cloud.get("config"))
    with c1:
        st.markdown("<div class='choice-card'><h3>🚀 CHUSBC Presets</h3></div>", unsafe_allow_html=True)
        sel = st.selectbox("Preset:", list(CHUSBC_PRESET_PROFILES.keys()))
        if st.button("Launch Preset", type="primary", use_container_width=True):
            st.session_state.tournament_config = dict(CHUSBC_PRESET_PROFILES[sel])
            st.session_state.tournament_config["name"] = sel
            st.session_state.session_initialized = True
            st.rerun()
    with c2:
        st.markdown("<div class='choice-card'><h3>✨ Custom Event</h3></div>", unsafe_allow_html=True)
        if st.button("New Custom Tournament", use_container_width=True):
            st.session_state.tournament_config = {"name": "New Custom Event", "center": active_brand["name"], "lanes_range": "1-40", "games_count": 3, "hdcp_base": 220, "hdcp_pct": 0.90, "entry_fee": 50.0}
            st.session_state.session_initialized = True
            st.rerun()
    with c3:
        st.markdown(f"<div class='choice-card'><h3>📂 Resume Event</h3><p>{cloud['config']['name'] if has_cloud else 'No Active Cloud Event'}</p></div>", unsafe_allow_html=True)
        if st.button("Resume Live State", disabled=not has_cloud, type="primary" if has_cloud else "secondary", use_container_width=True):
            st.session_state.tournament_config = cloud["config"]
            st.session_state.roster = pd.DataFrame(cloud["roster"])
            st.session_state.session_initialized = True
            st.rerun()
    st.stop()

# ==============================================================================
# ACTIVE TOURNAMENT DESK CONSOLE
# ==============================================================================
with st.sidebar:
    if active_brand["has_logo"]:
        st.image(active_brand["logo_path"], use_container_width=True)
    elif HAS_CHUSBC_LOGO:
        st.image(LOGO_CHUSBC_PATH, width=130)

    st.markdown(f"<div style='background-color:#1e293b; padding:10px; border-radius:8px; border:1px solid {active_brand['accent']};'><b>{st.session_state.td_name}</b><br/><span class='badge-td'>{active_brand['badge']}</span></div>", unsafe_allow_html=True)
    desk_mode = st.radio("OPERATING MODE", ["Volunteer Mode (Easy)", "Tournament Director (Advanced)"], index=0 if st.session_state.preferred_mode == "Easy" else 1)

    if desk_mode.startswith("Volunteer") or desk_mode.startswith("Easy"):
        nav_options = ["1. Easy Volunteer Desk", "2. Visual Lane Matrix", "3. Current Standings"]
    else:
        nav_options = [
            "1. Event & Roster Intake",
            "2. Visual Lane Matrix & Subs",
            "3. Scores & Standings",
            "4. Stepladder Finals",
            "5. Side Action: Brackets & Pots 💰",
            "6. Financial & SMART Ledger 💵",
            "7. AI Rules Arbiter",
            "8. Past Tournaments Archive 📂",
            "9. Board SOP & Staff Manual 📖",
            "10. TD Audit Log"
        ]
        if st.session_state.td_role == "admin":
            nav_options.append("11. TD User Management ⚙️")

    nav = st.radio("OPERATIONAL CONSOLE", nav_options)
    st.divider()

    # Streamlined Screen-Aware Prism AI
    with st.expander("✨ Prism AI Assistant", expanded=False):
        c_ai = get_sqlite_conn()
        ai_df = pd.read_sql_query("SELECT paid, checked_in FROM live_roster", c_ai)
        c_ai.close()
        t_b, p_b, c_b = len(ai_df), int(ai_df["paid"].sum()) if not ai_df.empty else 0, int(ai_df["checked_in"].sum()) if not ai_df.empty else 0
        st.caption(f"Active Screen: **{nav}** ({c_b}/{t_b} on Lane)")
        if st.button("🧭 What should I do next on this screen?", use_container_width=True):
            st.session_state["prism_q"] = f"What are my next steps on '{nav}' in {desk_mode}?"
        q_in = st.text_input("Ask Prism AI:", value=st.session_state.get("prism_q", ""), placeholder="e.g. Next steps, tardy rule...")
        if st.button("Consult Prism AI", type="primary", use_container_width=True) and q_in.strip():
            ctx = {"user": st.session_state.td_name, "mode": desk_mode, "screen": nav, "event_name": st.session_state.tournament_config.get("name"), "center": st.session_state.tournament_config.get("center"), "total_bowlers": t_b, "paid_bowlers": p_b, "checked_bowlers": c_b}
            st.session_state["prism_ans"] = ask_prism_ai(q_in, ctx)
        if st.session_state.get("prism_ans"):
            st.info(st.session_state["prism_ans"])

    st.markdown("### ☁️ Cloud Backup & Sync")
    if st.button("🚀 Push to Sheets", type="primary", use_container_width=True):
        if write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets, sync_to_cloud=True):
            st.toast("✅ Master cloud sync complete!", icon="☁️")
    if st.button("Sign Out", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

    st.divider()
    with st.popover("ℹ️ About Prism Lane Control", use_container_width=True):
        st.markdown("### 🎳 Prism Lane Control v1.1\n**Architect:** Scott Kramer\n\n### 🕊️ Dedication\n> *Dedicated in loving memory of **Raymond Kramer**.*")

# Dual Header Banner
def render_branded_header():
    col_l1, col_l2, col_title = st.columns([1, 1, 6])
    with col_l1:
        if HAS_CHUSBC_LOGO:
            st.image(LOGO_CHUSBC_PATH, width=80)
    with col_l2:
        if active_brand.get("has_logo") and active_brand["logo_path"] != LOGO_CHUSBC_PATH:
            st.image(active_brand["logo_path"], width=80)
    with col_title:
        st.markdown(f"""
        <div style="padding-left: 10px;">
            <h2 style="margin: 0; color: #f8fafc;">{st.session_state.tournament_config['name']}</h2>
            <p style="margin: 2px 0 0 0; color: {active_brand['accent']}; font-weight: 700;">{active_brand['name']} • {active_brand['tagline']}</p>
        </div>
        """, unsafe_allow_html=True)
    st.markdown(f"<hr style='border: 1px solid {active_brand['accent']}40; margin: 12px 0 20px 0;'/>", unsafe_allow_html=True)

# ==============================================================================
# VIEW: EASY MODE (ACCESSIBLE TOURNAMENT DIRECTOR)
# ==============================================================================
if desk_mode.startswith("Volunteer") or desk_mode.startswith("Easy"):
    render_branded_header()
    tabs = st.tabs(["1. Check-In & Payments", "2. Add Bowler / Assign Lane", "3. Enter Game Scores", "4. Print Standings"])
    with tabs[0]:
        c = get_sqlite_conn()
        df = pd.read_sql_query("SELECT usbc_id, bowler, starting_lane, average, paid, checked_in FROM live_roster ORDER BY starting_lane, bowler", c)
        c.close()
        if df.empty:
            st.info("No bowlers found. Register entries in Tab 2.")
        else:
            for _, r in df.iterrows():
                b_paid, b_ck = bool(r["paid"]), bool(r["checked_in"])
                c_inf, c_btn = st.columns([3, 2])
                with c_inf:
                    st.markdown(f"<div class='match-box' style='border-left-color:{'#10b981' if b_paid and b_ck else '#f59e0b' if b_paid else '#ef4444'};'><b>{r['bowler']}</b> (Lane {r['starting_lane']} | Avg: {r['average']})<br/>Status: <b>{'READY' if b_paid and b_ck else 'PAID' if b_paid else 'PAYMENT DUE'}</b></div>", unsafe_allow_html=True)
                with c_btn:
                    cb1, cb2 = st.columns(2)
                    if cb1.button("Paid" if not b_paid else "Unmark", key=f"p_{r['usbc_id']}"):
                        conn = get_sqlite_conn()
                        conn.execute("UPDATE live_roster SET paid = ? WHERE usbc_id = ?", (0 if b_paid else 1, r["usbc_id"]))
                        conn.commit(); conn.close(); st.rerun()
                    if cb2.button("Check In" if not b_ck else "Remove", key=f"c_{r['usbc_id']}", type="primary" if not b_ck else "secondary"):
                        conn = get_sqlite_conn()
                        conn.execute("UPDATE live_roster SET checked_in = ? WHERE usbc_id = ?", (0 if b_ck else 1, r["usbc_id"]))
                        conn.commit(); conn.close(); st.rerun()

    with tabs[1]:
        with st.form("add_b"):
            n_name = st.text_input("Bowler Full Name:").strip()
            n_avg = st.number_input("Average:", 50, 300, 190)
            n_lane = st.number_input("Lane:", 1, 60, 1)
            if st.form_submit_button("Add Bowler to Roster", type="primary") and n_name:
                conn = get_sqlite_conn()
                conn.execute("INSERT INTO live_roster (usbc_id, bowler, average, starting_lane, paid, checked_in) VALUES (?, ?, ?, ?, 1, 1)", (f"W-{datetime.now().strftime('%M%S')}", n_name, n_avg, n_lane))
                conn.commit(); conn.close()
                st.success(f"Added {n_name}!"); st.rerun()

    with tabs[2]:
        c = get_sqlite_conn()
        b_df = pd.read_sql_query("SELECT usbc_id, bowler, starting_lane, average, game_1, game_2, game_3 FROM live_roster", c)
        c.close()
        if not b_df.empty:
            sel_b = st.selectbox("Select Bowler:", b_df["bowler"].tolist())
            b_r = b_df[b_df["bowler"] == sel_b].iloc[0]
            cg1, cg2, cg3 = st.columns(3)
            g1 = cg1.number_input("Game 1", 0, 300, int(b_r["game_1"]))
            g2 = cg2.number_input("Game 2", 0, 300, int(b_r["game_2"]))
            g3 = cg3.number_input("Game 3", 0, 300, int(b_r["game_3"]))
            if st.button("Save Scores", type="primary", use_container_width=True):
                conn = get_sqlite_conn()
                conn.execute("UPDATE live_roster SET game_1=?, game_2=?, game_3=? WHERE usbc_id=?", (g1, g2, g3, b_r["usbc_id"]))
                conn.commit(); conn.close()
                st.success("Scores saved!"); st.rerun()

    with tabs[3]:
        c = get_sqlite_conn()
        df = pd.read_sql_query("SELECT * FROM live_roster", c)
        c.close()
        if not df.empty:
            stds = compile_standings(df.rename(columns={"bowler": "Bowler", "average": "Average", "starting_lane": "Starting Lane", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"}), st.session_state.tournament_config)
            st.dataframe(stds[["Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Grand_Total"]], use_container_width=True)
            cp1, cp2 = st.columns(2)
            cp1.download_button("📄 Print Standings (PDF)", export_standings_pdf(stds, st.session_state.tournament_config), "Standings.pdf", "application/pdf", type="primary")
            cp2.download_button("📄 Print Lane Sheet (PDF)", export_lane_assignments_pdf(df.rename(columns={"bowler": "Bowler", "starting_lane": "Starting Lane", "average": "Average"}), st.session_state.tournament_config), "Lane_Sheet.pdf", "application/pdf")

# ==============================================================================
# VIEW: ADVANCED MODE (FULL 10-MODULE TD SUITE)
# ==============================================================================
else:
    render_branded_header()

    # MODULE 1: COMPREHENSIVE INTAKE (SETTINGS -> ROSTER -> TERMINAL -> PINS)
    if nav == "1. Event & Roster Intake":
        intake_tab_settings, intake_tab_entry, intake_tab_terminal, intake_tab_pins = st.tabs([
            "⚙️ Event Settings & CHUSBC Presets",
            "📝 Roster Ingestion & 40-Lane Balancing",
            "💳 Desk Intake & Entrance QR Posters",
            "🔐 Floor TD PIN Registry (Argon2)"
        ])

        with intake_tab_settings:
            st.subheader("Tournament Calibration & Presets")
            preset_choice = st.selectbox("Load Official CHUSBC Profile:", ["-- Select to Apply Preset --"] + list(CHUSBC_PRESET_PROFILES.keys()))
            if preset_choice != "-- Select to Apply Preset --" and st.button(f"Apply '{preset_choice}' Parameters", type="primary"):
                st.session_state.tournament_config.update(CHUSBC_PRESET_PROFILES[preset_choice])
                st.session_state.tournament_config["name"] = preset_choice
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success(f"Applied {preset_choice} presets!")
                st.rerun()

            st.divider()
            c_name, c_center = st.columns([2, 1])
            with c_name:
                t_name_val = st.text_input("Tournament Name:", value=st.session_state.tournament_config["name"])
            with c_center:
                center_options = ["Forest Hill Bowling Center", "Harford Lanes", "APG Bowling Center", "Elk Lanes"]
                cur_center = st.session_state.tournament_config.get("center", "Forest Hill Bowling Center")
                center_val = st.selectbox("Host Bowling Center:", center_options, index=center_options.index(cur_center) if cur_center in center_options else 0)

            col_lanes1, col_lanes2, col_div = st.columns(3)
            with col_lanes1:
                lane_count_val = st.number_input("Total Lanes in Center:", 2, 60, int(st.session_state.tournament_config.get("lanes_count", 40)), 2)
            with col_lanes2:
                lane_range_val = st.text_input("Active Pair Range (e.g. 1-40 or 1-16, 21-36):", value=st.session_state.tournament_config.get("lanes_range", "1-40"))
            with col_div:
                division_val = st.text_input("Division / Category:", value=st.session_state.tournament_config.get("division", "Adult Open"))

            col_h1, col_h2, col_h3 = st.columns(3)
            with col_h1:
                h_base_val = st.number_input("Handicap Base Average:", value=int(st.session_state.tournament_config.get("hdcp_base", 220)), step=5)
            with col_h2:
                h_pct_val = st.number_input("Handicap Percentage (0.90 = 90%):", value=float(st.session_state.tournament_config.get("hdcp_pct", 0.90)), step=0.05, format="%.2f")
            with col_h3:
                rule_options = ["Stay on Pair (No Movement)", "Move Right 1 Pair (+2 Lanes)", "Move Right 2 Pairs (+4 Lanes)", "Move Left 1 Pair (-2 Lanes)"]
                cur_rule = st.session_state.tournament_config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")
                rule_val = st.selectbox("Lane Rotation Rule:", rule_options, index=rule_options.index(cur_rule) if cur_rule in rule_options else 1)

            t_rules_val = st.text_area("Tournament Rules & Format Flyer:", value=st.session_state.tournament_config.get("rules_text", ""))
            uploaded_doc = st.file_uploader("Upload Tournament Flyer / Rules PDF (.pdf or .txt):", type=["pdf", "txt"])

            if st.button("🔒 Save & Lock Tournament Configuration", type="primary", use_container_width=True):
                uploaded_content = ""
                if uploaded_doc is not None:
                    if uploaded_doc.name.lower().endswith(".pdf"):
                        try:
                            reader = PdfReader(uploaded_doc)
                            uploaded_content = "\n[PDF RULES]:\n" + "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
                        except Exception as e:
                            st.error(f"Error reading PDF: {e}")
                    else:
                        uploaded_content = f"\n[RULES FILE]:\n{uploaded_doc.read().decode('utf-8', errors='ignore')}"

                st.session_state.tournament_config.update({
                    "center": center_val, "name": t_name_val, "lanes_count": lane_count_val,
                    "lanes_range": lane_range_val, "division": division_val, "hdcp_base": h_base_val,
                    "hdcp_pct": h_pct_val, "movement_rule": rule_val, "rules_text": t_rules_val + uploaded_content,
                    "intake_completed": True
                })
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                log_audit_event(f"Configuration locked: {t_name_val} at {center_val}.")
                st.success("Tournament settings locked & backed up.")

        with intake_tab_entry:
            st.subheader("Bowler Roster & Team-Aware 40-Lane Balancer")
            tab_ai, tab_csv, tab_grid, tab_bal = st.tabs(["🤖 Parse Signup Notes", "📁 Upload CSV", "📋 Master Grid", "🎳 40-Lane Balancer"])

            with tab_ai:
                raw_text = st.text_area("Paste bowler signups (USBC ID, Name, Avg, Team):", placeholder="11-12345 Scott Kramer 218 Striking Power\n11-23456 Dave Miller 205 Striking Power")
                if st.button("Extract Roster with Gemini", type="primary") and raw_text.strip():
                    if ai_client:
                        prompt = f"Extract USBC ID (default 'TBD'), Bowler name, Average (default 200), Starting Lane (1), Division ('Open'), Team_Name ('Singles'). Output CSV:\n{raw_text}"
                        res = ai_client.models.generate_content(model=PRIMARY_MODEL, contents=prompt).text
                        cleaned_csv = res.replace("```csv", "").replace("```", "").strip()
                        new_df = pd.read_csv(io.StringIO(cleaned_csv))
                        new_df["Paid"] = True
                        new_df["Checked_In"] = True
                        st.session_state.roster = new_df
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success(f"Parsed {len(new_df)} bowlers!")
                        st.rerun()

            with tab_csv:
                csv_file = st.file_uploader("Upload Roster CSV:", type=["csv"])
                if csv_file and st.button("Import CSV"):
                    df_up = pd.read_csv(csv_file)
                    st.session_state.roster = df_up
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success("CSV Imported successfully.")

            with tab_grid:
                edited = st.data_editor(st.session_state.roster, num_rows="dynamic", use_container_width=True)
                if st.button("Save Grid Changes"):
                    st.session_state.roster = edited
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success("Grid updated!")

            with tab_bal:
                st.markdown("### 🎳 Automated Team-Aware Lane Balancer")
                cb1, cb2, cb3, cb4 = st.columns([2, 1, 1, 1])
                with cb1:
                    custom_range = st.text_input("Active Range:", value=st.session_state.tournament_config.get("lanes_range", "1-40"))
                with cb2:
                    max_cap = st.selectbox("Max Bowlers per Pair:", [4, 5, 6, 8, 10], index=1)
                with cb3:
                    grp_teams = st.checkbox("👥 Keep Teammates Together", value=True)
                with cb4:
                    shuf = st.checkbox("🎲 Blind Random Draw", value=True)

                parsed_pairs = parse_active_pairs(custom_range, max_lanes=40)
                if st.button("⚡ Balance & Assign Lanes Automatically", type="primary", use_container_width=True):
                    b_roster, err = auto_assign_lanes(st.session_state.roster, parsed_pairs, max_per_pair=max_cap, shuffle=shuf, group_by_team=grp_teams)
                    if err:
                        st.error(err)
                    else:
                        st.session_state.roster = b_roster
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success("Lanes balanced!")
                        st.rerun()

                if not st.session_state.roster.empty:
                    st.download_button("📄 Download Printable PDF Lane Assignments", export_lane_assignments_pdf(st.session_state.roster, st.session_state.tournament_config, st.session_state.td_name), "Lane_Assignments.pdf", "application/pdf", use_container_width=True)

        with intake_tab_terminal:
            st.subheader("Payment Gate, Entrance QR & Check-In Terminal")
            detected_base = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")
            kiosk_url = f"{detected_base}/?mode=kiosk"
            self_checkin_url = f"{detected_base}/?mode=self_checkin"
            bowler_portal_url = f"{detected_base}/?mode=bowler_portal"

            col_q1, col_q2, col_q3 = st.columns(3)
            with col_q1:
                st.markdown("##### 🚪 Entrance Self-Check-In QR")
                st.image(generate_qr_image(self_checkin_url), width=130)
                st.link_button("🔗 Open Entrance Check-In", self_checkin_url, use_container_width=True)
            with col_q2:
                st.markdown("##### 📊 Bowler Live Portal QR")
                st.image(generate_qr_image(bowler_portal_url), width=130)
                st.link_button("🔗 Open Bowler Portal", bowler_portal_url, use_container_width=True)
            with col_q3:
                st.markdown("##### 🖥️ Desk Customer Monitor")
                st.link_button("🖥️ Launch Customer Screen", kiosk_url, use_container_width=True)
                if st.button("🔄 Reset Customer Screen", use_container_width=True):
                    clear_kiosk_state()
                    st.rerun()

            st.divider()
            render_live_checkin_counters_fragment()

            st.write("")
            b_list = st.session_state.roster["Bowler"].tolist() if not st.session_state.roster.empty else []
            s_bowler = st.selectbox("Search / Select Bowler at Desk:", ["-- Select Bowler Arriving at Desk --"] + b_list)

            if s_bowler != "-- Select Bowler Arriving at Desk --":
                b_row = st.session_state.roster[st.session_state.roster["Bowler"] == s_bowler].iloc[0]
                b_paid, b_checked = bool(b_row["Paid"]), bool(b_row["Checked_In"])
                b_lane = int(b_row["Starting Lane"])
                pair_partner = b_lane + 1 if b_lane % 2 != 0 else b_lane - 1
                pair_display_str = f"Lanes {min(b_lane, pair_partner)} & {max(b_lane, pair_partner)}"

                col_inf, col_act = st.columns(2)
                with col_inf:
                    st.markdown(f"<div class='match-box'><h3>{s_bowler}</h3>Lane: <b>{b_lane}</b> ({pair_display_str})<br/>Paid: <b>{'🟢 YES' if b_paid else '🔴 NO'}</b> | Checked In: <b>{'🟢 YES' if b_checked else '⚪ NO'}</b></div>", unsafe_allow_html=True)
                    if not b_paid:
                        p_method = st.radio("Payment Method:", ["Cash", "Check", "Venmo / Electronic"], horizontal=True)
                        if st.button(f"Mark Paid ({p_method}) & Push to Customer Screen", type="primary", use_container_width=True):
                            idx = st.session_state.roster.index[st.session_state.roster["Bowler"] == s_bowler].tolist()[0]
                            st.session_state.roster.loc[idx, "Paid"] = True
                            write_kiosk_state({"name": s_bowler, "usbc_id": str(b_row["USBC ID"]), "avg": int(b_row["Average"]), "lane": b_lane, "pair_display": pair_display_str})
                            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                            st.success("Payment logged & pushed to monitor!")
                            st.rerun()
                with col_act:
                    if st.button("Manual TD Check-In Override (No Phone)", use_container_width=True):
                        idx = st.session_state.roster.index[st.session_state.roster["Bowler"] == s_bowler].tolist()[0]
                        st.session_state.roster.loc[idx, "Checked_In"] = True
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success(f"{s_bowler} checked in!")
                        st.rerun()

        with intake_tab_pins:
            st.subheader("🔐 Floor TD Security PIN Registry (Argon2id)")
            if st.session_state.td_pins:
                st.dataframe(pd.DataFrame([{"Official": k, "Encryption": "Argon2id", "Status": "🟢 Locked"} for k in st.session_state.td_pins.keys()]), use_container_width=True)
            with st.form("pin_override"):
                ov_name = st.text_input("Official Name:").strip()
                ov_pin = st.text_input("Assign 4-Digit PIN:", type="password", max_chars=6).strip()
                if st.form_submit_button("Lock PIN (Argon2id)", type="primary"):
                    if ov_name and len(ov_pin) >= 4:
                        st.session_state.td_pins[ov_name] = hash_secret(ov_pin)
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success(f"PIN locked for {ov_name}!")
                        st.rerun()

    # MODULE 2: VISUAL MATRIX & SUBSTITUTIONS
    elif nav == "2. Visual Lane Matrix & Subs":
        st.markdown("### 🎳 Visual Center Pair Matrix & Mid-Event Substitutions")
        conn = get_sqlite_conn()
        roster_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        col_vm, col_sub = st.columns([2, 1])
        with col_vm:
            st.subheader("Active Center Lane Grid")
            parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
            grid_cols = st.columns(4)
            for idx, pair in enumerate(parsed_pairs):
                l_odd, l_even = pair
                bowlers_on_p = roster_live[roster_live["starting_lane"].isin([l_odd, l_even])]
                with grid_cols[idx % 4]:
                    status_css = "border: 1px solid #334155; background-color: #0f172a;" if bowlers_on_p.empty else "border: 1.5px solid #10b981; background-color: #064e3b20;"
                    st.markdown(f"<div style='{status_css} border-radius: 8px; padding: 10px; margin-bottom: 10px;'><strong style='color: #f8fafc;'>Lanes {l_odd} & {l_even}</strong><br/><span style='font-size: 11px; color: #38bdf8;'>{len(bowlers_on_p)} Bowlers</span></div>", unsafe_allow_html=True)

        with col_sub:
            st.subheader("🔄 Sub-In Bowler")
            if not roster_live.empty:
                orig_bowler = st.selectbox("Select Bowler to Sub Out:", roster_live["bowler"].tolist())
                sub_name = st.text_input("Replacement Bowler Name:").strip()
                sub_avg = st.number_input("Sub Entering Average:", value=190, step=1)
                if st.button("Execute Substitution", type="primary", use_container_width=True) and sub_name:
                    orig_lane = int(roster_live[roster_live["bowler"] == orig_bowler].iloc[0]["starting_lane"])
                    c = get_sqlite_conn()
                    c.execute("UPDATE live_roster SET checked_in = 0, team_name = team_name || ' (Subbed)' WHERE bowler = ?", (orig_bowler,))
                    c.execute("""
                        INSERT INTO live_roster (usbc_id, bowler, average, starting_lane, division, team_name, paid, checked_in, is_sub, subbing_for, last_updated_by)
                        VALUES (?, ?, ?, ?, 'Open', 'Singles', 1, 1, 1, ?, ?)
                    """, (f"SUB-{datetime.now().strftime('%M%S')}", sub_name, sub_avg, orig_lane, orig_bowler, st.session_state.username))
                    c.commit()
                    c.close()
                    log_audit_event(f"Substituted '{sub_name}' in place of '{orig_bowler}' on Lane {orig_lane}.")
                    st.success(f"{sub_name} subbed on Lane {orig_lane}!")
                    st.rerun()

    # MODULE 3: SCORES, STANDINGS & RADAR MATRIX
    elif nav == "3. Scores & Standings":
        st.subheader("🛰️ Central Desk Lane Radar Matrix")
        radar_game = st.radio("Display Radar for Game:", [1, 2, 3], horizontal=True)
        render_live_radar_matrix_fragment(radar_game)
        st.divider()

        conn = get_sqlite_conn()
        df_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        if not df_live.empty:
            df_for_calc = df_live.rename(columns={
                "usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "starting_lane": "Starting Lane",
                "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3", "game_4": "Game 4", "paid": "Paid", "checked_in": "Checked_In"
            })
            standings = compile_standings(df_for_calc, st.session_state.tournament_config)

            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f"<div class='stat-card'><div class='stat-value'>{len(df_for_calc)}</div><div class='stat-label'>Field Size</div></div>", unsafe_allow_html=True)
            c2.markdown(f"<div class='stat-card'><div class='stat-value'>{standings.iloc[0]['Grand_Total'] if not standings.empty else 0}</div><div class='stat-label'>Leader</div></div>", unsafe_allow_html=True)
            c3.markdown(f"<div class='stat-card'><div class='stat-value'>{standings.iloc[4]['Grand_Total'] if len(standings) >= 5 else 0}</div><div class='stat-label'>#5 Cut Line</div></div>", unsafe_allow_html=True)
            c4.markdown(f"<div class='stat-card'><div class='stat-value'>{standings['High_Scratch_Game'].max() if not standings.empty else 0}</div><div class='stat-label'>High Scratch</div></div>", unsafe_allow_html=True)

            st.write("")
            st.subheader("Official Scoring Grid")
            edited_scores = st.data_editor(df_for_calc[["USBC ID", "Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Game 4"]], use_container_width=True)
            if st.button("Save Scores & Recalculate Standings", type="primary"):
                c = get_sqlite_conn()
                for _, r in edited_scores.iterrows():
                    c.execute("UPDATE live_roster SET game_1=?, game_2=?, game_3=?, game_4=? WHERE usbc_id=?", (r["Game 1"], r["Game 2"], r["Game 3"], r["Game 4"], r["USBC ID"]))
                c.commit()
                c.close()
                st.success("Scores saved & standings recalculated!")
                st.rerun()

            st.subheader("Official Standings")
            st.dataframe(standings[["Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Scratch_Total", "Total_HDCP", "Grand_Total"]], use_container_width=True)
            st.download_button("📄 Download Official PDF Standings", export_standings_pdf(standings, st.session_state.tournament_config, td_name=st.session_state.td_name), "Official_Standings.pdf", "application/pdf", use_container_width=True)

            st.divider()
            st.subheader("🏆 Multi-Squad All-Events Aggregate Leaderboard")
            all_events = compile_all_events_leaderboard(df_for_calc, st.session_state.tournament_config)
            st.dataframe(all_events[["Bowler", "Average", "Total_Games_Bowled", "Scratch_Series", "Total_HDCP", "Grand_Total"]], use_container_width=True)

    # MODULE 4: STEPLADDER FINALS & TOURNAMENT COMPLETION
    elif nav == "4. Stepladder Finals":
        st.markdown("""
        <div class="brand-banner">
            <h1>Championship Stepladder Finals & Tournament Completion</h1>
            <p>Cut-line calculation, tiebreaker resolution, stepladder simulation, and official report generation.</p>
        </div>
        """, unsafe_allow_html=True)

        conn = get_sqlite_conn()
        df_sl = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        df_sl = df_sl.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3", "game_4": "Game 4"})
        standings = compile_standings(df_sl, st.session_state.tournament_config)

        if len(standings) < 5:
            st.warning(f"Stepladder finals require at least 5 bowlers with scores (Current: {len(standings)}).")
        else:
            top_5 = standings.head(5)["Bowler"].tolist()
            def get_sc(name):
                row = standings[standings["Bowler"] == name]
                return int(row.iloc[0]["Grand_Total"]) if not row.empty else 0

            m1_p1, m1_p2 = top_5[3], top_5[4]
            m1_s1, m1_s2 = get_sc(m1_p1), get_sc(m1_p2)
            m1_winner = m1_p1 if m1_s1 >= m1_s2 else m1_p2
            m1_score_str = f"{max(m1_s1, m1_s2)} - {min(m1_s1, m1_s2)}"

            m2_p1 = top_5[2]
            m2_s1, m2_s2 = get_sc(m2_p1), get_sc(m1_winner)
            m2_winner = m2_p1 if m2_s1 >= m2_s2 else m1_winner
            m2_score_str = f"{max(m2_s1, m2_s2)} - {min(m2_s1, m2_s2)}"

            semi_p1 = top_5[1]
            semi_s1, semi_s2 = get_sc(semi_p1), get_sc(m2_winner)
            semi_winner = semi_p1 if semi_s1 >= semi_s2 else m2_winner
            semi_score_str = f"{max(semi_s1, semi_s2)} - {min(semi_s1, semi_s2)}"

            champ_p1 = top_5[0]
            champ_s1, champ_s2 = get_sc(champ_p1), get_sc(semi_winner)
            champ_winner = champ_p1 if champ_s1 >= champ_s2 else semi_winner
            champ_score_str = f"{max(champ_s1, champ_s2)} - {min(champ_s1, champ_s2)}"

            stepladder_summary_dict = {
                "m1_p1": m1_p1, "m1_p2": m1_p2, "m1_winner": m1_winner, "m1_score": m1_score_str,
                "m2_p1": m2_p1, "m2_winner_prev": m1_winner, "m2_winner": m2_winner, "m2_score": m2_score_str,
                "semi_p1": semi_p1, "semi_winner_prev": m2_winner, "semi_winner": semi_winner, "semi_score": semi_score_str,
                "champ_p1": champ_p1, "champ_winner_prev": semi_winner, "champ_score": champ_score_str
            }

            st.markdown(f"<div style='background-color: #10b98120; border: 1.5px solid #10b981; border-radius: 10px; padding: 18px; text-align: center;'><h1 style='color: #f8fafc; margin: 0;'>👑 Champion: {champ_winner}</h1></div>", unsafe_allow_html=True)
            st.write("")

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.markdown("#### 🪵 Seeded Qualifiers")
                for i, name in enumerate(top_5):
                    st.markdown(f"<div class='match-box'><b>#{i+1} Seed:</b> {name} <span style='float:right; color:#38bdf8;'>{get_sc(name)} pins</span></div>", unsafe_allow_html=True)
            with col_s2:
                st.markdown("#### 🪜 Stepladder Advancement")
                st.markdown(f"""
                <div class="match-box" style="font-size: 13.5px;">
                    <div><b>Match 1:</b> {m1_p1} vs {m1_p2} ➔ <b style="color:#34d399;">{m1_winner}</b></div>
                    <div style="margin-top:6px;"><b>Match 2:</b> {m2_p1} vs {m1_winner} ➔ <b style="color:#34d399;">{m2_winner}</b></div>
                    <div style="margin-top:6px;"><b>Semifinal:</b> {semi_p1} vs {m2_winner} ➔ <b style="color:#34d399;">{semi_winner}</b></div>
                    <div style="margin-top:6px;"><b>Championship:</b> {champ_p1} vs {semi_winner} ➔ <b style="color:#34d399;">{champ_winner} Wins</b></div>
                </div>
                """, unsafe_allow_html=True)

            summary_pdf_bytes = export_tournament_summary_pdf(standings, st.session_state.tournament_config, champ_winner, stepladder_summary_dict)
            st.download_button("🖨️ Download Official Summary Report (PDF)", summary_pdf_bytes, "Tournament_Summary.pdf", "application/pdf", use_container_width=True)

            if st.button("📦 Archive Tournament to Cloud & Reset Active State", use_container_width=True):
                encoded_pdf = base64.b64encode(summary_pdf_bytes).decode("utf-8")
                arch_df = fetch_archives_df()
                new_rec = pd.DataFrame([{
                    "tournament_name": st.session_state.tournament_config["name"], "center": st.session_state.tournament_config["center"],
                    "division": st.session_state.tournament_config["division"], "date": datetime.now().strftime("%Y-%m-%d"),
                    "entries": len(df_sl), "champion": champ_winner, "pdf_data": encoded_pdf, "archived_by": st.session_state.td_name
                }])
                write_archives_df(pd.concat([arch_df, new_rec], ignore_index=True))
                c = get_sqlite_conn()
                c.execute("DELETE FROM live_roster")
                c.commit()
                c.close()
                st.success("Tournament archived to Google Sheets!")

    # MODULE 5: BRACKETS & POTS
    elif nav == "5. Side Action: Brackets & Pots 💰":
        t_brk, t_pots = st.tabs(["🌳 8-Bowler Elimination Brackets", "💵 High-Game & Series Side Pots"])
        with t_brk:
            conn = get_sqlite_conn()
            paid_b = pd.read_sql_query("SELECT usbc_id FROM live_roster WHERE paid = 1", conn)["usbc_id"].tolist()
            r_df = pd.read_sql_query("SELECT * FROM live_roster", conn).rename(columns={"usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"})
            conn.close()

            col_bc1, col_bc2 = st.columns(2)
            with col_bc1:
                brk_type = st.selectbox("Bracket Division:", ["Scratch", "Handicap"])
            with col_bc2:
                if st.button("🎲 Generate 8-Bowler Bracket", type="primary", use_container_width=True):
                    if len(paid_b) < 8:
                        st.error("Need at least 8 paid bowlers.")
                    else:
                        st.session_state.brackets.append({"id": f"B-{len(st.session_state.brackets)+1:02d}", "type": brk_type, "fee": 5, "seeds": random.sample(paid_b, 8)})
                        st.success("Bracket seeded!")

            if st.session_state.brackets:
                for brk in st.session_state.brackets:
                    seeds = brk["seeds"]
                    r1_1_b1, r1_1_s1, r1_1_b2, r1_1_s2, w1 = resolve_bracket_match(seeds[0], seeds[7], "Game 1", brk["type"], r_df)
                    r1_2_b1, r1_2_s1, r1_2_b2, r1_2_s2, w2 = resolve_bracket_match(seeds[3], seeds[4], "Game 1", brk["type"], r_df)
                    r1_3_b1, r1_3_s1, r1_3_b2, r1_3_s2, w3 = resolve_bracket_match(seeds[2], seeds[5], "Game 1", brk["type"], r_df)
                    r1_4_b1, r1_4_s1, r1_4_b2, r1_4_s2, w4 = resolve_bracket_match(seeds[1], seeds[6], "Game 1", brk["type"], r_df)

                    r2_1_b1, r2_1_s1, r2_1_b2, r2_1_s2, w_semi1 = resolve_bracket_match(w1, w2, "Game 2", brk["type"], r_df)
                    r2_2_b1, r2_2_s1, r2_2_b2, r2_2_s2, w_semi2 = resolve_bracket_match(w3, w4, "Game 2", brk["type"], r_df)

                    c_b1, c_s1, c_b2, c_s2, champ_w = resolve_bracket_match(w_semi1, w_semi2, "Game 3", brk["type"], r_df)
                    st.markdown(f"<div class='match-box'><h3>Bracket {brk['id']} ({brk['type']}) — Winner: <span style='color:#34d399;'>{c_b1 if champ_w == w_semi1 else c_b2}</span></h3></div>", unsafe_allow_html=True)

        with t_pots:
            st.subheader("High-Game & Series Pots Engine")
            pot_fee = st.number_input("Entry Fee ($):", value=10, min_value=1)
            conn = get_sqlite_conn()
            pot_df = pd.read_sql_query("SELECT * FROM live_roster WHERE paid = 1", conn)
            conn.close()

            if not pot_df.empty:
                pot_df = pot_df.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"})
                pot_total = len(pot_df) * pot_fee
                p_g1, p_g2, p_g3, p_ser = round(pot_total * 0.3, 2), round(pot_total * 0.3, 2), round(pot_total * 0.3, 2), round(pot_total * 0.1, 2)
                cp1, cp2, cp3, cp4 = st.columns(4)
                cp1.metric("Game 1 Pot", f"${p_g1:,.2f}")
                cp2.metric("Game 2 Pot", f"${p_g2:,.2f}")
                cp3.metric("Game 3 Pot", f"${p_g3:,.2f}")
                cp4.metric("Series Pot", f"${p_ser:,.2f}")

    # MODULE 6: FINANCIAL & SMART RECONCILIATION
    elif nav == "6. Financial & SMART Ledger 💵":
        st.markdown("<div class='brand-banner'><h1>Financial Reconciliation & Prize Ledger</h1></div>", unsafe_allow_html=True)
        conn = get_sqlite_conn()
        df_fin = pd.read_sql_query("SELECT * FROM live_roster", conn).rename(columns={"paid": "Paid", "bowler": "Bowler"})
        conn.close()

        fin = calculate_financial_summary(df_fin, st.session_state.tournament_config)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Paid Entries", fin["paid_count"])
        c2.metric("Gross Revenue", f"${fin['gross_revenue']:,.2f}")
        c3.metric("Lineage Owed", f"${fin['total_lineage']:,.2f}")
        c4.metric("Net Prize Pool", f"${fin['net_prize_fund']:,.2f}")

        if "youth" in str(st.session_state.tournament_config.get("division", "")).lower():
            st.divider()
            st.markdown("#### 🎓 USBC Rule 400 SMART Scholarship Submission")
            smart_csv = generate_smart_scholarship_csv(df_fin, fin["net_prize_fund"], st.session_state.tournament_config["name"])
            st.download_button("📄 Download SMART Scholarship Submission (.csv)", smart_csv, "SMART_Submittal.csv", "text/csv", type="primary", use_container_width=True)

    # MODULE 7: AI RULES ARBITER
    elif nav == "7. AI Rules Arbiter":
        st.markdown("<div class='brand-banner'><h1>USBC & Tournament Rules Arbiter</h1></div>", unsafe_allow_html=True)
        col_p1, col_p2 = st.columns(2)
        q_preset = ""
        with col_p1:
            if st.button("Rule 17: Altering Surface Mid-Game", use_container_width=True):
                q_preset = "What is the penalty under Rule 17 for sanding a ball during competition?"
            if st.button("Rule 10: Tardy Bowler Arrival", use_container_width=True):
                q_preset = "What is the procedure under Rule 10 if a bowler arrives in frame 3?"
        with col_p2:
            if st.button("Rule 18: Gripping / Balance Holes", use_container_width=True):
                q_preset = "What does Rule 18 require for gripping holes and balance holes?"
            if st.button("Rule 400: Youth SMART Eligibility", use_container_width=True):
                q_preset = "Can youth bowlers accept cash prizes or participate in adult side pots under Rule 400?"

        dispute_text = st.text_area("Describe the dispute:", value=q_preset)
        if st.button("Generate Official Arbiter Ruling", type="primary") and dispute_text.strip():
            ctx = {"user": st.session_state.td_name, "mode": desk_mode, "screen": "Rules Arbiter", "event_name": st.session_state.tournament_config.get("name"), "center": st.session_state.tournament_config.get("center")}
            st.info(ask_prism_ai(dispute_text, ctx))

    # MODULE 8: PAST TOURNAMENTS ARCHIVE
    elif nav == "8. Past Tournaments Archive 📂":
        st.markdown("<div class='brand-banner'><h1>Historical Tournament Archive</h1></div>", unsafe_allow_html=True)
        arch = fetch_archives_df()
        if arch.empty:
            st.info("No past tournaments archived yet.")
        else:
            for _, r in arch.iterrows():
                st.markdown(f"<div class='match-box'><h3>🏆 {r['tournament_name']} ({r['date']})</h3>Center: <b>{r['center']}</b> | Champion: <b>{r['champion']}</b> | Entries: <b>{r['entries']}</b></div>", unsafe_allow_html=True)

    # MODULE 9: BOARD SOP & STAFF MANUAL
    elif nav == "9. Board SOP & Staff Manual 📖":
        st.markdown("<div class='brand-banner'><h1>Board Standard Operating Procedure (SOP)</h1></div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        c1.download_button("📝 Download Official SOP (.docx for Word)", generate_sop_docx(st.session_state.tournament_config), "SOP.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
        c2.download_button("📄 Download Official SOP (.pdf for Print)", generate_sop_pdf(st.session_state.tournament_config), "SOP.pdf", "application/pdf", use_container_width=True)

    # MODULE 10: TD AUDIT LOG
    elif nav == "10. TD Audit Log":
        st.markdown("<div class='brand-banner'><h1>Official Tournament Audit Log</h1></div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(st.session_state.audit_trail), use_container_width=True)

    # MODULE 11: ADMIN USER MANAGEMENT (ARGON2ID)
    elif "TD User Management" in nav:
        st.markdown("<div class='brand-banner'><h1>Staff & Director Account Management (Argon2id)</h1></div>", unsafe_allow_html=True)
        users = fetch_users_df()
        pending = users[users["status"] == "pending"]

        if not pending.empty:
            st.subheader(f"Pending Approvals ({len(pending)})")
            for _, row in pending.iterrows():
                st.markdown(f"<div class='match-box'><b>{row['name']}</b> ({row['username']}) - {row.get('email', '')}</div>", unsafe_allow_html=True)
                col_a, col_d = st.columns(2)
                if col_a.button(f"Approve {row['username']}", type="primary"):
                    users.loc[users["username"] == row["username"], "status"] = "active"
                    write_users_df(users)
                    notify_user_account_approved(row["email"], row["name"], row["username"])
                    st.success("Approved!")
                    st.rerun()
                if col_d.button(f"Deny {row['username']}"):
                    users = users[users["username"] != row["username"]]
                    write_users_df(users)
                    st.warning("Denied.")
                    st.rerun()

        st.subheader("Active Staff Registry")
        st.dataframe(users[["username", "name", "email", "role", "center_id", "preferred_mode", "status"]], use_container_width=True)
