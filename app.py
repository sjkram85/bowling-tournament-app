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
# 1. PAGE SETUP, ASSETS & HIGH-CONTRAST CROSS-BROWSER THEME
# ---------------------------------------------------------
st.set_page_config(
    page_title="Prism Lane Control v1.1 — CHUSBC",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded"
)

LOGO_CHUSBC_PATH = "CHUSBC.jpg"
HAS_CHUSBC_LOGO = os.path.exists(LOGO_CHUSBC_PATH)

LOGO_FOREST_HILL_PATH = "forest hill lanes.png"
HAS_FOREST_HILL_LOGO = os.path.exists(LOGO_FOREST_HILL_PATH)

# Fallback alias for document generation engines
LOGO_PATH = LOGO_CHUSBC_PATH
HAS_LOGO = HAS_CHUSBC_LOGO

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
        "badge": "🏛️ CHUSBC Central Desk",
        "logo_path": LOGO_CHUSBC_PATH,
        "has_logo": HAS_CHUSBC_LOGO
    },
    "forest_hill": {
        "name": "Forest Hill Bowling Center",
        "tagline": "Host Center • Forest Hill, MD",
        "accent": "#10b981",
        "badge": "🎳 Forest Hill Lanes",
        "logo_path": LOGO_FOREST_HILL_PATH,
        "has_logo": HAS_FOREST_HILL_LOGO
    },
    "harford": {
        "name": "Harford Lanes",
        "tagline": "Host Center • Aberdeen, MD",
        "accent": "#f59e0b",
        "badge": "🎳 Harford Lanes",
        "logo_path": LOGO_CHUSBC_PATH,
        "has_logo": HAS_CHUSBC_LOGO
    },
    "apg": {
        "name": "APG Bowling Center",
        "tagline": "Host Center • Aberdeen Proving Ground",
        "accent": "#ec4899",
        "badge": "🎳 APG Brewner Lanes",
        "logo_path": LOGO_CHUSBC_PATH,
        "has_logo": HAS_CHUSBC_LOGO
    }
}

# Enforce clean high-contrast dark theme & eliminate cross-browser input washouts
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
        padding: 20px 24px;
        margin-bottom: 20px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.45);
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
        padding: 20px;
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
# 3. ARGON2ID SECURITY & HYBRID PERSISTENCE BRIDGE
# ---------------------------------------------------------
ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)

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

def write_active_tournament_state(config: dict, roster_df: pd.DataFrame, brackets: list, sync_to_cloud: bool = False):
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

if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    td_user = st.session_state.get("mobile_scorer_td") or st.session_state.get("td_name") or st.session_state.get("username", "Staff")
    st.session_state.audit_trail.append({"timestamp": timestamp, "td": td_user, "action": action})

# ---------------------------------------------------------
# 4. CHUSBC PRESET ARCHITECTURE
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
        "rules_text": "USBC Certified. 3 Games across assigned pairs. Handicap: 90% of 220. All prize fees returned 100%."
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
        "rules_text": "USBC Certified. Open to female USBC members of Cecil Harford USBC. Handicap: 90% of 220."
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
        "rules_text": "Lighthouse Ladies Singles. 3 qualifying games into top 5 stepladder. Handicap: 90% of 215."
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
        "rules_text": "USBC Certified Senior Singles. Age 50+. Separate payout funds per age bracket."
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
        "rules_text": "CHUSBC Mixed Championship. 4-person team (2M/2W) and Doubles (1M/1W). Handicap: 90% of 220."
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
        "rules_text": "2 bowlers per team, alternating deliveries. Combined team handicap 90% of 430."
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
        "rules_text": "Valentine's 9-Pin No-Tap. 9 on first ball equals automatic strike. 90% of 220 handicap."
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
        "rules_text": "Invitational TOC for CHUSBC winter league winning teams. 3 qualifying into single-elimination bracket."
    }
}

# ---------------------------------------------------------
# 5. LANE BALANCER & CALCULATIONS
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
            return roster_df, "Unable to fit teams evenly across active pairs."

    for p, row_indices in pair_buckets.items():
        lane_odd, lane_even = p
        for order_on_pair, r_idx in enumerate(row_indices):
            assigned_lane = lane_odd if (order_on_pair % 2 == 0) else lane_even
            updated_df.loc[r_idx, "Starting Lane"] = int(assigned_lane)

    updated_df["Starting Lane"] = pd.to_numeric(updated_df["Starting Lane"], errors="coerce").fillna(1).astype(int)
    return updated_df.sort_values(by=["Starting Lane", "Team_Name", "Bowler"]).reset_index(drop=True), None

