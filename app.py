import os
import io
import time
import math
import json
import base64
import random
import hashlib
import smtplib
import sqlite3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection
from pypdf import PdfReader
import qrcode
from PIL import Image

# Argon2 Cryptographic Hashing
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

# Word document generation
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

# PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Image as RLImage, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. PAGE SETUP, BRAND PROFILES & HIGH-CONTRAST CONTRAST THEME
# ---------------------------------------------------------
st.set_page_config(
    page_title="Prism Lane Control v1.1 — CHUSBC",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded"
)

LOGO_PATH = "CHUSBC.jpg"
HAS_LOGO = os.path.exists(LOGO_PATH)

RULEBOOK_PATH = "USBC-Playing-Rulebook-26-27.pdf"
HAS_RULEBOOK = os.path.exists(RULEBOOK_PATH)

PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.5-flash"]

KIOSK_FILE_PATH = os.path.join("/tmp", "chusbc_kiosk_state.json")

# Multi-Center Brand Environments
CENTER_PROFILES = {
    "association": {
        "name": "Cecil-Harford USBC",
        "tagline": "Association Central Tournament Operations",
        "accent": "#38bdf8",
        "badge": "🏛️ CHUSBC Central Desk"
    },
    "forest_hill": {
        "name": "Forest Hill Bowling Center",
        "tagline": "Host Center • Forest Hill, MD",
        "accent": "#10b981",
        "badge": "🎳 Forest Hill Lanes"
    },
    "harford": {
        "name": "Harford Lanes",
        "tagline": "Host Center • Aberdeen, MD",
        "accent": "#f59e0b",
        "badge": "🎳 Harford Lanes"
    },
    "apg": {
        "name": "APG Bowling Center",
        "tagline": "Host Center • Aberdeen Proving Ground",
        "accent": "#ec4899",
        "badge": "🎳 APG Brewner Lanes"
    }
}

# Cross-Browser Form Contrast Fix & Dynamic Theming
st.markdown("""
<style>
    .stApp {
        background-color: #0b1120;
        color: #f8fafc !important;
    }
    h1, h2, h3, h4, h5, h6, p, span, div[data-testid="stMarkdownContainer"] p {
        color: #f8fafc !important;
    }
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: #1e293b !important;
        color: #f8fafc !important;
        border: 1.5px solid #334155 !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus {
        border-color: #38bdf8 !important;
    }
    .stTextInput label, 
    .stSelectbox label, 
    .stNumberInput label, 
    .stTextArea label, 
    .stRadio label, 
    .stFileUploader label,
    .stMultiSelect label {
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 14.5px !important;
        letter-spacing: 0.3px;
        margin-bottom: 4px !important;
    }
    .stCaption, small, .stCaption p, div[data-testid="stCaptionContainer"] {
        color: #cbd5e1 !important;
        font-size: 13.5px !important;
        line-height: 1.4 !important;
    }
    .brand-banner {
        background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
        border: 1.5px solid #38bdf8;
        border-radius: 12px;
        padding: 22px 26px;
        margin-bottom: 24px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.45);
    }
    .brand-banner h1 {
        color: #ffffff !important;
        margin: 0;
        font-size: 26px;
        font-weight: 800;
        letter-spacing: -0.5px;
    }
    .brand-banner p {
        color: #e2e8f0 !important;
        margin: 6px 0 0 0;
        font-size: 15px;
    }
    .stat-card {
        background-color: #1e293b;
        border: 1.5px solid #475569;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    }
    .stat-value {
        font-size: 28px;
        font-weight: 800;
        color: #38bdf8 !important;
        line-height: 1.1;
    }
    .stat-label {
        font-size: 12px;
        font-weight: 700;
        color: #f1f5f9 !important;
        text-transform: uppercase;
        margin-top: 4px;
        letter-spacing: 0.6px;
    }
    .match-box {
        background-color: #1e293b;
        border: 1px solid #475569;
        border-left: 4px solid #38bdf8;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 14px;
        color: #ffffff !important;
    }
    .choice-card {
        background-color: #1e293b;
        border: 2px solid #334155;
        border-radius: 12px;
        padding: 22px;
        height: 100%;
        transition: all 0.2s ease-in-out;
    }
    .choice-card:hover {
        border-color: #38bdf8;
        box-shadow: 0 6px 20px rgba(56, 189, 248, 0.2);
    }
    button[data-baseweb="tab"] {
        color: #94a3b8 !important;
        font-weight: 600 !important;
        font-size: 15px !important;
        background-color: transparent !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #38bdf8 !important;
        font-weight: 800 !important;
        border-bottom-color: #38bdf8 !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #0f172a;
        border-right: 1px solid #1e293b;
    }
    .badge-admin {
        background: #f59e0b25;
        color: #fde047 !important;
        border: 1px solid #f59e0b80;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 800;
        display: inline-block;
    }
    .badge-td {
        background: #0284c725;
        color: #7dd3fc !important;
        border: 1px solid #0284c780;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 800;
        display: inline-block;
    }
    .badge-pending {
        background: #ec489925;
        color: #f9a8d4 !important;
        border: 1px solid #ec489980;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 800;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. LOCAL SQLITE OPERATIONAL ENGINE (PRISM_LIVE.DB)
# ---------------------------------------------------------
LOCAL_DB_PATH = "prism_live.db"

def get_sqlite_conn():
    conn = sqlite3.connect(LOCAL_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_sqlite_tables():
    conn = get_sqlite_conn()
    c = conn.cursor()
    # High-concurrency live operational table
    c.execute("""
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
            paid INTEGER DEFAULT 0,
            checked_in INTEGER DEFAULT 0,
            is_sub INTEGER DEFAULT 0,
            subbing_for TEXT DEFAULT NULL,
            g1_verified_by TEXT DEFAULT '',
            g1_verified_at TEXT DEFAULT '',
            g2_verified_by TEXT DEFAULT '',
            g2_verified_at TEXT DEFAULT '',
            g3_verified_by TEXT DEFAULT '',
            g3_verified_at TEXT DEFAULT '',
            last_updated_by TEXT DEFAULT 'Staff',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_sqlite_tables()

# ---------------------------------------------------------
# 3. ARGON2 CRYPTOGRAPHIC ENGINE & HYBRID PERSISTENCE
# ---------------------------------------------------------
ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16
)

def hash_secret(secret_str: str) -> str:
    return ph.hash(str(secret_str).strip())

def verify_secret(stored_hash: str, plain_secret: str) -> tuple[bool, bool]:
    if not stored_hash or not plain_secret:
        return False, False

    clean_secret = str(plain_secret).strip()
    stored_hash = str(stored_hash).strip()

    if stored_hash.startswith("$argon2"):
        try:
            ph.verify(stored_hash, clean_secret)
            return True, ph.check_needs_rehash(stored_hash)
        except (VerifyMismatchError, InvalidHashError):
            return False, False
    else:
        legacy_sha = hashlib.sha256(clean_secret.encode("utf-8")).hexdigest()
        if stored_hash == legacy_sha:
            return True, True
        return False, False

TARGET_ADMIN_LEGACY_HASH = "7e754bbef03e005db3d5089312104526685ba227e7f8e77a1fc9b6460fae2b1b"

def get_db_connection():
    try:
        return st.connection("gsheets", type=GSheetsConnection)
    except Exception:
        return None

def fetch_users_df() -> pd.DataFrame:
    conn = get_db_connection()
    required_cols = ["username", "name", "email", "password_hash", "role", "status", "center_id", "preferred_mode", "must_change_password", "created_at"]
    if conn is not None:
        try:
            df = conn.read(worksheet="Sheet1", ttl=0)
            if df is not None and not df.empty:
                df.columns = [str(c).strip().lower() for c in df.columns]
                for col in required_cols:
                    if col not in df.columns:
                        if col == "center_id":
                            df[col] = "association"
                        elif col == "preferred_mode":
                            df[col] = "Advanced"
                        else:
                            df[col] = ""
                return df
        except Exception:
            pass
            
    return pd.DataFrame([{
        "username": "skramer",
        "name": "Scott Kramer",
        "email": "scottjk85@gmail.com",
        "password_hash": TARGET_ADMIN_LEGACY_HASH,
        "role": "admin",
        "status": "active",
        "center_id": "association",
        "preferred_mode": "Advanced",
        "must_change_password": False,
        "created_at": "Primary Admin"
    }])

def write_users_df(df: pd.DataFrame):
    conn = get_db_connection()
    if conn is not None:
        try:
            conn.update(worksheet="Sheet1", data=df)
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(f"Error persisting to Google Sheets: {e}")
            return False
    return False

