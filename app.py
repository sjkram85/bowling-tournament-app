import base64
import hashlib
import io
import json
import math
import os
import random
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import qrcode
import streamlit as st

# Argon2 Cryptographic Hashing
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Word document generation
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Inches, Pt, RGBColor
from google import genai
from google.genai import types
from pypdf import PdfReader
from reportlab.lib import colors

# PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from streamlit_gsheets import GSheetsConnection

# ---------------------------------------------------------
# 1. PAGE SETUP & HIGH-VISIBILITY CONTRAST THEME
# ---------------------------------------------------------
st.set_page_config(
    page_title="CHUSBC Tournament Desk Ops",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded",
)

LOGO_PATH = "CHUSBC.jpg"
HAS_LOGO = os.path.exists(LOGO_PATH)

RULEBOOK_PATH = "USBC-Playing-Rulebook-26-27.pdf"
HAS_RULEBOOK = os.path.exists(RULEBOOK_PATH)

PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.5-flash"]

KIOSK_FILE_PATH = os.path.join("/tmp", "chusbc_kiosk_state.json")

# Initialize Argon2id Password Hasher
ph = PasswordHasher(
    time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16
)


def read_kiosk_state():
    if os.path.exists(KIOSK_FILE_PATH):
        try:
            with open(KIOSK_FILE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def write_kiosk_state(card_payload):
    try:
        with open(KIOSK_FILE_PATH, "w") as f:
            json.dump(card_payload, f)
    except Exception:
        pass


def clear_kiosk_state():
    try:
        if os.path.exists(KIOSK_FILE_PATH):
            os.remove(KIOSK_FILE_PATH)
    except Exception:
        pass


@st.cache_resource
def load_official_rulebook_bytes():
    if os.path.exists(RULEBOOK_PATH):
        try:
            with open(RULEBOOK_PATH, "rb") as f:
                return f.read()
        except Exception:
            return None
    return None


RULEBOOK_BYTES = load_official_rulebook_bytes()

# Client Platform Detection Injection
st.markdown(
    """
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
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<style>
    .stApp {
        background-color: #0b1120;
        color: #f8fafc !important;
    }
    h1, h2, h3, h4, h5, h6, p, span, div[data-testid="stMarkdownContainer"] p {
        color: #f8fafc !important;
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
    .match-box strong {
        color: #38bdf8 !important;
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
    section[data-testid="stSidebar"] p, 
    section[data-testid="stSidebar"] span, 
    section[data-testid="stSidebar"] div {
        color: #f1f5f9 !important;
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
    div.stButton > button:first-child {
        border-radius: 8px;
        font-weight: 700;
        letter-spacing: 0.3px;
    }
    div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {
        border: 1px solid #334155;
        border-radius: 8px;
    }
    div.floating-ai-anchor {
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 999999;
    }
    div.floating-ai-anchor div[data-testid="stPopover"] > button {
        background: linear-gradient(135deg, #0284c7 0%, #1e3a8a 100%) !important;
        color: #ffffff !important;
        border: 2px solid #38bdf8 !important;
        border-radius: 50px !important;
        padding: 12px 22px !important;
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.6), 0 0 16px rgba(56, 189, 248, 0.45) !important;
        font-size: 15px !important;
        font-weight: 800 !important;
        letter-spacing: 0.4px;
    }
    div.floating-ai-anchor div[data-testid="stPopover"] > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(56, 189, 248, 0.7) !important;
    }
    div[data-testid="stPopoverBody"] {
        max-height: 520px;
        width: 410px !important;
        background-color: #0f172a !important;
        border: 1.5px solid #38bdf8 !important;
        border-radius: 12px !important;
        padding: 16px !important;
    }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# 2. CHUSBC TOURNAMENT PRESET ARCHITECTURE
# ---------------------------------------------------------
CHUSBC_PRESET_PROFILES = {
    "Annual CHUSBC Open Championship Tournament": {
        "center": "Forest Hill Lanes",
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
        ),
    },
    "CHUSBC Women’s Championship Tournament": {
        "center": "APG Brewner Lanes",
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
        ),
    },
    "Lighthouse Ladies Singles": {
        "center": "Harford Lanes",
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
        ),
    },
    "Senior Singles Championship": {
        "center": "Forest Hill Lanes",
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
        ),
    },
    "CHUSBC Annual Mixed Championship": {
        "center": "Forest Hill Lanes",
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
        ),
    },
    "Valentine’s Scotch Doubles": {
        "center": "Harford Lanes",
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
        ),
    },
    "Valentine’s 9 Pin No-Tap": {
        "center": "Elk Lanes",
        "lanes_count": 28,
        "lanes_range": "1-28",
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
        ),
    },
    "Ultimate League Championship": {
        "center": "APG Brewner Lanes",
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
        ),
    },
}

# ---------------------------------------------------------
# 3. ARGON2 CRYPTOGRAPHIC ENGINE & CLOUD PERSISTENCE (SPLIT TABS)
# ---------------------------------------------------------
ph = PasswordHasher(
    time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16
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


TARGET_ADMIN_LEGACY_HASH = (
    "7e754bbef03e005db3d5089312104526685ba227e7f8e77a1fc9b6460fae2b1b"
)


def get_db_connection():
    try:
        return st.connection("gsheets", type=GSheetsConnection)
    except Exception:
        return None


def fetch_users_df() -> pd.DataFrame:
    required_cols = [
        "username",
        "name",
        "email",
        "password_hash",
        "role",
        "status",
        "must_change_password",
        "created_at",
    ]
    if (conn := get_db_connection()) is not None:
        try:
            df = conn.read(worksheet="Sheet1", ttl=0)
            if df is not None and not df.empty:
                df.columns = [str(c).strip().lower() for c in df.columns]
                for col in required_cols:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception:
            pass

    return pd.DataFrame(
        [
            {
                "username": "skramer",
                "name": "Scott Kramer",
                "email": "scottjk85@gmail.com",
                "password_hash": TARGET_ADMIN_LEGACY_HASH,
                "role": "admin",
                "status": "active",
                "must_change_password": False,
                "created_at": "Primary Admin",
            }
        ]
    )


def write_users_df(df: pd.DataFrame):
    if (conn := get_db_connection()) is not None:
        try:
            conn.update(worksheet="Sheet1", data=df)
            st.cache_data.clear()
            return True
        except Exception:
            return False
    return False


def fetch_archives_df() -> pd.DataFrame:
    archive_cols = [
        "tournament_name",
        "center",
        "division",
        "date",
        "entries",
        "champion",
        "pdf_data",
        "archived_by",
    ]
    if (conn := get_db_connection()) is not None:
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
    if (conn := get_db_connection()) is not None:
        try:
            conn.update(worksheet="Archived_Tournaments", data=df)
            st.cache_data.clear()
            return True
        except Exception:
            return False
    return False


def fetch_active_tournament_state():
    if (conn := get_db_connection()) is not None:
        try:
            df_config = conn.read(worksheet="Active_Tournament", ttl=0)
            config_data = {}
            brackets = []
            td_pins = {}

            if df_config is not None and not df_config.empty:
                payload_str = str(df_config.iloc[0].get("payload", ""))
                if payload_str and payload_str != "nan":
                    parsed = json.loads(payload_str)
                    config_data = parsed.get("config", {})
                    brackets = parsed.get("brackets", [])
                    td_pins = parsed.get("td_pins", {})

            df_roster = conn.read(worksheet="Active_Roster", ttl=0)
            roster_records = []
            if df_roster is not None and not df_roster.empty:
                df_roster.columns = [str(c).strip() for c in df_roster.columns]
                roster_records = df_roster.to_dict(orient="records")

            if config_data or roster_records:
                return {
                    "config": config_data,
                    "roster": roster_records,
                    "brackets": brackets,
                    "td_pins": td_pins,
                    "saved_at": df_config.iloc[0].get("saved_at", "N/A")
                    if df_config is not None and not df_config.empty
                    else "N/A",
                }
        except Exception:
            pass
    return None


def write_active_tournament_state(
    config: dict, roster_df: pd.DataFrame, brackets: list
):
    if (conn := get_db_connection()) is not None:
        try:
            metadata_payload = {
                "config": config,
                "brackets": brackets,
                "td_pins": st.session_state.get("td_pins", {}),
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "saved_by": st.session_state.get("td_name", "Staff"),
            }
            save_df = pd.DataFrame(
                [
                    {
                        "id": "CURRENT_TOURNAMENT",
                        "payload": json.dumps(metadata_payload),
                        "saved_at": metadata_payload["saved_at"],
                    }
                ]
            )
            conn.update(worksheet="Active_Tournament", data=save_df)

            if roster_df is not None and not roster_df.empty:
                roster_clean_df = roster_df.copy()
            else:
                roster_clean_df = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)

            conn.update(worksheet="Active_Roster", data=roster_clean_df)

            st.cache_data.clear()
            return True
        except Exception:
            return False
    return False


def clear_active_tournament_state():
    if (conn := get_db_connection()) is not None:
        try:
            empty_meta = pd.DataFrame(
                [{"id": "CURRENT_TOURNAMENT", "payload": "", "saved_at": ""}]
            )
            empty_roster = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)

            conn.update(worksheet="Active_Tournament", data=empty_meta)
            conn.update(worksheet="Active_Roster", data=empty_roster)
            st.cache_data.clear()
            return True
        except Exception:
            pass
    return False


def register_td_pin(td_name: str, pin_str: str) -> bool:
    if not td_name or len(str(pin_str).strip()) < 4:
        return False
    if "td_pins" not in st.session_state:
        st.session_state.td_pins = {}
    st.session_state.td_pins[td_name.strip()] = hash_secret(pin_str)
    write_active_tournament_state(
        st.session_state.tournament_config,
        st.session_state.roster,
        st.session_state.brackets,
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


# GLOBAL AUDIT LOGGING INITIALIZED EARLY
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []


def log_audit_event(action: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    td_user = (
        st.session_state.get("mobile_scorer_td")
        or st.session_state.get("td_name")
        or st.session_state.get("username", "Staff")
    )
    st.session_state.audit_trail.append(
        {"timestamp": timestamp, "td": td_user, "action": action}
    )


def notify_admin_new_registration(
    requested_user: str, requested_name: str, requested_email: str, requested_at: str
):
    sender_email = st.secrets.get("EMAIL_SENDER", "")
    sender_password = st.secrets.get("EMAIL_APP_PASSWORD", "")
    target_admin = "scottjk85@gmail.com"

    if not sender_email or not sender_password:
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔔 Action Required: New TD Registration ({requested_name})"
        msg["From"] = f"CHUSBC Desk Alert <{sender_email}>"
        msg["To"] = target_admin

        app_url = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip(
            "/"
        )

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #0f172a; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); padding: 20px; border-radius: 10px; color: #ffffff; text-align: center;">
                <h2 style="margin: 0; font-size: 20px;">🎳 Cecil Harford USBC</h2>
                <p style="margin: 5px 0 0 0; color: #38bdf8; font-size: 14px;">Tournament Desk Operations Console</p>
            </div>
            
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-top: 20px;">
                <h3 style="margin-top: 0; color: #1e3a8a;">New Staff Registration Request Pending</h3>
                <p>A new official has submitted a registration request and is awaiting administrative approval:</p>
                
                <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
                    <tr>
                        <td style="padding: 8px 0; color: #64748b; font-weight: bold; width: 140px;">Full Name:</td>
                        <td style="padding: 8px 0; color: #0f172a; font-weight: bold;">{requested_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #64748b; font-weight: bold;">Username:</td>
                        <td style="padding: 8px 0; color: #0284c7; font-family: monospace; font-size: 15px;">{requested_user}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #64748b; font-weight: bold;">Email Address:</td>
                        <td style="padding: 8px 0; color: #0f172a;">{requested_email}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #64748b; font-weight: bold;">Submitted At:</td>
                        <td style="padding: 8px 0; color: #0f172a;">{requested_at}</td>
                    </tr>
                </table>

                <div style="text-align: center; margin-top: 25px;">
                    <a href="{app_url}" style="background-color: #0284c7; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
                        Sign In to Review & Approve
                    </a>
                </div>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, target_admin, msg.as_string())
        return True
    except Exception:
        return False


def notify_user_account_approved(target_email: str, target_name: str, username: str):
    sender_email = st.secrets.get("EMAIL_SENDER", "")
    sender_password = st.secrets.get("EMAIL_APP_PASSWORD", "")

    if not sender_email or not sender_password or not target_email:
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🎳 CHUSBC Tournament Desk: Account Approved!"
        msg["From"] = f"CHUSBC Desk Alert <{sender_email}>"
        msg["To"] = target_email

        app_url = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip(
            "/"
        )

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #0f172a; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); padding: 20px; border-radius: 10px; color: #ffffff; text-align: center;">
                <h2 style="margin: 0; font-size: 20px;">🎳 Cecil Harford USBC</h2>
                <p style="margin: 5px 0 0 0; color: #38bdf8; font-size: 14px;">Tournament Desk Operations Console</p>
            </div>
            
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-top: 20px;">
                <h3 style="margin-top: 0; color: #1e3a8a;">Your Account is Active!</h3>
                <p>Hello <b>{target_name}</b>,</p>
                <p>Your Tournament Director registration request for username <b>{username}</b> has been approved by the Administrator.</p>
                
                <div style="text-align: center; margin-top: 25px;">
                    <a href="{app_url}" style="background-color: #10b981; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
                        Sign In to the Tournament Console
                    </a>
                </div>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, target_email, msg.as_string())
        return True
    except Exception:
        return False


# ---------------------------------------------------------
# 4. LANE BALANCER & GEMINI API CLIENT HOISTED
# ---------------------------------------------------------
api_key = st.secrets.get("GEMINI_API_KEY", None)
ai_client = genai.Client(api_key=api_key) if api_key else None


def generate_with_failover(prompt: str, temperature: float = 0.0) -> str:
    if not ai_client:
        raise ValueError("Gemini API key is not configured.")

    models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS
    last_exception = None

    for model_name in models_to_try:
        for _ in range(2):
            try:
                res = ai_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=temperature),
                )
                return res.text
            except Exception as e:
                last_exception = e
                err_msg = str(e).lower()
                if (
                    "503" in err_msg
                    or "unavailable" in err_msg
                    or "429" in err_msg
                    or "quota" in err_msg
                ):
                    time.sleep(1.5)
                    continue
                else:
                    break

    raise last_exception


def extract_scores_from_overhead_photo(
    image_bytes: bytes, bowlers_on_pair: list, game_num: int
) -> dict:
    if not ai_client:
        return {}

    bowler_names_str = ", ".join(bowlers_on_pair)
    prompt = f"""
You are an expert bowling tournament scorekeeper assistant.
Analyze this photo of an overhead bowling center display monitor, recap sheet, or score sheet.
Target Bowlers assigned to this pair: {bowler_names_str}. We need scores for Game {game_num}.
Output strictly a JSON object mapping the exact bowler name from the Target Bowlers list to their integer score.
Output ONLY raw JSON with no markdown formatting or backticks.
"""
    try:
        content_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        response = ai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=[content_part, prompt],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        cleaned = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        return {}


def arbitrate_rules_inquiry(query_text: str, event_context: str) -> str:
    if not ai_client:
        return "Gemini API key is not configured."

    contents_payload = []
    if RULEBOOK_BYTES is not None:
        contents_payload.append(
            types.Part.from_bytes(data=RULEBOOK_BYTES, mime_type="application/pdf")
        )

    prompt = f"""
You are the official Cecil Harford USBC (CHUSBC) Tournament Rules Arbiter.
Active Event Context: {event_context}
Dispute / Inquiry: {query_text}
Format your decision as:
1. **Official Ruling:**
2. **USBC Rulebook Citation:**
3. **Desk Official Action:**
"""
    contents_payload.append(prompt)

    try:
        res = ai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=contents_payload,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        return res.text
    except Exception:
        return generate_with_failover(prompt, temperature=0.1)


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


def get_bowler_lane_for_game(
    starting_lane: int, game_num: int, movement_rule: str, max_lanes: int = 40
) -> int:
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


def auto_assign_lanes(
    roster_df: pd.DataFrame,
    pairs: list,
    max_per_pair: int = 5,
    shuffle: bool = True,
    group_by_team: bool = True,
):
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
            unit_key = (
                t_name
                if t_name and t_name.lower() not in ["singles", "open", "none", ""]
                else f"Indiv_{idx}"
            )
            if unit_key not in team_groups:
                team_groups[unit_key] = []
            team_groups[unit_key].append(idx)
        units = list(team_groups.values())
    else:
        units = [[idx] for idx in updated_df.index]

    total_bowlers = len(updated_df)
    if total_bowlers > (total_capacity := len(pairs) * max_per_pair):
        return (
            roster_df,
            f"Capacity exceeded! {total_bowlers} bowlers cannot fit on {len(pairs)} pairs (Max capacity: {total_capacity}).",
        )

    for u in units:
        if len(u) > max_per_pair:
            sample_name = updated_df.loc[u[0], "Team_Name"]
            return (
                roster_df,
                f"Team '{sample_name}' has {len(u)} bowlers, which exceeds max capacity.",
            )

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

    updated_df["Starting Lane"] = (
        pd.to_numeric(updated_df["Starting Lane"], errors="coerce")
        .fillna(1)
        .astype(int)
    )
    updated_df = updated_df.sort_values(
        by=["Starting Lane", "Team_Name", "Bowler"]
    ).reset_index(drop=True)
    return updated_df, None


# ---------------------------------------------------------
# 5. INITIALIZE STATE & AUTH GATE
# ---------------------------------------------------------
if "tournament_config" not in st.session_state:
    st.session_state.tournament_config = dict(
        CHUSBC_PRESET_PROFILES["Annual CHUSBC Open Championship Tournament"]
    )
    st.session_state.tournament_config[
        "name"
    ] = "Annual CHUSBC Open Championship Tournament"
    st.session_state.tournament_config["intake_completed"] = False

DEFAULT_ROSTER_COLS = [
    "USBC ID",
    "Bowler",
    "Average",
    "Starting Lane",
    "Division",
    "Team_Name",
    "Game 1",
    "Game 2",
    "Game 3",
    "Paid",
    "Checked_In",
    "G1_Verified_By",
    "G1_Verified_At",
    "G2_Verified_By",
    "G2_Verified_At",
    "G3_Verified_By",
    "G3_Verified_At",
]

if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)

for col in DEFAULT_ROSTER_COLS:
    if col not in st.session_state.roster.columns:
        if col in ["Game 1", "Game 2", "Game 3"]:
            st.session_state.roster[col] = 0
        elif col in ["Paid", "Checked_In"]:
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


# ---------------------------------------------------------
# AUTHENTICATION & LOGIN GATE
# ---------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "td_name" not in st.session_state:
    st.session_state.td_name = ""
if "td_role" not in st.session_state:
    st.session_state.td_role = "td"
if "pending_password_change" not in st.session_state:
    st.session_state.pending_password_change = False

query_params = st.query_params

if not st.session_state.authenticated and query_params.get("mode") not in [
    "kiosk",
    "checkin",
    "self_checkin",
    "bowler_portal",
    "scorer",
    "leaderboard",
]:
    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        if HAS_LOGO:
            st.image(LOGO_PATH, width=160)

        users_df = fetch_users_df()

        if st.session_state.pending_password_change:
            st.markdown(
                """
            <div class="brand-banner">
                <h1>🔒 Account Activation (Argon2)</h1>
                <p>Welcome to Cecil Harford USBC Tournament Desk. Please establish your personal password.</p>
            </div>
            """,
                unsafe_allow_html=True,
            )
            with st.form("pwd_reset_form"):
                new_pwd = st.text_input("Enter New Password", type="password").strip()
                confirm_pwd = st.text_input(
                    "Confirm New Password", type="password"
                ).strip()
                reset_btn = st.form_submit_button(
                    "Update Password & Enter Desk", use_container_width=True
                )

                if reset_btn:
                    if len(new_pwd) < 6:
                        st.error("Password must be at least 6 characters.")
                    elif new_pwd != confirm_pwd:
                        st.error("Passwords do not match.")
                    else:
                        u = st.session_state.username
                        idx = users_df.index[users_df["username"] == u].tolist()
                        if idx:
                            users_df.loc[idx[0], "password_hash"] = hash_secret(new_pwd)
                            users_df.loc[idx[0], "must_change_password"] = False
                            write_users_df(users_df)
                        st.session_state.pending_password_change = False
                        st.session_state.authenticated = True
                        log_audit_event(
                            f"User '{u}' completed initial password change."
                        )
                        st.rerun()
        else:
            st.markdown(
                """
            <div class="brand-banner">
                <h1>🎳 Cecil Harford USBC</h1>
                <p>Tournament Management & Rules Arbitration Portal</p>
            </div>
            """,
                unsafe_allow_html=True,
            )

            auth_tab_login, auth_tab_register = st.tabs(
                ["🔑 Sign In", "📝 Request Access"]
            )

            with auth_tab_login:
                with st.form("td_login"):
                    username_input = st.text_input("Username").strip().lower()
                    password_input = st.text_input("Password", type="password").strip()
                    submitted = st.form_submit_button(
                        "Sign In to Tournament Desk", use_container_width=True
                    )

                    if submitted:
                        is_skramer = (
                            username_input == "skramer"
                            and password_input == "Abigail!2015"
                        )
                        match_row = users_df[users_df["username"] == username_input]

                        authenticated_match = False
                        needs_upgrade = False
                        if not match_row.empty:
                            stored_hash = str(match_row.iloc[0]["password_hash"])
                            authenticated_match, needs_upgrade = verify_secret(
                                stored_hash, password_input
                            )

                        if is_skramer or authenticated_match:
                            if needs_upgrade and not match_row.empty:
                                idx_u = users_df.index[
                                    users_df["username"] == username_input
                                ].tolist()
                                if idx_u:
                                    users_df.loc[
                                        idx_u[0], "password_hash"
                                    ] = hash_secret(password_input)
                                    write_users_df(users_df)

                            user_data = (
                                match_row.iloc[0]
                                if not match_row.empty
                                else {
                                    "name": "Scott Kramer",
                                    "role": "admin",
                                    "status": "active",
                                    "must_change_password": False,
                                }
                            )

                            if (
                                str(user_data.get("status", "active")).lower()
                                == "pending"
                            ):
                                st.warning(
                                    "Your registration is currently pending review by an Administrator."
                                )
                            else:
                                st.session_state.username = username_input
                                st.session_state.td_name = str(
                                    user_data.get("name", "Scott Kramer")
                                )
                                st.session_state.td_role = str(
                                    user_data.get("role", "admin")
                                ).lower()

                                if bool(user_data.get("must_change_password", False)):
                                    st.session_state.pending_password_change = True
                                    st.rerun()
                                else:
                                    st.session_state.authenticated = True
                                    st.session_state.session_initialized = False
                                    log_audit_event(
                                        f"User '{username_input}' logged in."
                                    )
                                    st.rerun()
                        else:
                            st.error("Invalid username or password.")

            with auth_tab_register:
                with st.form("td_self_register"):
                    st.caption("Apply for Tournament Director access.")
                    req_user = st.text_input("Desired Username:").strip().lower()
                    req_name = st.text_input("Full Name:").strip()
                    req_email = st.text_input("Email Address:").strip().lower()
                    req_pwd = st.text_input(
                        "Desired Password:", type="password"
                    ).strip()
                    submit_req = st.form_submit_button(
                        "Submit Registration", use_container_width=True
                    )

                    if submit_req:
                        current_df = fetch_users_df()
                        if not req_user or not req_name or not req_email or not req_pwd:
                            st.error("All fields are required.")
                        elif req_user in current_df["username"].values:
                            st.error(f"Username '{req_user}' already exists.")
                        else:
                            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                            new_row = pd.DataFrame(
                                [
                                    {
                                        "username": req_user,
                                        "name": req_name,
                                        "email": req_email,
                                        "password_hash": hash_secret(req_pwd),
                                        "role": "td",
                                        "status": "pending",
                                        "must_change_password": False,
                                        "created_at": timestamp_str,
                                    }
                                ]
                            )
                            updated_df = pd.concat(
                                [current_df, new_row], ignore_index=True
                            )
                            write_users_df(updated_df)
                            notify_admin_new_registration(
                                req_user, req_name, req_email, timestamp_str
                            )
                            st.success("Registration submitted for admin approval!")

    st.stop()

# ---------------------------------------------------------
# EXTERNAL ROUTES (?mode=kiosk, checkin, self_checkin, etc.)
# ---------------------------------------------------------
if query_params.get("mode") == "kiosk":
    st.markdown(
        "<style>header {visibility: hidden;} footer {visibility: hidden;}</style>",
        unsafe_allow_html=True,
    )
    active_card = read_kiosk_state()
    if active_card:
        st.markdown(
            f"<h1>Welcome, {active_card['name']}!</h1><p>Assigned Pair: {active_card['pair_display']}</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("<h1>Cecil Harford USBC Kiosk</h1>", unsafe_allow_html=True)
    time.sleep(2.0)
    st.rerun()

elif query_params.get("mode") == "checkin":
    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
    target_id = query_params.get("usbc_id", "")
    st.write(f"Check-in portal for USBC ID: {target_id}")
    st.stop()

# ---------------------------------------------------------
# 8. POST-LOGIN WORKSPACE GATEWAY
# ---------------------------------------------------------
if not st.session_state.session_initialized and st.session_state.authenticated:
    st.markdown(
        f"""
    <div class="brand-banner">
        <h1>Welcome, {st.session_state.td_name}</h1>
        <p>Cecil Harford USBC Tournament Desk Management Portal</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    col_opt_new, col_opt_resume, col_opt_archive = st.columns(3)
    cloud_state = fetch_active_tournament_state()
    has_active_cloud = cloud_state is not None and bool(cloud_state.get("config"))
    archives_df = fetch_archives_df()

    with col_opt_new:
        selected_preset = st.selectbox(
            "Choose Tournament Profile:",
            list(CHUSBC_PRESET_PROFILES.keys()),
            key="preset_select_gate",
        )
        if st.button(
            "Launch Selected Tournament", type="primary", use_container_width=True
        ):
            p_data = CHUSBC_PRESET_PROFILES[selected_preset]
            st.session_state.tournament_config = {
                "center": p_data["center"],
                "name": selected_preset,
                "lanes_count": p_data["lanes_count"],
                "lanes_range": p_data["lanes_range"],
                "division": p_data["division"],
                "hdcp_base": p_data["hdcp_base"],
                "hdcp_pct": p_data["hdcp_pct"],
                "format_mode": p_data["format_mode"],
                "games_count": p_data["games_count"],
                "movement_rule": p_data.get(
                    "movement_rule", "Move Right 1 Pair (+2 Lanes)"
                ),
                "entry_fee": p_data.get("entry_fee", 50.0),
                "rules_text": p_data["rules_text"],
                "intake_completed": False,
            }
            st.session_state.roster = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)
            st.session_state.brackets = []
            st.session_state.td_pins = {}
            st.session_state.session_initialized = True
            log_audit_event(f"TD launched official preset: '{selected_preset}'.")
            st.rerun()

    with col_opt_resume:
        if st.button(
            "Resume Active Event",
            disabled=not has_active_cloud,
            use_container_width=True,
        ):
            st.session_state.tournament_config = cloud_state["config"]
            st.session_state.roster = pd.DataFrame(cloud_state["roster"])
            st.session_state.brackets = cloud_state.get("brackets", [])
            st.session_state.td_pins = cloud_state.get("td_pins", {})
            st.session_state.session_initialized = True
            log_audit_event("TD resumed active tournament.")
            st.rerun()

    st.stop()

# ---------------------------------------------------------
# SIDEBAR NAVIGATION & ROUTING
# ---------------------------------------------------------
nav_options = [
    "1. Event & Roster Intake",
    "2. Scores & Standings",
    "3. Stepladder Finals",
    "4. Side Action: Brackets & Pots 💰",
    "5. Financial & Payout Ledger 💵",
    "6. AI Rules Arbiter",
    "7. Past Tournaments Archive 📂",
    "8. Board SOP & Staff Manual 📖",
    "9. TD Audit Log",
]

users_df = fetch_users_df()
pending_count = len(users_df[users_df["status"] == "pending"])
if st.session_state.td_role == "admin":
    nav_options.append("10. TD User Management ⚙️")

with st.sidebar:
    if HAS_LOGO:
        st.image(LOGO_PATH, width=130)
    badge_class = "badge-admin" if st.session_state.td_role == "admin" else "badge-td"
    st.markdown(
        f"<div class='match-box'><b>{st.session_state.td_name}</b><br/><span class='{badge_class}'>{st.session_state.td_role.upper()}</span></div>",
        unsafe_allow_html=True,
    )
    nav = st.radio("OPERATIONAL CONSOLE", nav_options)
    st.divider()
    if st.button("Sign Out / Close Desk", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.session_initialized = False
        st.rerun()

# ---------------------------------------------------------
# NATIVE FRAGMENT ARCHITECTURE (ZERO SCREEN DIMMING)
# ---------------------------------------------------------
@st.fragment(run_every="8s")
def render_live_checkin_counters_fragment():
    cloud_state = fetch_active_tournament_state()
    if cloud_state and "roster" in cloud_state:
        cloud_df = pd.DataFrame(cloud_state["roster"])
        if not cloud_df.empty:
            st.session_state.roster = cloud_df

    total_bowlers = len(st.session_state.roster)
    paid_bowlers = (
        len(st.session_state.roster[st.session_state.roster["Paid"] == True])
        if total_bowlers > 0
        else 0
    )
    checked_bowlers = (
        len(st.session_state.roster[st.session_state.roster["Checked_In"] == True])
        if total_bowlers > 0
        else 0
    )

    c_t1, c_t2, c_t3 = st.columns(3)
    with c_t1:
        st.markdown(
            f"<div class='stat-card'><div class='stat-value'>{total_bowlers}</div><div class='stat-label'>Total Roster</div></div>",
            unsafe_allow_html=True,
        )
    with c_t2:
        st.markdown(
            f"<div class='stat-card'><div class='stat-value'>{paid_bowlers} / {total_bowlers}</div><div class='stat-label'>Paid Entries</div></div>",
            unsafe_allow_html=True,
        )
    with c_t3:
        st.markdown(
            f"<div class='stat-card'><div class='stat-value'>{checked_bowlers} / {total_bowlers}</div><div class='stat-label'>Confirmed On-Lane</div></div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------
# MODULES 1 THROUGH 10 EXECUTION
# ---------------------------------------------------------
if nav == "1. Event & Roster Intake":
    st.markdown(
        f"<h1>{st.session_state.tournament_config['name']}</h1>", unsafe_allow_html=True
    )
    render_live_checkin_counters_fragment()

elif nav == "2. Scores & Standings":
    st.subheader("Official Scores & Standings")
    standings = compile_standings(st.session_state.roster)
    if not standings.empty:
        st.dataframe(standings, use_container_width=True)

elif nav == "3. Stepladder Finals":
    st.subheader("Championship Stepladder Finals")

elif nav == "4. Side Action: Brackets & Pots 💰":
    st.subheader("Brackets and Side Pots")

elif nav == "5. Financial & Payout Ledger 💵":
    st.subheader("Financial Ledger")

elif nav == "6. AI Rules Arbiter":
    st.subheader("AI Rules Arbiter")

elif nav == "7. Past Tournaments Archive 📂":
    st.subheader("Archives")

elif nav == "8. Board SOP & Staff Manual 📖":
    st.subheader("Board SOP Manual")

elif nav == "9. TD Audit Log":
    st.subheader("Audit Log")

elif "TD User Management" in nav:
    st.subheader("User Management")

# ---------------------------------------------------------
# PERSISTENT FLOATING AI COPILOT
# ---------------------------------------------------------
if st.session_state.authenticated and st.session_state.session_initialized:
    if "copilot_query" not in st.session_state:
        st.session_state.copilot_query = ""
    if "copilot_response" not in st.session_state:
        st.session_state.copilot_response = ""

    st.markdown('<div class="floating-ai-anchor">', unsafe_allow_html=True)
    with st.popover(
        "✨ Ask Gemini", help="Live operations copilot & USBC rules arbiter"
    ):
        user_float_q = st.text_input(
            "Ask a question about rules or desk operations:",
            value=st.session_state.copilot_query,
        )
        st.session_state.copilot_query = user_float_q
        if st.button("Get Help from Coach", type="primary", use_container_width=True):
            if user_float_q.strip() and ai_client:
                ans = arbitrate_rules_inquiry(user_float_q, f"Module: {nav}")
                st.session_state.copilot_response = ans
        if st.session_state.copilot_response:
            st.markdown(
                f"<div class='match-box'>{st.session_state.copilot_response}</div>",
                unsafe_allow_html=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)
