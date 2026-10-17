import io
import math
import hashlib
from datetime import datetime
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. PAGE SETUP & CONFIGURATION
# ---------------------------------------------------------
st.set_page_config(
    page_title="CHUSBC Tournament Desk Ops",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------
# 2. TOURNAMENT DIRECTOR AUTHENTICATION & AUDIT LOG
# ---------------------------------------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

DEFAULT_USER = "admin"
DEFAULT_PW_HASH = "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918"  # "admin"

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "td_name" not in st.session_state:
    st.session_state.td_name = ""
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.audit_trail.append({
        "timestamp": timestamp,
        "td": st.session_state.td_name,
        "action": action
    })

if not st.session_state.authenticated:
    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        st.markdown("### 🎳 Cecil Harford USBC Desk Portal")
        st.caption("Authorized Tournament Directors & Officials Only")
        with st.form("td_login"):
            username = st.text_input("TD Username")
            td_real_name = st.text_input("Tournament Director Full Name")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Verify & Open Desk")

            if submitted:
                stored_user = st.secrets.get("TD_USER", DEFAULT_USER)
                stored_hash = st.secrets.get("TD_PASSWORD_HASH", DEFAULT_PW_HASH)

                if username == stored_user and hash_password(password) == stored_hash and td_real_name.strip():
                    st.session_state.authenticated = True
                    st.session_state.td_name = td_real_name.strip()
                    log_audit_event("Tournament Director logged into desk session.")
                    st.success("Authorized.")
                    st.rerun()
                else:
                    st.error("Invalid credentials. Please enter your name, username, and password.")
    st.stop()

# ---------------------------------------------------------
# 3. GEMINI API CLIENT SETUP
# ---------------------------------------------------------
api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    with st.sidebar:
        api_key = st.text_input("Gemini API Key", type="password")

ai_client = genai.Client(api_key=api_key) if api_key else None

# ---------------------------------------------------------
# 4. TOURNAMENT INTAKE STATE
# ---------------------------------------------------------
if "tournament_config" not in st.session_state:
    st.session_state.tournament_config = {
        "center": "Forest Hill Lanes",
        "name": "Cecil Harford Annual Championship",
        "lanes_count": 16,
        "lanes_range": "1-16",
        "division": "Mixed",
        "rules_text": "Qualifying: 3 games across 3 pairs. Cut to top 5 for stepladder finals. Handicap based on 90% of 220 based on highest 2025-26 book average.",
        "intake_completed": False
    }

if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame([
        {"Bowler": "Marcus Vance", "Average": 198, "Starting Lane": 1, "Game 1": 214, "Game 2": 235, "Game 3": 201},
        {"Bowler": "Elena Rostova", "Average": 215, "Starting Lane": 1, "Game 1": 257, "Game 2": 248, "Game 3": 222},
        {"Bowler": "Derek Jackson", "Average": 182, "Starting Lane": 2, "Game 1": 178, "Game 2": 195, "Game 3": 210},
        {"Bowler": "Chloe Davenport", "Average": 204, "Starting Lane": 2, "Game 1": 225, "Game 2": 210, "Game 3": 244},
        {"Bowler": "Samir Patel", "Average": 175, "Starting Lane": 3, "Game 1": 180, "Game 2": 192, "Game 3": 175},
        {"Bowler": "Tanya Miller", "Average": 211, "Starting Lane": 3, "Game 1": 204, "Game 2": 231, "Game 3": 220},
    ])

# ---------------------------------------------------------
# 5. DETERMINISTIC SCORING ENGINE (NO HALLUCINATIONS)
# ---------------------------------------------------------
def calculate_handicap(avg: int, base: int = 220, percentage: float = 0.90) -> int:
    """Official USBC Handicap Convention: Drop fractions (floor)."""
    if avg >= base:
        return 0
    return math.floor(percentage * (base - avg))

def compile_standings(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates scratch totals, handicaps, grand totals, and resolves ties deterministically."""
    if df.empty:
        return pd.DataFrame()
        
    calc_df = df.copy()
    for col in ["Game 1", "Game 2", "Game 3", "Average"]:
        if col not in calc_df.columns:
            calc_df[col] = 0
        calc_df[col] = pd.to_numeric(calc_df[col], errors="coerce").fillna(0).astype(int)

    calc_df["HDCP_Per_Game"] = calc_df["Average"].apply(calculate_handicap)
    calc_df["Total_HDCP"] = calc_df["HDCP_Per_Game"] * 3
    calc_df["Scratch_Total"] = calc_df["Game 1"] + calc_df["Game 2"] + calc_df["Game 3"]
    calc_df["Grand_Total"] = calc_df["Scratch_Total"] + calc_df["Total_HDCP"]
    calc_df["High_Scratch_Game"] = calc_df[["Game 1", "Game 2", "Game 3"]].max(axis=1)

    # Sort deterministically: Grand Total DESC -> High Scratch Game DESC -> Scratch Total DESC
    calc_df = calc_df.sort_values(
        by=["Grand_Total", "High_Scratch_Game", "Scratch_Total"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    calc_df.index += 1
    calc_df.index.name = "Rank"
    return calc_df

# ---------------------------------------------------------
# 6. REPORTLAB PDF STANDINGS GENERATOR
# ---------------------------------------------------------
def export_standings_pdf(standings_df: pd.DataFrame, config: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4
    )
    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12
    )

    story.append(Paragraph(f"Cecil Harford USBC — {config['name']}", title_style))
    story.append(Paragraph(
        f"Center: {config['center']} | Division: {config['division']} | Lanes: {config['lanes_range']}<br/>"
        f"TD: {st.session_state.td_name} | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')}",
        meta_style
    ))

    table_data = [["Pos", "Bowler Name", "Avg", "HDCP", "G1", "G2", "G3", "Scratch", "Total"]]
    for rank, row in standings_df.reset_index().iterrows():
        table_data.append([
            str(row["Rank"]),
            str(row["Bowler"]),
            str(row["Average"]),
            str(row["Total_HDCP"]),
            str(row["Game 1"]),
            str(row["Game 2"]),
            str(row["Game 3"]),
            str(row["Scratch_Total"]),
            str(row["Grand_Total"])
        ])

    table = Table(table_data, colWidths=[28, 160, 36, 42, 42, 42, 42, 60, 65])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0284c7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("FONTNAME", (0, 1), (-1, -1),