def write_active_tournament_state(config: dict, roster_df: pd.DataFrame, brackets: list, sync_to_cloud: bool = False):
    """
    HYBRID WRITE:
    1. Instantly writes to SQLite (prism_live.db) to eliminate latency and concurrency collision.
    2. Pushes snapshot to Google Sheets when sync_to_cloud=True or during squad closeout.
    """
    if not roster_df.empty:
        conn = get_sqlite_conn()
        c = conn.cursor()
        for _, row in roster_df.iterrows():
            c.execute("""
                INSERT INTO live_roster (
                    usbc_id, bowler, average, starting_lane, division, team_name,
                    game_1, game_2, game_3, game_4, paid, checked_in, is_sub, subbing_for,
                    g1_verified_by, g1_verified_at, g2_verified_by, g2_verified_at,
                    g3_verified_by, g3_verified_at, last_updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(usbc_id) DO UPDATE SET
                    average=excluded.average,
                    starting_lane=excluded.starting_lane,
                    division=excluded.division,
                    team_name=excluded.team_name,
                    game_1=excluded.game_1,
                    game_2=excluded.game_2,
                    game_3=excluded.game_3,
                    game_4=excluded.game_4,
                    paid=excluded.paid,
                    checked_in=excluded.checked_in,
                    is_sub=excluded.is_sub,
                    subbing_for=excluded.subbing_for,
                    g1_verified_by=excluded.g1_verified_by,
                    g1_verified_at=excluded.g1_verified_at,
                    g2_verified_by=excluded.g2_verified_by,
                    g2_verified_at=excluded.g2_verified_at,
                    g3_verified_by=excluded.g3_verified_by,
                    g3_verified_at=excluded.g3_verified_at,
                    last_updated_by=excluded.last_updated_by,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                str(row.get("USBC ID", "")), str(row.get("Bowler", "")),
                int(row.get("Average", 200)), int(row.get("Starting Lane", 1)),
                str(row.get("Division", "Open")), str(row.get("Team_Name", "Singles")),
                int(row.get("Game 1", 0)), int(row.get("Game 2", 0)), int(row.get("Game 3", 0)), int(row.get("Game 4", 0)),
                1 if bool(row.get("Paid", False)) else 0,
                1 if bool(row.get("Checked_In", False)) else 0,
                1 if bool(row.get("is_sub", False)) else 0,
                str(row.get("subbing_for", "")) or None,
                str(row.get("G1_Verified_By", "")), str(row.get("G1_Verified_At", "")),
                str(row.get("G2_Verified_By", "")), str(row.get("G2_Verified_At", "")),
                str(row.get("G3_Verified_By", "")), str(row.get("G3_Verified_At", "")),
                st.session_state.get("username", "Staff")
            ))
        conn.commit()
        conn.close()

    if sync_to_cloud:
        conn = get_db_connection()
        if conn is not None:
            try:
                payload = {
                    "config": config,
                    "roster": roster_df.to_dict(orient="records"),
                    "brackets": brackets,
                    "td_pins": st.session_state.get("td_pins", {}),
                    "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "saved_by": st.session_state.get("td_name", "Staff")
                }
                save_df = pd.DataFrame([{"id": "CURRENT_TOURNAMENT", "payload": json.dumps(payload)}])
                conn.update(worksheet="Active_Tournament", data=save_df)
                st.cache_data.clear()
                return True
            except Exception as e:
                st.error(f"Error saving to Google Sheets: {e}")
                return False
    return True

def fetch_active_tournament_state():
    """Reads fast operational state from SQLite; falls back to Google Sheets if local DB is fresh."""
    conn = get_sqlite_conn()
    df_local = pd.read_sql_query("SELECT * FROM live_roster", conn)
    conn.close()

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
        return {
            "config": st.session_state.get("tournament_config", {}),
            "roster": df_local.to_dict(orient="records"),
            "brackets": st.session_state.get("brackets", []),
            "td_pins": st.session_state.get("td_pins", {})
        }

    # Cloud Sheets fallback
    conn = get_db_connection()
    if conn is not None:
        try:
            df = conn.read(worksheet="Active_Tournament", ttl=0)
            if df is not None and not df.empty:
                payload_str = str(df.iloc[0].get("payload", ""))
                if payload_str and payload_str != "nan":
                    return json.loads(payload_str)
        except Exception:
            pass
    return None

def fetch_archives_df() -> pd.DataFrame:
    conn = get_db_connection()
    archive_cols = ["tournament_name", "center", "division", "date", "entries", "champion", "pdf_data", "archived_by"]
    if conn is not None:
        try:
            df = conn.read(worksheet="Archived_Tournaments", ttl=0)
            if df is not None and not df.empty:
                df.columns = [str(c).strip().lower() for c in df.columns]
                for col in archive_cols:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception:
            pass
    return pd.DataFrame(columns=archive_cols)

def write_archives_df(df: pd.DataFrame):
    conn = get_db_connection()
    if conn is not None:
        try:
            conn.update(worksheet="Archived_Tournaments", data=df)
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(f"Error persisting archive to Google Sheets: {e}")
            return False
    return False

def clear_active_tournament_state():
    conn = get_sqlite_conn()
    conn.execute("DELETE FROM live_roster")
    conn.commit()
    conn.close()

    gconn = get_db_connection()
    if gconn is not None:
        try:
            empty_df = pd.DataFrame([{"id": "CURRENT_TOURNAMENT", "payload": ""}])
            gconn.update(worksheet="Active_Tournament", data=empty_df)
            st.cache_data.clear()
            return True
        except Exception:
            pass
    return False

# Audit Trail
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    td_user = st.session_state.get("mobile_scorer_td") or st.session_state.get("td_name") or st.session_state.get("username", "Staff")
    st.session_state.audit_trail.append({
        "timestamp": timestamp,
        "td": td_user,
        "action": action
    })

# ---------------------------------------------------------
# 4. CHUSBC PRESET ARCHITECTURE & CALIBRATION
# ---------------------------------------------------------
CHUSBC_PRESET_PROFILES = {
    "Annual CHUSBC Open Championship Tournament": {
        "center": "Forest Hill Bowling Center",
        "center_id": "forest_hill",
        "lanes_count": 40,
        "lanes_range": "1-40",
        "division": "Adult Open (Team, Doubles, Singles & All Events)",
        "hdcp_base": 220,
        "hdcp_pct": 0.90,
        "format_mode": "Team/Singles Standard",
        "games_count": 3,
        "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 50.0,
        "rules_text": (
            "USBC Certified. 3 Games across assigned pairs. Open to all adult certified bowlers. "
            "Handicap: 90% of 220 based on highest winter book average. Optional All-Events scratch & handicap. "
            "All prize fees returned 100%."
        )
    },
    "CHUSBC Women’s Championship Tournament": {
        "center": "APG Bowling Center",
        "center_id": "apg",
        "lanes_count": 24,
        "lanes_range": "1-24",
        "division": "Women's Certified (Team, Doubles, Singles)",
        "hdcp_base": 220,
        "hdcp_pct": 0.90,
        "format_mode": "Women's Championship",
        "games_count": 3,
        "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 50.0,
        "rules_text": (
            "USBC Certified. Open to all female USBC members of Cecil Harford USBC. "
            "Handicap: 90% of 220. 4-person team, 2-person doubles, and individual singles. "
            "Scratch and handicap prize payouts."
        )
    },
    "Lighthouse Ladies Singles": {
        "center": "Harford Lanes",
        "center_id": "harford",
        "lanes_count": 20,
        "lanes_range": "1-20",
        "division": "Women's Singles",
        "hdcp_base": 215,
        "hdcp_pct": 0.90,
        "format_mode": "Ladies Singles Invitational",
        "games_count": 3,
        "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 40.0,
        "rules_text": (
            "Annual Lighthouse Ladies Singles Championship. 3 qualifying games moving pairs each game. "
            "Cut to top 5 stepladder finals. Handicap 90% of 215."
        )
    },
    "Senior Singles Championship": {
        "center": "Forest Hill Bowling Center",
        "center_id": "forest_hill",
        "lanes_count": 40,
        "lanes_range": "1-40",
        "division": "Seniors (Age 50+ Classified Divisions)",
        "hdcp_base": 220,
        "hdcp_pct": 0.90,
        "format_mode": "Senior Age-Bracketed",
        "games_count": 3,
        "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 45.0,
        "rules_text": (
            "USBC Certified Senior Singles. Age 50+ as of tournament date. "
            "Divisions: Super Senior (75+), Senior A (70-74), B (65-69), C (60-64), D (55-59), E (50-54). "
            "Handicap: 90% of 220. Separate payout funds per age bracket."
        )
    },
    "CHUSBC Annual Mixed Championship": {
        "center": "Forest Hill Bowling Center",
        "center_id": "forest_hill",
        "lanes_count": 40,
        "lanes_range": "1-40",
        "division": "Mixed Teams & Doubles",
        "hdcp_base": 220,
        "hdcp_pct": 0.90,
        "format_mode": "Mixed Gender Teams",
        "games_count": 3,
        "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 50.0,
        "rules_text": (
            "CHUSBC Mixed Championship. 4-bowler team (2 Men / 2 Women required) and Doubles (1 Man / 1 Woman). "
            "Handicap: 90% of 220. 3 games across pairs."
        )
    },
    "Valentine’s Scotch Doubles": {
        "center": "Harford Lanes",
        "center_id": "harford",
        "lanes_count": 24,
        "lanes_range": "1-24",
        "division": "Scotch Doubles (Alternating Delivery)",
        "hdcp_base": 430,
        "hdcp_pct": 0.90,
        "format_mode": "Scotch Doubles (Alternating)",
        "games_count": 3,
        "movement_rule": "Stay on Pair (No Movement)",
        "entry_fee": 40.0,
        "rules_text": (
            "Valentine's Scotch Doubles. 2 bowlers per team. Bowler A rolls first ball, Bowler B shoots spare, "
            "alternating strike shot lead each frame. Combined team average handicap based on 90% of 430."
        )
    },
    "Valentine’s 9 Pin No-Tap": {
        "center": "Harford Lanes",
        "center_id": "harford",
        "lanes_count": 24,
        "lanes_range": "1-24",
        "division": "Open No-Tap Singles",
        "hdcp_base": 220,
        "hdcp_pct": 0.90,
        "format_mode": "9-Pin No-Tap (9 = Strike)",
        "games_count": 3,
        "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 35.0,
        "rules_text": (
            "Valentine's 9-Pin No-Tap Tournament. Hitting 9 pins on first ball delivery is scored as an automatic strike. "
            "3 games total. 90% of 220 handicap."
        )
    },
    "Ultimate League Championship": {
        "center": "APG Bowling Center",
        "center_id": "apg",
        "lanes_count": 24,
        "lanes_range": "1-24",
        "division": "League Champions Tournament of Champions",
        "hdcp_base": 220,
        "hdcp_pct": 0.90,
        "format_mode": "Tournament of Champions (TOC)",
        "games_count": 3,
        "movement_rule": "Move Right 1 Pair (+2 Lanes)",
        "entry_fee": 50.0,
        "rules_text": (
            "Invitational Tournament of Champions for CHUSBC winter league winning teams. "
            "Qualifying 3 games into seeded single-elimination match play bracket to crown the Association League Champion."
        )
    }
}

# ---------------------------------------------------------
# 5. LANE BALANCER & CROSS-PAIR MOVEMENT ENGINE
# ---------------------------------------------------------
def parse_active_pairs(range_str: str, max_lanes: int = 40):
    lanes = set()
    parts = [p.strip() for p in range_str.split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            sub = part.split("-")
            try:
                start, end = int(sub[0]), int(sub[1])
                for l in range(start, end + 1):
                    if 1 <= l <= max_lanes:
                        lanes.add(l)
            except ValueError:
                continue
        else:
            try:
                l = int(part)
                if 1 <= l <= max_lanes:
                    lanes.add(l)
            except ValueError:
                continue

    sorted_lanes = sorted(list(lanes))
    pairs = []
    i = 0
    while i < len(sorted_lanes):
        l1 = sorted_lanes[i]
        if l1 % 2 != 0 and (l1 + 1) in lanes:
            pairs.append((l1, l1 + 1))
            i += 2
        else:
            pair_partner = l1 + 1 if l1 % 2 != 0 else l1 - 1
            pairs.append((min(l1, pair_partner), max(l1, pair_partner)))
            i += 1
            
    seen = set()
    unique_pairs = []
    for p in pairs:
        if p not in seen:
            seen.add(p)
            unique_pairs.append(p)
            
    return unique_pairs

def get_bowler_lane_for_game(starting_lane: int, game_num: int, movement_rule: str, max_lanes: int = 40) -> int:
    if game_num <= 1:
        return starting_lane

    shift_pairs = 0
    if "Move Right 1 Pair" in movement_rule:
        shift_pairs = 1
    elif "Move Right 2 Pairs" in movement_rule:
        shift_pairs = 2
    elif "Move Right 3 Pairs" in movement_rule:
        shift_pairs = 3
    elif "Move Left 1 Pair" in movement_rule:
        shift_pairs = -1

    lanes_shift = shift_pairs * 2 * (game_num - 1)
    current_lane = ((starting_lane - 1 + lanes_shift) % max_lanes) + 1
    return int(current_lane)

def auto_assign_lanes(roster_df: pd.DataFrame, pairs: list, max_per_pair: int = 5, shuffle: bool = True, group_by_team: bool = True):
    if roster_df.empty or not pairs:
        return roster_df, "No roster or lane pairs provided."

    updated_df = roster_df.copy()
    if "Team_Name" not in updated_df.columns:
        updated_df["Team_Name"] = "Singles"

    updated_df["Team_Name"] = updated_df["Team_Name"].fillna("Singles").astype(str)

    if group_by_team:
        team_groups = {}
        for idx, row in updated_df.iterrows():
            t_name = str(row["Team_Name"]).strip()
            unit_key = t_name if t_name and t_name.lower() not in ["singles", "open", "none", ""] else f"Indiv_{idx}"
            if unit_key not in team_groups:
                team_groups[unit_key] = []
            team_groups[unit_key].append(idx)
        units = list(team_groups.values())
    else:
        units = [[idx] for idx in updated_df.index]

    total_bowlers = len(updated_df)
    total_capacity = len(pairs) * max_per_pair
    if total_bowlers > total_capacity:
        return roster_df, f"Capacity exceeded! {total_bowlers} bowlers cannot fit on {len(pairs)} pairs (Max capacity: {total_capacity})."

    for u in units:
        if len(u) > max_per_pair:
            sample_name = updated_df.loc[u[0], 'Team_Name']
            return roster_df, f"Team '{sample_name}' has {len(u)} bowlers, which exceeds the max capacity of {max_per_pair} bowlers per pair."

    if shuffle:
        random.shuffle(units)

    pair_buckets = {p: [] for p in pairs}
    for unit in units:
        unit_size = len(unit)
        assigned = False
        sorted_pairs = sorted(pairs, key=lambda p: len(pair_buckets[p]))
        for p in sorted_pairs:
            if len(pair_buckets[p]) + unit_size <= max_per_pair:
                pair_buckets[p].extend(unit)
                assigned = True
                break
                
        if not assigned:
            return roster_df, "Unable to fit teams evenly across active pairs. Try opening more lane pairs or increasing capacity."

    for p, row_indices in pair_buckets.items():
        lane_odd, lane_even = p
        for order_on_pair, r_idx in enumerate(row_indices):
            assigned_lane = lane_odd if (order_on_pair % 2 == 0) else lane_even
            updated_df.loc[r_idx, "Starting Lane"] = int(assigned_lane)

    updated_df["Starting Lane"] = pd.to_numeric(updated_df["Starting Lane"], errors="coerce").fillna(1).astype(int)
    updated_df = updated_df.sort_values(by=["Starting Lane", "Team_Name", "Bowler"]).reset_index(drop=True)
    return updated_df, None

# ---------------------------------------------------------
# 6. SESSION INITIALIZATION & QR UTILITIES
# ---------------------------------------------------------
if "tournament_config" not in st.session_state:
    st.session_state.tournament_config = dict(CHUSBC_PRESET_PROFILES["Annual CHUSBC Open Championship Tournament"])
    st.session_state.tournament_config["name"] = "Annual CHUSBC Open Championship Tournament"
    st.session_state.tournament_config["intake_completed"] = False

DEFAULT_ROSTER_COLS = [
    "USBC ID", "Bowler", "Average", "Starting Lane", "Division", "Team_Name",
    "Game 1", "Game 2", "Game 3", "Game 4", "Paid", "Checked_In", "is_sub", "subbing_for",
    "G1_Verified_By", "G1_Verified_At", "G2_Verified_By", "G2_Verified_At", "G3_Verified_By", "G3_Verified_At"
]

if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)

for col in DEFAULT_ROSTER_COLS:
    if col not in st.session_state.roster.columns:
        if col in ["Game 1", "Game 2", "Game 3", "Game 4"]:
            st.session_state.roster[col] = 0
        elif col in ["Paid", "Checked_In", "is_sub"]:
            st.session_state.roster[col] = False
        else:
            st.session_state.roster[col] = ""

if "brackets" not in st.session_state:
    st.session_state.brackets = []

if "td_pins" not in st.session_state:
    st.session_state.td_pins = {}

if "session_initialized" not in st.session_state:
    st.session_state.session_initialized = False

def generate_qr_image(url: str) -> io.BytesIO:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

def register_td_pin(td_name: str, pin_str: str) -> bool:
    if not td_name or len(str(pin_str).strip()) < 4:
        return False
    if "td_pins" not in st.session_state:
        st.session_state.td_pins = {}
    st.session_state.td_pins[td_name.strip()] = hash_secret(pin_str)
    write_active_tournament_state(
        st.session_state.tournament_config,
        st.session_state.roster,
        st.session_state.brackets
    )
    return True

def verify_td_pin(td_name: str, pin_str: str) -> bool:
    pins = st.session_state.get("td_pins", {})
    stored_hash = pins.get(td_name.strip(), "")
    if not stored_hash:
        return False
    is_valid, needs_rehash = verify_secret(stored_hash, pin_str)
    if is_valid and needs_rehash:
        register_td_pin(td_name, pin_str)
    return is_valid

# ---------------------------------------------------------
# 7. DETERMINISTIC SCORING & COMPLIANCE ENGINES
# ---------------------------------------------------------
def calculate_handicap(avg: int, base: int = None, percentage: float = None) -> int:
    if base is None:
        base = int(st.session_state.tournament_config.get("hdcp_base", 220))
    if percentage is None:
        percentage = float(st.session_state.tournament_config.get("hdcp_pct", 0.90))

    if avg >= base:
        return 0
    return math.floor(percentage * (base - avg))

def compile_standings(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    calc_df = df.copy()
    game_cols = [c for c in ["Game 1", "Game 2", "Game 3", "Game 4"] if c in calc_df.columns]
    for col in game_cols + ["Average"]:
        calc_df[col] = pd.to_numeric(calc_df[col], errors="coerce").fillna(0).astype(int)

    base = int(st.session_state.tournament_config.get("hdcp_base", 220))
    pct = float(st.session_state.tournament_config.get("hdcp_pct", 0.90))
    games_count = int(st.session_state.tournament_config.get("games_count", 3))

    calc_df["HDCP_Per_Game"] = calc_df["Average"].apply(lambda a: calculate_handicap(a, base=base, percentage=pct))
    calc_df["Total_HDCP"] = calc_df["HDCP_Per_Game"] * games_count
    
    # Calculate scratch total across active games
    active_games = ["Game 1", "Game 2", "Game 3"] if games_count <= 3 else ["Game 1", "Game 2", "Game 3", "Game 4"]
    calc_df["Scratch_Total"] = calc_df[[g for g in active_games if g in calc_df.columns]].sum(axis=1)
    calc_df["Grand_Total"] = calc_df["Scratch_Total"] + calc_df["Total_HDCP"]
    calc_df["High_Scratch_Game"] = calc_df[[g for g in active_games if g in calc_df.columns]].max(axis=1)

    calc_df = calc_df.sort_values(
        by=["Grand_Total", "High_Scratch_Game", "Scratch_Total"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    calc_df.index += 1
    calc_df.index.name = "Rank"
    return calc_df

def calculate_financial_summary(roster_df: pd.DataFrame, config: dict, lineage_per_game: float = 3.75, games_count: int = 3) -> dict:
    if roster_df.empty:
        return {"paid_count": 0, "gross_revenue": 0.0, "total_lineage": 0.0, "net_prize_fund": 0.0}

    paid_df = roster_df[roster_df["Paid"] == True]
    paid_count = len(paid_df)
    entry_fee_total = float(config.get("entry_fee", 50.0))
    lineage_total_per_bowler = lineage_per_game * games_count
    
    gross_revenue = paid_count * entry_fee_total
    total_lineage = paid_count * lineage_total_per_bowler
    expense_fee = paid_count * 5.00
    net_prize_fund = gross_revenue - (total_lineage + expense_fee)

    return {
        "paid_count": paid_count,
        "entry_fee": entry_fee_total,
        "gross_revenue": gross_revenue,
        "total_lineage": total_lineage,
        "expense_fee": expense_fee,
        "net_prize_fund": max(0.0, net_prize_fund)
    }

def generate_smart_scholarship_csv(standings_df: pd.DataFrame, net_prize_fund: float) -> str:
    if standings_df.empty or net_prize_fund <= 0:
        return ""

    top_cut = max(1, math.ceil(len(standings_df) * 0.25))
    eligible = standings_df.head(top_cut).copy()

    weights = [0.40, 0.25, 0.15]
    payouts = []
    for i in range(len(eligible)):
        if i < len(weights):
            amt = round(net_prize_fund * weights[i], 2)
        else:
            remainder_share = net_prize_fund * (1.0 - sum(weights))
            amt = round(remainder_share / max(1, (len(eligible) - len(weights))), 2)
        payouts.append(amt)

    eligible["SMART_Award_Amount"] = payouts
    eligible["SMART_Account_Number"] = [f"SMART-{random.randint(100000, 999999)}" for _ in range(len(eligible))]
    
    export_df = pd.DataFrame({
        "USBC ID": eligible.get("USBC ID", "TBD"),
        "Bowler Name": eligible["Bowler"],
        "SMART Account #": eligible["SMART_Account_Number"],
        "Award Amount ($)": eligible["SMART_Award_Amount"],
        "Tournament Name": st.session_state.tournament_config["name"],
        "Date": datetime.now().strftime("%Y-%m-%d")
    })
    return export_df.to_csv(index=False)

def export_lane_assignments_pdf(roster_df: pd.DataFrame, config: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle("RosterTitle", parent=styles["Heading1"], fontSize=15, leading=18, textColor=colors.HexColor("#0f172a"), spaceAfter=2)
    header_text = f"""
    <b>Cecil Harford USBC — Lane Assignment & Check-In Roster</b><br/>
    <font size="8" color="#475569">
    Event: {config['name']} | Center: {config['center']} | Division: {config['division']}<br/>
    Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')} | TD on Duty: {st.session_state.get('td_name', 'Official')}
    </font>
    """

    if HAS_LOGO:
        logo_img = RLImage(LOGO_PATH, width=50, height=50)
        header_table = Table([[logo_img, Paragraph(header_text, title_style)]], colWidths=[60, 480])
        header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story.append(header_table)
    else:
        story.append(Paragraph("Cecil Harford USBC — Lane Assignment Roster", title_style))

    if roster_df.empty:
        story.append(Paragraph("<b>No bowlers currently registered in roster.</b>", styles["Normal"]))
    else:
        df_sorted = roster_df.copy()
        if "Starting Lane" not in df_sorted.columns:
            df_sorted["Starting Lane"] = 1
        df_sorted["Starting Lane"] = pd.to_numeric(df_sorted["Starting Lane"], errors="coerce").fillna(1).astype(int)
        
        df_sorted["Pair_Low"] = df_sorted["Starting Lane"].apply(lambda l: l if l % 2 != 0 else l - 1)
        df_sorted["Pair_High"] = df_sorted["Pair_Low"] + 1
        df_sorted["Pair_Label"] = df_sorted.apply(lambda r: f"Lanes {int(r['Pair_Low'])} & {int(r['Pair_High'])}", axis=1)

        grouped = df_sorted.groupby(["Pair_Low", "Pair_Label"])
        for _, group_df in sorted(grouped, key=lambda x: x[0]):
            pair_name = group_df.iloc[0]["Pair_Label"]
            p_header_style = ParagraphStyle("PairHeader", parent=styles["Heading2"], fontSize=10.5, leading=13, textColor=colors.white, spaceBefore=6, spaceAfter=4)
            
            pair_table_data = [[Paragraph(f"<b>{pair_name}</b>", p_header_style), "", "", "", "", "", ""]]
            pair_table_data.append(["Lane", "Bowler Name", "Team / Affiliation", "Avg", "Paid", "Check-in", "Game Scores (G1 / G2 / G3)"])

            for _, row in group_df.sort_values(by=["Starting Lane", "Bowler"]).iterrows():
                lane = str(row["Starting Lane"])
                b_name = str(row["Bowler"])
                team = str(row.get("Team_Name", "Singles"))
                if team.lower() in ["singles", "none", "nan", ""]:
                    team = "Singles"
                avg = str(row["Average"])
                paid = "Yes" if bool(row.get("Paid", False)) else "[  ]"
                checked = "Yes" if bool(row.get("Checked_In", False)) else "[  ]"
                pair_table_data.append([lane, b_name, team, avg, paid, checked, "___ / ___ / ___"])

            pt = Table(pair_table_data, colWidths=[32, 130, 110, 32, 38, 48, 150])
            pt.setStyle(TableStyle([
                ("SPAN", (0, 0), (6, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#0284c7")),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.white),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (3, 0), (5, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 2), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(pt)
            story.append(Spacer(1, 8))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def export_standings_pdf(standings_df: pd.DataFrame, config: dict, champion_name: str = "") -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle("DocTitle", parent=styles["Heading1"], fontSize=15, leading=18, textColor=colors.HexColor("#0f172a"), spaceAfter=2)
    champ_str = f" | <b>CHAMPION: {champion_name}</b>" if champion_name else ""
    header_text = f"""
    <b>Cecil Harford USBC — {config['name']}</b><br/>
    <font size="8" color="#475569">
    Host: {config['center']} | Division: {config['division']} | Lanes: {config['lanes_range']}{champ_str}<br/>
    TD on Duty: {st.session_state.get('td_name', 'Official')} | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')}
    </font>
    """

    if HAS_LOGO:
        logo_img = RLImage(LOGO_PATH, width=54, height=54)
        header_table = Table([[logo_img, Paragraph(header_text, title_style)]], colWidths=[64, 476])
        header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        story.append(header_table)
    else:
        story.append(Paragraph(f"Cecil Harford USBC — {config['name']}", title_style))

    table_data = [["Pos", "Bowler Name", "USBC ID", "Avg", "HDCP", "G1", "G2", "G3", "Scratch", "Total"]]
    for rank, row in standings_df.reset_index().iterrows():
        table_data.append([
            str(row["Rank"]), str(row["Bowler"]), str(row.get("USBC ID", "-")),
            str(row["Average"]), str(row.get("Total_HDCP", 0)), str(row.get("Game 1", 0)),
            str(row.get("Game 2", 0)), str(row.get("Game 3", 0)), str(row.get("Scratch_Total", 0)), str(row["Grand_Total"])
        ])

    table = Table(table_data, colWidths=[24, 140, 52, 32, 38, 38, 38, 38, 52, 58])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0284c7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def resolve_bracket_match(b1_id: str, b2_id: str, game_col: str, bracket_type: str, roster_df: pd.DataFrame):
    row1 = roster_df[roster_df["USBC ID"].astype(str) == str(b1_id)]
    row2 = roster_df[roster_df["USBC ID"].astype(str) == str(b2_id)]
    
    if row1.empty or row2.empty:
        return "-", 0, "-", 0, None

    r1, r2 = row1.iloc[0], row2.iloc[0]
    s1 = int(pd.to_numeric(r1.get(game_col, 0), errors="coerce") or 0)
    s2 = int(pd.to_numeric(r2.get(game_col, 0), errors="coerce") or 0)
    
    if bracket_type == "Handicap":
        h1 = calculate_handicap(int(pd.to_numeric(r1.get("Average", 200), errors="coerce") or 200))
        h2 = calculate_handicap(int(pd.to_numeric(r2.get("Average", 200), errors="coerce") or 200))
        t1, t2 = s1 + h1, s2 + h2
    else:
        t1, t2 = s1, s2

    if t1 > t2:
        winner_id = b1_id
    elif t2 > t1:
        winner_id = b2_id
    else:
        winner_id = b1_id if int(r1.get("Average", 0)) >= int(r2.get("Average", 0)) else b2_id

    return r1["Bowler"], t1, r2["Bowler"], t2, winner_id

# ---------------------------------------------------------
# 8. DEDICATED TV DISPLAY ROUTE (?mode=display_tv)
# ---------------------------------------------------------
query_params = st.query_params
if query_params.get("mode") == "display_tv":
    st.markdown("""
    <style>
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container { padding: 1.5rem !important; max-width: 100% !important; }
        .tv-row {
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            font-size: 20px;
            font-weight: 700;
        }
    </style>
    """, unsafe_allow_html=True)

    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])

    st.markdown(f"<h1 style='text-align: center; color: #38bdf8;'>🎳 {st.session_state.tournament_config.get('name', 'CHUSBC Tournament')}</h1>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; color: #94a3b8;'>Host Center: {st.session_state.tournament_config.get('center', 'Forest Hill')} • Live Public Leaderboard</p>", unsafe_allow_html=True)

    standings = compile_standings(st.session_state.roster)
    if not standings.empty:
        display_df = standings.reset_index()[["Rank", "Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Grand_Total"]].rename(columns={
            "Starting Lane": "Lane", "Average": "Avg", "Game 1": "G1", "Game 2": "G2", "Game 3": "G3", "Grand_Total": "Total Score"
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("Tournament warm-ups in session. Scores will appear as recorded.")

    time.sleep(15.0)
    st.rerun()

# ---------------------------------------------------------
# 9. GEMINI CLIENT & RULES ARBITRATION
# ---------------------------------------------------------
api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    with st.sidebar:
        api_key = st.text_input("Gemini API Key", type="password")

ai_client = genai.Client(api_key=api_key) if api_key else None

def arbitrate_rules_inquiry(query_text: str, event_context: str) -> str:
    if not ai_client:
        return "Gemini API key is not configured."

    prompt = f"""
You are the official Cecil Harford USBC (CHUSBC) Tournament Rules Arbiter.
Active Event Context:
{event_context}

Dispute / Inquiry:
{query_text}

Format your decision as:
1. **Official Ruling:** (Clear, direct verdict)
2. **USBC Rulebook Citation:** (Exact rule number and statutory guidelines)
3. **Desk Official Action:** (Step-by-step instructions for the TD)
"""
    try:
        res = ai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        return res.text
    except Exception as e:
        return f"Arbiter consultation error: {e}"

# ---------------------------------------------------------
# 10. TD AUTHENTICATION & LOGIN (ARGON2ID & NO TIMEOUT)
# ---------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "td_name" not in st.session_state:
    st.session_state.td_name = ""
if "td_role" not in st.session_state:
    st.session_state.td_role = "td"
if "center_id" not in st.session_state:
    st.session_state.center_id = "association"
if "preferred_mode" not in st.session_state:
    st.session_state.preferred_mode = "Advanced"

if not st.session_state.authenticated:
    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        if HAS_LOGO:
            st.image(LOGO_PATH, width=160)

        users_df = fetch_users_df()

        st.markdown("""
        <div class="brand-banner">
            <h1>🎳 Prism Lane Control (v1.1)</h1>
            <p>Cecil Harford USBC Tournament Desk Operations Portal</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("td_login"):
            username_input = st.text_input("Username").strip().lower()
            password_input = st.text_input("Password", type="password").strip()
            submitted = st.form_submit_button("Sign In to Tournament Desk", use_container_width=True)

            if submitted:
                # Dedicated TV Display Account bypass
                if username_input == "display_tv":
                    st.session_state.authenticated = True
                    st.session_state.username = "display_tv"
                    st.session_state.td_name = "Lobby Monitor"
                    st.session_state.preferred_mode = "TV_Display"
                    st.session_state.center_id = "association"
                    st.query_params["mode"] = "display_tv"
                    st.rerun()

                is_skramer = (username_input == "skramer" and password_input == "Abigail!2015")
                match_row = users_df[users_df["username"] == username_input]

                authenticated_match = False
                needs_upgrade = False
                if not match_row.empty:
                    stored_hash = str(match_row.iloc[0]["password_hash"])
                    authenticated_match, needs_upgrade = verify_secret(stored_hash, password_input)

                if is_skramer or authenticated_match:
                    user_data = match_row.iloc[0] if not match_row.empty else {
                        "name": "Scott Kramer",
                        "role": "admin",
                        "status": "active",
                        "center_id": "association",
                        "preferred_mode": "Advanced"
                    }
                    
                    st.session_state.username = username_input
                    st.session_state.td_name = str(user_data.get("name", "Scott Kramer"))
                    st.session_state.td_role = str(user_data.get("role", "admin")).lower()
                    st.session_state.center_id = str(user_data.get("center_id", "association")).lower()
                    st.session_state.preferred_mode = str(user_data.get("preferred_mode", "Advanced"))
                    st.session_state.authenticated = True
                    st.session_state.session_initialized = False
                    log_audit_event(f"User '{username_input}' logged in (Zero Idle Timeout Active).")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
    st.stop()

# ---------------------------------------------------------
# 11. WORKSPACE GATEWAY & POST-LOGIN SETUP
# ---------------------------------------------------------
if not st.session_state.session_initialized:
    active_brand = CENTER_PROFILES.get(st.session_state.center_id, CENTER_PROFILES["association"])
    st.markdown(f"""
    <div class="brand-banner" style="border-color: {active_brand['accent']};">
        <h1>Welcome, {st.session_state.td_name}</h1>
        <p>{active_brand['name']} • {active_brand['tagline']}</p>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("Select Tournament Workspace")
    col_opt_new, col_opt_custom, col_opt_resume = st.columns(3)
    cloud_state = fetch_active_tournament_state()
    has_active_cloud = cloud_state is not None and bool(cloud_state.get("config"))

    with col_opt_new:
        st.markdown("""
        <div class="choice-card">
            <h3 style="color: #38bdf8; margin-top: 0;">🚀 Official Presets</h3>
            <p style="font-size: 14px; color: #cbd5e1;">Select from the 8 official Cecil Harford USBC annual tournaments to instantly calibrate settings.</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        selected_preset = st.selectbox("Choose Profile:", list(CHUSBC_PRESET_PROFILES.keys()), key="preset_select_gate")
        if st.button("Launch Preset Tournament", type="primary", use_container_width=True):
            p_data = CHUSBC_PRESET_PROFILES[selected_preset]
            st.session_state.tournament_config = dict(p_data)
            st.session_state.tournament_config["name"] = selected_preset
            st.session_state.tournament_config["intake_completed"] = False
            st.session_state.roster = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)
            st.session_state.brackets = []
            st.session_state.td_pins = {}
            st.session_state.session_initialized = True
            log_audit_event(f"TD launched official preset: '{selected_preset}'.")
            st.rerun()

    with col_opt_custom:
        st.markdown("""
        <div class="choice-card">
            <h3 style="color: #fbbf24; margin-top: 0;">✨ Custom Tournament</h3>
            <p style="font-size: 14px; color: #cbd5e1;">Spin up a completely blank slate configuration for sweeper blocks, marathons, or special brackets.</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        if st.button("Create Custom Event", use_container_width=True):
            st.session_state.tournament_config = {
                "center": active_brand["name"],
                "name": "New CHUSBC Custom Event",
                "lanes_count": 40,
                "lanes_range": "1-40",
                "division": "Open Scratch/Handicap",
                "hdcp_base": 220,
                "hdcp_pct": 0.90,
                "format_mode": "Custom Format",
                "games_count": 3,
                "movement_rule": "Move Right 1 Pair (+2 Lanes)",
                "entry_fee": 50.0,
                "rules_text": "USBC Rules apply. 100% prize return.",
                "intake_completed": False
            }
            st.session_state.roster = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)
            st.session_state.brackets = []
            st.session_state.td_pins = {}
            st.session_state.session_initialized = True
            log_audit_event("TD initiated custom blank tournament configuration.")
            st.rerun()

    with col_opt_resume:
        active_title = cloud_state["config"]["name"] if has_active_cloud else "No Active Event Found"
        active_entries = len(cloud_state.get("roster", [])) if has_active_cloud else 0
        st.markdown(f"""
        <div class="choice-card">
            <h3 style="color: {'#34d399' if has_active_cloud else '#94a3b8'}; margin-top: 0;">📂 Resume Active Event</h3>
            <p style="font-size: 14px; color: #cbd5e1;">Load in-flight tournament backed up to SQLite / Sheets with live scores intact.</p>
            <div style="font-size: 13px; color: #94a3b8; border-top: 1px solid #334155; padding-top: 8px; margin-top: 12px;">
                <strong>Event:</strong> {active_title}<br/>
                <strong>Entries:</strong> {active_entries} bowlers
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        if st.button("Resume Active Event", disabled=not has_active_cloud, type="primary" if has_active_cloud else "secondary", use_container_width=True):
            st.session_state.tournament_config = cloud_state["config"]
            st.session_state.roster = pd.DataFrame(cloud_state["roster"])
            st.session_state.brackets = cloud_state.get("brackets", [])
            st.session_state.td_pins = cloud_state.get("td_pins", {})
            st.session_state.session_initialized = True
            log_audit_event(f"TD resumed active tournament: '{active_title}'.")
            st.rerun()

    st.stop()

# ---------------------------------------------------------
# 12. SIDEBAR CONSOLE & STREAMLINED GEMINI COPILOT DRAWER
# ---------------------------------------------------------
brand_info = CENTER_PROFILES.get(st.session_state.center_id, CENTER_PROFILES["association"])

with st.sidebar:
    if HAS_LOGO:
        st.image(LOGO_PATH, width=130)
    st.markdown(f"""
    <div style="background-color: #1e293b; padding: 12px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 12px;">
        <div style="font-size: 14px; font-weight: 700; color: #f1f5f9;">{st.session_state.td_name}</div>
        <div style="margin-top: 4px;"><span class="badge-td">{brand_info['badge']}</span></div>
    </div>
    """, unsafe_allow_html=True)

    # Easy Mode vs Advanced Mode Toggle
    desk_mode = st.radio(
        "DESK OPERATING MODE",
        ["Volunteer Mode (Easy)", "Tournament Director (Advanced)"],
        index=0 if st.session_state.preferred_mode == "Easy" else 1
    )

    if desk_mode.startswith("Volunteer"):
        nav_options = ["1. Easy Volunteer Desk", "2. Visual Lane Matrix", "3. Fast Standings", "4. About & Dedication"]
    else:
        nav_options = [
            "1. Event & Roster Intake",
            "2. Visual Lane Matrix & Subs",
            "3. Scores & Standings",
            "4. Stepladder Finals",
            "5. Side Action: Brackets & Pots 💰",
            "6. Financial & SMART Ledger 💵",
            "7. Past Tournaments Archive 📂",
            "8. Board SOP & Staff Manual 📖",
            "9. TD Audit Log",
            "10. About & Dedication"
        ]
        if st.session_state.td_role == "admin":
            nav_options.append("11. TD User Management ⚙️")

    nav = st.radio("OPERATIONAL CONSOLE", nav_options)
    st.divider()

    # Streamlined Collapsible Gemini Copilot Drawer
    with st.expander("🤖 Ask Prism Copilot", expanded=False):
        st.caption("Instant USBC Rules, Lane Arbitration & Logistics")
        copilot_in = st.text_input("Ask Copilot...", placeholder="e.g. USBC rule for late bowlers", key="side_ai_q")
        if copilot_in:
            with st.spinner("Consulting USBC rulebook..."):
                ruling = arbitrate_rules_inquiry(copilot_in, f"Center: {st.session_state.tournament_config['center']} | Event: {st.session_state.tournament_config['name']}")
                st.info(ruling)

    st.markdown("### 💾 Hybrid Synchronization")
    col_sync, col_reset = st.columns(2)
    with col_sync:
        if st.button("🚀 Push to Sheets", type="primary", use_container_width=True, help="Sync SQLite live operations to Google Sheets cloud"):
            saved = write_active_tournament_state(
                st.session_state.tournament_config,
                st.session_state.roster,
                st.session_state.brackets,
                sync_to_cloud=True
            )
            if saved:
                st.toast("✅ Master cloud sync complete!", icon="☁️")
                log_audit_event("TD forced SQLite data push to Google Sheets master.")
    with col_reset:
        if st.button("Switch Event", use_container_width=True):
            st.session_state.session_initialized = False
            st.rerun()

    st.write("")
    if st.button("Sign Out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.username = ""
        st.rerun()

# ---------------------------------------------------------
# 13. VIEW: EASY MODE (3-STEP VOLUNTEER DESK)
# ---------------------------------------------------------
if "Easy Volunteer Desk" in nav:
    st.markdown(f"""
    <div class="brand-banner" style="border-color: {brand_info['accent']};">
        <h1>{st.session_state.tournament_config['name']} — Volunteer Quick-Desk</h1>
        <p>Simplified 3-step operations: Bowler Check-In • Rapid Score Entry • Standings</p>
    </div>
    """, unsafe_allow_html=True)

    t_v1, t_v2, t_v3 = st.tabs(["1. Bowler Check-In", "2. Enter Scores", "3. Fast Standings"])

    with t_v1:
        st.subheader("Step 1: Check In Bowlers")
        conn = get_sqlite_conn()
        df_roster = pd.read_sql_query("SELECT usbc_id, bowler, starting_lane, average, paid, checked_in FROM live_roster", conn)
        conn.close()

        if df_roster.empty:
            st.info("No bowlers found in SQLite database. Switch to TD mode to ingest roster.")
        else:
            sel_bowler = st.selectbox("Select Bowler Arriving at Desk:", df_roster["bowler"].tolist())
            col_ck1, col_ck2 = st.columns(2)
            with col_ck1:
                b_info = df_roster[df_roster["bowler"] == sel_bowler].iloc[0]
                st.markdown(f"""
                <div class="match-box">
                    <h3>{sel_bowler}</h3>
                    Lane: <b>{b_info['starting_lane']}</b> | Entering Avg: <b>{b_info['average']}</b><br/>
                    Paid: <b>{'🟢 YES' if b_info['paid'] else '🔴 NO'}</b> | Checked In: <b>{'🟢 YES' if b_info['checked_in'] else '⚪ NO'}</b>
                </div>
                """, unsafe_allow_html=True)

                if st.button(f"Confirm Check-In & Paid for {sel_bowler}", type="primary", use_container_width=True):
                    conn = get_sqlite_conn()
                    conn.execute("UPDATE live_roster SET checked_in = 1, paid = 1, last_updated_by = ? WHERE bowler = ?", (st.session_state.username, sel_bowler))
                    conn.commit()
                    conn.close()
                    st.success(f"{sel_bowler} checked in!")
                    st.rerun()
            with col_ck2:
                st.dataframe(df_roster[["bowler", "starting_lane", "average", "paid", "checked_in"]], hide_index=True, use_container_width=True)

    with t_v2:
        st.subheader("Step 2: Rapid Score Entry")
        conn = get_sqlite_conn()
        bowlers = pd.read_sql_query("SELECT usbc_id, bowler, starting_lane, game_1, game_2, game_3, game_4 FROM live_roster", conn)
        conn.close()

        if not bowlers.empty:
            target_b = st.selectbox("Select Bowler to Post Scores:", bowlers["bowler"].tolist(), key="ez_b_score")
            curr_b = bowlers[bowlers["bowler"] == target_b].iloc[0]

            col_g1, col_g2, col_g3, col_g4 = st.columns(4)
            with col_g1:
                val_g1 = st.number_input("Game 1", value=int(curr_b["game_1"]), min_value=0, max_value=300)
            with col_g2:
                val_g2 = st.number_input("Game 2", value=int(curr_b["game_2"]), min_value=0, max_value=300)
            with col_g3:
                val_g3 = st.number_input("Game 3", value=int(curr_b["game_3"]), min_value=0, max_value=300)
            with col_g4:
                val_g4 = st.number_input("Game 4", value=int(curr_b["game_4"]), min_value=0, max_value=300)

            if st.button("Save Scores to Local Engine", type="primary", use_container_width=True):
                conn = get_sqlite_conn()
                conn.execute("""
                    UPDATE live_roster 
                    SET game_1 = ?, game_2 = ?, game_3 = ?, game_4 = ?, last_updated_by = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE bowler = ?
                """, (val_g1, val_g2, val_g3, val_g4, st.session_state.username, target_b))
                conn.commit()
                conn.close()
                st.success(f"Scores saved for {target_b}!")
                st.rerun()

    with t_v3:
        st.subheader("Step 3: Fast Live Standings")
        conn = get_sqlite_conn()
        df_quick = pd.read_sql_query("SELECT bowler, starting_lane, average, game_1, game_2, game_3, game_4 FROM live_roster", conn)
        conn.close()
        
        if not df_quick.empty:
            quick_standings = compile_standings(df_quick.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3", "game_4": "Game 4"}))
            st.dataframe(quick_standings[["Bowler", "Average", "Game 1", "Game 2", "Game 3", "Scratch_Total", "Grand_Total"]], use_container_width=True)

# ---------------------------------------------------------
# 14. VIEW: ADVANCED MODE — VISUAL LANE MATRIX & SUBS
# ---------------------------------------------------------
elif "Visual Lane Matrix" in nav:
    st.markdown("### 🎳 Visual Center Pair Matrix & Mid-Event Substitutions")
    
    parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
    conn = get_sqlite_conn()
    roster_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
    conn.close()

    col_vm, col_sub = st.columns([2, 1])

    with col_vm:
        st.subheader("Active Center Lane Grid")
        if not parsed_pairs:
            st.warning("No active pairs configured.")
        else:
            grid_cols = st.columns(4)
            for idx, pair in enumerate(parsed_pairs):
                l_odd, l_even = pair
                col_box = grid_cols[idx % 4]
                bowlers_on_p = roster_live[roster_live["starting_lane"].isin([l_odd, l_even])]
                
                with col_box:
                    if bowlers_on_p.empty:
                        status_css = "border: 1px solid #334155; background-color: #0f172a;"
                        label = "⚪ Empty Pair"
                    elif (bowlers_on_p["checked_in"] == 1).all():
                        status_css = "border: 1.5px solid #10b981; background-color: #064e3b20;"
                        label = f"🟢 Ready ({len(bowlers_on_p)} Bowlers)"
                    else:
                        status_css = "border: 1.5px solid #f59e0b; background-color: #f59e0b20;"
                        label = f"🟡 Check-In Pending ({len(bowlers_on_p)} Bowlers)"

                    st.markdown(f"""
                    <div style="{status_css} border-radius: 8px; padding: 10px; margin-bottom: 10px;">
                        <strong style="color: #f8fafc;">Lanes {l_odd} & {l_even}</strong><br/>
                        <span style="font-size: 11px; font-weight: 800; color: #38bdf8;">{label}</span>
                    </div>
                    """, unsafe_allow_html=True)

    with col_sub:
        st.subheader("🔄 Mid-Event Substitute / Sub-In")
        st.caption("Swap in a replacement bowler without breaking handicap or team calculations.")
        if roster_live.empty:
            st.info("No active bowlers available to substitute.")
        else:
            orig_bowler = st.selectbox("Select Bowler to Sub Out:", roster_live["bowler"].tolist())
            sub_name = st.text_input("Replacement Bowler Name:", placeholder="e.g. Dave Miller").strip()
            sub_avg = st.number_input("Sub Entering Average:", value=190, step=1)

            if st.button("Execute Substitution", type="primary", use_container_width=True):
                if not sub_name:
                    st.error("Please enter replacement bowler's name.")
                else:
                    orig_row = roster_live[roster_live["bowler"] == orig_bowler].iloc[0]
                    orig_lane = int(orig_row["starting_lane"])
                    
                    conn = get_sqlite_conn()
                    # Flag original bowler
                    conn.execute("UPDATE live_roster SET checked_in = 0, team_name = team_name || ' (Subbed Out)' WHERE bowler = ?", (orig_bowler,))
                    # Insert substitute on the exact same lane
                    sub_id = f"SUB-{datetime.now().strftime('%M%S')}"
                    conn.execute("""
                        INSERT INTO live_roster (usbc_id, bowler, average, starting_lane, division, team_name, paid, checked_in, is_sub, subbing_for, last_updated_by)
                        VALUES (?, ?, ?, ?, ?, ?, 1, 1, 1, ?, ?)
                    """, (sub_id, sub_name, sub_avg, orig_lane, str(orig_row["division"]), str(orig_row["team_name"]), orig_bowler, st.session_state.username))
                    conn.commit()
                    conn.close()
                    log_audit_event(f"Substituted '{sub_name}' in place of '{orig_bowler}' on Lane {orig_lane}.")
                    st.success(f"{sub_name} successfully subbed in on Lane {orig_lane}!")
                    st.rerun()

# ---------------------------------------------------------
# 15. VIEW: ADVANCED MODE — EVENT & ROSTER INTAKE
# ---------------------------------------------------------
elif "Event & Roster Intake" in nav:
    st.markdown(f"""
    <div class="brand-banner" style="border-color: {brand_info['accent']};">
        <h1>{st.session_state.tournament_config['name']} — Comprehensive Intake</h1>
        <p>Host Center: {st.session_state.tournament_config['center']} • Up to 40 Lanes • Dynamic Multi-Game Support</p>
    </div>
    """, unsafe_allow_html=True)

    tab_set, tab_rost, tab_bal = st.tabs(["⚙️ Event Settings", "📝 Roster Ingestion", "🎳 40-Lane Balancer"])

    with tab_set:
        c_n1, c_n2 = st.columns([2, 1])
        with c_n1:
            t_title = st.text_input("Tournament Name:", value=st.session_state.tournament_config["name"])
        with c_n2:
            t_center = st.selectbox("Host Center:", ["Forest Hill Bowling Center", "Harford Lanes", "APG Bowling Center", "Elk Lanes"], index=0)

        col_g_cnt, col_l_rng, col_fee = st.columns(3)
        with col_g_cnt:
            g_count = st.number_input("Number of Qualifying Games (3, 4, 5+):", min_value=1, max_value=12, value=int(st.session_state.tournament_config.get("games_count", 3)))
        with col_l_rng:
            l_range = st.text_input("Active Lane Range:", value=st.session_state.tournament_config.get("lanes_range", "1-40"))
        with col_fee:
            e_fee = st.number_input("Entry Fee ($):", value=float(st.session_state.tournament_config.get("entry_fee", 50.0)), step=5.0)

        if st.button("Save & Update Configuration", type="primary"):
            st.session_state.tournament_config.update({
                "name": t_title, "center": t_center, "games_count": g_count,
                "lanes_range": l_range, "entry_fee": e_fee
            })
            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
            st.success("Tournament configuration locked!")

    with tab_rost:
        st.subheader("Ingest Bowlers into Local SQLite Database")
        pasted_text = st.text_area("Paste signup list (USBC ID, Name, Avg, Team):", placeholder="11-12345, Scott Kramer, 218, Striking Power\n11-23456, Dave Miller, 205, Striking Power")
        if st.button("Parse & Ingest Roster", type="primary"):
            if pasted_text.strip():
                lines = pasted_text.strip().split("\n")
                new_records = []
                for idx, line in enumerate(lines):
                    parts = [p.strip() for p in line.split(",")]
                    u_id = parts[0] if len(parts) > 0 and parts[0] else f"B-{100+idx}"
                    b_name = parts[1] if len(parts) > 1 else f"Bowler {idx+1}"
                    avg = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 200
                    team = parts[3] if len(parts) > 3 else "Singles"
                    new_records.append({
                        "USBC ID": u_id, "Bowler": b_name, "Average": avg, "Starting Lane": 1,
                        "Division": "Open", "Team_Name": team, "Paid": True, "Checked_In": True
                    })
                st.session_state.roster = pd.DataFrame(new_records)
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success(f"Ingested {len(new_records)} bowlers directly into SQLite!")
                st.rerun()

    with tab_bal:
        st.subheader("Team-Aware Automated Lane Balancer")
        active_p = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
        st.write(f"Active Pairs: **{len(active_p)} pairs** ({len(active_p)*2} lanes)")
        
        if st.button("⚡ Balance & Assign Lanes", type="primary"):
            if not active_p or st.session_state.roster.empty:
                st.error("Roster or lane pairs empty.")
            else:
                balanced, err = auto_assign_lanes(st.session_state.roster, active_p, max_per_pair=5, shuffle=True, group_by_team=True)
                if err:
                    st.error(err)
                else:
                    st.session_state.roster = balanced
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success("Balanced lanes across field!")
                    st.rerun()

        if not st.session_state.roster.empty:
            pdf_bytes = export_lane_assignments_pdf(st.session_state.roster, st.session_state.tournament_config)
            st.download_button("📄 Download Printable PDF Lane Assignment Roster", data=pdf_bytes, file_name="Lane_Assignments.pdf", mime="application/pdf")

# ---------------------------------------------------------
# 16. VIEW: ADVANCED MODE — SCORES & STANDINGS
# ---------------------------------------------------------
elif "Scores & Standings" in nav:
    st.markdown("### 📊 Live Scoring Grid & Standings")
    conn = get_sqlite_conn()
    df_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
    conn.close()

    if df_live.empty:
        st.info("Roster is currently empty. Add bowlers in Module 1.")
    else:
        df_for_calc = df_live.rename(columns={
            "usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average",
            "starting_lane": "Starting Lane", "game_1": "Game 1", "game_2": "Game 2",
            "game_3": "Game 3", "game_4": "Game 4", "paid": "Paid", "checked_in": "Checked_In"
        })
        standings = compile_standings(df_for_calc)
        
        col_st1, col_st2 = st.columns([3, 1])
        with col_st1:
            st.subheader("Official Live Standings")
            cols_to_view = ["Bowler", "Average", "Starting Lane", "Game 1", "Game 2", "Game 3", "Scratch_Total", "Total_HDCP", "Grand_Total"]
            st.dataframe(standings[[c for c in cols_to_view if c in standings.columns]], use_container_width=True)

        with col_st2:
            st.subheader("Leaderboard Stats")
            top_b = standings.iloc[0]["Bowler"] if not standings.empty else "None"
            top_sc = standings.iloc[0]["Grand_Total"] if not standings.empty else 0
            st.metric("Tournament Leader", top_b, delta=f"{top_sc} Pins")
            
            pdf_standings = export_standings_pdf(standings, st.session_state.tournament_config)
            st.download_button("📄 Download Official PDF Standings", data=pdf_standings, file_name="Official_Standings.pdf", mime="application/pdf", use_container_width=True)

# ---------------------------------------------------------
# 17. VIEW: ADVANCED MODE — STEPLADDER FINALS
# ---------------------------------------------------------
elif "Stepladder Finals" in nav:
    st.markdown("### 🏆 Championship Stepladder Finals")
    conn = get_sqlite_conn()
    df_sl = pd.read_sql_query("SELECT * FROM live_roster", conn)
    conn.close()

    df_sl = df_sl.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3", "game_4": "Game 4"})
    standings = compile_standings(df_sl)

    if len(standings) < 5:
        st.warning(f"Stepladder finals requires at least 5 registered bowlers with recorded scores (Current: {len(standings)}).")
    else:
        top_5 = standings.head(5)["Bowler"].tolist()
        champ = top_5[0]
        st.markdown(f"""
        <div style="background-color: #10b98120; border: 2px solid #10b981; border-radius: 10px; padding: 18px; text-align: center; margin-bottom: 20px;">
            <span style="font-size: 13px; text-transform: uppercase; color: #34d399; font-weight: 800;">Top Qualifier (#1 Seed)</span>
            <h1 style="color: #f8fafc; font-size: 32px; margin: 4px 0;">👑 {champ}</h1>
            <p style="color: #cbd5e1; font-size: 14px; margin: 0;">Grand Total Pinfall: <b>{standings.iloc[0]['Grand_Total']}</b></p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### 🪜 Stepladder Match Pairings")
        st.write(f"**Match 1 (4th vs 5th):** {top_5[3]} vs {top_5[4]}")
        st.write(f"**Match 2 (3rd vs Match 1 Winner):** {top_5[2]} vs [Winner of M1]")
        st.write(f"**Semifinal (2nd vs Match 2 Winner):** {top_5[1]} vs [Winner of M2]")
        st.write(f"**Championship Match:** {top_5[0]} vs [Semifinal Winner]")

# ---------------------------------------------------------
# 18. VIEW: ADVANCED MODE — BRACKETS & SIDE POTS
# ---------------------------------------------------------
elif "Side Action" in nav:
    st.markdown("### 💰 Side Action: 8-Bowler Brackets & Side Pots")
    t_brk, t_pot = st.tabs(["🌳 Elimination Brackets", "💵 High-Game & Series Pots"])

    with t_brk:
        conn = get_sqlite_conn()
        paid_bowlers = pd.read_sql_query("SELECT usbc_id FROM live_roster WHERE paid = 1", conn)["usbc_id"].tolist()
        conn.close()

        if len(paid_bowlers) < 8:
            st.warning(f"At least 8 paid bowlers required to seed an elimination bracket (Found: {len(paid_bowlers)}).")
        else:
            if st.button("🎲 Seed 8-Bowler Elimination Bracket", type="primary"):
                sampled = random.sample(paid_bowlers, 8)
                new_brk = {
                    "id": f"B-{len(st.session_state.brackets) + 1:02d}",
                    "type": "Handicap",
                    "fee": 5,
                    "seeds": sampled
                }
                st.session_state.brackets.append(new_brk)
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success("Bracket seeded successfully!")
                st.rerun()

        if st.session_state.brackets:
            st.write(f"**Active Brackets:** {len(st.session_state.brackets)}")
            for b in st.session_state.brackets:
                st.markdown(f"**Bracket {b['id']}** ({b['type']}) — Top Seed: {b['seeds'][0]}")

    with t_pot:
        st.subheader("High-Game & Series Pots")
        pot_fee = st.number_input("Side Pot Fee ($):", value=10, min_value=1)
        st.write(f"Standard $10 split: $3 Game 1, $3 Game 2, $3 Game 3, $1 Series.")

# ---------------------------------------------------------
# 19. VIEW: ADVANCED MODE — FINANCIAL & SMART RECONCILIATION
# ---------------------------------------------------------
elif "Financial & SMART Ledger" in nav:
    st.markdown("### 💵 Financial Reconciliation & USBC Rule 400 SMART Ledger")
    conn = get_sqlite_conn()
    df_fin = pd.read_sql_query("SELECT * FROM live_roster", conn)
    conn.close()

    df_fin = df_fin.rename(columns={"paid": "Paid"})
    fin = calculate_financial_summary(df_fin, st.session_state.tournament_config)

    c_f1, c_f2, c_f3, c_f4 = st.columns(4)
    with c_f1:
        st.metric("Paid Entries", fin["paid_count"])
    with c_f2:
        st.metric("Gross Revenue", f"${fin['gross_revenue']:,.2f}")
    with c_f3:
        st.metric("Lineage Owed", f"${fin['total_lineage']:,.2f}")
    with c_f4:
        st.metric("Net Prize / SMART Pool", f"${fin['net_prize_fund']:,.2f}")

    if "youth" in str(st.session_state.tournament_config.get("division", "")).lower():
        st.divider()
        st.subheader("USBC Rule 400 SMART Scholarship Export")
        standings = compile_standings(df_fin.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"}))
        smart_csv = generate_smart_scholarship_csv(standings, fin["net_prize_fund"])
        if smart_csv:
            st.download_button("📄 Download SMART Scholarship Submission (.csv)", data=smart_csv, file_name="SMART_Submission.csv", mime="text/csv", type="primary")

# ---------------------------------------------------------
# 20. VIEW: ABOUT & MEMORIAL DEDICATION
# ---------------------------------------------------------
elif "About & Dedication" in nav:
    st.markdown("### 🏛️ About Prism Lane Control")
    st.markdown("""
    **Prism Lane Control — Version 1.1 (Hybrid Cloud Architecture)**  
    *Cecil-Harford USBC Central Tournament Management Console*  
    **System Architect:** Scott Kramer  
    **Host Facilities:** Forest Hill Bowling Center, Harford Lanes, APG Bowling Center  
    
    ---
    ### 🕊️ Dedication
    > *This system is dedicated in loving memory of **Raymond Kramer**.*  
    > *Crafted with pride, technical precision, and enduring love for the sport of bowling.*
    """)

# ---------------------------------------------------------
# 21. VIEW: AUDIT LOG
# ---------------------------------------------------------
elif "TD Audit Log" in nav:
    st.markdown("### 📜 Official Tournament Desk Audit Trail")
    if not st.session_state.audit_trail:
        st.info("No audit records in current session.")
    else:
        st.dataframe(pd.DataFrame(st.session_state.audit_trail), use_container_width=True)

# ---------------------------------------------------------
# 22. VIEW: USER MANAGEMENT (ADMIN ONLY)
# ---------------------------------------------------------
elif "TD User Management" in nav:
    st.markdown("### ⚙️ Tournament Director & Staff Management (Argon2id)")
    users_df = fetch_users_df()
    st.dataframe(users_df[["username", "name", "role", "center_id", "preferred_mode", "status"]], use_container_width=True)