def calculate_handicap(avg: int, base: int = None, percentage: float = None) -> int:
    if base is None:
        base = int(st.session_state.tournament_config.get("hdcp_base", 220))
    if percentage is None:
        percentage = float(st.session_state.tournament_config.get("hdcp_pct", 0.90))
    return 0 if avg >= base else math.floor(percentage * (base - avg))

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
    active_games = ["Game 1", "Game 2", "Game 3"] if games_count <= 3 else ["Game 1", "Game 2", "Game 3", "Game 4"]
    calc_df["Scratch_Total"] = calc_df[[g for g in active_games if g in calc_df.columns]].sum(axis=1)
    calc_df["Grand_Total"] = calc_df["Scratch_Total"] + calc_df["Total_HDCP"]
    calc_df["High_Scratch_Game"] = calc_df[[g for g in active_games if g in calc_df.columns]].max(axis=1)

    calc_df = calc_df.sort_values(by=["Grand_Total", "High_Scratch_Game", "Scratch_Total"], ascending=[False, False, False]).reset_index(drop=True)
    calc_df.index += 1
    calc_df.index.name = "Rank"
    return calc_df

def calculate_financial_summary(roster_df: pd.DataFrame, config: dict, lineage_per_game: float = 3.75, games_count: int = 3) -> dict:
    if roster_df.empty:
        return {"paid_count": 0, "gross_revenue": 0.0, "total_lineage": 0.0, "net_prize_fund": 0.0}
    paid_count = len(roster_df[roster_df["Paid"] == True])
    entry_fee_total = float(config.get("entry_fee", 50.0))
    gross_revenue = paid_count * entry_fee_total
    total_lineage = paid_count * (lineage_per_game * games_count)
    expense_fee = paid_count * 5.00
    net_prize_fund = gross_revenue - (total_lineage + expense_fee)
    return {
        "paid_count": paid_count, "gross_revenue": gross_revenue,
        "total_lineage": total_lineage, "net_prize_fund": max(0.0, net_prize_fund)
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

def get_report_logo_path(config: dict) -> tuple[str, bool]:
    center_name = str(config.get("center", "")).lower()
    if "forest hill" in center_name and HAS_FOREST_HILL_LOGO:
        return LOGO_FOREST_HILL_PATH, True
    if HAS_CHUSBC_LOGO:
        return LOGO_CHUSBC_PATH, True
    return "", False

def export_lane_assignments_pdf(roster_df: pd.DataFrame, config: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []
    title_style = ParagraphStyle("RosterTitle", parent=styles["Heading1"], fontSize=14, leading=17, textColor=colors.HexColor("#0f172a"), spaceAfter=2)
    header_text = f"""
    <b>Cecil Harford USBC — Official Lane Assignment & Check-In Roster</b><br/>
    <font size="8" color="#475569">
    Event: {config['name']} | Host: {config['center']} | Division: {config['division']}<br/>
    Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')} | TD on Duty: {st.session_state.get('td_name', 'Official')}
    </font>
    """
    pdf_logo_file, has_pdf_logo = get_report_logo_path(config)
    if has_pdf_logo:
        logo_img = RLImage(pdf_logo_file, width=50, height=50)
        header_table = Table([[logo_img, Paragraph(header_text, title_style)]], colWidths=[60, 480])
        header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story.append(header_table)
    else:
        story.append(Paragraph("Cecil Harford USBC — Lane Assignment Roster", title_style))

    if not roster_df.empty:
        df_sorted = roster_df.copy()
        df_sorted["Starting Lane"] = pd.to_numeric(df_sorted.get("Starting Lane", 1), errors="coerce").fillna(1).astype(int)
        df_sorted["Pair_Low"] = df_sorted["Starting Lane"].apply(lambda l: l if l % 2 != 0 else l - 1)
        grouped = df_sorted.groupby("Pair_Low")
        for pair_low, group_df in sorted(grouped, key=lambda x: x[0]):
            pair_name = f"Lanes {int(pair_low)} & {int(pair_low + 1)}"
            p_header = ParagraphStyle("PairHeader", parent=styles["Heading2"], fontSize=10, leading=12, textColor=colors.white)
            pair_table_data = [[Paragraph(f"<b>{pair_name}</b>", p_header), "", "", "", "", "", ""]]
            pair_table_data.append(["Lane", "Bowler Name", "Team / Affiliation", "Avg", "Paid", "Check-in", "Scores (G1 / G2 / G3)"])
            for _, row in group_df.sort_values(by=["Starting Lane", "Bowler"]).iterrows():
                paid = "Yes" if bool(row.get("Paid", False)) else "[  ]"
                checked = "Yes" if bool(row.get("Checked_In", False)) else "[  ]"
                pair_table_data.append([str(row["Starting Lane"]), str(row["Bowler"]), str(row.get("Team_Name", "Singles")), str(row["Average"]), paid, checked, "___ / ___ / ___"])
            pt = Table(pair_table_data, colWidths=[32, 130, 110, 32, 38, 48, 150])
            pt.setStyle(TableStyle([
                ("SPAN", (0, 0), (6, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#0284c7")),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.white),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
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
    title_style = ParagraphStyle("DocTitle", parent=styles["Heading1"], fontSize=14, leading=17, textColor=colors.HexColor("#0f172a"), spaceAfter=2)
    header_text = f"""
    <b>Cecil Harford USBC — {config['name']} Standings</b><br/>
    <font size="8" color="#475569">
    Host: {config['center']} | Division: {config['division']} | Lanes: {config['lanes_range']}<br/>
    TD on Duty: {st.session_state.get('td_name', 'Official')} | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')}
    </font>
    """
    pdf_logo_file, has_pdf_logo = get_report_logo_path(config)
    if has_pdf_logo:
        logo_img = RLImage(pdf_logo_file, width=50, height=50)
        header_table = Table([[logo_img, Paragraph(header_text, title_style)]], colWidths=[60, 480])
        header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
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
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 6. DEDICATED TV DISPLAY ROUTE (?mode=display_tv)
# ---------------------------------------------------------
query_params = st.query_params
if query_params.get("mode") == "display_tv":
    st.markdown("""
    <style>
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container { padding: 1.5rem !important; max-width: 100% !important; }
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
# 7. SCREEN-AWARE PRISM AI ENGINE (CONTEXT ARBITER)
# ---------------------------------------------------------
api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    with st.sidebar:
        api_key = st.text_input("Gemini API Key", type="password")

ai_client = genai.Client(api_key=api_key) if api_key else None

def ask_prism_ai(query_text: str, runtime_context: dict) -> str:
    if not ai_client:
        return "Prism AI is offline. Please configure a valid Gemini API key."
    prompt = f"""
You are "Prism AI", the tournament desk assistant for the Cecil-Harford USBC (CHUSBC).
You are assisting Tournament Director or volunteer '{runtime_context.get('user', 'Staff')}'.

ACTIVE TOURNAMENT RUNTIME CONTEXT:
- Operating Mode: {runtime_context.get('mode', 'Advanced')}
- Active Screen / Module: {runtime_context.get('screen', 'Main')}
- Event Name: {runtime_context.get('event_name', 'CHUSBC Tournament')}
- Host Center: {runtime_context.get('center', 'Forest Hill Bowling Center')}
- Active Lane Range: {runtime_context.get('lane_range', '1-40')}
- Current Field: {runtime_context.get('total_bowlers', 0)} Bowlers ({runtime_context.get('paid_bowlers', 0)} Paid, {runtime_context.get('checked_bowlers', 0)} Checked In)

USER INQUIRY / REQUEST:
"{query_text}"

INSTRUCTIONS FOR PRISM AI:
1. Screen-Aware Guidance: If the user asks what to do next or how to proceed, reference the exact tabs or buttons on their CURRENT screen ({runtime_context.get('screen')}) in {runtime_context.get('mode')} mode.
2. USBC Rules Arbitration: If they ask about an on-lane dispute or USBC statute (e.g. Rule 10 tardiness, Rule 17 ball surface, Rule 18 gripping holes, or Rule 400 SMART scholarships), provide:
   - **Immediate Ruling:** Clear verdict on what stands.
   - **USBC Rulebook Citation:** Official rule section.
   - **Exact Next Step:** What button or input to adjust right now.
3. Tone: Direct, supportive, professional, and concise. Avoid technical database jargon.
"""
    try:
        res = ai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        return res.text
    except Exception as e:
        return f"Prism AI consultation error: {e}"

# ---------------------------------------------------------
# 8. TD AUTHENTICATION & LOGIN (ARGON2ID & NO TIMEOUT)
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
        if HAS_CHUSBC_LOGO:
            st.image(LOGO_CHUSBC_PATH, width=160)
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
                if not match_row.empty:
                    stored_hash = str(match_row.iloc[0]["password_hash"])
                    authenticated_match, _ = verify_secret(stored_hash, password_input)

                if is_skramer or authenticated_match:
                    user_data = match_row.iloc[0] if not match_row.empty else {
                        "name": "Scott Kramer", "role": "admin", "center_id": "association", "preferred_mode": "Advanced"
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
# 9. WORKSPACE GATEWAY & POST-LOGIN SETUP
# ---------------------------------------------------------
if not st.session_state.session_initialized:
    active_brand = CENTER_PROFILES.get(st.session_state.center_id, CENTER_PROFILES["association"])
    st.markdown(f"""
    <div class="brand-banner" style="border-color: {active_brand['accent']};">
        <h1>Welcome, {st.session_state.td_name}</h1>
        <p>{active_brand['name']} • {active_brand['tagline']}</p>
    </div>
    """, unsafe_allow_html=True)

    col_opt_new, col_opt_custom, col_opt_resume = st.columns(3)
    cloud_state = fetch_active_tournament_state()
    has_active_cloud = cloud_state is not None and bool(cloud_state.get("config"))

    with col_opt_new:
        st.markdown("""
        <div class="choice-card">
            <h3 style="color: #38bdf8; margin-top: 0;">🚀 Official Presets</h3>
            <p style="font-size: 14px; color: #cbd5e1;">Calibrate instantly with official Cecil Harford USBC annual tournament profiles.</p>
        </div>
        """, unsafe_allow_html=True)
        selected_preset = st.selectbox("Choose Profile:", list(CHUSBC_PRESET_PROFILES.keys()), key="preset_select_gate")
        if st.button("Launch Preset Tournament", type="primary", use_container_width=True):
            p_data = CHUSBC_PRESET_PROFILES[selected_preset]
            st.session_state.tournament_config = dict(p_data)
            st.session_state.tournament_config["name"] = selected_preset
            st.session_state.tournament_config["intake_completed"] = False
            st.session_state.roster = pd.DataFrame(columns=["USBC ID", "Bowler", "Average", "Starting Lane", "Division", "Team_Name", "Game 1", "Game 2", "Game 3", "Game 4", "Paid", "Checked_In"])
            st.session_state.brackets = []
            st.session_state.session_initialized = True
            log_audit_event(f"TD launched official preset: '{selected_preset}'.")
            st.rerun()

    with col_opt_custom:
        st.markdown("""
        <div class="choice-card">
            <h3 style="color: #fbbf24; margin-top: 0;">✨ Custom Tournament</h3>
            <p style="font-size: 14px; color: #cbd5e1;">Configure a custom blank-slate event for sweepers, marathons, or special brackets.</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        if st.button("Create Custom Event", use_container_width=True):
            st.session_state.tournament_config = {
                "center": active_brand["name"], "name": "New CHUSBC Custom Event",
                "lanes_count": 40, "lanes_range": "1-40", "division": "Open Scratch/Handicap",
                "hdcp_base": 220, "hdcp_pct": 0.90, "format_mode": "Custom Format",
                "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)",
                "entry_fee": 50.0, "rules_text": "USBC Rules apply. 100% prize return."
            }
            st.session_state.roster = pd.DataFrame(columns=["USBC ID", "Bowler", "Average", "Starting Lane", "Division", "Team_Name", "Game 1", "Game 2", "Game 3", "Game 4", "Paid", "Checked_In"])
            st.session_state.brackets = []
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
            st.session_state.session_initialized = True
            log_audit_event(f"TD resumed active tournament: '{active_title}'.")
            st.rerun()
    st.stop()

# ---------------------------------------------------------
# 10. SIDEBAR CONSOLE & STREAMLINED PRISM AI
# ---------------------------------------------------------
active_center_id = st.session_state.get("center_id", "association")
brand_info = CENTER_PROFILES.get(active_center_id, CENTER_PROFILES["association"])

with st.sidebar:
    if brand_info["has_logo"]:
        st.image(brand_info["logo_path"], use_container_width=True)
    elif HAS_CHUSBC_LOGO:
        st.image(LOGO_CHUSBC_PATH, width=130)

    st.markdown(f"""
    <div style="background-color: #1e293b; padding: 12px; border-radius: 8px; border: 1.5px solid {brand_info['accent']}; margin-bottom: 12px;">
        <div style="font-size: 14px; font-weight: 700; color: #f1f5f9;">{st.session_state.td_name}</div>
        <div style="margin-top: 4px;"><span class="badge-td" style="border-color: {brand_info['accent']}; color: {brand_info['accent']} !important;">{brand_info['badge']}</span></div>
    </div>
    """, unsafe_allow_html=True)

    desk_mode = st.radio(
        "DESK OPERATING MODE",
        ["Volunteer Mode (Easy)", "Tournament Director (Advanced)"],
        index=0 if st.session_state.preferred_mode == "Easy" else 1
    )

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
            "7. Past Tournaments Archive 📂",
            "8. TD Audit Log"
        ]
        if st.session_state.td_role == "admin":
            nav_options.append("9. TD User Management ⚙️")

    nav = st.radio("OPERATIONAL CONSOLE", nav_options)
    st.divider()

    # Streamlined Screen-Aware Prism AI
    with st.expander("✨ Prism AI Assistant", expanded=False):
        conn_ai = get_sqlite_conn()
        ai_roster_df = pd.read_sql_query("SELECT paid, checked_in FROM live_roster", conn_ai)
        conn_ai.close()

        total_b = len(ai_roster_df)
        paid_b = int(ai_roster_df["paid"].sum()) if total_b > 0 else 0
        checked_b = int(ai_roster_df["checked_in"].sum()) if total_b > 0 else 0
        current_screen_name = nav

        st.markdown(f"""
        <div style="background-color: #0f172a; border-left: 3px solid #38bdf8; padding: 6px 10px; border-radius: 6px; margin-bottom: 8px;">
            <span style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700;">Active Screen:</span><br/>
            <span style="font-size: 13px; font-weight: 800; color: #f8fafc;">{current_screen_name}</span><br/>
            <span style="font-size: 11px; color: #34d399;">{desk_mode.split(' ')[0]} Mode • {checked_b}/{total_b} On Lane</span>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🧭 What should I do next on this screen?", use_container_width=True, key="btn_ai_next"):
            st.session_state["prism_ai_query"] = f"What are my immediate next steps on '{current_screen_name}' in {desk_mode}?"

        ai_in = st.text_input("Ask Prism AI:", value=st.session_state.get("prism_ai_query", ""), placeholder="e.g. Next steps, tardy rule, sub swap...", key="in_ai_box")
        st.session_state["prism_ai_query"] = ai_in

        if st.button("Consult Prism AI", type="primary", use_container_width=True, key="btn_run_ai"):
            if ai_in.strip():
                runtime_ctx = {
                    "user": st.session_state.get("td_name", "Staff"),
                    "mode": desk_mode, "screen": current_screen_name,
                    "event_name": st.session_state.tournament_config.get("name", "CHUSBC Event"),
                    "center": st.session_state.tournament_config.get("center", "Forest Hill Bowling Center"),
                    "lane_range": st.session_state.tournament_config.get("lanes_range", "1-40"),
                    "total_bowlers": total_b, "paid_bowlers": paid_b, "checked_bowlers": checked_b
                }
                with st.spinner("Prism AI analyzing active screen..."):
                    st.session_state["prism_ai_response"] = ask_prism_ai(ai_in, runtime_ctx)

        if st.session_state.get("prism_ai_response"):
            st.markdown(f"""
            <div style="background-color: #1e293b; border: 1px solid #334155; border-left: 3px solid #38bdf8; padding: 10px; border-radius: 6px; font-size: 12.5px; margin-top: 8px; color: #f8fafc;">
                {st.session_state['prism_ai_response']}
            </div>
            """, unsafe_allow_html=True)
            if st.button("Clear Response", key="btn_clr_ai", use_container_width=True):
                st.session_state["prism_ai_response"] = ""
                st.session_state["prism_ai_query"] = ""
                st.rerun()

    st.markdown("### ☁️ Cloud Backup & Sync")
    col_sync, col_reset = st.columns(2)
    with col_sync:
        if st.button("🚀 Push to Sheets", type="primary", use_container_width=True, help="Force sync local data to Google Sheets cloud"):
            saved = write_active_tournament_state(
                st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets, sync_to_cloud=True
            )
            if saved:
                st.toast("✅ Master cloud sync complete!", icon="☁️")
                log_audit_event("TD pushed live operations state to Google Sheets cloud.")
    with col_reset:
        if st.button("Switch Event", use_container_width=True):
            st.session_state.session_initialized = False
            st.rerun()

    st.write("")
    if st.button("Sign Out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.username = ""
        st.rerun()

    st.divider()
    with st.popover("ℹ️ About Prism Lane Control", use_container_width=True):
        st.markdown("""
        ### 🎳 Prism Lane Control
        **Version:** 1.1 (Hybrid Cloud Architecture)  
        **System Architect:** Scott Kramer  
        **Association:** Cecil-Harford United States Bowling Congress (CHUSBC)  
        **Host Facilities:** Forest Hill Bowling Center, Harford Lanes, APG Bowling Center  

        ---
        ### 🕊️ Dedication
        > *This platform is dedicated in loving memory of **Raymond Kramer**.*  
        > *Built with pride, precision, and enduring love for the sport of bowling.*
        """)

# Co-Branded Dual Header Banner
def render_branded_header():
    col_l1, col_l2, col_title = st.columns([1, 1, 6])
    with col_l1:
        if HAS_CHUSBC_LOGO:
            st.image(LOGO_CHUSBC_PATH, width=80)
    with col_l2:
        if brand_info.get("has_logo") and brand_info["logo_path"] != LOGO_CHUSBC_PATH:
            st.image(brand_info["logo_path"], width=80)
    with col_title:
        st.markdown(f"""
        <div style="padding-left: 10px;">
            <h2 style="margin: 0; color: #f8fafc;">{st.session_state.tournament_config['name']}</h2>
            <p style="margin: 2px 0 0 0; color: {brand_info['accent']}; font-weight: 700;">{brand_info['name']} • {brand_info['tagline']}</p>
        </div>
        """, unsafe_allow_html=True)
    st.markdown(f"<hr style='border: 1px solid {brand_info['accent']}40; margin: 12px 0 20px 0;'/>", unsafe_allow_html=True)

# ---------------------------------------------------------
# 11. VIEW: EASY MODE (ACCESSIBLE TOURNAMENT DIRECTOR)
# ---------------------------------------------------------
if desk_mode.startswith("Volunteer") or desk_mode.startswith("Easy"):
    render_branded_header()
    easy_tabs = st.tabs(["1. Check-In & Payments", "2. Add Bowler / Assign Lane", "3. Enter Game Scores", "4. Print Standings"])

    with easy_tabs[0]:
        st.subheader("Bowler Arrival & Payment Check-In")
        conn = get_sqlite_conn()
        df_roster = pd.read_sql_query("SELECT usbc_id, bowler, starting_lane, average, paid, checked_in FROM live_roster ORDER BY starting_lane, bowler", conn)
        conn.close()

        if df_roster.empty and not st.session_state.roster.empty:
            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
            conn = get_sqlite_conn()
            df_roster = pd.read_sql_query("SELECT usbc_id, bowler, starting_lane, average, paid, checked_in FROM live_roster ORDER BY starting_lane, bowler", conn)
            conn.close()

        if df_roster.empty:
            st.info("📋 **No active bowler roster loaded for this event yet.**\nTap **'2. Add Bowler / Assign Lane'** or switch to TD mode to initialize entries.")
        else:
            col_search, col_filter = st.columns([2, 1])
            with col_search:
                search_term = st.text_input("🔍 Search Bowler by Name:", placeholder="Type a name to filter...").strip().lower()
            with col_filter:
                show_unpaid_only = st.checkbox("Show Unpaid Only", value=False)

            filtered_df = df_roster.copy()
            if search_term:
                filtered_df = filtered_df[filtered_df["bowler"].str.lower().str.contains(search_term)]
            if show_unpaid_only:
                filtered_df = filtered_df[filtered_df["paid"] == 0]

            for _, row in filtered_df.iterrows():
                b_id = row["usbc_id"]
                b_name = row["bowler"]
                b_lane = row["starting_lane"]
                b_avg = row["average"]
                b_paid = bool(row["paid"])
                b_checked = bool(row["checked_in"])
                pair_low = b_lane if b_lane % 2 != 0 else b_lane - 1
                pair_label = f"Lanes {pair_low}-{pair_low + 1} (Lane {b_lane})"

                card_border = "#10b981" if (b_paid and b_checked) else "#f59e0b" if b_paid else "#ef4444"
                status_desc = "Ready on Lane" if (b_paid and b_checked) else "Paid, Not Checked In" if b_paid else "Payment Due"

                c_info, c_action = st.columns([3, 2])
                with c_info:
                    st.markdown(f"""
                    <div style="background-color: #1e293b; border-left: 6px solid {card_border}; padding: 12px 16px; border-radius: 8px; margin-bottom: 8px;">
                        <span style="font-size: 18px; font-weight: 800; color: #f8fafc;">{b_name}</span>
                        <span style="font-size: 13px; color: #94a3b8; margin-left: 10px;">Avg: <b>{b_avg}</b> | Assigned: <b>{pair_label}</b></span><br/>
                        <span style="font-size: 12px; font-weight: 700; color: {card_border};">STATUS: {status_desc.upper()}</span>
                    </div>
                    """, unsafe_allow_html=True)
                with c_action:
                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        btn_paid_label = "Mark Paid" if not b_paid else "Unmark Paid"
                        if st.button(btn_paid_label, key=f"ez_p_{b_id}", use_container_width=True):
                            c = get_sqlite_conn()
                            c.execute("UPDATE live_roster SET paid = ? WHERE usbc_id = ?", (0 if b_paid else 1, b_id))
                            c.commit()
                            c.close()
                            st.rerun()
                    with col_b2:
                        btn_check_label = "Check In" if not b_checked else "Remove Check-In"
                        if st.button(btn_check_label, key=f"ez_c_{b_id}", type="primary" if not b_checked else "secondary", use_container_width=True):
                            c = get_sqlite_conn()
                            c.execute("UPDATE live_roster SET checked_in = ? WHERE usbc_id = ?", (0 if b_checked else 1, b_id))
                            c.commit()
                            c.close()
                            st.rerun()

    with easy_tabs[1]:
        st.subheader("Register Bowler & Assign Lane")
        with st.form("ez_add_bowler"):
            col_a1, col_a2 = st.columns(2)
            with col_a1:
                new_b_name = st.text_input("Bowler Full Name:", placeholder="e.g. John Smith").strip()
                new_b_avg = st.number_input("Entering Average:", min_value=50, max_value=300, value=190, step=1)
            with col_a2:
                new_b_usbc = st.text_input("USBC ID (Optional):", placeholder="e.g. 11-12345").strip() or f"W-{datetime.now().strftime('%M%S')}"
                parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
                pair_options = [f"Lanes {p[0]}-{p[1]} (Lane {p[0]})" for p in parsed_pairs] or ["Lane 1"]
                assigned_pair_selection = st.selectbox("Assign Starting Lane:", pair_options)

            col_opt1, col_opt2 = st.columns(2)
            with col_opt1:
                mark_paid_now = st.checkbox("Mark Entry Fee Paid ($50.00)", value=True)
            with col_opt2:
                mark_checked_now = st.checkbox("Check In Bowler Immediately", value=True)

            if st.form_submit_button("Add Bowler to Tournament Roster", type="primary", use_container_width=True):
                if new_b_name:
                    assigned_lane_num = int(assigned_pair_selection.split("Lane ")[-1].replace(")", ""))
                    c = get_sqlite_conn()
                    c.execute("""
                        INSERT INTO live_roster (usbc_id, bowler, average, starting_lane, division, team_name, paid, checked_in, last_updated_by)
                        VALUES (?, ?, ?, ?, 'Open', 'Singles', ?, ?, ?)
                    """, (new_b_usbc, new_b_name, new_b_avg, assigned_lane_num, 1 if mark_paid_now else 0, 1 if mark_checked_now else 0, st.session_state.username))
                    c.commit()
                    c.close()
                    log_audit_event(f"Easy Mode: Added bowler '{new_b_name}' on Lane {assigned_lane_num}.")
                    st.success(f"{new_b_name} added successfully on Lane {assigned_lane_num}!")
                    st.rerun()

    with easy_tabs[2]:
        st.subheader("Post & Adjust Game Scores")
        conn = get_sqlite_conn()
        bowlers_df = pd.read_sql_query("SELECT usbc_id, bowler, starting_lane, average, game_1, game_2, game_3 FROM live_roster ORDER BY starting_lane, bowler", conn)
        conn.close()

        if bowlers_df.empty:
            st.info("No bowlers found. Register entries in Tab 2 first.")
        else:
            selected_bowler_for_score = st.selectbox("Select Bowler to Score:", bowlers_df["bowler"].tolist())
            b_data = bowlers_df[bowlers_df["bowler"] == selected_bowler_for_score].iloc[0]
            st.markdown(f"<div class='match-box'>Scoring: <b>{selected_bowler_for_score}</b> (Lane {b_data['starting_lane']} | Entering Avg: {b_data['average']})</div>", unsafe_allow_html=True)

            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                ez_g1 = st.number_input("Game 1 Score:", min_value=0, max_value=300, value=int(b_data["game_1"]))
            with col_s2:
                ez_g2 = st.number_input("Game 2 Score:", min_value=0, max_value=300, value=int(b_data["game_2"]))
            with col_s3:
                ez_g3 = st.number_input("Game 3 Score:", min_value=0, max_value=300, value=int(b_data["game_3"]))

            hdcp_per_game = calculate_handicap(int(b_data["average"]))
            scratch_series = ez_g1 + ez_g2 + ez_g3
            total_with_hdcp = scratch_series + (hdcp_per_game * 3)
            st.write(f"**Scratch Series:** {scratch_series} | **Handicap Total:** {total_with_hdcp} (+{hdcp_per_game * 3} HDCP)")

            if st.button("Save Scores", type="primary", use_container_width=True):
                c = get_sqlite_conn()
                c.execute("""
                    UPDATE live_roster 
                    SET game_1 = ?, game_2 = ?, game_3 = ?, last_updated_by = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE usbc_id = ?
                """, (ez_g1, ez_g2, ez_g3, st.session_state.username, b_data["usbc_id"]))
                c.commit()
                c.close()
                log_audit_event(f"Easy Mode: Updated scores for '{selected_bowler_for_score}' ({ez_g1}, {ez_g2}, {ez_g3}).")
                st.success(f"Scores saved for {selected_bowler_for_score}!")
                st.rerun()

    with easy_tabs[3]:
        st.subheader("Step 3: Current Standings")
        conn = get_sqlite_conn()
        df_for_print = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        if not df_for_print.empty:
            calc_input = df_for_print.rename(columns={"usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "starting_lane": "Starting Lane", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"})
            standings = compile_standings(calc_input)
            st.dataframe(standings[["Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Scratch_Total", "Total_HDCP", "Grand_Total"]], use_container_width=True)

            col_p1, col_p2 = st.columns(2)
            with col_p1:
                pdf_bytes = export_standings_pdf(standings, st.session_state.tournament_config)
                st.download_button("📄 Print Current Standings (PDF)", data=pdf_bytes, file_name="Standings.pdf", mime="application/pdf", type="primary", use_container_width=True)
            with col_p2:
                roster_pdf_bytes = export_lane_assignments_pdf(calc_input, st.session_state.tournament_config)
                st.download_button("📄 Print Lane Sheet (PDF)", data=roster_pdf_bytes, file_name="Lane_Sheet.pdf", mime="application/pdf", use_container_width=True)

# ---------------------------------------------------------
# 12. VIEW: ADVANCED MODE — FULL DIRECTOR SUITE
# ---------------------------------------------------------
else:
    render_branded_header()

    if nav == "1. Event & Roster Intake":
        tab_set, tab_rost, tab_bal = st.tabs(["⚙️ Event Settings", "📝 Tournament Roster Ingestion", "🎳 40-Lane Balancer"])
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
                st.session_state.tournament_config.update({"name": t_title, "center": t_center, "games_count": g_count, "lanes_range": l_range, "entry_fee": e_fee})
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success("Configuration updated!")

        with tab_rost:
            st.subheader("Tournament Roster Ingestion")
            pasted_text = st.text_area("Paste signup list (USBC ID, Name, Avg, Team):", placeholder="11-12345, Scott Kramer, 218, Striking Power\n11-23456, Dave Miller, 205, Striking Power")
            if st.button("Parse & Ingest Roster", type="primary"):
                if pasted_text.strip():
                    new_records = []
                    for idx, line in enumerate(pasted_text.strip().split("\n")):
                        parts = [p.strip() for p in line.split(",")]
                        new_records.append({
                            "USBC ID": parts[0] if len(parts) > 0 and parts[0] else f"B-{100+idx}",
                            "Bowler": parts[1] if len(parts) > 1 else f"Bowler {idx+1}",
                            "Average": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 200,
                            "Starting Lane": 1, "Division": "Open", "Team_Name": parts[3] if len(parts) > 3 else "Singles",
                            "Paid": True, "Checked_In": True
                        })
                    st.session_state.roster = pd.DataFrame(new_records)
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success(f"Ingested {len(new_records)} bowlers into operational engine!")
                    st.rerun()

        with tab_bal:
            st.subheader("Team-Aware Automated Lane Balancer")
            active_p = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
            if st.button("⚡ Balance & Assign Lanes", type="primary"):
                balanced, err = auto_assign_lanes(st.session_state.roster, active_p, max_per_pair=5, shuffle=True, group_by_team=True)
                if not err:
                    st.session_state.roster = balanced
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success("Lanes balanced across active pairs!")
                    st.rerun()

    elif nav == "2. Visual Lane Matrix & Subs":
        st.markdown("### 🎳 Visual Center Pair Matrix & Substitutions")
        parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
        conn = get_sqlite_conn()
        roster_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        col_vm, col_sub = st.columns([2, 1])
        with col_vm:
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
                orig_bowler = st.selectbox("Original Bowler:", roster_live["bowler"].tolist())
                sub_name = st.text_input("Replacement Name:").strip()
                sub_avg = st.number_input("Sub Average:", value=190, step=1)
                if st.button("Execute Substitution", type="primary", use_container_width=True):
                    orig_lane = int(roster_live[roster_live["bowler"] == orig_bowler].iloc[0]["starting_lane"])
                    conn = get_sqlite_conn()
                    conn.execute("UPDATE live_roster SET checked_in = 0, team_name = team_name || ' (Subbed)' WHERE bowler = ?", (orig_bowler,))
                    conn.execute("""
                        INSERT INTO live_roster (usbc_id, bowler, average, starting_lane, division, team_name, paid, checked_in, is_sub, subbing_for, last_updated_by)
                        VALUES (?, ?, ?, ?, 'Open', 'Singles', 1, 1, 1, ?, ?)
                    """, (f"SUB-{datetime.now().strftime('%M%S')}", sub_name, sub_avg, orig_lane, orig_bowler, st.session_state.username))
                    conn.commit()
                    conn.close()
                    log_audit_event(f"Substituted '{sub_name}' for '{orig_bowler}' on Lane {orig_lane}.")
                    st.success(f"{sub_name} subbed in on Lane {orig_lane}!")
                    st.rerun()

    elif nav == "3. Scores & Standings":
        conn = get_sqlite_conn()
        df_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()
        if not df_live.empty:
            df_for_calc = df_live.rename(columns={"usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "starting_lane": "Starting Lane", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3", "game_4": "Game 4"})
            standings = compile_standings(df_for_calc)
            st.dataframe(standings[["Bowler", "Average", "Starting Lane", "Game 1", "Game 2", "Game 3", "Scratch_Total", "Total_HDCP", "Grand_Total"]], use_container_width=True)
            pdf_standings = export_standings_pdf(standings, st.session_state.tournament_config)
            st.download_button("📄 Download Official PDF Standings", data=pdf_standings, file_name="Standings.pdf", mime="application/pdf")

    elif nav == "4. Stepladder Finals":
        conn = get_sqlite_conn()
        df_sl = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()
        df_sl = df_sl.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"})
        standings = compile_standings(df_sl)
        if len(standings) >= 5:
            top_5 = standings.head(5)["Bowler"].tolist()
            st.markdown(f"<div style='background-color: #10b98120; border: 2px solid #10b981; border-radius: 10px; padding: 18px; text-align: center;'><h1 style='color: #f8fafc; margin: 0;'>👑 #1 Seed: {top_5[0]}</h1></div>", unsafe_allow_html=True)
            st.write(f"**Match 1 (4th vs 5th):** {top_5[3]} vs {top_5[4]}")
            st.write(f"**Match 2 (3rd vs M1 Winner):** {top_5[2]} vs [Winner M1]")
            st.write(f"**Semifinal (2nd vs M2 Winner):** {top_5[1]} vs [Winner M2]")
            st.write(f"**Championship:** {top_5[0]} vs [Semifinal Winner]")

    elif nav == "5. Side Action: Brackets & Pots 💰":
        conn = get_sqlite_conn()
        paid_bowlers = pd.read_sql_query("SELECT usbc_id FROM live_roster WHERE paid = 1", conn)["usbc_id"].tolist()
        conn.close()
        if len(paid_bowlers) >= 8:
            if st.button("🎲 Seed 8-Bowler Elimination Bracket", type="primary"):
                sampled = random.sample(paid_bowlers, 8)
                st.session_state.brackets.append({"id": f"B-{len(st.session_state.brackets)+1:02d}", "type": "Handicap", "seeds": sampled})
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success("Bracket seeded!")
                st.rerun()
        if st.session_state.brackets:
            st.write(f"**Active Brackets:** {len(st.session_state.brackets)}")

    elif nav == "6. Financial & SMART Ledger 💵":
        conn = get_sqlite_conn()
        df_fin = pd.read_sql_query("SELECT * FROM live_roster", conn).rename(columns={"paid": "Paid"})
        conn.close()
        fin = calculate_financial_summary(df_fin, st.session_state.tournament_config)
        c_f1, c_f2, c_f3, c_f4 = st.columns(4)
        c_f1.metric("Paid Entries", fin["paid_count"])
        c_f2.metric("Gross Revenue", f"${fin['gross_revenue']:,.2f}")
        c_f3.metric("Lineage Owed", f"${fin['total_lineage']:,.2f}")
        c_f4.metric("Net Prize Pool", f"${fin['net_prize_fund']:,.2f}")

    elif nav == "7. Past Tournaments Archive 📂":
        st.info("Archive module ready.Concluded tournaments are archived to Google Sheets.")

    elif nav == "8. TD Audit Log":
        st.subheader("Official Tournament Desk Audit Trail")
        st.dataframe(pd.DataFrame(st.session_state.audit_trail), use_container_width=True)

    elif "TD User Management" in nav:
        st.subheader("Tournament Staff Management (Argon2id)")
        st.dataframe(fetch_users_df()[["username", "name", "role", "center_id", "preferred_mode", "status"]], use_container_width=True)
