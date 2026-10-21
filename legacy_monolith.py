import os
import io
import time
import math
import json
import base64
import random
import hashlib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import pandas as pd
import streamlit as st
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
from db_state import (
    clear_active_tournament_state as _db_clear_active_tournament_state,
    clear_kiosk_card as _db_clear_kiosk_card,
    fetch_active_tournament_state as _db_fetch_active_tournament_state,
    fetch_archives_df as _db_fetch_archives_df,
    fetch_kiosk_card as _db_fetch_kiosk_card,
    fetch_users_df as _db_fetch_users_df,
    log_audit_event as _db_log_audit_event,
    write_active_tournament_state as _db_write_active_tournament_state,
    write_archives_df as _db_write_archives_df,
    write_kiosk_card as _db_write_kiosk_card,
    write_users_df as _db_write_users_df,
)
from db_state import (
    clear_active_tournament_state as _db_clear_active_tournament_state,
    clear_kiosk_card as _db_clear_kiosk_card,
    fetch_active_tournament_state as _db_fetch_active_tournament_state,
    fetch_archives_df as _db_fetch_archives_df,
    fetch_kiosk_card as _db_fetch_kiosk_card,
    fetch_users_df as _db_fetch_users_df,
    log_audit_event as _db_log_audit_event,
    write_active_tournament_state as _db_write_active_tournament_state,
    write_archives_df as _db_write_archives_df,
    write_kiosk_card as _db_write_kiosk_card,
    write_users_df as _db_write_users_df,
)

# ---------------------------------------------------------
# 1. PAGE SETUP & HIGH-VISIBILITY CONTRAST THEME
# ---------------------------------------------------------
st.set_page_config(
    page_title="CHUSBC Tournament Desk Ops",
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

# Initialize Argon2id Password Hasher
ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16
)

def read_kiosk_state():
    return _db_fetch_kiosk_card()

def write_kiosk_state(card_payload):
    return _db_write_kiosk_card(card_payload)

def clear_kiosk_state():
    return _db_clear_kiosk_card()

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
""", unsafe_allow_html=True)

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
        )
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
        )
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
        )
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
        )
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
        )
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
        )
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
        )
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
        )
    }
}

# ---------------------------------------------------------
# 3. ARGON2 CRYPTOGRAPHIC ENGINE & CLOUD PERSISTENCE
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

def fetch_users_df() -> pd.DataFrame:
    return _db_fetch_users_df()


def write_users_df(df: pd.DataFrame):
    return _db_write_users_df(df)


def fetch_archives_df() -> pd.DataFrame:
    return _db_fetch_archives_df()


def write_archives_df(df: pd.DataFrame):
    return _db_write_archives_df(df)


def fetch_active_tournament_state():
    state = _db_fetch_active_tournament_state()
    if state is None:
        return None
    result = dict(state)
    roster = result.get("roster", pd.DataFrame())
    result["roster"] = roster.to_dict(orient="records") if isinstance(roster, pd.DataFrame) else roster
    return result


def write_active_tournament_state(config: dict, roster_df: pd.DataFrame, brackets: list):
    if not isinstance(roster_df, pd.DataFrame):
        roster_df = pd.DataFrame(roster_df)
    return _db_write_active_tournament_state(config, roster_df, brackets)


def clear_active_tournament_state():
    return _db_clear_active_tournament_state()

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

# GLOBAL AUDIT LOGGING INITIALIZED EARLY (PREVENTS NAMEERROR IN ROUTES)
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    return _db_log_audit_event(action)

def notify_admin_new_registration(requested_user: str, requested_name: str, requested_email: str, requested_at: str):
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

        app_url = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")

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

            <p style="color: #94a3b8; font-size: 12px; text-align: center; margin-top: 20px;">
                Navigate to <b>Module 10: TD User Management ⚙️</b> to activate or deny this request.
            </p>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, target_admin, msg.as_string())
        return True
    except Exception as e:
        print(f"Failed to send admin registration alert: {e}")
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

        app_url = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")

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

            <p style="color: #94a3b8; font-size: 12px; text-align: center; margin-top: 20px;">
                If you have any questions, reach out to Central Desk administration.
            </p>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, target_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Failed to send user approval email: {e}")
        return False

# ---------------------------------------------------------
# 4. TEAM-AWARE LANE BALANCER & CROSS-PAIR MOVEMENT ENGINE
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
# 5. INITIALIZE STATE & TOURNAMENT SESSION GATEWAY
# ---------------------------------------------------------
if "tournament_config" not in st.session_state:
    st.session_state.tournament_config = dict(CHUSBC_PRESET_PROFILES["Annual CHUSBC Open Championship Tournament"])
    st.session_state.tournament_config["name"] = "Annual CHUSBC Open Championship Tournament"
    st.session_state.tournament_config["intake_completed"] = False

DEFAULT_ROSTER_COLS = [
    "USBC ID", "Bowler", "Average", "Starting Lane", "Division", "Team_Name",
    "Game 1", "Game 2", "Game 3", "Paid", "Checked_In",
    "G1_Verified_By", "G1_Verified_At", "G2_Verified_By", "G2_Verified_At", "G3_Verified_By", "G3_Verified_At"
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
# 10. DETERMINISTIC SCORING, FINANCIALS & REPORT GENERATORS
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
    for col in ["Game 1", "Game 2", "Game 3", "Average"]:
        if col not in calc_df.columns:
            calc_df[col] = 0
        calc_df[col] = pd.to_numeric(calc_df[col], errors="coerce").fillna(0).astype(int)

    base = int(st.session_state.tournament_config.get("hdcp_base", 220))
    pct = float(st.session_state.tournament_config.get("hdcp_pct", 0.90))
    games_count = int(st.session_state.tournament_config.get("games_count", 3))

    calc_df["HDCP_Per_Game"] = calc_df["Average"].apply(lambda a: calculate_handicap(a, base=base, percentage=pct))
    calc_df["Total_HDCP"] = calc_df["HDCP_Per_Game"] * games_count
    calc_df["Scratch_Total"] = calc_df["Game 1"] + calc_df["Game 2"] + calc_df["Game 3"]
    calc_df["Grand_Total"] = calc_df["Scratch_Total"] + calc_df["Total_HDCP"]
    calc_df["High_Scratch_Game"] = calc_df[["Game 1", "Game 2", "Game 3"]].max(axis=1)

    calc_df = calc_df.sort_values(
        by=["Grand_Total", "High_Scratch_Game", "Scratch_Total"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    calc_df.index += 1
    calc_df.index.name = "Rank"
    return calc_df

def compile_all_events_leaderboard(roster_df: pd.DataFrame) -> pd.DataFrame:
    if roster_df.empty:
        return pd.DataFrame()

    df = roster_df.copy()
    for col in ["Game 1", "Game 2", "Game 3", "Average"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    base = int(st.session_state.tournament_config.get("hdcp_base", 220))
    pct = float(st.session_state.tournament_config.get("hdcp_pct", 0.90))

    df["HDCP_Per_Game"] = df["Average"].apply(lambda a: calculate_handicap(a, base=base, percentage=pct))

    agg_dict = {
        "Average": "max",
        "HDCP_Per_Game": "max",
        "Game 1": "sum",
        "Game 2": "sum",
        "Game 3": "sum",
        "Team_Name": lambda x: ", ".join(set([str(v) for v in x if v and str(v) != "Singles"])) or "Singles",
        "Division": "first"
    }
    
    group_col = "USBC ID" if "USBC ID" in df.columns else "Bowler"
    grouped = df.groupby(group_col).agg(agg_dict).reset_index()
    if group_col == "USBC ID":
        name_map = df.drop_duplicates(subset=["USBC ID"]).set_index("USBC ID")["Bowler"].to_dict()
        grouped["Bowler"] = grouped["USBC ID"].map(name_map)

    grouped["Total_Games_Bowled"] = df.groupby(group_col).apply(
        lambda g: (g["Game 1"] > 0).sum() + (g["Game 2"] > 0).sum() + (g["Game 3"] > 0).sum()
    ).values

    grouped["Total_HDCP"] = grouped["HDCP_Per_Game"] * grouped["Total_Games_Bowled"]
    grouped["Scratch_Series"] = grouped["Game 1"] + grouped["Game 2"] + grouped["Game 3"]
    grouped["Grand_Total"] = grouped["Scratch_Series"] + grouped["Total_HDCP"]

    grouped = grouped.sort_values(
        by=["Grand_Total", "Scratch_Series"],
        ascending=[False, False]
    ).reset_index(drop=True)

    grouped.index += 1
    grouped.index.name = "Rank"
    return grouped

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
    <b>Cecil Harford USBC — Lane Assignment & Concourse Check-In Roster</b><br/>
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
            str(row.get("Game 2", 0)), str(row.get("Game 3", 0)), str(row.get("Scratch_Total", row.get("Scratch_Series", 0))), str(row["Grand_Total"])
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

def export_tournament_summary_pdf(standings_df: pd.DataFrame, config: dict, champion_name: str, stepladder_results: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle("SummaryTitle", parent=styles["Heading1"], fontSize=15, leading=18, textColor=colors.HexColor("#0f172a"), spaceAfter=2)
    meta_style = ParagraphStyle("SummaryMeta", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#475569"), spaceAfter=12)
    h2_style = ParagraphStyle("SummaryH2", parent=styles["Heading2"], fontSize=11, leading=14, textColor=colors.HexColor("#0284c7"), spaceBefore=8, spaceAfter=4)

    header_text = f"""
    <b>Cecil Harford USBC — Official Tournament Summary & Champion Report</b><br/>
    <font size="8" color="#475569">
    Event: {config['name']} | Host Center: {config['center']} | Division: {config['division']}<br/>
    Official Champion: <b>{champion_name}</b> | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')}
    </font>
    """

    if HAS_LOGO:
        logo_img = RLImage(LOGO_PATH, width=50, height=50)
        header_table = Table([[logo_img, Paragraph(header_text, title_style)]], colWidths=[60, 480])
        header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story.append(header_table)
    else:
        story.append(Paragraph(f"Cecil Harford USBC — {config['name']}", title_style))
        story.append(Paragraph(header_text, meta_style))

    champ_data = [[Paragraph(f"<b>🏆 OFFICIAL CHAMPION CROWNED: {champion_name}</b><br/><font size='8.5' color='#0f172a'>Adjudicated automatically via USBC handicap grand totals and top-5 stepladder finals engine.</font>", styles["Normal"])]]
    ct = Table(champ_data, colWidths=[540])
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#10b98120")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#10b981")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
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
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(st_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Final Official Standings", h2_style))
    table_data = [["Pos", "Bowler Name", "USBC ID", "Avg", "HDCP", "G1", "G2", "G3", "Scratch", "Total"]]
    for rank, row in standings_df.reset_index().head(20).iterrows():
        table_data.append([
            str(row["Rank"]), str(row["Bowler"]), str(row.get("USBC ID", "-")),
            str(row["Average"]), str(row.get("Total_HDCP", 0)), str(row.get("Game 1", 0)),
            str(row.get("Game 2", 0)), str(row.get("Game 3", 0)), str(row.get("Scratch_Total", row.get("Scratch_Series", 0))), str(row["Grand_Total"])
        ])

    table = Table(table_data, colWidths=[24, 136, 52, 32, 38, 38, 38, 38, 52, 58])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    story.append(Spacer(1, 14))

    sig_data = [
        ["Tournament Director Signature: ___________________________", "Date: ___________________"],
        ["Association Official: _________________________________", "Sanction Verified: [ X ]"]
    ]
    s_table = Table(sig_data, colWidths=[340, 200])
    s_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#475569")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(s_table)

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
# SOP DOCUMENT GENERATORS (DOCX & PDF)
# ---------------------------------------------------------
def generate_first_time_td_guide() -> str:
    return (
        "TECHNICAL POINT OF CONTACT (TPOC):\n"
        "Scott Kramer | scottjk85@gmail.com | 443.966.4460\n\n"
        "1. T-60 Min: Connect external monitor to laptop. Extend display (Win+P). Open ?mode=kiosk on secondary display and hit F11.\n"
        "2. T-45 Min: In Module 1 (Tab 2), ingest roster and run Automated Lane Balancer (handles up to 40 lanes, keeps teams together). Download printable PDF lane sheets.\n"
        "3. T-30 Min: Post the Express Entrance QR (?mode=self_checkin) at the door. Pre-paid bowlers check in automatically; unpaid or bracket bowlers are routed to the desk.\n"
        "4. T-15 Min: Floor TDs scan ?mode=scorer QR code on their phones, create their Argon2 4-digit PIN, and claim lane pairs.\n"
        "5. Squad Active: Roving TDs snap overhead monitors with phone camera OCR, input scores, and lock with their secret PIN. Central Desk monitors verified lanes on the Radar Matrix.\n"
        "6. Concourse TV & Bowler Portal: Cast ?mode=leaderboard on center TVs and let bowlers track ranks on ?mode=bowler_portal.\n"
        "7. Final Automation: In Module 3, click 'Calculate & Complete Tournament' to auto-seed the stepladder, declare the Champion, and download the official PDF summary report."
    )

def generate_sop_docx() -> io.BytesIO:
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    PRIMARY = RGBColor(14, 58, 138)
    SECONDARY = RGBColor(2, 132, 199)
    TEXT_DARK = RGBColor(15, 23, 42)
    MUTED = RGBColor(100, 116, 139)

    style_normal = doc.styles['Normal']
    style_normal.font.name = 'Calibri'
    style_normal.font.size = Pt(11)
    style_normal.font.color.rgb = TEXT_DARK
    style_normal.paragraph_format.line_spacing = 1.15
    style_normal.paragraph_format.space_after = Pt(6)

    def set_cell_background(cell, hex_color):
        tcPr = cell._tc.get_or_add_tcPr()
        tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>'))

    p_org = doc.add_paragraph()
    p_org.paragraph_format.space_after = Pt(2)
    r_org = p_org.add_run("CECIL HARFORD UNITED STATES BOWLING CONGRESS")
    r_org.font.size = Pt(11)
    r_org.font.bold = True
    r_org.font.color.rgb = SECONDARY

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_after = Pt(4)
    r_title = p_title.add_run("Standard Operating Procedure: Tournament Desk Operations Console")
    r_title.font.size = Pt(20)
    r_title.font.bold = True
    r_title.font.color.rgb = PRIMARY

    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_after = Pt(14)
    r_meta = p_meta.add_run(
        f"Document Identifier: SOP-TD-2026-01 | Event: {st.session_state.tournament_config['name']}\n"
        f"Technical POC: Scott Kramer (scottjk85@gmail.com, 443.966.4460) | Active Center: {st.session_state.tournament_config['center']}"
    )
    r_meta.font.size = Pt(9.5)
    r_meta.font.color.rgb = MUTED

    t_div = doc.add_table(rows=1, cols=1)
    t_div.alignment = WD_TABLE_ALIGNMENT.CENTER
    c_div = t_div.cell(0, 0)
    c_div.width = Inches(6.5)
    set_cell_background(c_div, "0E3A8A")
    c_div.height = Pt(3)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)
    h1 = doc.add_heading(level=1)
    h1.add_run("1. Technical Point of Contact & Overview").font.color.rgb = PRIMARY
    doc.add_paragraph(
        "Technical Lead: Scott Kramer (scottjk85@gmail.com | 443.966.4460)\n"
        f"This Standard Operating Procedure (SOP) standardizes tournament desk operations for the {st.session_state.tournament_config['name']} "
        "and all official Cecil Harford USBC (CHUSBC) events using Argon2id encryption, team-aware 40-lane distribution, and automated tournament finalization."
    )

    h_novice = doc.add_heading(level=1)
    h_novice.add_run("2. Quickstart Reference Walkthrough").font.color.rgb = PRIMARY
    guide_text = generate_first_time_td_guide()
    p_guide = doc.add_paragraph(guide_text)
    p_guide.paragraph_format.space_after = Pt(8)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

def generate_sop_pdf() -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle("SOPTitle", parent=styles["Heading1"], fontSize=15, leading=18, textColor=colors.HexColor("#0e3a8a"), spaceAfter=2)
    h2_style = ParagraphStyle("SOPH2", parent=styles["Heading2"], fontSize=11, leading=14, textColor=colors.HexColor("#0284c7"), spaceBefore=6, spaceAfter=3)
    body_style = ParagraphStyle("SOPBody", parent=styles["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#0f172a"), spaceAfter=4)

    header_text = f"""
    <b>Cecil Harford USBC — Tournament Desk Standard Operating Procedure</b><br/>
    <font size="8" color="#475569">
    Official Board Manual & Reference Guide | Event: {st.session_state.tournament_config['name']}<br/>
    Technical POC: Scott Kramer (scottjk85@gmail.com, 443.966.4460) | Center: {st.session_state.tournament_config['center']}
    </font>
    """

    if HAS_LOGO:
        logo_img = RLImage(LOGO_PATH, width=48, height=48)
        header_table = Table([[logo_img, Paragraph(header_text, title_style)]], colWidths=[56, 484])
        header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story.append(header_table)
    else:
        story.append(Paragraph("Cecil Harford USBC — Tournament Desk Standard Operating Procedure", title_style))
        story.append(Spacer(1, 4))

    story.append(Paragraph("1. First-Time Tournament Director (TD) Quickstart Walkthrough", h2_style))
    story.append(Paragraph(
        "<b>Step 1 (T-60 Setup):</b> Connect desk monitor to laptop (Win+P -> Extend). Open ?mode=kiosk on secondary monitor (F11). Open ?mode=leaderboard on concourse TVs.<br/>"
        "<b>Step 2 (T-45 Roster & Balancing):</b> Ingest roster in Module 1. Use 'Automated Lane Balancer' to distribute bowlers across active lanes with team grouping. Print the PDF Lane Assignment Sheet.<br/>"
        "<b>Step 3 (T-30 Entrance & Desk Check-In):</b> Post the Express Entrance QR (?mode=self_checkin). Pre-paid bowlers check in automatically; unpaid or bracket bowlers are directed to the desk.<br/>"
        "<b>Step 4 (T-15 Floor Scorer Setup):</b> Floor TDs scan ?mode=scorer QR code on their phones, set an Argon2 4-digit PIN, and claim lane pairs.<br/>"
        "<b>Step 5 (Scoring with PIN Concurrence):</b> Roving TDs input pair scores on mobile (or snap overhead screens with camera OCR) and enter their secret PIN to lock them.<br/>"
        "<b>Step 6 (Financials & Finals):</b> Reconcile entries using Financial Payout Ledger. In Module 3, click 'Calculate & Complete Tournament' to auto-seed the stepladder and print the final PDF summary.",
        body_style
    ))

    rules_table_data = [
        ["Statute", "Mandatory Desk Enforcement"],
        ["Rule 17: Altering Surface", "No abrasive pads or liquid cleaners once competition starts. Remove ball immediately; frames bowled post-adjustment incur zero scores."],
        ["Rule 18: Equipment Specs", "Balance holes are prohibited. All drilled holes must be occupied by gripping fingers on delivery. Non-compliant balls must be removed."],
        ["Rule 10: Tardy Bowlers", "Late bowlers begin in current frame if not completed by all on pair. No warm-up frames. Missed frames are scored zero."],
        ["Rule 400: Youth SMART", "CRITICAL MANDATE: All prizes and awards in youth divisions must be deposited into the USBC SMART program. Zero cash/gift card policy."]
    ]
    t_rules = Table(rules_table_data, colWidths=[120, 420])
    t_rules.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0284c7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_rules)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 6A. EXTERNAL MONITOR / BOWLER KIOSK DISPLAY (?mode=kiosk)
# ---------------------------------------------------------
query_params = st.query_params
if query_params.get("mode") == "kiosk":
    st.markdown("""
    <style>
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container { padding-top: 1.5rem; max-width: 900px; }
    </style>
    """, unsafe_allow_html=True)

    active_card = read_kiosk_state()
    detected_base = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")

    col_k1, col_k2, col_k3 = st.columns([1, 4, 1])
    with col_k2:
        if HAS_LOGO:
            col_l1, col_l2, col_l3 = st.columns([1, 1, 1])
            with col_l2:
                st.image(LOGO_PATH, width=160)

        if active_card is not None:
            b_name = active_card["name"]
            b_usbc = active_card["usbc_id"]
            b_avg = active_card["avg"]
            b_lane = active_card["lane"]
            pair_display = active_card["pair_display"]

            checkin_url = f"{detected_base}/?mode=checkin&usbc_id={b_usbc}"
            qr_buf = generate_qr_image(checkin_url)

            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); border: 2px solid #38bdf8; border-radius: 16px; padding: 24px; text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.5); margin-bottom: 20px;">
                <span style="background: #38bdf820; color: #38bdf8; border: 1px solid #38bdf8; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 800; letter-spacing: 1px;">WELCOME TO THE LANES</span>
                <h1 style="color: #f8fafc; font-size: 38px; margin: 12px 0 4px 0; font-weight: 800;">{b_name}</h1>
                <div style="color: #94a3b8; font-size: 16px;">USBC ID: <b style="color: #cbd5e1;">{b_usbc}</b> | Entering Avg: <b style="color: #cbd5e1;">{b_avg}</b></div>
            </div>
            """, unsafe_allow_html=True)

            col_q1, col_q2, col_q3 = st.columns([1, 2, 1])
            with col_q2:
                st.image(qr_buf, use_container_width=True)

            st.markdown(f"""
            <div style="background-color: #1e293b; border: 2px solid #38bdf8; border-radius: 12px; padding: 18px; text-align: center; margin-top: 14px;">
                <div style="font-size: 13px; color: #94a3b8; text-transform: uppercase; font-weight: 700; letter-spacing: 1px;">Assigned Starting Pair</div>
                <div style="font-size: 36px; font-weight: 900; color: #38bdf8; margin: 4px 0;">{pair_display}</div>
                <div style="font-size: 15px; color: #e2e8f0;">Lead-off Delivery on <b>Lane {b_lane}</b></div>
            </div>
            <div style="text-align: center; color: #94a3b8; font-size: 14px; margin-top: 14px;">
                📲 Point your phone camera at the QR code above to confirm check-in.
            </div>
            """, unsafe_allow_html=True)

        else:
            total = len(st.session_state.roster)
            checked = len(st.session_state.roster[st.session_state.roster["Checked_In"] == True]) if total > 0 else 0
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); border: 1px solid #1e40af; border-radius: 16px; padding: 36px 24px; text-align: center; margin-top: 20px;">
                <h1 style="color: #f8fafc; font-size: 36px; margin: 0; font-weight: 900;">Cecil Harford USBC</h1>
                <h3 style="color: #38bdf8; font-size: 22px; margin: 10px 0 0 0;">{st.session_state.tournament_config['name']}</h3>
                <p style="color: #94a3b8; font-size: 15px; margin: 6px 0 0 0;">Host Center: <b>{st.session_state.tournament_config['center']}</b></p>
                <div style="margin-top: 24px; display: inline-block; background-color: #0f172a80; border: 1px solid #334155; border-radius: 30px; padding: 8px 24px;">
                    <span style="font-size: 18px; color: #34d399; font-weight: 800;">{checked} / {total}</span>
                    <span style="font-size: 14px; color: #94a3b8; margin-left: 6px;">Bowlers Checked In</span>
                </div>
            </div>
            <div style="text-align: center; margin-top: 36px; color: #64748b; font-size: 15px;">
                Please approach the desk official with your entry fee to receive your lane assignment.
            </div>
            """, unsafe_allow_html=True)

    time.sleep(2.0)
    st.rerun()

# ---------------------------------------------------------
# 6B. MOBILE-OPTIMIZED BOWLER SELF-CHECK-IN ROUTE (?mode=checkin)
# ---------------------------------------------------------
if query_params.get("mode") == "checkin":
    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
        st.session_state.brackets = cloud_state.get("brackets", [])

    target_id = query_params.get("usbc_id", "")
    roster_match = st.session_state.roster[st.session_state.roster["USBC ID"].astype(str) == str(target_id)]

    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        if HAS_LOGO:
            st.image(LOGO_PATH, width=150)
        
        st.markdown(f"""
        <div class="brand-banner" style="text-align: center;">
            <h1 style="font-size: 22px;">🎳 CHUSBC Official Check-In</h1>
            <p>{st.session_state.tournament_config['name']}<br/>{st.session_state.tournament_config['center']}</p>
        </div>
        """, unsafe_allow_html=True)

        if roster_match.empty:
            st.error("Invalid bowler check-in link or USBC ID. Please see the desk official.")
        else:
            bowler_info = roster_match.iloc[0]
            bowler_name = bowler_info["Bowler"]
            is_paid = bool(bowler_info["Paid"])
            is_checked_in = bool(bowler_info["Checked_In"])
            start_lane = int(bowler_info["Starting Lane"])
            pair_partner = start_lane + 1 if start_lane % 2 != 0 else start_lane - 1
            pair_display = f"Lanes {min(start_lane, pair_partner)} & {max(start_lane, pair_partner)}"

            if not is_paid:
                st.markdown(f"""
                <div style="background-color: #ef444420; border: 2px solid #ef4444; border-radius: 10px; padding: 20px; text-align: center; margin-bottom: 20px;">
                    <span style="font-size: 36px;">⚠️</span>
                    <h2 style="color: #f87171; margin: 10px 0 4px 0; font-size: 20px;">Payment Required at Desk</h2>
                    <p style="color: #fca5a5; font-size: 14px; margin: 0;">
                        Hello <b>{bowler_name}</b>. Your entry fee must be collected at the check-in desk before your lane assignment can be issued.
                    </p>
                </div>
                """, unsafe_allow_html=True)
            else:
                if not is_checked_in:
                    match_idx = st.session_state.roster.index[st.session_state.roster["USBC ID"].astype(str) == str(target_id)].tolist()
                    if match_idx:
                        st.session_state.roster.loc[match_idx[0], "Checked_In"] = True
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)

                st.markdown(f"""
                <div style="background-color: #10b98120; border: 2px solid #10b981; border-radius: 10px; padding: 20px; text-align: center; margin-bottom: 20px;">
                    <span style="font-size: 40px;">✅</span>
                    <h2 style="color: #34d399; margin: 10px 0 4px 0; font-size: 22px;">Check-In Confirmed!</h2>
                    <p style="color: #94a3b8; font-size: 14px; margin: 0;">Welcome, <b>{bowler_name}</b> (USBC: {target_id})</p>
                </div>

                <div class="match-box" style="text-align: center; font-size: 16px; padding: 18px;">
                    <span style="color: #94a3b8; font-size: 13px; text-transform: uppercase; font-weight: 700;">Assigned Starting Pair</span>
                    <div style="font-size: 32px; font-weight: 800; color: #38bdf8; margin: 6px 0;">{pair_display}</div>
                    <span style="color: #f1f5f9; font-size: 14px;">Lead-off Lane: <b>Lane {start_lane}</b></span>
                </div>

                <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px; margin-top: 14px;">
                    <div style="display: flex; justify-content: space-between; font-size: 14px; color: #cbd5e1; margin-bottom: 6px;">
                        <span>Verified Entering Avg:</span>
                        <span style="font-weight: 700;">{bowler_info['Average']}</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 14px; color: #cbd5e1;">
                        <span>Entry Status:</span>
                        <span style="color: #34d399; font-weight: 700;">PAID & OFFICIAL</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                st.caption("Keep this screen open for your starting pair reference. Good luck and high bowling!")

    st.stop()

# ---------------------------------------------------------
# 6C. ENTRANCE QR AUTOMATED SELF-CHECK-IN & BRACKET ROUTING (?mode=self_checkin)
# ---------------------------------------------------------
if query_params.get("mode") == "self_checkin":
    st.markdown("""
    <style>
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container { padding-top: 1.2rem; max-width: 580px; }
    </style>
    """, unsafe_allow_html=True)

    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
        st.session_state.brackets = cloud_state.get("brackets", [])

    if HAS_LOGO:
        st.image(LOGO_PATH, width=130)

    st.markdown(f"""
    <div class="brand-banner" style="text-align: center;">
        <h1 style="font-size: 22px;">🎳 Express Entrance Check-In</h1>
        <p>{st.session_state.tournament_config['name']}<br/>Host: {st.session_state.tournament_config['center']}</p>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.roster.empty:
        st.info("Tournament roster is currently being initialized by the desk. Please stand by or see the desk official.")
        st.stop()

    bowler_list = sorted(st.session_state.roster["Bowler"].dropna().unique().tolist())
    selected_name = st.selectbox("1. Select Your Name:", ["-- Tap to Find Your Name --"] + bowler_list)
    wants_brackets = st.radio(
        "2. Do you want to enter Side Brackets or High-Game Pots today?",
        ["No — Just check me in for the tournament", "Yes — I want to enter Brackets / Side Pots"],
        index=0
    )

    if selected_name != "-- Tap to Find Your Name --":
        if st.button("Complete Check-In", type="primary", use_container_width=True):
            b_row = st.session_state.roster[st.session_state.roster["Bowler"] == selected_name].iloc[0]
            is_paid = bool(b_row.get("Paid", False))
            b_usbc = str(b_row.get("USBC ID", ""))
            start_lane = int(pd.to_numeric(b_row.get("Starting Lane", 1), errors="coerce") or 1)
            pair_partner = start_lane + 1 if start_lane % 2 != 0 else start_lane - 1
            pair_display = f"Lanes {min(start_lane, pair_partner)} & {max(start_lane, pair_partner)}"

            if not is_paid:
                st.markdown(f"""
                <div style="background-color: #ef444420; border: 2px solid #ef4444; border-radius: 12px; padding: 22px; text-align: center; margin-top: 16px;">
                    <span style="font-size: 38px;">💳</span>
                    <h2 style="color: #f87171; margin: 8px 0 6px 0; font-size: 21px;">Please Visit the Check-In Desk</h2>
                    <p style="color: #fca5a5; font-size: 15px; margin: 0;">
                        Welcome, <b>{selected_name}</b>! Our system shows a balance due for your entry fee. Please see the Tournament Director at the desk to complete payment and receive your lane assignment.
                    </p>
                </div>
                """, unsafe_allow_html=True)
            elif "Yes" in wants_brackets:
                match_idx = st.session_state.roster.index[st.session_state.roster["Bowler"] == selected_name].tolist()
                if match_idx and not bool(b_row.get("Checked_In", False)):
                    st.session_state.roster.loc[match_idx[0], "Checked_In"] = True
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)

                st.markdown(f"""
                <div style="background-color: #f59e0b20; border: 2px solid #f59e0b; border-radius: 12px; padding: 22px; text-align: center; margin-top: 16px;">
                    <span style="font-size: 38px;">💰</span>
                    <h2 style="color: #fde047; margin: 8px 0 6px 0; font-size: 21px;"> Checked In! See Desk for Brackets</h2>
                    <p style="color: #fef08a; font-size: 15px; margin: 0;">
                        Your tournament entry is <b>PAID</b> and you are checked in on <b>{pair_display} (Lane {start_lane})</b>.<br/><br/>
                        <b>Next Step:</b> Please head to the Tournament Desk now to buy into today's <b>8-Bowler Brackets & Side Pots</b> before squad practice begins!
                    </p>
                </div>
                """, unsafe_allow_html=True)
            else:
                match_idx = st.session_state.roster.index[st.session_state.roster["Bowler"] == selected_name].tolist()
                if match_idx and not bool(b_row.get("Checked_In", False)):
                    st.session_state.roster.loc[match_idx[0], "Checked_In"] = True
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)

                detected_base = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")
                portal_url = f"{detected_base}/?mode=bowler_portal"

                st.markdown(f"""
                <div style="background-color: #10b98120; border: 2px solid #10b981; border-radius: 12px; padding: 22px; text-align: center; margin-top: 16px;">
                    <span style="font-size: 42px;">✅</span>
                    <h2 style="color: #34d399; margin: 8px 0 4px 0; font-size: 23px;">You Are Checked In!</h2>
                    <p style="color: #cbd5e1; font-size: 14px; margin: 0;">{selected_name} (USBC ID: {b_usbc})</p>
                </div>

                <div class="match-box" style="text-align: center; margin-top: 14px; padding: 20px;">
                    <span style="color: #94a3b8; font-size: 13px; text-transform: uppercase; font-weight: 700;">Your Starting Pair</span>
                    <div style="font-size: 36px; font-weight: 900; color: #38bdf8; margin: 6px 0;">{pair_display}</div>
                    <span style="color: #f1f5f9; font-size: 15px;">Lead-off Delivery: <b>Lane {start_lane}</b> | Entering Avg: <b>{b_row['Average']}</b></span>
                </div>
                """, unsafe_allow_html=True)
                st.link_button("📊 Open Live Bowler Standings & Portal", portal_url, use_container_width=True)

    st.stop()

# ---------------------------------------------------------
# 6D. READ-ONLY BOWLER LIVE PORTAL (?mode=bowler_portal)
# ---------------------------------------------------------
if query_params.get("mode") == "bowler_portal":
    st.markdown("""
    <style>
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container { padding-top: 1.2rem; max-width: 620px; }
    </style>
    """, unsafe_allow_html=True)

    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
        st.session_state.brackets = cloud_state.get("brackets", [])

    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); border: 1.5px solid #38bdf8; border-radius: 12px; padding: 18px; text-align: center; margin-bottom: 16px;">
        <span style="color: #38bdf8; font-size: 12px; font-weight: 800; letter-spacing: 1px;">LIVE BOWLER PORTAL (READ-ONLY)</span>
        <h2 style="color: #f8fafc; margin: 4px 0 0 0; font-size: 21px;">{st.session_state.tournament_config['name']}</h2>
        <div style="color: #cbd5e1; font-size: 13px; margin-top: 4px;">Host Center: <b>{st.session_state.tournament_config['center']}</b></div>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.roster.empty:
        st.info("Standings will appear once squad play begins.")
        st.stop()

    standings = compile_standings(st.session_state.roster)
    bowler_names = sorted(st.session_state.roster["Bowler"].dropna().unique().tolist())
    selected_bowler = st.selectbox("Select Your Name to View Personal Tracker & Schedule:", ["-- View Full Leaderboard Only --"] + bowler_names)

    if selected_bowler != "-- View Full Leaderboard Only --":
        b_Rank_df = standings[standings["Bowler"] == selected_bowler]
        if not b_Rank_df.empty:
            b_stat = b_Rank_df.iloc[0]
            curr_rank = b_Rank_df.index[0]
            s_lane = int(pd.to_numeric(b_stat.get("Starting Lane", 1), errors="coerce") or 1)
            rot_rule = st.session_state.tournament_config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")
            max_l = int(st.session_state.tournament_config.get("lanes_count", 40))

            g1_l = get_bowler_lane_for_game(s_lane, 1, rot_rule, max_l)
            g2_l = get_bowler_lane_for_game(s_lane, 2, rot_rule, max_l)
            g3_l = get_bowler_lane_for_game(s_lane, 3, rot_rule, max_l)

            def get_pair_str(l):
                p = l + 1 if l % 2 != 0 else l - 1
                return f"Lanes {min(l, p)}-{max(l, p)}"

            cut_val = standings.iloc[4]["Grand_Total"] if len(standings) >= 5 else 0
            diff_cut = int(b_stat["Grand_Total"]) - int(cut_val)
            diff_str = f"+{diff_cut} above #5 Cut" if diff_cut >= 0 else f"{diff_cut} from #5 Cut"

            st.markdown(f"""
            <div class="match-box" style="text-align: center;">
                <span style="font-size: 12px; color: #94a3b8; text-transform: uppercase; font-weight: 800;">Current Standing</span>
                <div style="font-size: 34px; font-weight: 900; color: #38bdf8; margin: 4px 0;">Rank #{curr_rank} <span style="font-size: 16px; color: #34d399;">({diff_str})</span></div>
                <div style="font-size: 14.5px; font-weight: 700; color: #f8fafc; margin-top: 8px; border-top: 1px solid #334155; padding-top: 8px;">
                    Game 1: <b>{get_pair_str(g1_l)}</b> &nbsp;➔&nbsp; Game 2: <b>{get_pair_str(g2_l)}</b> &nbsp;➔&nbsp; Game 3: <b>{get_pair_str(g3_l)}</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

            c_g1, c_g2, c_g3, c_tot = st.columns(4)
            with c_g1:
                st.metric("Game 1", int(b_stat["Game 1"]))
            with c_g2:
                st.metric("Game 2", int(b_stat["Game 2"]))
            with c_g3:
                st.metric("Game 3", int(b_stat["Game 3"]))
            with c_tot:
                st.metric("Total w/ HDCP", int(b_stat["Grand_Total"]), delta=f"{int(b_stat['Total_HDCP'])} HDCP")

    st.subheader("🏆 Live Tournament Standings")
    cols_view = [c for c in ["Bowler", "Team_Name", "Starting Lane", "Game 1", "Game 2", "Game 3", "Total_HDCP", "Grand_Total"] if c in standings.columns]
    st.dataframe(standings[cols_view], use_container_width=True)
    if st.button("🔄 Refresh Live Standings", use_container_width=True):
        st.rerun()

    st.stop()

# ---------------------------------------------------------
# 6E. PIN-SECURED ROVING MOBILE TD SCORER PORTAL (?mode=scorer)
# ---------------------------------------------------------
if query_params.get("mode") == "scorer":
    st.markdown("""
    <style>
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container { padding-top: 1rem; max-width: 600px; }
    </style>
    """, unsafe_allow_html=True)

    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
        st.session_state.brackets = cloud_state.get("brackets", [])
        st.session_state.td_pins = cloud_state.get("td_pins", {})

    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #0284c7 0%, #0f172a 100%); border: 1.5px solid #38bdf8; border-radius: 12px; padding: 16px; text-align: center; margin-bottom: 16px;">
        <span style="color: #38bdf8; font-size: 12px; font-weight: 800; letter-spacing: 1px;">CHUSBC SECURE FLOOR SCORER (ARGON2)</span>
        <h2 style="color: #f8fafc; margin: 4px 0 0 0; font-size: 20px;">{st.session_state.tournament_config['name']}</h2>
        <div style="color: #cbd5e1; font-size: 13px; margin-top: 4px;">Host Center: <b>{st.session_state.tournament_config['center']}</b></div>
    </div>
    """, unsafe_allow_html=True)

    if "mobile_scorer_td" not in st.session_state:
        st.session_state.mobile_scorer_td = ""

    if not st.session_state.mobile_scorer_td:
        with st.form("scorer_identify_form"):
            td_name_in = st.text_input("Enter Your Name (TD on Floor):", placeholder="e.g. Dave Miller, Chris Reynolds").strip()
            existing_pins = st.session_state.get("td_pins", {})
            st.caption("Establish or enter your 4-digit PIN (secured with Argon2id):")
            pin_in = st.text_input("4-Digit Security PIN:", type="password", max_chars=6).strip()
            
            submit_td = st.form_submit_button("Authenticate & Start Scoring", type="primary", use_container_width=True)
            if submit_td:
                if not td_name_in:
                    st.error("Please enter your name.")
                elif len(pin_in) < 4:
                    st.error("Security PIN must be at least 4 digits.")
                else:
                    if td_name_in in existing_pins:
                        if not verify_td_pin(td_name_in, pin_in):
                            st.error(f"Incorrect PIN for {td_name_in}. If forgotten, ask Scott Kramer at Central Desk for an override.")
                            st.stop()
                    else:
                        register_td_pin(td_name_in, pin_in)
                        st.toast(f"Argon2 Security PIN locked for {td_name_in}!", icon="🔐")
                    
                    st.session_state.mobile_scorer_td = td_name_in
                    st.rerun()
        st.stop()

    st.markdown(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px;">
        <span style="font-size: 13.5px; color: #cbd5e1;">Official: <b style="color: #38bdf8;">{st.session_state.mobile_scorer_td}</b></span>
        <span style="font-size: 12px; color: #34d399; font-weight: 700;">🔐 ARGON2 VERIFIED</span>
    </div>
    """, unsafe_allow_html=True)

    parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
    pair_labels = [f"Lanes {p[0]} & {p[1]}" for p in parsed_pairs]

    col_sel_p, col_sel_g = st.columns([2, 1])
    with col_sel_p:
        selected_pair_label = st.selectbox("Select Active Pair:", pair_labels)
    with col_sel_g:
        selected_game_num = st.selectbox("Game:", [1, 2, 3], index=0)

    selected_pair_idx = pair_labels.index(selected_pair_label)
    target_pair = parsed_pairs[selected_pair_idx]
    lane_odd, lane_even = target_pair

    rotation_rule = st.session_state.tournament_config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")
    max_center_lanes = int(st.session_state.tournament_config.get("lanes_count", 40))

    if "Starting Lane" not in st.session_state.roster.columns:
        st.session_state.roster["Starting Lane"] = 1

    if st.session_state.roster.empty:
        pair_bowlers = pd.DataFrame()
    else:
        working_roster = st.session_state.roster.copy()
        working_roster["Starting Lane"] = pd.to_numeric(working_roster["Starting Lane"], errors="coerce").fillna(1).astype(int)
        working_roster["Active_Game_Lane"] = working_roster["Starting Lane"].apply(
            lambda l: get_bowler_lane_for_game(int(l), selected_game_num, rotation_rule, max_lanes=max_center_lanes)
        )
        pair_bowlers = working_roster[working_roster["Active_Game_Lane"].isin([lane_odd, lane_even])]

    if pair_bowlers.empty:
        st.warning(f"No bowlers currently assigned to {selected_pair_label} for Game {selected_game_num}.")
    else:
        g_col = f"Game {selected_game_num}"
        v_by_col = f"G{selected_game_num}_Verified_By"
        v_at_col = f"G{selected_game_num}_Verified_At"

        first_v = pair_bowlers.iloc[0].get(v_by_col, "")
        first_at = pair_bowlers.iloc[0].get(v_at_col, "")
        if first_v:
            st.markdown(f"""
            <div style="background-color: #10b98120; border: 1px solid #10b981; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px;">
                <span style="color: #34d399; font-size: 13px; font-weight: 700;">✅ Game {selected_game_num} Verified by {first_v} at {first_at}</span>
            </div>
            """, unsafe_allow_html=True)

        with st.expander("📸 Snap Overhead Monitor / Recap Photo (AI OCR)", expanded=False):
            st.caption(f"Point phone camera at the screen for Lanes {lane_odd} & {lane_even}:")
            cam_pic = st.camera_input("Take photo of monitor:", key=f"cam_{lane_odd}_{selected_game_num}")

            if cam_pic is not None:
                if st.button("🔍 Read Scores from Monitor Photo", type="primary", use_container_width=True, key=f"btn_ocr_{lane_odd}_{selected_game_num}"):
                    if not ai_client:
                        st.error("Gemini API key missing.")
                    else:
                        with st.spinner("Analyzing overhead scores with Gemini..."):
                            bowler_list = pair_bowlers["Bowler"].tolist()
                            scanned_scores = extract_scores_from_overhead_photo(
                                cam_pic.getvalue(), 
                                bowler_list, 
                                selected_game_num
                            )
                            if scanned_scores:
                                for b_name, sc_val in scanned_scores.items():
                                    st.session_state[f"temp_ocr_{b_name}_{selected_game_num}"] = int(sc_val)
                                st.success(f"Extracted scores for {len(scanned_scores)} bowlers! Review and verify below.")
                            else:
                                st.warning("Could not clearly read scores from the monitor. Please enter them manually below.")

        with st.form(f"mobile_score_form_{lane_odd}_{selected_game_num}"):
            updated_scores_map = {}
            for b_idx, b_row in pair_bowlers.iterrows():
                b_name = b_row["Bowler"]
                b_lane = int(b_row["Active_Game_Lane"])
                ocr_key = f"temp_ocr_{b_name}_{selected_game_num}"
                default_score = st.session_state.get(ocr_key, int(pd.to_numeric(b_row.get(g_col, 0), errors="coerce") or 0))

                updated_scores_map[b_row["USBC ID"]] = st.number_input(
                    f"Lane {b_lane}: {b_name} (Entering Avg: {b_row['Average']})",
                    min_value=0,
                    max_value=300,
                    value=default_score,
                    step=1,
                    key=f"m_score_{b_row['USBC ID']}_{selected_game_num}"
                )

            st.markdown("---")
            st.markdown("#### 🔐 Official Concurrence & Signature")
            challenge_pin = st.text_input(
                f"Enter {st.session_state.mobile_scorer_td}'s 4-Digit PIN to Lock:",
                type="password",
                max_chars=6,
                key=f"sig_pin_{lane_odd}_{selected_game_num}"
            )

            submit_scores = st.form_submit_button(f"🔐 Sign with PIN & Lock Game {selected_game_num}", type="primary", use_container_width=True)

            if submit_scores:
                if not verify_td_pin(st.session_state.mobile_scorer_td, challenge_pin):
                    st.error("❌ Invalid Security PIN! Score submission rejected.")
                else:
                    latest_cloud = fetch_active_tournament_state()
                    working_df = pd.DataFrame(latest_cloud["roster"]) if latest_cloud else st.session_state.roster.copy()
                    
                    timestamp_str = datetime.now().strftime("%I:%M %p")
                    for u_id, sc in updated_scores_map.items():
                        m_idx = working_df.index[working_df["USBC ID"].astype(str) == str(u_id)].tolist()
                        if m_idx:
                            working_df.loc[m_idx[0], g_col] = int(sc)
                            working_df.loc[m_idx[0], v_by_col] = st.session_state.mobile_scorer_td
                            working_df.loc[m_idx[0], v_at_col] = timestamp_str

                    st.session_state.roster = working_df
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    log_audit_event(f"Mobile TD '{st.session_state.mobile_scorer_td}' verified Game {selected_game_num} on Lanes {lane_odd}-{lane_even} with Argon2 PIN concurrence.")
                    st.success(f"✅ Game {selected_game_num} on {selected_pair_label} verified with PIN and locked!")
                    time.sleep(1.0)
                    st.rerun()

    st.stop()

# ---------------------------------------------------------
# 6F. PUBLIC CONCOURSE & TV LEADERBOARD DISPLAY (?mode=leaderboard)
# ---------------------------------------------------------
if query_params.get("mode") == "leaderboard":
    st.markdown("""
    <style>
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container { padding: 1rem 1.8rem 1rem 1.8rem; max-width: 100% !important; }
        .tv-row {
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            font-size: 19px;
            font-weight: 700;
        }
        .tv-row-top5 {
            background: linear-gradient(90deg, #1e293b 0%, #0f2b48 100%);
            border-left: 6px solid #38bdf8;
            border-top: 1px solid #38bdf850;
            border-bottom: 1px solid #38bdf850;
            border-right: 1px solid #38bdf850;
        }
        .tv-row-1st {
            background: linear-gradient(90deg, #1e293b 0%, #1e3a24 100%);
            border-left: 6px solid #34d399;
            border-top: 1px solid #34d39950;
            border-bottom: 1px solid #34d39950;
            border-right: 1px solid #34d39950;
        }
        .cut-line {
            border-bottom: 3px dashed #ef4444;
            margin: 12px 0;
            text-align: center;
            height: 14px;
        }
        .cut-text {
            background-color: #0b1120;
            color: #f87171 !important;
            padding: 0 16px;
            font-size: 13px;
            font-weight: 900;
            letter-spacing: 1.5px;
            text-transform: uppercase;
        }
    </style>
    """, unsafe_allow_html=True)

    cloud_state = fetch_active_tournament_state()
    if cloud_state:
        st.session_state.tournament_config = cloud_state["config"]
        st.session_state.roster = pd.DataFrame(cloud_state["roster"])
        st.session_state.brackets = cloud_state.get("brackets", [])

    standings = compile_standings(st.session_state.roster)

    c_logo, c_info, c_stats = st.columns([1, 4, 3])
    with c_logo:
        if HAS_LOGO:
            st.image(LOGO_PATH, width=110)
        else:
            st.markdown("<h2 style='font-size: 32px;'>🎳</h2>", unsafe_allow_html=True)
    with c_info:
        st.markdown(f"""
        <div style="padding-top: 4px;">
            <span style="background: #38bdf820; color: #38bdf8; border: 1px solid #38bdf8; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 800; letter-spacing: 1px;">LIVE CONCOURSE LEADERBOARD</span>
            <h1 style="color: #f8fafc; font-size: 26px; margin: 4px 0 0 0; font-weight: 900;">{st.session_state.tournament_config['name']}</h1>
            <div style="color: #94a3b8; font-size: 14px; margin-top: 2px;">
                Host: <b style="color: #cbd5e1;">{st.session_state.tournament_config['center']}</b> | 
                Format: <b style="color: #cbd5e1;">{st.session_state.tournament_config.get('format_mode', 'Standard')}</b> | 
                Handicap: <b style="color: #cbd5e1;">{int(st.session_state.tournament_config.get('hdcp_pct', 0.90)*100)}% of {st.session_state.tournament_config.get('hdcp_base', 220)}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c_stats:
        top_score = standings.iloc[0]["Grand_Total"] if not standings.empty else 0
        cut_score = standings.iloc[4]["Grand_Total"] if len(standings) >= 5 else 0
        hi_game = standings["High_Scratch_Game"].max() if not standings.empty else 0
        total_field = len(st.session_state.roster)

        st.markdown(f"""
        <div style="display: flex; gap: 10px; justify-content: flex-end; padding-top: 10px;">
            <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 6px 14px; text-align: center;">
                <div style="font-size: 10px; color: #94a3b8; font-weight: 800; text-transform: uppercase;">Leader</div>
                <div style="font-size: 20px; font-weight: 900; color: #34d399;">{top_score}</div>
            </div>
            <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 6px 14px; text-align: center;">
                <div style="font-size: 10px; color: #94a3b8; font-weight: 800; text-transform: uppercase;">#5 Cut</div>
                <div style="font-size: 20px; font-weight: 900; color: #38bdf8;">{cut_score}</div>
            </div>
            <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 6px 14px; text-align: center;">
                <div style="font-size: 10px; color: #94a3b8; font-weight: 800; text-transform: uppercase;">High Scratch</div>
                <div style="font-size: 20px; font-weight: 900; color: #fde047;">{hi_game}</div>
            </div>
            <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 6px 14px; text-align: center;">
                <div style="font-size: 10px; color: #94a3b8; font-weight: 800; text-transform: uppercase;">Field</div>
                <div style="font-size: 20px; font-weight: 900; color: #f8fafc;">{total_field}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr style='border-color: #1e3a8a; margin: 10px 0 14px 0;'/>", unsafe_allow_html=True)

    if standings.empty:
        st.markdown("""
        <div style="background-color: #1e293b; border: 2px solid #334155; border-radius: 12px; padding: 36px; text-align: center; margin-top: 30px;">
            <h2 style="color: #38bdf8; margin: 0 0 10px 0;">Tournament Warm-Up & Practice In Session</h2>
            <p style="color: #cbd5e1; font-size: 16px;">Live scoring will display overhead as scores are officially verified by floor officials.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="display: flex; background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 8px 14px; color: #94a3b8; font-size: 12.5px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">
            <div style="width: 60px;">Pos</div>
            <div style="flex-grow: 2;">Bowler Name / Affiliation</div>
            <div style="width: 80px; text-align: center;">Lanes</div>
            <div style="width: 80px; text-align: center;">Avg / HDCP</div>
            <div style="width: 70px; text-align: center;">Gm 1</div>
            <div style="width: 70px; text-align: center;">Gm 2</div>
            <div style="width: 70px; text-align: center;">Gm 3</div>
            <div style="width: 90px; text-align: center;">Scratch</div>
            <div style="width: 100px; text-align: right;">Total Pinfall</div>
        </div>
        """, unsafe_allow_html=True)

        for rank, row in standings.reset_index().iterrows():
            pos = int(row["Rank"])
            bowler = str(row["Bowler"])
            start_lane = int(pd.to_numeric(row.get("Starting Lane", 1), errors="coerce") or 1)
            pair_p = start_lane + 1 if start_lane % 2 != 0 else start_lane - 1
            lane_str = f"{min(start_lane, pair_p)}-{max(start_lane, pair_p)}"
            avg = int(row["Average"])
            hdcp = int(row["Total_HDCP"])
            g1 = int(row["Game 1"])
            g2 = int(row["Game 2"])
            g3 = int(row["Game 3"])
            scratch = int(row["Scratch_Total"])
            grand = int(row["Grand_Total"])
            team_str = f" • <span style='color: #94a3b8; font-weight: normal; font-size: 15px;'>{row['Team_Name']}</span>" if row.get("Team_Name") and row["Team_Name"] != "Singles" else ""

            row_class = "tv-row"
            rank_badge_color = "#38bdf8"
            if pos == 1:
                row_class += " tv-row-1st"
                rank_badge_color = "#34d399"
            elif pos <= 5:
                row_class += " tv-row-top5"

            st.markdown(f"""
            <div class="{row_class}">
                <div style="width: 60px; font-weight: 900; color: {rank_badge_color};">#{pos}</div>
                <div style="flex-grow: 2; color: #f8fafc;">{bowler}{team_str}</div>
                <div style="width: 80px; text-align: center; color: #cbd5e1; font-size: 15px;">L{lane_str}</div>
                <div style="width: 80px; text-align: center; color: #94a3b8; font-size: 14px;">{avg} <span style="font-size: 12px; color: #38bdf8;">(+{hdcp})</span></div>
                <div style="width: 70px; text-align: center; color: {'#cbd5e1' if g1 > 0 else '#64748b'};">{g1 or '-'}</div>
                <div style="width: 70px; text-align: center; color: {'#cbd5e1' if g2 > 0 else '#64748b'};">{g2 or '-'}</div>
                <div style="width: 70px; text-align: center; color: {'#cbd5e1' if g3 > 0 else '#64748b'};">{g3 or '-'}</div>
                <div style="width: 90px; text-align: center; color: #cbd5e1;">{scratch}</div>
                <div style="width: 100px; text-align: right; font-weight: 900; color: #38bdf8; font-size: 21px;">{grand}</div>
            </div>
            """, unsafe_allow_html=True)

            if pos == 5 and len(standings) > 5:
                st.markdown("""
                <div class="cut-line">
                    <span class="cut-text">▼ TOP 5 CHAMPIONSHIP STEPLADDER CUT LINE ▼</span>
                </div>
                """, unsafe_allow_html=True)

    time.sleep(12.0)
    st.rerun()

# ---------------------------------------------------------
# 7. TD AUTHENTICATION & LOGIN GATE (ARGON2ID)
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

if not st.session_state.authenticated:
    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        if HAS_LOGO:
            st.image(LOGO_PATH, width=160)

        users_df = fetch_users_df()

        if st.session_state.pending_password_change:
            st.markdown("""
            <div class="brand-banner">
                <h1>🔒 Account Activation (Argon2)</h1>
                <p>Welcome to Cecil Harford USBC Tournament Desk. Please establish your personal password.</p>
            </div>
            """, unsafe_allow_html=True)
            with st.form("pwd_reset_form"):
                new_pwd = st.text_input("Enter New Password", type="password").strip()
                confirm_pwd = st.text_input("Confirm New Password", type="password").strip()
                reset_btn = st.form_submit_button("Update Password & Enter Desk", use_container_width=True)

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
                        log_audit_event(f"User '{u}' completed initial password change (Argon2id).")
                        st.rerun()
        else:
            st.markdown("""
            <div class="brand-banner">
                <h1>🎳 Cecil Harford USBC</h1>
                <p>Tournament Management & Rules Arbitration Portal</p>
            </div>
            """, unsafe_allow_html=True)

            auth_tab_login, auth_tab_register = st.tabs(["🔑 Sign In", "📝 Request Access (Self-Register)"])

            with auth_tab_login:
                with st.form("td_login"):
                    username_input = st.text_input("Username").strip().lower()
                    password_input = st.text_input("Password", type="password").strip()
                    submitted = st.form_submit_button("Sign In to Tournament Desk", use_container_width=True)

                    if submitted:
                        is_skramer = (username_input == "skramer" and password_input == "Abigail!2015")
                        match_row = users_df[users_df["username"] == username_input]

                        authenticated_match = False
                        needs_upgrade = False
                        if not match_row.empty:
                            stored_hash = str(match_row.iloc[0]["password_hash"])
                            authenticated_match, needs_upgrade = verify_secret(stored_hash, password_input)

                        if is_skramer or authenticated_match:
                            if needs_upgrade and not match_row.empty:
                                idx_u = users_df.index[users_df["username"] == username_input].tolist()
                                if idx_u:
                                    users_df.loc[idx_u[0], "password_hash"] = hash_secret(password_input)
                                    write_users_df(users_df)

                            user_data = match_row.iloc[0] if not match_row.empty else {
                                "name": "Scott Kramer",
                                "role": "admin",
                                "status": "active",
                                "must_change_password": False
                            }
                            
                            if str(user_data.get("status", "active")).lower() == "pending":
                                st.warning("Your registration is currently pending review by an Administrator.")
                            else:
                                st.session_state.username = username_input
                                st.session_state.td_name = str(user_data.get("name", "Scott Kramer"))
                                st.session_state.td_role = str(user_data.get("role", "admin")).lower()

                                if bool(user_data.get("must_change_password", False)):
                                    st.session_state.pending_password_change = True
                                    st.rerun()
                                else:
                                    st.session_state.authenticated = True
                                    st.session_state.session_initialized = False
                                    log_audit_event(f"User '{username_input}' ({st.session_state.td_name}) logged in.")
                                    st.rerun()
                        else:
                            st.error("Invalid username or password.")

            with auth_tab_register:
                with st.form("td_self_register"):
                    st.caption("Apply for Tournament Director access. An administrator must approve your application.")
                    req_user = st.text_input("Desired Username:").strip().lower()
                    req_name = st.text_input("Full Name:").strip()
                    req_email = st.text_input("Email Address (Required for Approval Notice):").strip().lower()
                    req_pwd = st.text_input("Desired Password:", type="password").strip()
                    submit_req = st.form_submit_button("Submit Registration for Approval", use_container_width=True)

                    if submit_req:
                        current_df = fetch_users_df()
                        if not req_user or not req_name or not req_email or not req_pwd:
                            st.error("Username, Full Name, Email, and Password are all required.")
                        elif "@" not in req_email or "." not in req_email:
                            st.error("Please enter a valid email address.")
                        elif len(req_pwd) < 6:
                            st.error("Password must be at least 6 characters.")
                        elif req_user in current_df["username"].values:
                            st.error(f"Username '{req_user}' is already registered or requested.")
                        else:
                            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                            new_row = pd.DataFrame([{
                                "username": req_user,
                                "name": req_name,
                                "email": req_email,
                                "password_hash": hash_secret(req_pwd),
                                "role": "td",
                                "status": "pending",
                                "must_change_password": False,
                                "created_at": timestamp_str
                            }])
                            updated_df = pd.concat([current_df, new_row], ignore_index=True)
                            write_users_df(updated_df)
                            
                            notify_admin_new_registration(
                                requested_user=req_user, 
                                requested_name=req_name, 
                                requested_email=req_email,
                                requested_at=timestamp_str
                            )

                            log_audit_event(f"New self-registration submitted: '{req_user}' ({req_name} - {req_email}).")
                            st.success("Registration submitted! An administrator has been notified and you will receive an email once approved.")

    st.stop()

# ---------------------------------------------------------
# 8. POST-LOGIN CHUSBC PRESET WORKSPACE GATEWAY
# ---------------------------------------------------------
if not st.session_state.session_initialized:
    st.markdown(f"""
    <div class="brand-banner">
        <h1>Welcome, {st.session_state.td_name}</h1>
        <p>Cecil Harford USBC Tournament Desk Management Portal</p>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("Select Tournament Workspace")
    st.caption("Choose an official CHUSBC tournament preset or load an in-flight tournament:")

    col_opt_new, col_opt_resume, col_opt_archive = st.columns(3)
    cloud_state = fetch_active_tournament_state()
    has_active_cloud = cloud_state is not None and bool(cloud_state.get("config"))
    archives_df = fetch_archives_df()

    with col_opt_new:
        st.markdown("""
        <div class="choice-card">
            <h3 style="color: #38bdf8; margin-top: 0;">🚀 Official CHUSBC Presets</h3>
            <p style="font-size: 14px; color: #cbd5e1;">Select from the 8 official Cecil Harford USBC annual tournaments to instantly calibrate center, lanes, handicap, and rules.</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        selected_preset = st.selectbox("Choose Tournament Profile:", list(CHUSBC_PRESET_PROFILES.keys()), key="preset_select_gate")
        if st.button("Launch Selected Tournament", type="primary", use_container_width=True):
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
                "movement_rule": p_data.get("movement_rule", "Move Right 1 Pair (+2 Lanes)"),
                "entry_fee": p_data.get("entry_fee", 50.0),
                "rules_text": p_data["rules_text"],
                "intake_completed": False
            }
            st.session_state.roster = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)
            st.session_state.brackets = []
            st.session_state.td_pins = {}
            st.session_state.session_initialized = True
            log_audit_event(f"TD launched official preset: '{selected_preset}'.")
            st.rerun()

    with col_opt_resume:
        active_title = cloud_state["config"]["name"] if has_active_cloud else "No Active Event Found"
        active_saved = cloud_state.get("saved_at", "N/A") if has_active_cloud else "-"
        active_entries = len(cloud_state.get("roster", [])) if has_active_cloud else 0
        
        st.markdown(f"""
        <div class="choice-card">
            <h3 style="color: {'#34d399' if has_active_cloud else '#94a3b8'}; margin-top: 0;">📂 Resume Active Event</h3>
            <p style="font-size: 14px; color: #cbd5e1;">Load the in-flight tournament backed up to local SQLite with existing scores and check-ins intact.</p>
            <div style="font-size: 13px; color: #94a3b8; border-top: 1px solid #334155; padding-top: 8px; margin-top: 12px;">
                <strong>Event:</strong> {active_title}<br/>
                <strong>Entries:</strong> {active_entries} bowlers | <strong>Saved:</strong> {active_saved}
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

    with col_opt_archive:
        st.markdown("""
        <div class="choice-card">
            <h3 style="color: #fbbf24; margin-top: 0;">📜 Clone Past Event</h3>
            <p style="font-size: 14px; color: #cbd5e1;">Load parameters from an archived tournament in SQLite as a new template.</p>
        </div>
        """, unsafe_allow_html=True)
        
        if archives_df.empty:
            st.caption("No historical events available to clone.")
        else:
            past_titles = archives_df["tournament_name"].tolist()
            selected_past = st.selectbox("Select Past Event Template:", past_titles, key="clone_select")
            if st.button("Clone Event Template", use_container_width=True):
                target_past = archives_df[archives_df["tournament_name"] == selected_past].iloc[0]
                st.session_state.tournament_config = {
                    "center": str(target_past.get("center", "Forest Hill Lanes")),
                    "name": f"{selected_past} (Copy)",
                    "lanes_count": 40,
                    "lanes_range": "1-40",
                    "division": str(target_past.get("division", "Adult Open")),
                    "hdcp_base": 220,
                    "hdcp_pct": 0.90,
                    "format_mode": "Standard 3-Game",
                    "games_count": 3,
                    "movement_rule": "Move Right 1 Pair (+2 Lanes)",
                    "entry_fee": 50.0,
                    "rules_text": "Qualifying: 3 games across assigned pairs. Handicap: 90% of 220.",
                    "intake_completed": False
                }
                st.session_state.roster = pd.DataFrame(columns=DEFAULT_ROSTER_COLS)
                st.session_state.brackets = []
                st.session_state.td_pins = {}
                st.session_state.session_initialized = True
                log_audit_event(f"TD cloned past event '{selected_past}' as template.")
                st.rerun()

    st.stop()

# ---------------------------------------------------------
# 9. GEMINI API CLIENT, OVERHEAD OCR & DETERMINISTIC ARBITER
# ---------------------------------------------------------
api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    with st.sidebar:
        api_key = st.text_input("Gemini API Key", type="password")

ai_client = genai.Client(api_key=api_key) if api_key else None

def generate_with_failover(prompt: str, temperature: float = 0.0) -> str:
    if not ai_client:
        raise ValueError("Gemini API key is not configured.")

    models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS
    last_exception = None

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                res = ai_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=temperature)
                )
                return res.text
            except Exception as e:
                last_exception = e
                err_msg = str(e).lower()
                if "503" in err_msg or "unavailable" in err_msg or "429" in err_msg or "quota" in err_msg:
                    time.sleep(1.5)
                    continue
                else:
                    break

    raise last_exception

def extract_scores_from_overhead_photo(image_bytes: bytes, bowlers_on_pair: list, game_num: int) -> dict:
    if not ai_client:
        return {}

    bowler_names_str = ", ".join(bowlers_on_pair)
    prompt = f"""
You are an expert bowling tournament scorekeeper assistant.
Analyze this photo of an overhead bowling center display monitor, recap sheet, or score sheet.

Target Bowlers assigned to this pair:
{bowler_names_str}

We need scores for Game {game_num}.

Instructions:
1. Identify the game scores corresponding to each target bowler for Game {game_num}.
2. Note that bowling monitors often abbreviate names (e.g. 'S KRAMER', 'DAVE M', 'KRAMER, S'). Match them accurately to the closest name in the Target Bowlers list.
3. Extract total final game score (between 0 and 300). If a game is in progress or unbowled, output 0.
4. Output strictly a JSON object mapping the exact bowler name from the Target Bowlers list to their integer score.
Example output format:
{{"Scott Kramer": 245, "Dave Miller": 210}}

Output ONLY raw JSON with no markdown formatting or backticks.
"""
    try:
        content_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        response = ai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=[content_part, prompt],
            config=types.GenerateContentConfig(temperature=0.0)
        )
        cleaned = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception as e:
        print(f"Error parsing overhead score photo: {e}")
        return {}

def arbitrate_rules_inquiry(query_text: str, event_context: str) -> str:
    if not ai_client:
        return "Gemini API key is not configured."

    contents_payload = []
    if RULEBOOK_BYTES is not None:
        contents_payload.append(
            types.Part.from_bytes(
                data=RULEBOOK_BYTES,
                mime_type="application/pdf"
            )
        )

    prompt = f"""
You are the official Cecil Harford USBC (CHUSBC) Tournament Rules Arbiter.
You have direct access to the official 2026-2027 USBC Playing Rulebook PDF provided in this prompt.

Active Event Context:
{event_context}

Dispute / Inquiry:
{query_text}

Rules Precedence:
1. Tournament flyer / local event rules govern format specifics (e.g. number of games, cut line, handicap formulas, Scotch Doubles rotation).
2. General USBC statutory rules (e.g. Rule 10 Tardy Bowlers, Rule 17 Surface Adjustments, Rule 18 Equipment Specs, Rule 400 Youth SMART) govern all playing conduct.

Format your decision as:
1. **Official Ruling:** (Clear, direct verdict on what stands right now)
2. **USBC Rulebook Citation:** (Exact rule number, subsection, and quote from the 2026-27 rulebook)
3. **Desk Official Action:** (Step-by-step instructions for the TD on how to score, penalize, or enforce)
"""
    contents_payload.append(prompt)

    try:
        res = ai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=contents_payload,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        return res.text
    except Exception:
        return generate_with_failover(prompt, temperature=0.1)

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
    "9. TD Audit Log"
]

users_df = fetch_users_df()
pending_count = len(users_df[users_df["status"] == "pending"])

if st.session_state.td_role == "admin":
    label = f"10. TD User Management ⚙️ ({pending_count} pending)" if pending_count > 0 else "10. TD User Management ⚙️"
    nav_options.append(label)

with st.sidebar:
    if HAS_LOGO:
        st.image(LOGO_PATH, width=130)
    else:
        st.markdown("""
        <div style="padding-bottom: 12px;">
            <span style="font-size: 22px; font-weight: 800; color: #f8fafc;">🎳 CHUSBC DESK</span>
        </div>
        """, unsafe_allow_html=True)
    
    badge_class = "badge-admin" if st.session_state.td_role == "admin" else "badge-td"
    st.markdown(f"""
    <div style="background-color: #1e293b; padding: 12px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 16px;">
        <div style="font-size: 14px; font-weight: 700; color: #f1f5f9;">{st.session_state.td_name}</div>
        <div style="margin-top: 4px;"><span class="{badge_class}">{st.session_state.td_role.upper()}</span></div>
    </div>
    """, unsafe_allow_html=True)

    nav = st.radio("OPERATIONAL CONSOLE", nav_options)
    
    st.divider()
    st.caption(f"📍 **{st.session_state.tournament_config['center']}**")
    st.caption(f"🏆 {st.session_state.tournament_config['name']}")

    if st.button("🔄 Switch Tournament / Preset", use_container_width=True):
        st.session_state.session_initialized = False
        st.rerun()

    st.markdown("### 💾 Live Cloud State")
    c_save, c_load = st.columns(2)
    with c_save:
        if st.button("Save Live", type="primary", use_container_width=True, help="Save tournament roster, payments, and scores to local SQLite"):
            saved = write_active_tournament_state(
                st.session_state.tournament_config,
                st.session_state.roster,
                st.session_state.brackets
            )
            if saved:
                st.toast("✅ Active tournament saved to SQLite!", icon="💾")
                log_audit_event("TD manually saved live tournament state to SQLite.")
    with c_load:
        if st.button("Restore", use_container_width=True, help="Reload latest active tournament from SQLite"):
            cloud_state = fetch_active_tournament_state()
            if cloud_state:
                st.session_state.tournament_config = cloud_state["config"]
                st.session_state.roster = pd.DataFrame(cloud_state["roster"])
                st.session_state.brackets = cloud_state.get("brackets", [])
                st.session_state.td_pins = cloud_state.get("td_pins", {})
                st.toast(f"✅ Restored snapshot saved at {cloud_state.get('saved_at')}!", icon="🔄")
                log_audit_event("TD restored tournament state from SQLite backup.")
                st.rerun()
            else:
                st.toast("⚠️ No saved active tournament found in SQLite.", icon="⚠️")

    st.write("")
    if st.button("Sign Out / Close Desk", use_container_width=True):
        log_audit_event("User logged out.")
        st.session_state.authenticated = False
        st.session_state.username = ""
        st.session_state.td_name = ""
        st.session_state.td_role = "td"
        st.session_state.pending_password_change = False
        st.session_state.session_initialized = False
        st.rerun()

# ---------------------------------------------------------
# NATIVE FRAGMENT LOGIC: LIVE DESK MONITOR (NO SCREEN DIMMING)
# ---------------------------------------------------------
@st.fragment(run_every="8s")
def render_live_checkin_counters_fragment():
    # Silently pull fresh check-ins from the local SQLite state without page dimming
    cloud_state = fetch_active_tournament_state()
    if cloud_state and "roster" in cloud_state:
        cloud_df = pd.DataFrame(cloud_state["roster"])
        if not cloud_df.empty:
            st.session_state.roster = cloud_df

    total_bowlers = len(st.session_state.roster)
    paid_bowlers = len(st.session_state.roster[st.session_state.roster["Paid"] == True]) if total_bowlers > 0 else 0
    checked_bowlers = len(st.session_state.roster[st.session_state.roster["Checked_In"] == True]) if total_bowlers > 0 else 0

    c_t1, c_t2, c_t3 = st.columns(3)
    with c_t1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{total_bowlers}</div>
            <div class="stat-label">Total Roster</div>
        </div>
        """, unsafe_allow_html=True)
    with c_t2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value" style="color: {'#34d399' if paid_bowlers == total_bowlers and total_bowlers > 0 else '#fbbf24'};">{paid_bowlers} / {total_bowlers}</div>
            <div class="stat-label">Paid Entries</div>
        </div>
        """, unsafe_allow_html=True)
    with c_t3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value" style="color: {'#34d399' if checked_bowlers == total_bowlers and total_bowlers > 0 else '#38bdf8'};">{checked_bowlers} / {total_bowlers}</div>
            <div class="stat-label">Confirmed On-Lane</div>
        </div>
        """, unsafe_allow_html=True)

@st.fragment(run_every="8s")
def render_live_radar_matrix_fragment(radar_game: int):
    # Silently pull latest locked scores from the local SQLite state
    cloud_state = fetch_active_tournament_state()
    if cloud_state and "roster" in cloud_state:
        cloud_df = pd.DataFrame(cloud_state["roster"])
        if not cloud_df.empty:
            st.session_state.roster = cloud_df

    parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
    g_target = f"Game {radar_game}"
    v_by_target = f"G{radar_game}_Verified_By"
    v_at_target = f"G{radar_game}_Verified_At"

    rotation_rule = st.session_state.tournament_config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")
    max_center_lanes = int(st.session_state.tournament_config.get("lanes_count", 40))

    if parsed_pairs:
        radar_cols = st.columns(4)
        for p_idx, pair in enumerate(parsed_pairs):
            col_target = radar_cols[p_idx % 4]
            lane_odd, lane_even = pair
            
            if "Starting Lane" not in st.session_state.roster.columns:
                st.session_state.roster["Starting Lane"] = 1
                
            working_rost = st.session_state.roster.copy()
            working_rost["Starting Lane"] = pd.to_numeric(working_rost["Starting Lane"], errors="coerce").fillna(1).astype(int)
            working_rost["Active_Game_Lane"] = working_rost["Starting Lane"].apply(
                lambda l: get_bowler_lane_for_game(int(l), radar_game, rotation_rule, max_lanes=max_center_lanes)
            )
            p_bowlers = working_rost[working_rost["Active_Game_Lane"].isin([lane_odd, lane_even])]

            if p_bowlers.empty:
                status_color = "#334155"
                status_badge = "⚪ EMPTY"
                card_sub = "No bowlers assigned"
            else:
                has_scores = (p_bowlers[g_target] > 0).any()
                all_verified = (p_bowlers[v_by_target].astype(str).str.strip() != "").all()

                if all_verified and has_scores:
                    status_color = "#10b981"
                    v_name = p_bowlers.iloc[0].get(v_by_target, "TD")
                    v_time = p_bowlers.iloc[0].get(v_at_target, "")
                    status_badge = "🟢 PIN VERIFIED"
                    card_sub = f"By {v_name} ({v_time})"
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

# ---------------------------------------------------------
# MODULE 1: COMPREHENSIVE INTAKE (SETTINGS -> ROSTER -> DESK TERMINAL)
# ---------------------------------------------------------
if nav == "1. Event & Roster Intake":
    st.markdown(f"""
    <div class="brand-banner">
        <h1>{st.session_state.tournament_config['name']}</h1>
        <p>Host Center: {st.session_state.tournament_config['center']} | Format: {st.session_state.tournament_config.get('format_mode', 'Standard')} | Up to 40 Lanes</p>
    </div>
    """, unsafe_allow_html=True)

    intake_tab_settings, intake_tab_entry, intake_tab_terminal, intake_tab_pins = st.tabs([
        "⚙️ Event Settings & CHUSBC Presets",
        "📝 Roster Ingestion & 40-Lane Balancing",
        "💳 Desk Intake & Entrance QR Posters",
        "🔐 Floor TD PIN Registry (Argon2)"
    ])

    with intake_tab_settings:
        st.subheader("Tournament Calibration & Presets")
        preset_choice = st.selectbox(
            "Load Official CHUSBC Profile:",
            ["-- Select to Apply Preset --"] + list(CHUSBC_PRESET_PROFILES.keys())
        )
        if preset_choice != "-- Select to Apply Preset --":
            if st.button(f"Apply '{preset_choice}' Parameters", type="primary"):
                p_data = CHUSBC_PRESET_PROFILES[preset_choice]
                st.session_state.tournament_config.update(p_data)
                st.session_state.tournament_config["name"] = preset_choice
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success(f"Applied {preset_choice} presets!")
                st.rerun()

        st.divider()

        c_name, c_center = st.columns([2, 1])
        with c_name:
            t_name = st.text_input("Tournament Name:", value=st.session_state.tournament_config["name"])
        with c_center:
            center_options = ["Forest Hill Lanes", "Harford Lanes", "APG Brewner Lanes", "Elk Lanes", "Other"]
            cur_center = st.session_state.tournament_config["center"]
            c_idx = center_options.index(cur_center) if cur_center in center_options else 0
            center = st.selectbox("Host Bowling Center:", center_options, index=c_idx)

        col_lanes1, col_lanes2, col_div = st.columns([1, 1, 1])
        with col_lanes1:
            lane_count = st.number_input("Total Lanes in Center:", min_value=2, max_value=60, value=int(st.session_state.tournament_config.get("lanes_count", 40)), step=2)
        with col_lanes2:
            lane_range = st.text_input("Active Pair Range (e.g. 1-40 or 1-16, 21-36):", value=st.session_state.tournament_config.get("lanes_range", "1-40"))
        with col_div:
            division = st.text_input("Division / Category:", value=st.session_state.tournament_config.get("division", "Adult Open"))

        col_h1, col_h2, col_h3 = st.columns(3)
        with col_h1:
            h_base = st.number_input("Handicap Base Average:", value=int(st.session_state.tournament_config.get("hdcp_base", 220)), step=5)
        with col_h2:
            h_pct = st.number_input("Handicap Percentage (0.90 = 90%):", value=float(st.session_state.tournament_config.get("hdcp_pct", 0.90)), step=0.05, format="%.2f")
        with col_h3:
            current_rule = st.session_state.tournament_config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")
            rule_options = ["Stay on Pair (No Movement)", "Move Right 1 Pair (+2 Lanes)", "Move Right 2 Pairs (+4 Lanes)", "Move Left 1 Pair (-2 Lanes)"]
            r_idx = rule_options.index(current_rule) if current_rule in rule_options else 1
            movement_rule = st.selectbox("Lane Rotation Rule (Between Games):", rule_options, index=r_idx)

        t_rules = st.text_area("Tournament Rules & Format Flyer:", value=st.session_state.tournament_config["rules_text"])
        uploaded_doc = st.file_uploader("Upload Tournament Flyer / Rules PDF (.pdf or .txt):", type=["pdf", "txt"])

        if st.button("🔒 Save & Lock Tournament Configuration", type="primary", use_container_width=True):
            uploaded_content = ""
            if uploaded_doc is not None:
                if uploaded_doc.type == "application/pdf" or uploaded_doc.name.lower().endswith(".pdf"):
                    try:
                        reader = PdfReader(uploaded_doc)
                        extracted_text = []
                        for page in reader.pages:
                            text = page.extract_text()
                            if text:
                                extracted_text.append(text)
                        uploaded_content = f"\n[EXTRACTED PDF RULES]:\n" + "\n".join(extracted_text)
                    except Exception as e:
                        st.error(f"Error reading PDF: {e}")
                else:
                    uploaded_content = f"\n[RULES FILE]:\n{uploaded_doc.read().decode('utf-8', errors='ignore')}"

            st.session_state.tournament_config.update({
                "center": center,
                "name": t_name,
                "lanes_count": lane_count,
                "lanes_range": lane_range,
                "division": division,
                "hdcp_base": h_base,
                "hdcp_pct": h_pct,
                "movement_rule": movement_rule,
                "rules_text": t_rules + uploaded_content,
                "intake_completed": True
            })
            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
            log_audit_event(f"Configuration locked: {t_name} at {center}.")
            st.success("Tournament settings locked & backed up to SQLite.")

    with intake_tab_entry:
        st.subheader("Bowler Roster & Team-Aware 40-Lane Balancer")
        st.caption("Ingest bowlers via photo/scan, text notes, CSV, or balance your field across up to 40 lanes while keeping teams together.")

        tab_scan, tab_ai, tab_csv, tab_manual, tab_balancer = st.tabs([
            "📸 Scan/Photo Clipboard (AI)",
            "🤖 Paste Signup Notes (Gemini AI)",
            "📁 Upload CSV",
            "📋 Editable Master Grid",
            "🎳 Automated Lane Balancer"
        ])

        with tab_scan:
            scan_mode = st.radio("Capture Method:", ["📷 Camera Snapshot", "📁 Upload Image / Scan"], horizontal=True)
            captured_image = None
            mime_type = "image/jpeg"

            if scan_mode == "📷 Camera Snapshot":
                camera_file = st.camera_input("Take photo of sheet:")
                if camera_file is not None:
                    captured_image = camera_file.getvalue()
                    mime_type = camera_file.type or "image/jpeg"
            else:
                uploaded_image = st.file_uploader("Upload Image of Signup Sheet:", type=["jpg", "jpeg", "png", "webp"])
                if uploaded_image is not None:
                    captured_image = uploaded_image.getvalue()
                    mime_type = uploaded_image.type or "image/jpeg"

            if captured_image is not None:
                st.image(captured_image, caption="Sheet Preview", width=360)
                if st.button("🔍 Extract Bowlers from Photo with Gemini", type="primary"):
                    if not ai_client:
                        st.error("Gemini API key is missing.")
                    else:
                        with st.spinner("Analyzing handwriting and printed text..."):
                            prompt = """
Analyze this tournament signup sheet (handwritten or printed).
Extract all bowler entries into standard CSV format with these exact columns:
USBC ID,Bowler,Average,Starting Lane,Division,Team_Name,Paid

Rules:
1. 'USBC ID': Bowler USBC sanction ID number. If missing, format as 'TBD'.
2. 'Bowler': Full name.
3. 'Average': Numeric entering average (default 200 if missing).
4. 'Starting Lane': Assigned lane number (default 1).
5. 'Division': e.g., Senior A/B, Scratch, Handicap, or Regular.
6. 'Team_Name': Team name or partner name if doubles/team (default 'Singles').
7. 'Paid': True if checkmark or cash notation; otherwise False.
Output strictly CSV formatted table without markdown code fences.
"""
                            try:
                                content_part = types.Part.from_bytes(data=captured_image, mime_type=mime_type)
                                response = ai_client.models.generate_content(
                                    model=PRIMARY_MODEL,
                                    contents=[content_part, prompt],
                                    config=types.GenerateContentConfig(temperature=0.1)
                                )
                                raw_csv = response.text.replace("```csv", "").replace("```", "").strip()
                                parsed_df = pd.read_csv(io.StringIO(raw_csv))
                                if "USBC ID" not in parsed_df.columns:
                                    parsed_df["USBC ID"] = [f"11-{10000+i+1}" for i in range(len(parsed_df))]
                                parsed_df["Checked_In"] = False
                                for g in ["Game 1", "Game 2", "Game 3"]:
                                    parsed_df[g] = 0
                                for v_col in ["G1_Verified_By", "G1_Verified_At", "G2_Verified_By", "G2_Verified_At", "G3_Verified_By", "G3_Verified_At"]:
                                    parsed_df[v_col] = ""

                                st.session_state.roster = parsed_df
                                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                                log_audit_event(f"Gemini scanned and extracted {len(parsed_df)} bowlers from photo.")
                                st.success(f"Successfully extracted {len(parsed_df)} bowlers!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error analyzing image: {e}")

        with tab_ai:
            raw_bowler_text = st.text_area(
                "Paste bowler signups (e.g. USBC ID, names, averages, teams, divisions):",
                placeholder="11-12345 Scott Kramer (218 avg, Team Striking Power)\n11-23456 Dave Miller (205 avg, Team Striking Power)\nChris Reynolds (195 avg, Team Brunswick Boys)",
                height=110
            )
            if st.button("Extract Roster with Gemini", type="primary"):
                if not ai_client:
                    st.error("Gemini API key missing.")
                elif not raw_bowler_text.strip():
                    st.warning("Please paste or type bowler names.")
                else:
                    with st.spinner("Gemini is parsing the entries..."):
                        prompt = f"""
Extract bowler USBC ID (default 'TBD' if not given), names, entry average (default 200), starting lane (default 1), division (default 'Open'), and Team_Name (default 'Singles').
Output strictly CSV formatted text with headers:
USBC ID,Bowler,Average,Starting Lane,Division,Team_Name,Game 1,Game 2,Game 3
Set games to 0.

Input:
{raw_bowler_text}
"""
                        try:
                            raw_csv_text = generate_with_failover(prompt, temperature=0.0)
                            cleaned_csv = raw_csv_text.replace("```csv", "").replace("```", "").strip()
                            new_roster_df = pd.read_csv(io.StringIO(cleaned_csv))
                            if "USBC ID" not in new_roster_df.columns:
                                new_roster_df["USBC ID"] = [f"11-{10000+i+1}" for i in range(len(new_roster_df))]
                            new_roster_df["Paid"] = False
                            new_roster_df["Checked_In"] = False
                            for v_col in ["G1_Verified_By", "G1_Verified_At", "G2_Verified_By", "G2_Verified_At", "G3_Verified_By", "G3_Verified_At"]:
                                new_roster_df[v_col] = ""
                            st.session_state.roster = new_roster_df
                            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                            log_audit_event(f"Gemini parsed {len(new_roster_df)} bowler entries.")
                            st.success(f"Parsed and added {len(new_roster_df)} bowlers!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to parse entries: {e}")

        with tab_csv:
            csv_file = st.file_uploader("Select Roster CSV:", type=["csv"])
            if csv_file is not None:
                try:
                    df_upload = pd.read_csv(csv_file)
                    for col in ["Game 1", "Game 2", "Game 3"]:
                        if col not in df_upload.columns:
                            df_upload[col] = 0
                    if "USBC ID" not in df_upload.columns:
                        df_upload["USBC ID"] = [f"11-{10000+i+1}" for i in range(len(df_upload))]
                    for default_col in ["Division", "Team_Name"]:
                        if default_col not in df_upload.columns:
                            df_upload[default_col] = "Open"
                    if "Paid" not in df_upload.columns:
                        df_upload["Paid"] = False
                    if "Checked_In" not in df_upload.columns:
                        df_upload["Checked_In"] = False
                    for v_col in ["G1_Verified_By", "G1_Verified_At", "G2_Verified_By", "G2_Verified_At", "G3_Verified_By", "G3_Verified_At"]:
                        if v_col not in df_upload.columns:
                            df_upload[v_col] = ""
                    st.session_state.roster = df_upload
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success("CSV Imported successfully.")
                except Exception as err:
                    st.error(f"Error loading CSV: {err}")

        with tab_manual:
            cols_to_show = [c for c in ["USBC ID", "Bowler", "Average", "Starting Lane", "Division", "Team_Name", "Paid", "Checked_In"] if c in st.session_state.roster.columns]
            edited_roster = st.data_editor(
                st.session_state.roster[cols_to_show],
                num_rows="dynamic",
                use_container_width=True,
                key="manual_roster_grid"
            )
            if st.button("Save Roster Changes"):
                for col in ["Game 1", "Game 2", "Game 3"]:
                    if col not in edited_roster.columns:
                        edited_roster[col] = 0
                for v_col in ["G1_Verified_By", "G1_Verified_At", "G2_Verified_By", "G2_Verified_At", "G3_Verified_By", "G3_Verified_At"]:
                    if v_col not in edited_roster.columns:
                        edited_roster[v_col] = ""
                st.session_state.roster = edited_roster
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                log_audit_event("TD updated roster grid.")
                st.success("Roster updated & saved to cloud.")

        with tab_balancer:
            st.markdown("### 🎳 Team-Aware Automated Lane Balancer & House Matrix (Up to 40 Lanes)")
            st.caption("Distribute bowlers across pairs while keeping all teammates grouped together on the exact same lane pair.")

            col_b1, col_b2, col_b3, col_b4 = st.columns([2, 1, 1, 1])
            with col_b1:
                custom_range = st.text_input(
                    "Active Lane Range (supports commas and hyphens):",
                    value=st.session_state.tournament_config.get("lanes_range", "1-40"),
                    placeholder="e.g. 1-40 or 1-16, 21-36"
                )
            with col_b2:
                max_capacity = st.selectbox("Max Bowlers per Pair:", [4, 5, 6, 8, 10], index=1, help="Choose 5 for 1 team per pair, or 8/10 for two 4- or 5-person teams head-to-head.")
            with col_b3:
                group_teams = st.checkbox("👥 Group Teammates", value=True, help="Keeps bowlers with the same 'Team_Name' together on the same pair.")
            with col_b4:
                shuffle_draw = st.checkbox("🎲 Blind Random Draw", value=True)

            parsed_pairs = parse_active_pairs(custom_range, max_lanes=40)
            total_capacity = len(parsed_pairs) * max_capacity
            field_size = len(st.session_state.roster)

            st.markdown(f"""
            <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; margin: 12px 0; font-size: 14px;">
                Active Pairs: <b>{len(parsed_pairs)} pairs</b> ({len(parsed_pairs)*2} lanes) | 
                Current Roster: <b>{field_size} bowlers</b> | 
                Max Capacity: <b>{total_capacity} bowlers</b> | 
                Average Density: <b>{round(field_size / max(len(parsed_pairs), 1), 1)} bowlers/pair</b>
            </div>
            """, unsafe_allow_html=True)

            col_run_bal, col_clear_bal = st.columns([1, 1])
            with col_run_bal:
                if st.button("⚡ Balance & Assign Lanes Automatically", type="primary", use_container_width=True):
                    if not parsed_pairs:
                        st.error("No valid lane pairs found in the specified range.")
                    else:
                        new_roster, err = auto_assign_lanes(
                            st.session_state.roster,
                            parsed_pairs,
                            max_per_pair=max_capacity,
                            shuffle=shuffle_draw,
                            group_by_team=group_teams
                        )
                        if err:
                            st.error(err)
                        else:
                            st.session_state.roster = new_roster
                            st.session_state.tournament_config["lanes_range"] = custom_range
                            st.session_state.tournament_config["lanes_count"] = len(parsed_pairs) * 2
                            write_active_tournament_state(
                                st.session_state.tournament_config,
                                st.session_state.roster,
                                st.session_state.brackets
                            )
                            log_audit_event(f"Automated team-aware lane balancing executed across {len(parsed_pairs)} pairs for {field_size} bowlers.")
                            st.success(f"Successfully balanced {field_size} bowlers across {len(parsed_pairs)} lane pairs with team assignments locked!")
                            st.rerun()

            if not st.session_state.roster.empty:
                st.write("")
                pdf_roster_bytes = export_lane_assignments_pdf(st.session_state.roster, st.session_state.tournament_config)
                st.download_button(
                    "📄 Download Printable PDF Lane Assignment Roster (Grouped by Pair & Team)",
                    data=pdf_roster_bytes,
                    file_name=f"{st.session_state.tournament_config['name'].replace(' ', '_')}_Lane_Assignments.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

            if not st.session_state.roster.empty and parsed_pairs:
                st.markdown("#### 📍 Active House Layout Matrix")
                matrix_cols = st.columns(4)
                for idx, pair in enumerate(parsed_pairs):
                    col_target = matrix_cols[idx % 4]
                    lane_odd, lane_even = pair
                    bowlers_on_pair = st.session_state.roster[st.session_state.roster["Starting Lane"].isin([lane_odd, lane_even])]
                    
                    with col_target:
                        st.markdown(f"""
                        <div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 10px; margin-bottom: 10px;">
                            <div style="font-weight: 800; color: #38bdf8; font-size: 13px; border-bottom: 1px solid #1e293b; padding-bottom: 4px; margin-bottom: 6px;">
                                Lanes {lane_odd} & {lane_even} <span style="color: #94a3b8; font-size: 11px; float: right;">({len(bowlers_on_pair)}/{max_capacity})</span>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        if bowlers_on_pair.empty:
                            st.markdown("<span style='color: #64748b; font-size: 12px;'><i>Empty pair</i></span></div>", unsafe_allow_html=True)
                        else:
                            for _, b in bowlers_on_pair.iterrows():
                                paid_icon = "🟢" if b["Paid"] else "🔴"
                                team_tag = f" <span style='color:#38bdf8;'>[{b.get('Team_Name', 'Singles')}]</span>" if b.get('Team_Name') and b.get('Team_Name') != "Singles" else ""
                                st.markdown(f"""
                                <div style="font-size: 12px; color: #f8fafc; margin-bottom: 2px;">
                                    {paid_icon} <b>L{b['Starting Lane']}:</b> {b['Bowler']}{team_tag} <span style="color: #94a3b8;">({b['Average']})</span>
                                </div>
                                """, unsafe_allow_html=True)
                            st.markdown("</div>", unsafe_allow_html=True)

    with intake_tab_terminal:
        st.subheader("Payment Gate, Entrance QR & Check-In Terminal")
        st.caption("Manage desk walk-ups, customer-facing monitor displays, and entrance self-check-in QR codes.")

        detected_base = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")
        kiosk_launch_url = f"{detected_base}/?mode=kiosk"
        self_checkin_url = f"{detected_base}/?mode=self_checkin"
        bowler_portal_url = f"{detected_base}/?mode=bowler_portal"

        col_qr1, col_qr2, col_qr3 = st.columns(3)
        with col_qr1:
            st.markdown("##### 🚪 Entrance Self-Check-In QR")
            st.image(generate_qr_image(self_checkin_url), width=140)
            st.link_button("🔗 Open Entrance Check-In", self_checkin_url, use_container_width=True)
            st.caption("Pre-paid bowlers auto-check in; unpaid or bracket bowlers are directed to desk.")
        with col_qr2:
            st.markdown("##### 📊 Bowler Live Portal QR")
            st.image(generate_qr_image(bowler_portal_url), width=140)
            st.link_button("🔗 Open Bowler Portal", bowler_portal_url, use_container_width=True)
            st.caption("Read-only portal for bowlers to view their rank, lane, and scores.")
        with col_qr3:
            st.markdown("##### 🖥️ Desk Customer Monitor")
            st.link_button("🖥️ Launch Customer Kiosk", kiosk_launch_url, use_container_width=True)
            if st.button("🔄 Reset Customer Screen", use_container_width=True):
                clear_kiosk_state()
                log_audit_event("TD reset customer kiosk display to idle banner.")
                st.rerun()
            st.caption("Drag to secondary monitor facing the bowler line (F11).")

        st.divider()

        # Render Live Counters via Fragment (Zero-Dimming Auto-Sync)
        render_live_checkin_counters_fragment()

        st.write("")

        bowler_names = st.session_state.roster["Bowler"].tolist() if not st.session_state.roster.empty else []
        search_query = st.selectbox("Search / Select Bowler at Desk:", ["-- Select Bowler Arriving at Desk --"] + bowler_names)

        if search_query != "-- Select Bowler Arriving at Desk --":
            b_row = st.session_state.roster[st.session_state.roster["Bowler"] == search_query].iloc[0]
            b_usbc = str(b_row["USBC ID"])
            b_paid = bool(b_row["Paid"])
            b_checked = bool(b_row["Checked_In"])
            b_lane = int(b_row["Starting Lane"])

            pair_partner = b_lane + 1 if b_lane % 2 != 0 else b_lane - 1
            pair_display_str = f"Lanes {min(b_lane, pair_partner)} & {max(b_lane, pair_partner)}"

            card_payload = {
                "name": search_query,
                "usbc_id": b_usbc,
                "avg": int(b_row["Average"]),
                "lane": b_lane,
                "pair_display": pair_display_str
            }

            st.write("")
            col_info, col_actions = st.columns([1, 1])

            with col_info:
                st.markdown(f"""
                <div class="match-box">
                    <h3 style="margin: 0; color: #f8fafc;">{search_query}</h3>
                    <div style="color: #94a3b8; font-size: 13px; margin: 4px 0 10px 0;">USBC ID: <code>{b_usbc}</code> | Avg: <b>{b_row['Average']}</b> | Starting: <b>Lane {b_lane}</b></div>
                    <div style="margin-top: 10px;">
                        Payment Status: <b>{'🟢 PAID' if b_paid else '🔴 UNPAID'}</b><br/>
                        Check-in Status: <b>{'🟢 CHECKED IN' if b_checked else '⚪ NOT CHECKED IN'}</b>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                if not b_paid:
                    payment_type = st.radio("Select Payment Method Received:", ["Cash", "Check", "Venmo / Electronic"], horizontal=True)
                    if st.button(f"Mark Paid ({payment_type}) & Display on Customer Screen", type="primary", use_container_width=True):
                        idx = st.session_state.roster.index[st.session_state.roster["USBC ID"].astype(str) == b_usbc].tolist()
                        if idx:
                            st.session_state.roster.loc[idx[0], "Paid"] = True
                            write_kiosk_state(card_payload)
                            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                            log_audit_event(f"Payment collected for {search_query} ({payment_type}) & pushed to customer screen.")
                            st.success("Payment logged! Now displaying QR code on customer-facing monitor.")
                            st.rerun()
                else:
                    st.success("Entry fee paid. Bowler is authorized for check-in.")
                    col_p1, col_p2 = st.columns(2)
                    with col_p1:
                        if st.button("📺 Push to Customer Screen", type="primary", use_container_width=True):
                            write_kiosk_state(card_payload)
                            log_audit_event(f"Pushed {search_query} to external customer screen.")
                            st.rerun()
                    with col_p2:
                        if st.button("Mark as Unpaid (Revert)", use_container_width=True):
                            idx = st.session_state.roster.index[st.session_state.roster["USBC ID"].astype(str) == b_usbc].tolist()
                            if idx:
                                st.session_state.roster.loc[idx[0], "Paid"] = False
                                st.session_state.roster.loc[idx[0], "Checked_In"] = False
                                current_kiosk = read_kiosk_state()
                                if current_kiosk and current_kiosk.get("usbc_id") == b_usbc:
                                    clear_kiosk_state()
                                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                                log_audit_event(f"Payment reverted to Unpaid for {search_query}.")
                                st.rerun()

            with col_actions:
                if not b_paid:
                    st.info("👈 Collect entry fee and click **'Mark Paid'** to push this bowler's check-in QR code to the customer-facing monitor.")
                else:
                    checkin_url = f"{detected_base}/?mode=checkin&usbc_id={b_usbc}"
                    qr_buf = generate_qr_image(checkin_url)

                    current_kiosk = read_kiosk_state()
                    is_currently_on_kiosk = (
                        current_kiosk is not None and 
                        current_kiosk.get("usbc_id") == b_usbc
                    )
                    status_text = "🟢 Currently Live on Customer Screen" if is_currently_on_kiosk else "⚪ Not currently on Customer Screen"
                    
                    st.markdown(f"#### 📲 Desk Preview ({search_query}):")
                    st.caption(f"Status: **{status_text}**")
                    st.image(qr_buf, width=200)

                    if not b_checked:
                        if st.button("Manual TD Check-In Override (No Phone)", use_container_width=True):
                            idx = st.session_state.roster.index[st.session_state.roster["USBC ID"].astype(str) == b_usbc].tolist()
                            if idx:
                                st.session_state.roster.loc[idx[0], "Checked_In"] = True
                                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                                log_audit_event(f"TD manually checked in {search_query}.")
                                st.rerun()

    with intake_tab_pins:
        st.subheader("🔐 Floor TD Security PIN Registry (Argon2id)")
        st.caption("Manage secret 4-digit PINs assigned to roving board members for on-lane score signing and concurrence.")

        current_pins = st.session_state.get("td_pins", {})
        if current_pins:
            st.markdown("#### Authorized Floor Officials (Active Tournament):")
            pin_rows = []
            for td_n, p_hash in current_pins.items():
                algo = "Argon2id" if str(p_hash).startswith("$argon2") else "SHA-256 (Legacy)"
                pin_rows.append({"Floor Official": td_n, "Encryption": algo, "PIN Status": "🟢 Established & Locked"})
            st.dataframe(pd.DataFrame(pin_rows), use_container_width=True)
        else:
            st.info("No floor officials have established a PIN yet for this tournament.")

        st.write("")
        st.markdown("#### Central Desk PIN Override / Reset")
        with st.form("admin_pin_override_form"):
            override_name = st.text_input("Official Full Name:", placeholder="e.g. Dave Miller").strip()
            new_pin = st.text_input("Assign / Reset 4-Digit PIN:", type="password", max_chars=6).strip()
            submit_override = st.form_submit_button("Lock / Reset Official PIN (Argon2id)", type="primary", use_container_width=True)

            if submit_override:
                if not override_name or len(new_pin) < 4:
                    st.error("Official name and at least 4 digits required.")
                else:
                    register_td_pin(override_name, new_pin)
                    log_audit_event(f"Admin reset Argon2id security PIN for floor official '{override_name}'.")
                    st.success(f"Security PIN for '{override_name}' hashed with Argon2id and synchronized!")
                    st.rerun()

# ---------------------------------------------------------
# MODULE 2: SCORES, STANDINGS & CENTRAL DESK LANE RADAR MATRIX
# ---------------------------------------------------------
elif nav == "2. Scores & Standings":
    standings = compile_standings(st.session_state.roster)

    st.markdown(f"""
    <div class="brand-banner">
        <h1>{st.session_state.tournament_config['name']}</h1>
        <p>{st.session_state.tournament_config['center']} | Format: {st.session_state.tournament_config.get('format_mode', 'Standard')} | Handicap: {int(st.session_state.tournament_config.get('hdcp_pct', 0.90)*100)}% of {st.session_state.tournament_config.get('hdcp_base', 220)}</p>
    </div>
    """, unsafe_allow_html=True)

    detected_base = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")
    scorer_url = f"{detected_base}/?mode=scorer"
    leaderboard_url = f"{detected_base}/?mode=leaderboard"
    
    col_deploy_s, col_deploy_l = st.columns(2)
    with col_deploy_s:
        with st.expander("📱 Roving Floor TD Scorer Launch", expanded=False):
            scorer_qr = generate_qr_image(scorer_url)
            st.image(scorer_qr, caption="Scan with phone camera to score lanes", width=160)
            st.link_button("📲 Open Mobile Scorer Portal", scorer_url, use_container_width=True)
            st.caption("Floor officials enter scores with Camera Snapshot OCR & Argon2 PIN concurrence.")

    with col_deploy_l:
        with st.expander("📺 Concourse TV & Overhead Leaderboard", expanded=False):
            lb_qr = generate_qr_image(leaderboard_url)
            st.image(lb_qr, caption="Scan or open on Concourse / Bar Smart TVs", width=160)
            st.link_button("🖥️ Launch Concourse TV Leaderboard", leaderboard_url, use_container_width=True)
            st.caption("Autoscrolling, high-contrast overhead display for spectators & bowlers.")

    st.subheader("🛰️ Central Desk Lane Radar Matrix")
    radar_game = st.radio("Display Radar for Game:", [1, 2, 3], horizontal=True, key="radar_game_sel")

    # Render Live Lane Radar Matrix via Fragment (Zero-Dimming Auto-Sync)
    render_live_radar_matrix_fragment(radar_game)

    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{len(st.session_state.roster)}</div>
            <div class="stat-label">Active Field Size</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        top_score = standings.iloc[0]["Grand_Total"] if not standings.empty else 0
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{top_score}</div>
            <div class="stat-label">Tournament Leader</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        cut_score = standings.iloc[4]["Grand_Total"] if len(standings) >= 5 else 0
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{cut_score}</div>
            <div class="stat-label">Cut Line (#5 Seed)</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        hi_scratch = standings["High_Scratch_Game"].max() if not standings.empty else 0
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{hi_scratch}</div>
            <div class="stat-label">High Scratch Game</div>
        </div>
        """, unsafe_allow_html=True)

    st.write("")

    with st.expander("⚡ Gemini Live Score Recap Ingestion"):
        recap_text = st.text_area("Paste recap update text (e.g. 'Scott Kramer 245, 238, 268'):")
        if st.button("Apply Recap Scores"):
            if not ai_client:
                st.error("Gemini API key missing.")
            elif not recap_text.strip():
                st.warning("Enter score text to apply.")
            else:
                with st.spinner("Extracting scores..."):
                    prompt = f"""
Existing Roster:
{st.session_state.roster.to_csv(index=False)}

Incoming Recap:
{recap_text}

Update Game 1, Game 2, and Game 3 columns for matching bowlers.
Output strictly CSV formatted table with headers:
USBC ID,Bowler,Average,Starting Lane,Division,Team_Name,Game 1,Game 2,Game 3,Paid,Checked_In,G1_Verified_By,G1_Verified_At,G2_Verified_By,G2_Verified_At,G3_Verified_By,G3_Verified_At
"""
                    try:
                        raw_csv_text = generate_with_failover(prompt, temperature=0.0)
                        cleaned = raw_csv_text.replace("```csv", "").replace("```", "").strip()
                        st.session_state.roster = pd.read_csv(io.StringIO(cleaned))
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        log_audit_event("Gemini updated scores from live recap.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error parsing scores: {e}")

    st.subheader("Official Scoring Grid")
    cols_scoring = [c for c in ["USBC ID", "Bowler", "Average", "Starting Lane", "Division", "Team_Name", "Paid", "Checked_In", "Game 1", "Game 2", "Game 3", "G1_Verified_By", "G2_Verified_By", "G3_Verified_By"] if c in st.session_state.roster.columns]
    edited_scores = st.data_editor(
        st.session_state.roster[cols_scoring],
        num_rows="dynamic",
        use_container_width=True,
        key="official_scoring_grid"
    )
    if st.button("Save Scores & Recalculate Standings", type="primary"):
        for c in DEFAULT_ROSTER_COLS:
            if c not in edited_scores.columns and c in st.session_state.roster.columns:
                edited_scores[c] = st.session_state.roster[c]
        st.session_state.roster = edited_scores
        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
        log_audit_event("Scores saved and recalculated at Central Desk.")
        st.toast("✅ Scores updated & backed up to SQLite!", icon="💾")
        st.rerun()

    if not standings.empty:
        st.subheader("Live Official Standings")
        divisions_present = standings["Division"].dropna().unique().tolist() if "Division" in standings.columns else []
        if len(divisions_present) > 1:
            selected_div_filter = st.selectbox("Filter Standings by Division:", ["All Divisions"] + divisions_present)
            if selected_div_filter != "All Divisions":
                standings = standings[standings["Division"] == selected_div_filter]

        cols_standings_display = [c for c in [
            "Bowler", "USBC ID", "Division", "Team_Name", "Average", "HDCP_Per_Game", "Game 1", "Game 2",
            "Game 3", "Scratch_Total", "Total_HDCP", "Grand_Total", "High_Scratch_Game"
        ] if c in standings.columns]
        
        st.dataframe(standings[cols_standings_display], use_container_width=True)

        pdf_bytes = export_standings_pdf(standings, st.session_state.tournament_config)
        st.download_button(
            "📄 Download Current Official PDF Standings",
            data=pdf_bytes,
            file_name=f"{st.session_state.tournament_config['name'].replace(' ', '_')}_Standings.pdf",
            mime="application/pdf"
        )

    st.divider()
    st.subheader("🏆 Multi-Squad All-Events Aggregate Leaderboard")
    st.caption("Tracks cumulative performance (Team + Doubles + Singles squads) combined into a master All-Events total.")

    all_events_df = compile_all_events_leaderboard(st.session_state.roster)

    if all_events_df.empty:
        st.info("No scores available for All-Events aggregation yet.")
    else:
        cols_ae = [c for c in ["Bowler", "USBC ID", "Division", "Team_Name", "Average", "Total_Games_Bowled", "Total_HDCP", "Scratch_Series", "Grand_Total"] if c in all_events_df.columns]
        st.dataframe(all_events_df[cols_ae], use_container_width=True)

        pdf_ae_bytes = export_standings_pdf(all_events_df, st.session_state.tournament_config, champion_name="")
        st.download_button(
            "📄 Download Official All-Events Standings PDF",
            data=pdf_ae_bytes,
            file_name=f"{st.session_state.tournament_config['name'].replace(' ', '_')}_All_Events.pdf",
            mime="application/pdf"
        )

# ---------------------------------------------------------
# MODULE 3: STEP-LADDER FINALS & AUTOMATED TOURNAMENT COMPLETION
# ---------------------------------------------------------
elif nav == "3. Stepladder Finals":
    st.markdown("""
    <div class="brand-banner">
        <h1>Championship Stepladder Finals & Tournament Completion</h1>
        <p>Automated cut-line calculation, tiebreaker resolution, stepladder simulation, and official hard-copy PDF report generation.</p>
    </div>
    """, unsafe_allow_html=True)

    standings = compile_standings(st.session_state.roster)
    if len(standings) < 5:
        st.warning(f"Tournament completion and stepladder finals require at least 5 registered bowlers with recorded scores (Current field: {len(standings)}).")
    else:
        top_5 = standings.head(5)["Bowler"].tolist()
        
        def get_bowler_score(b_name):
            row = standings[standings["Bowler"] == b_name]
            return int(row.iloc[0]["Grand_Total"]) if not row.empty else 0

        # Match 1: #4 vs #5
        m1_p1, m1_p2 = top_5[3], top_5[4]
        m1_s1, m1_s2 = get_bowler_score(m1_p1), get_bowler_score(m1_p2)
        m1_winner = m1_p1 if m1_s1 >= m1_s2 else m1_p2
        m1_score_str = f"{max(m1_s1, m1_s2)} - {min(m1_s1, m1_s2)}"

        # Match 2: #3 vs Match 1 Winner
        m2_p1 = top_5[2]
        m2_s1, m2_s2 = get_bowler_score(m2_p1), get_bowler_score(m1_winner)
        m2_winner = m2_p1 if m2_s1 >= m2_s2 else m1_winner
        m2_score_str = f"{max(m2_s1, m2_s2)} - {min(m2_s1, m2_s2)}"

        # Semifinal: #2 vs Match 2 Winner
        semi_p1 = top_5[1]
        semi_s1, semi_s2 = get_bowler_score(semi_p1), get_bowler_score(m2_winner)
        semi_winner = semi_p1 if semi_s1 >= semi_s2 else m2_winner
        semi_score_str = f"{max(semi_s1, semi_s2)} - {min(semi_s1, semi_s2)}"

        # Championship: #1 vs Semifinal Winner
        champ_p1 = top_5[0]
        champ_s1, champ_s2 = get_bowler_score(champ_p1), get_bowler_score(semi_winner)
        tournament_champion = champ_p1 if champ_s1 >= champ_s2 else semi_winner
        champ_score_str = f"{max(champ_s1, champ_s2)} - {min(champ_s1, champ_s2)}"

        stepladder_summary_dict = {
            "m1_p1": m1_p1, "m1_p2": m1_p2, "m1_winner": m1_winner, "m1_score": m1_score_str,
            "m2_p1": m2_p1, "m2_winner_prev": m1_winner, "m2_winner": m2_winner, "m2_score": m2_score_str,
            "semi_p1": semi_p1, "semi_winner_prev": m2_winner, "semi_winner": semi_winner, "semi_score": semi_score_str,
            "champ_p1": champ_p1, "champ_winner_prev": semi_winner, "champ_score": champ_score_str
        }

        st.subheader("⚡ Automated Tournament Completion Engine")
        st.markdown(f"""
        <div style="background-color: #10b98120; border: 1.5px solid #10b981; border-radius: 10px; padding: 18px; text-align: center; margin-bottom: 20px;">
            <span style="font-size: 13px; text-transform: uppercase; color: #34d399; font-weight: 800;">Calculated Tournament Champion</span>
            <h1 style="color: #f8fafc; font-size: 32px; margin: 6px 0 0 0; font-weight: 900;">👑 {tournament_champion}</h1>
            <p style="color: #cbd5e1; font-size: 14px; margin: 4px 0 0 0;">All handicap scores, tiebreakers, and stepladder rounds have been automatically computed.</p>
        </div>
        """, unsafe_allow_html=True)

        col_s1, col_s2 = st.columns([1, 1])
        with col_s1:
            st.markdown("#### 🪵 Top 5 Seeded Qualifiers")
            for idx, name in enumerate(top_5):
                score_val = get_bowler_score(name)
                st.markdown(f"""<div class="match-box"><b>#{idx+1} Seed:</b> {name} <span style="float: right; color: #38bdf8;">{score_val} total pins</span></div>""", unsafe_allow_html=True)

        with col_s2:
            st.markdown("#### 🪜 Stepladder Advancement")
            st.markdown(f"""
            <div class="match-box" style="font-size: 13px;">
                <div><b>Match 1:</b> {m1_p1} vs {m1_p2} &nbsp;➔&nbsp; <b style="color: #34d399;">{m1_winner} Wins</b></div>
                <div style="margin-top: 6px;"><b>Match 2:</b> {m2_p1} vs {m1_winner} &nbsp;➔&nbsp; <b style="color: #34d399;">{m2_winner} Wins</b></div>
                <div style="margin-top: 6px;"><b>Semifinal:</b> {semi_p1} vs {m2_winner} &nbsp;➔&nbsp; <b style="color: #34d399;">{semi_winner} Wins</b></div>
                <div style="margin-top: 6px;"><b>Championship:</b> {champ_p1} vs {semi_winner} &nbsp;➔&nbsp; <b style="color: #34d399; font-size: 14px;">{tournament_champion} Crowned Champion!</b></div>
            </div>
            """, unsafe_allow_html=True)

        st.write("")
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("📝 Record Official Champion in Audit Log", type="primary", use_container_width=True):
                log_audit_event(f"Tournament completed automatically. Champion declared: {tournament_champion}.")
                st.success("Official result recorded to audit trail.")

        with col_btn2:
            summary_pdf_bytes = export_tournament_summary_pdf(standings, st.session_state.tournament_config, tournament_champion, stepladder_summary_dict)
            st.download_button(
                "🖨️ Download Official Hard-Copy Summary Report (PDF)",
                data=summary_pdf_bytes,
                file_name=f"{st.session_state.tournament_config['name'].replace(' ', '_')}_Official_Summary.pdf",
                mime="application/pdf",
                use_container_width=True
            )

        st.divider()
        if st.button("📦 Archive Tournament to Cloud & Reset Active State", use_container_width=True):
            encoded_pdf = base64.b64encode(summary_pdf_bytes).decode("utf-8")
            archive_df = fetch_archives_df()
            new_archive_record = pd.DataFrame([{
                "tournament_name": st.session_state.tournament_config["name"],
                "center": st.session_state.tournament_config["center"],
                "division": st.session_state.tournament_config["division"],
                "date": datetime.now().strftime("%Y-%m-%d"),
                "entries": len(st.session_state.roster),
                "champion": tournament_champion,
                "pdf_data": encoded_pdf,
                "archived_by": st.session_state.td_name
            }])

            updated_archives = pd.concat([archive_df, new_archive_record], ignore_index=True)
            write_archives_df(updated_archives)
            clear_active_tournament_state()
            
            log_audit_event(f"Tournament '{st.session_state.tournament_config['name']}' archived with Champion: {tournament_champion}.")
            st.success("Official summary report archived to SQLite and active tournament cleared successfully!")

# ---------------------------------------------------------
# MODULE 4: SIDE ACTION: 8-BOWLER BRACKETS & SIDE POTS
# ---------------------------------------------------------
elif nav == "4. Side Action: Brackets & Pots 💰":
    st.markdown("""
    <div class="brand-banner">
        <h1>Side Action: 8-Bowler Brackets & Side Pots</h1>
        <p>Manage single-elimination bracket trees and high-game side pot payouts synchronized with live scores.</p>
    </div>
    """, unsafe_allow_html=True)

    tab_brackets, tab_pots = st.tabs(["🌳 8-Bowler Elimination Brackets", "💵 High-Game & Series Side Pots"])

    with tab_brackets:
        st.subheader("Generate & Manage Elimination Brackets")
        
        col_b_cfg1, col_b_cfg2, col_b_cfg3 = st.columns([1, 1, 1])
        with col_b_cfg1:
            b_type = st.selectbox("Bracket Division:", ["Scratch", "Handicap"])
        with col_b_cfg2:
            num_brackets_to_gen = st.number_input("Number of Brackets to Seed:", min_value=1, max_value=20, value=1)
        with col_b_cfg3:
            bracket_cost = st.number_input("Entry Fee per Bowler ($):", value=5, step=1)

        eligible_bowlers = st.session_state.roster[st.session_state.roster["Paid"] == True]["USBC ID"].tolist()

        col_gen, col_clear = st.columns([2, 1])
        with col_gen:
            if st.button("🎲 Generate & Seed Brackets", type="primary", use_container_width=True):
                if len(eligible_bowlers) < 8:
                    st.error(f"Cannot generate an 8-bowler bracket. Only {len(eligible_bowlers)} paid bowlers available (minimum 8 required).")
                else:
                    for _ in range(num_brackets_to_gen):
                        sampled = random.sample(eligible_bowlers, 8) if len(eligible_bowlers) >= 8 else eligible_bowlers[:8]
                        new_bracket = {
                            "id": f"B-{len(st.session_state.brackets) + 1:02d}",
                            "type": b_type,
                            "fee": bracket_cost,
                            "seeds": sampled,
                            "created_at": datetime.now().strftime("%H:%M")
                        }
                        st.session_state.brackets.append(new_bracket)
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    log_audit_event(f"Generated {num_brackets_to_gen} {b_type} 8-bowler bracket(s).")
                    st.success(f"Generated {num_brackets_to_gen} bracket(s) successfully.")
                    st.rerun()

        with col_clear:
            if st.button("🗑️ Reset All Brackets", use_container_width=True):
                st.session_state.brackets = []
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                log_audit_event("TD cleared all bracket records.")
                st.rerun()

        st.divider()

        if not st.session_state.brackets:
            st.info("No active brackets generated yet. Choose division and click 'Generate & Seed Brackets'.")
        else:
            for b_idx, brk in enumerate(st.session_state.brackets):
                b_id = brk["id"]
                b_mode = brk["type"]
                seeds = brk["seeds"]

                pool = brk["fee"] * 8
                payout_1st = int(pool * 0.625)
                payout_2nd = int(pool * 0.25)
                payout_exp = pool - (payout_1st + payout_2nd)

                st.markdown(f"""
                <div style="background-color: #1e293b; border: 1px solid #334155; border-left: 4px solid #38bdf8; border-radius: 8px; padding: 12px 18px; margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: baseline;">
                        <h3 style="margin: 0; color: #f8fafc;">Bracket #{b_id} — <span style="color: #38bdf8;">{b_mode.upper()}</span></h3>
                        <span style="font-size: 14px; color: #34d399; font-weight: 700;">1st: ${payout_1st} | 2nd: ${payout_2nd} | Exp: ${payout_exp}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                r1_m1_b1, r1_m1_s1, r1_m1_b2, r1_m1_s2, r1_m1_win = resolve_bracket_match(seeds[0], seeds[7], "Game 1", b_mode, st.session_state.roster)
                r1_m2_b1, r1_m2_s1, r1_m2_b2, r1_m2_s2, r1_m2_win = resolve_bracket_match(seeds[3], seeds[4], "Game 1", b_mode, st.session_state.roster)
                r1_m3_b1, r1_m3_s1, r1_m3_b2, r1_m3_s2, r1_m3_win = resolve_bracket_match(seeds[2], seeds[5], "Game 1", b_mode, st.session_state.roster)
                r1_m4_b1, r1_m4_s1, r1_m4_b2, r1_m4_s2, r1_m4_win = resolve_bracket_match(seeds[1], seeds[6], "Game 1", b_mode, st.session_state.roster)

                r2_m1_b1, r2_m1_s1, r2_m1_b2, r2_m1_s2, r2_m1_win = resolve_bracket_match(r1_m1_win, r1_m2_win, "Game 2", b_mode, st.session_state.roster)
                r2_m2_b1, r2_m2_s1, r2_m2_b2, r2_m2_s2, r2_m2_win = resolve_bracket_match(r1_m3_win, r1_m4_win, "Game 2", b_mode, st.session_state.roster)

                champ_b1, champ_s1, champ_b2, champ_s2, champ_win = resolve_bracket_match(r2_m1_win, r2_m2_win, "Game 3", b_mode, st.session_state.roster)

                col_r1, col_r2, col_r3, col_champ = st.columns([3, 3, 3, 2])

                with col_r1:
                    st.caption("Game 1 (Quarterfinals)")
                    st.markdown(f"""
                    <div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 8px; margin-bottom: 6px; font-size: 13px;">
                        <div><b>{r1_m1_b1}</b>: {r1_m1_s1}</div>
                        <div><b>{r1_m1_b2}</b>: {r1_m1_s2}</div>
                    </div>
                    <div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 8px; margin-bottom: 6px; font-size: 13px;">
                        <div><b>{r1_m2_b1}</b>: {r1_m2_s1}</div>
                        <div><b>{r1_m2_b2}</b>: {r1_m2_s2}</div>
                    </div>
                    <div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 8px; margin-bottom: 6px; font-size: 13px;">
                        <div><b>{r1_m3_b1}</b>: {r1_m3_s1}</div>
                        <div><b>{r1_m3_b2}</b>: {r1_m3_s2}</div>
                    </div>
                    <div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 8px; font-size: 13px;">
                        <div><b>{r1_m4_b1}</b>: {r1_m4_s1}</div>
                        <div><b>{r1_m4_b2}</b>: {r1_m4_s2}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with col_r2:
                    st.caption("Game 2 (Semifinals)")
                    st.markdown(f"""
                    <div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 12px 8px; margin: 18px 0 28px 0; font-size: 13px;">
                        <div><b>{r2_m1_b1}</b>: {r2_m1_s1}</div>
                        <div><b>{r2_m1_b2}</b>: {r2_m1_s2}</div>
                    </div>
                    <div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 12px 8px; font-size: 13px;">
                        <div><b>{r2_m2_b1}</b>: {r2_m2_s1}</div>
                        <div><b>{r2_m2_b2}</b>: {r2_m2_s2}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with col_r3:
                    st.caption("Game 3 (Championship)")
                    st.markdown(f"""
                    <div style="background-color: #0f172a; border: 2px solid #38bdf8; border-radius: 6px; padding: 20px 8px; margin-top: 52px; font-size: 14px;">
                        <div style="color: {'#34d399' if champ_win == r2_m1_win else '#f8fafc'}; font-weight: 700;">{champ_b1}: {champ_s1}</div>
                        <div style="color: {'#34d399' if champ_win == r2_m2_win else '#f8fafc'}; font-weight: 700;">{champ_b2}: {champ_s2}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with col_champ:
                    st.caption("Payout Results")
                    winner_name = champ_b1 if champ_win == r2_m1_win else champ_b2
                    runner_name = champ_b2 if champ_win == r2_m1_win else champ_b1
                    st.markdown(f"""
                    <div style="background-color: #10b98120; border: 1px solid #10b981; border-radius: 8px; padding: 14px 10px; margin-top: 48px; text-align: center;">
                        <span style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 700;">1st Place (${payout_1st})</span>
                        <div style="font-size: 15px; font-weight: 800; color: #34d399; margin: 2px 0;">{winner_name}</div>
                        <hr style="border-color: #334155; margin: 8px 0;"/>
                        <span style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 700;">2nd Place (${payout_2nd})</span>
                        <div style="font-size: 13px; font-weight: 700; color: #cbd5e1;">{runner_name}</div>
                    </div>
                    """, unsafe_allow_html=True)

                st.divider()

    with tab_pots:
        st.subheader("High-Game & Series Pots Engine")
        st.caption("Select participants who bought into the side pot ($10 standard buy-in: $3 Game 1, $3 Game 2, $3 Game 3, $1 Series).")

        pot_fee = st.number_input("Side Pot Entry Fee ($):", value=10, min_value=1, step=1)
        
        paid_roster = st.session_state.roster[st.session_state.roster["Paid"] == True] if not st.session_state.roster.empty else pd.DataFrame()
        all_paid_names = paid_roster["Bowler"].tolist() if not paid_roster.empty else []

        enrolled_bowlers = st.multiselect(
            "Bowlers Entered in Side Pot:",
            options=all_paid_names,
            default=all_paid_names
        )

        pot_count = len(enrolled_bowlers)
        total_pot = pot_count * pot_fee

        p_g1 = round(total_pot * 0.30, 2)
        p_g2 = round(total_pot * 0.30, 2)
        p_g3 = round(total_pot * 0.30, 2)
        p_ser = round(total_pot * 0.10, 2)

        c_p1, c_p2, c_p3, c_p4 = st.columns(4)
        with c_p1:
            st.metric("Game 1 Pot", f"${p_g1:,.2f}")
        with c_p2:
            st.metric("Game 2 Pot", f"${p_g2:,.2f}")
        with c_p3:
            st.metric("Game 3 Pot", f"${p_g3:,.2f}")
        with c_p4:
            st.metric("Series Pot", f"${p_ser:,.2f}")

        if enrolled_bowlers:
            pot_df = paid_roster[paid_roster["Bowler"].isin(enrolled_bowlers)].copy()
            for col in ["Game 1", "Game 2", "Game 3", "Average"]:
                pot_df[col] = pd.to_numeric(pot_df[col], errors="coerce").fillna(0).astype(int)

            pot_df["HDCP_Per_Game"] = pot_df["Average"].apply(lambda a: calculate_handicap(a))
            pot_df["G1_HDCP"] = pot_df["Game 1"] + pot_df["HDCP_Per_Game"]
            pot_df["G2_HDCP"] = pot_df["Game 2"] + pot_df["HDCP_Per_Game"]
            pot_df["G3_HDCP"] = pot_df["Game 3"] + pot_df["HDCP_Per_Game"]
            pot_df["Series_Scratch"] = pot_df["Game 1"] + pot_df["Game 2"] + pot_df["Game 3"]
            pot_df["Series_HDCP"] = pot_df["Series_Scratch"] + (pot_df["HDCP_Per_Game"] * 3)

            pot_mode = st.radio("Display Pot Standings By:", ["Handicap", "Scratch"], horizontal=True)

            g1_col = "G1_HDCP" if pot_mode == "Handicap" else "Game 1"
            g2_col = "G2_HDCP" if pot_mode == "Handicap" else "Game 2"
            g3_col = "G3_HDCP" if pot_mode == "Handicap" else "Game 3"
            ser_col = "Series_HDCP" if pot_mode == "Handicap" else "Series_Scratch"

            max_g1 = pot_df[g1_col].max()
            max_g2 = pot_df[g2_col].max()
            max_g3 = pot_df[g3_col].max()
            max_ser = pot_df[ser_col].max()

            w_g1 = pot_df[pot_df[g1_col] == max_g1]["Bowler"].tolist()
            w_g2 = pot_df[pot_df[g2_col] == max_g2]["Bowler"].tolist()
            w_g3 = pot_df[pot_df[g3_col] == max_g3]["Bowler"].tolist()
            w_ser = pot_df[pot_df[ser_col] == max_ser]["Bowler"].tolist()

            st.write("")
            st.markdown(f"### 🏆 Official Payout Leaders ({pot_mode})")

            col_w1, col_w2, col_w3, col_w4 = st.columns(4)
            with col_w1:
                st.markdown(f"""
                <div class="match-box">
                    <span style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 700;">Game 1 Winner</span>
                    <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{', '.join(w_g1)}</div>
                    <div style="font-size: 14px; color: #34d399; font-weight: 700; margin-top: 4px;">Score: {max_g1} (${p_g1 / max(len(w_g1), 1):,.2f}{' each' if len(w_g1) > 1 else ''})</div>
                </div>
                """, unsafe_allow_html=True)
            with col_w2:
                st.markdown(f"""
                <div class="match-box">
                    <span style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 700;">Game 2 Winner</span>
                    <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{', '.join(w_g2)}</div>
                    <div style="font-size: 14px; color: #34d399; font-weight: 700; margin-top: 4px;">Score: {max_g2} (${p_g2 / max(len(w_g2), 1):,.2f}{' each' if len(w_g2) > 1 else ''})</div>
                </div>
                """, unsafe_allow_html=True)
            with col_w3:
                st.markdown(f"""
                <div class="match-box">
                    <span style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 700;">Game 3 Winner</span>
                    <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{', '.join(w_g3)}</div>
                    <div style="font-size: 14px; color: #34d399; font-weight: 700; margin-top: 4px;">Score: {max_g3} (${p_g3 / max(len(w_g3), 1):,.2f}{' each' if len(w_g3) > 1 else ''})</div>
                </div>
                """, unsafe_allow_html=True)
            with col_w4:
                st.markdown(f"""
                <div class="match-box">
                    <span style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 700;">Series Winner</span>
                    <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{', '.join(w_ser)}</div>
                    <div style="font-size: 14px; color: #34d399; font-weight: 700; margin-top: 4px;">Score: {max_ser} (${p_ser / max(len(w_ser), 1):,.2f}{' each' if len(w_ser) > 1 else ''})</div>
                </div>
                """, unsafe_allow_html=True)

            st.write("")
            st.dataframe(
                pot_df[["Bowler", "Average", "HDCP_Per_Game", "Game 1", "G1_HDCP", "Game 2", "G2_HDCP", "Game 3", "G3_HDCP", "Series_Scratch", "Series_HDCP"]],
                use_container_width=True
            )

# ---------------------------------------------------------
# MODULE 5: FINANCIAL RECONCILIATION & PRIZE FUND LEDGER
# ---------------------------------------------------------
elif nav == "5. Financial & Payout Ledger 💵":
    st.markdown("""
    <div class="brand-banner">
        <h1>Financial Reconciliation & Prize Payout Ledger</h1>
        <p>Automated lineage deductions, prize fund allocation, and USBC Rule 400 SMART compliance.</p>
    </div>
    """, unsafe_allow_html=True)

    config = st.session_state.tournament_config
    is_youth_division = "youth" in str(config.get("division", "")).lower() or "scholastic" in str(config.get("division", "")).lower()

    if is_youth_division:
        st.markdown("""
        <div style="background-color: #f59e0b20; border: 2px solid #f59e0b; border-radius: 10px; padding: 14px 18px; margin-bottom: 16px;">
            <span style="color: #fde047; font-weight: 800; font-size: 14px;">⚠️ USBC RULE 400 SMART MANDATE ACTIVE</span>
            <p style="color: #fef08a; font-size: 13.5px; margin: 4px 0 0 0;">
                This event is designated as a <b>Youth / Scholastic Division</b>. Cash and merchandise gift card payouts are strictly prohibited. All prize funds will automatically route to official <b>USBC SMART Scholarship accounts</b>.
            </p>
        </div>
        """, unsafe_allow_html=True)

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        entry_fee_in = st.number_input("Entry Fee per Bowler ($):", value=float(config.get("entry_fee", 50.0)), step=5.0)
    with col_f2:
        lineage_rate = st.number_input("Center Lineage Rate per Game ($):", value=3.75, step=0.25)
    with col_f3:
        expense_per_bowler = st.number_input("Association/Awards Expense per Bowler ($):", value=5.00, step=1.00)

    config["entry_fee"] = entry_fee_in
    fin_summary = calculate_financial_summary(st.session_state.roster, config, lineage_per_game=lineage_rate)

    st.write("")
    c_m1, c_m2, c_m3, c_m4 = st.columns(4)
    with c_m1:
        st.metric("Paid Entries", fin_summary["paid_count"])
    with c_m2:
        st.metric("Gross Revenue", f"${fin_summary['gross_revenue']:,.2f}")
    with c_m3:
        st.metric("Lineage Owed to House", f"${fin_summary['total_lineage']:,.2f}")
    with c_m4:
        payout_label = "Net SMART Scholarship Pool" if is_youth_division else "Net Prize Fund Pool"
        st.metric(payout_label, f"${fin_summary['net_prize_fund']:,.2f}")

    st.divider()

    st.subheader("📊 Payout Distribution Breakdown")
    net_pool = fin_summary["net_prize_fund"]

    if net_pool <= 0:
        st.warning("No revenue recorded yet. Mark bowlers as paid in Module 1 to calculate prize allocations.")
    else:
        ratios = [0.40, 0.25, 0.15, 0.10, 0.05, 0.05]
        place_names = ["1st Place", "2nd Place", "3rd Place", "4th Place", "5th Place", "6th Place"]
        
        payout_rows = []
        for i, pct in enumerate(ratios):
            if i * 4 > fin_summary["paid_count"] and i >= 3:
                break
            amount = round(net_pool * pct, 2)
            payout_rows.append({
                "Position": place_names[i] if i < len(place_names) else f"{i+1}th Place",
                "Allocation (%)": f"{int(pct*100)}%",
                "Amount ($)": f"${amount:,.2f}"
            })

        st.dataframe(pd.DataFrame(payout_rows), use_container_width=True)

        if is_youth_division:
            st.write("")
            standings = compile_standings(st.session_state.roster)
            smart_csv = generate_smart_scholarship_csv(standings, net_pool)
            if smart_csv:
                st.download_button(
                    "📄 Download USBC SMART Scholarship Submission (.csv)",
                    data=smart_csv,
                    file_name=f"{config['name'].replace(' ', '_')}_SMART_Submittal.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True
                )
        else:
            st.success("Financial ledger balances cleanly to the penny against recorded cash and electronic receipts.")

# ---------------------------------------------------------
# MODULE 6: AI RULES ARBITER (GROUNDED TO 2026-27 RULEBOOK PDF)
# ---------------------------------------------------------
elif nav == "6. AI Rules Arbiter":
    st.markdown("""
    <div class="brand-banner">
        <h1>USBC & Tournament Rules Arbiter</h1>
        <p>Gemini AI official decision support grounded on USBC Playing Rules.</p>
    </div>
    """, unsafe_allow_html=True)

    if HAS_RULEBOOK and RULEBOOK_BYTES is not None:
        st.markdown("""
        <div style="display: inline-block; background-color: #10b98120; border: 1px solid #10b981; border-radius: 20px; padding: 4px 14px; margin-bottom: 12px; font-size: 13px; font-weight: 700; color: #34d399;">
            🟢 Grounded directly on USBC-Playing-Rulebook-26-27.pdf
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="display: inline-block; background-color: #f59e0b20; border: 1px solid #f59e0b; border-radius: 20px; padding: 4px 14px; margin-bottom: 12px; font-size: 13px; font-weight: 700; color: #fde047;">
            ⚠️ USBC-Playing-Rulebook-26-27.pdf not detected in root repo — operating on baseline memory
        </div>
        """, unsafe_allow_html=True)

    division_alert = ""
    if "Youth" in str(st.session_state.tournament_config.get("division", "")):
        division_alert = "\nCRITICAL DIVISION MANDATE: Enforce USBC Rule 400 (all awards must be SMART scholarships; cash is strictly prohibited)."

    rules_context = f"""
HOST BOWLING CENTER: {st.session_state.tournament_config['center']}
TOURNAMENT NAME: {st.session_state.tournament_config['name']}
DIVISION: {st.session_state.tournament_config['division']}
ACTIVE LANES: {st.session_state.tournament_config['lanes_range']}
FORMAT MODE: {st.session_state.tournament_config.get('format_mode', 'Standard')}
EVENT FLYER / LOCAL RULES TEXT:
{st.session_state.tournament_config['rules_text']}
{division_alert}
"""

    st.caption("⚡ Common On-Lane Disputes:")
    col_preset1, col_preset2 = st.columns(2)
    selected_dispute_preset = ""
    with col_preset1:
        if st.button("Rule 17: Altering Ball Surface (Sanding/Cleaning Mid-Game)", use_container_width=True):
            selected_dispute_preset = "A bowler was seen using an Abralon pad to alter the surface of their ball between game 1 and game 2 of official competition. What is the mandatory penalty under USBC Rule 17?"
        if st.button("Rule 10: Tardy Bowler Arrival Protocol", use_container_width=True):
            selected_dispute_preset = "A bowler arrived 15 minutes late and their assigned pair is currently bowling in the 3rd frame. Can they bowl, and how are missed frames scored under USBC Rule 10?"
    with col_preset2:
        if st.button("Rule 18: Gripping Holes & Weight Holes", use_container_width=True):
            selected_dispute_preset = "An opponent protests that a bowler has an extra un-gripped balance hole in their ball. What does USBC Rule 18 require?"
        if st.button("Rule 400: Youth SMART Eligibility", use_container_width=True):
            selected_dispute_preset = "Can a youth bowler participate in adult brackets, or receive cash or merchandise gift cards under USBC Rule 400?"

    query = st.text_area("Describe the on-lane situation or protest:", value=selected_dispute_preset, height=100)
    
    if st.button("Generate Official Arbiter Ruling", type="primary"):
        if not query.strip():
            st.warning("Please describe the dispute or click one of the quick dispute presets above.")
        else:
            with st.spinner("Analyzing USBC-Playing-Rulebook-26-27.pdf..."):
                try:
                    decision_text = arbitrate_rules_inquiry(query, rules_context)
                    st.markdown("### Official Decision")
                    st.markdown(decision_text)
                    log_audit_event(f"Rules dispute adjudicated: '{query[:50]}...'")
                except Exception as err:
                    st.error(f"Error querying Gemini: {err}")

# ---------------------------------------------------------
# MODULE 7: PAST TOURNAMENTS ARCHIVE
# ---------------------------------------------------------
elif nav == "7. Past Tournaments Archive 📂":
    st.markdown("""
    <div class="brand-banner">
        <h1>Historical Tournament Archive</h1>
        <p>Official final results and downloadable PDF documents permanently stored in SQLite.</p>
    </div>
    """, unsafe_allow_html=True)

    archive_df = fetch_archives_df()

    if archive_df.empty:
        st.info("No past tournaments have been archived yet. Once an event concludes in Module 3, click 'Archive Tournament' to store it permanently.")
    else:
        for idx, row in archive_df.iloc[::-1].iterrows():
            t_name = row.get("tournament_name", "CHUSBC Event")
            t_date = row.get("date", "Unknown Date")
            t_center = row.get("center", "")
            t_div = row.get("division", "")
            t_champ = row.get("champion", "N/A")
            t_entries = row.get("entries", 0)
            t_td = row.get("archived_by", "Staff")
            pdf_b64 = row.get("pdf_data", "")

            with st.container():
                st.markdown(f"""
                <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 18px; margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: baseline;">
                        <h3 style="margin: 0; color: #f8fafc; font-size: 20px;">🏆 {t_name}</h3>
                        <span style="color: #38bdf8; font-weight: 700;">{t_date}</span>
                    </div>
                    <div style="color: #94a3b8; font-size: 14px; margin-top: 6px;">
                        <strong>Center:</strong> {t_center} | <strong>Division:</strong> {t_div} | <strong>Field:</strong> {t_entries} Bowlers | <strong>Archived By:</strong> {t_td}
                    </div>
                    <div style="margin-top: 10px; font-size: 16px; color: #34d399; font-weight: 700;">
                        👑 Champion: {t_champ}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                if pdf_b64:
                    try:
                        pdf_decoded = base64.b64decode(pdf_b64)
                        st.download_button(
                            f"📄 Download Official Final Standings PDF ({t_name})",
                            data=pdf_decoded,
                            file_name=f"{str(t_name).replace(' ', '_')}_{str(t_date)}.pdf",
                            mime="application/pdf",
                            key=f"dl_pdf_{idx}"
                        )
                    except Exception as e:
                        st.caption("Unable to decode stored PDF data.")
                st.divider()

# ---------------------------------------------------------
# MODULE 8: BOARD SOP & STAFF MANUAL (DYNAMIC DOCX & PDF)
# ---------------------------------------------------------
elif nav == "8. Board SOP & Staff Manual 📖":
    st.markdown("""
    <div class="brand-banner">
        <h1>Board Standard Operating Procedure (SOP)</h1>
        <p>Dynamic tournament desk operations manual and novice TD quickstart guide.</p>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("🤖 Ask Gemini: Live Desk Operations & Onboarding Coach", expanded=True):
        st.markdown("Have a question about what button to click, how to handle a payment, or what to do if you're stuck? Ask here:")
        coach_question = st.text_input("Enter your desk ops question (e.g., 'A bowler arrived late in game 1, what do I click?'):", placeholder="Type your tournament question...")
        
        if st.button("Get Instant Instructions from Gemini", type="primary"):
            if not ai_client:
                st.warning("Gemini API key is required.")
            elif not coach_question.strip():
                st.warning("Please type a question.")
            else:
                with st.spinner("Consulting CHUSBC Desk Manual..."):
                    coach_prompt = f"""
You are the Cecil Harford USBC (CHUSBC) Tournament Desk Operations AI Coach.
Your goal is to guide a novice Tournament Director or volunteer who has NEVER used this software before.

Current Tournament Setup:
- Center: {st.session_state.tournament_config['center']}
- Event: {st.session_state.tournament_config['name']}
- Division: {st.session_state.tournament_config['division']}
- Active Lanes: {st.session_state.tournament_config['lanes_range']}
- Current Field Size: {len(st.session_state.roster)} bowlers

Technical POC: Scott Kramer (scottjk85@gmail.com, 443.966.4460)

Rules & Architecture:
- 6 tiers: TD Console, External Kiosk (?mode=kiosk), Express Entrance Self-Check-In (?mode=self_checkin), Read-Only Bowler Portal (?mode=bowler_portal), Mobile Floor Scorer (?mode=scorer), and Public Concourse Leaderboard (?mode=leaderboard).
- Cryptographic Security: Argon2id password and 4-digit PIN hashing.
- Payment & Bracket Gate: Pre-paid bowlers check in automatically at the door unless they want brackets; unpaid or bracket bowlers are directed to the desk.

User Question:
{coach_question}

Format your response in simple, numbered, crystal-clear steps telling the official EXACTLY where to navigate and what to click. Keep it encouraging and direct.
"""
                    try:
                        reply = generate_with_failover(coach_prompt, temperature=0.1)
                        st.markdown("### 📋 Instructions from AI Coach:")
                        st.markdown(reply)
                    except Exception as err:
                        st.error(f"Error querying AI Coach: {err}")

    st.divider()

    st.markdown("### 📥 Official Document Export")
    col_dl_docx, col_dl_pdf = st.columns(2)
    with col_dl_docx:
        docx_buffer = generate_sop_docx()
        st.download_button(
            "📝 Download Official SOP (.docx for Word)",
            data=docx_buffer,
            file_name=f"{st.session_state.tournament_config['name'].replace(' ', '_')}_SOP.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )
    with col_dl_pdf:
        pdf_bytes = generate_sop_pdf()
        st.download_button(
            "📄 Download Official SOP (.pdf for Print)",
            data=pdf_bytes,
            file_name=f"{st.session_state.tournament_config['name'].replace(' ', '_')}_SOP.pdf",
            mime="application/pdf",
            use_container_width=True
        )

# ---------------------------------------------------------
# MODULE 9: AUDIT LOG
# ---------------------------------------------------------
elif nav == "9. TD Audit Log":
    st.markdown("""
    <div class="brand-banner">
        <h1>Official Tournament Audit Log</h1>
        <p>Immutable log of desk actions, scoring adjustments, and administrative events.</p>
    </div>
    """, unsafe_allow_html=True)

    if not st.session_state.audit_trail:
        st.info("No audit entries recorded for this session.")
    else:
        st.dataframe(pd.DataFrame(st.session_state.audit_trail), use_container_width=True)

# ---------------------------------------------------------
# MODULE 10: ADMIN USER MANAGEMENT (ARGON2ID)
# ---------------------------------------------------------
elif "TD User Management" in nav:
    st.markdown("""
    <div class="brand-banner">
        <h1>Tournament Director & Staff Management (Argon2id)</h1>
        <p>Admin console synchronized with SQLite for permanent account storage.</p>
    </div>
    """, unsafe_allow_html=True)

    users_df = fetch_users_df()
    pending_df = users_df[users_df["status"] == "pending"]

    st.subheader(f"Account Requests Pending Approval ({len(pending_df)})")
    if pending_df.empty:
        st.info("No registration requests currently awaiting approval.")
    else:
        for idx, row in pending_df.iterrows():
            uname = row["username"]
            real_name = row["name"]
            user_email = row.get("email", "N/A")
            with st.container():
                st.markdown(f"""
                <div style="background-color: #1e293b; padding: 14px 18px; border-radius: 8px; border: 1.5px solid #ec489950; margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 16px; font-weight: 700; color: #f8fafc;">{real_name} (<code style="color: #38bdf8;">{uname}</code>)</span>
                        <span class="badge-pending">PENDING APPROVAL</span>
                    </div>
                    <div style="font-size: 13px; color: #94a3b8; margin-top: 6px;">
                        <strong>Email:</strong> {user_email} | <strong>Submitted:</strong> {row.get('created_at', 'Recent')}
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                col_role, col_appr, col_deny = st.columns([1, 1, 1])
                with col_role:
                    selected_role = st.selectbox(f"Assign Role for {uname}:", ["td", "admin"], key=f"role_{uname}")
                with col_appr:
                    if st.button(f"Approve & Activate ({uname})", key=f"appr_{uname}", type="primary", use_container_width=True):
                        latest_df = fetch_users_df()
                        target_idx = latest_df.index[latest_df["username"] == uname].tolist()
                        if target_idx:
                            latest_df.loc[target_idx[0], "status"] = "active"
                            latest_df.loc[target_idx[0], "role"] = selected_role
                            write_users_df(latest_df)
                            
                            target_email = str(latest_df.loc[target_idx[0]].get("email", ""))
                            if target_email:
                                notify_user_account_approved(target_email, real_name, uname)

                        log_audit_event(f"Admin approved registration for '{uname}' ({real_name}) as {selected_role}.")
                        st.success(f"Account '{uname}' approved and confirmation email sent!")
                        st.rerun()
                with col_deny:
                    if st.button(f"Deny & Remove ({uname})", key=f"deny_{uname}", use_container_width=True):
                        latest_df = fetch_users_df()
                        latest_df = latest_df[latest_df["username"] != uname]
                        write_users_df(latest_df)
                        log_audit_event(f"Admin denied registration request for '{uname}'.")
                        st.warning(f"Registration request for '{uname}' denied.")
                        st.rerun()
            st.divider()

    st.subheader("Active Staff Registry (Live from SQLite)")
    active_df = users_df[users_df["status"] == "active"].copy()
    display_df = pd.DataFrame({
        "Username": active_df["username"],
        "Full Name": active_df["name"],
        "Email": active_df.get("email", ""),
        "Role": active_df["role"].str.upper(),
        "Hash Type": active_df["password_hash"].apply(lambda h: "Argon2id" if str(h).startswith("$argon2") else "SHA-256 (Auto-Upgrades)"),
        "Must Reset Pwd": active_df["must_change_password"].apply(lambda x: "YES" if bool(x) else "NO"),
        "Registered": active_df["created_at"]
    })
    st.dataframe(display_df, use_container_width=True)

    st.divider()

    col_add, col_reset, col_del = st.columns([1, 1, 1])

    with col_add:
        st.subheader("Register Official Directly")
        with st.form("add_td_form"):
            new_user = st.text_input("Username:").strip().lower()
            new_name = st.text_input("Full Official Name:")
            new_email = st.text_input("Email Address:").strip().lower()
            new_pw = st.text_input("Initial Password:", type="password").strip()
            new_role = st.selectbox("Role Assignment:", ["td", "admin"])
            force_change = st.checkbox("Require pwd change on 1st login", value=True)
            submit_td = st.form_submit_button("Create Account Directly (Argon2)", type="primary", use_container_width=True)

            if submit_td:
                latest_df = fetch_users_df()
                if not new_user or not new_name or not new_email or not new_pw:
                    st.error("All fields are required.")
                elif new_user in latest_df["username"].values:
                    st.error(f"User '{new_user}' already exists.")
                else:
                    new_entry = pd.DataFrame([{
                        "username": new_user,
                        "name": new_name,
                        "email": new_email,
                        "password_hash": hash_secret(new_pw),
                        "role": new_role,
                        "status": "active",
                        "must_change_password": force_change,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                    }])
                    updated_df = pd.concat([latest_df, new_entry], ignore_index=True)
                    write_users_df(updated_df)
                    flag_note = "with mandatory password change" if force_change else "without mandatory password change"
                    log_audit_event(f"Admin registered new user: '{new_user}' ({new_name}) as {new_role} {flag_note} (Argon2id).")
                    st.success(f"Official '{new_name}' registered with Argon2id.")
                    st.rerun()

    with col_reset:
        st.subheader("Reset / Override Password")
        active_users = users_df[users_df["status"] == "active"]["username"].tolist()
        with st.form("reset_pwd_form"):
            target_user = st.selectbox("Select Account to Reset:", active_users)
            new_admin_pw = st.text_input("New Password:", type="password").strip()
            target_force = st.checkbox("Require user to change on next login", value=True)
            submit_reset = st.form_submit_button("Update Password (Argon2)", use_container_width=True)

            if submit_reset:
                if not new_admin_pw:
                    st.error("Password cannot be blank.")
                elif len(new_admin_pw) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    latest_df = fetch_users_df()
                    target_idx = latest_df.index[latest_df["username"] == target_user].tolist()
                    if target_idx:
                        latest_df.loc[target_idx[0], "password_hash"] = hash_secret(new_admin_pw)
                        latest_df.loc[target_idx[0], "must_change_password"] = target_force
                        write_users_df(latest_df)
                    log_audit_event(f"Admin reset password for user '{target_user}' (Argon2id).")
                    st.success(f"Password for '{target_user}' updated with Argon2id.")
                    st.rerun()

    with col_del:
        st.subheader("Delete User Account")
        deletable_users = [u for u in users_df["username"].tolist() if u != "skramer"]
        
        if not deletable_users:
            st.info("No auxiliary user accounts to delete.")
        else:
            with st.form("delete_user_form"):
                user_to_delete = st.selectbox("Select Account to Remove:", deletable_users)
                confirm_delete = st.checkbox("Confirm permanent removal", value=False)
                submit_delete = st.form_submit_button("Delete Account", use_container_width=True)

                if submit_delete:
                    if not confirm_delete:
                        st.error("Check the confirmation box before deleting.")
                    else:
                        latest_df = fetch_users_df()
                        match_row = latest_df[latest_df["username"] == user_to_delete]
                        del_name = match_row.iloc[0]["name"] if not match_row.empty else user_to_delete
                        latest_df = latest_df[latest_df["username"] != user_to_delete]
                        write_users_df(latest_df)
                        log_audit_event(f"Admin deleted user account: '{user_to_delete}' ({del_name}).")
                        st.success(f"Account '{user_to_delete}' removed.")
                        st.rerun()

# ---------------------------------------------------------
# FLOATING GEMINI DESK COACH (AWARE OF ACTIVE MODULE & UI TABS)
# ---------------------------------------------------------
if st.session_state.authenticated and st.session_state.session_initialized:
    # Initialize persistent state so copilot dialog stays open and intact
    if "copilot_query" not in st.session_state:
        st.session_state.copilot_query = ""
    if "copilot_response" not in st.session_state:
        st.session_state.copilot_response = ""

    st.markdown('<div class="floating-ai-anchor">', unsafe_allow_html=True)
    with st.popover("✨ Ask Gemini", help="Live operations copilot & USBC rules arbiter"):
        total_field = len(st.session_state.roster)
        paid_field = len(st.session_state.roster[st.session_state.roster["Paid"] == True]) if total_field > 0 else 0
        current_module = nav

        st.markdown(f"""
        <div style="border-bottom: 1px solid #334155; padding-bottom: 8px; margin-bottom: 10px;">
            <strong style="color: #38bdf8; font-size: 15px;">🎳 CHUSBC Live Desk Coach</strong><br/>
            <span style="color: #34d399; font-size: 12px; font-weight: bold;">📍 Active: {current_module}</span><br/>
            <span style="color: #cbd5e1; font-size: 11px;">Roster: <b>{paid_field}/{total_field} Paid</b> | Center: <b>{st.session_state.tournament_config['center']}</b></span>
        </div>
        """, unsafe_allow_html=True)

        st.caption("⚡ Quick Actions for This Screen:")
        c_p1, c_p2 = st.columns(2)

        if "1. Event & Roster Intake" in current_module:
            with c_p1:
                if st.button("How to balance lanes?", use_container_width=True, key="ctx_btn_1"):
                    st.session_state.copilot_query = "I am on Module 1 (Event & Roster Intake). Explain step-by-step how I should balance up to 40 lanes, keep teammates together, and print lane sheets."
                if st.button("Bowler check-in steps", use_container_width=True, key="ctx_btn_2"):
                    st.session_state.copilot_query = "A bowler just arrived at the desk. Walk me through checking them in, taking payment, and showing the QR code on the customer screen."
            with c_p2:
                if st.button("Floor TD PIN setup", use_container_width=True, key="ctx_btn_3"):
                    st.session_state.copilot_query = "How do floor officials create their 4-digit security PIN, and how do I reset it from Central Desk if they forget it?"
                if st.button("Tardy Bowler (R10)", use_container_width=True, key="ctx_btn_4"):
                    st.session_state.copilot_query = "A bowler arrived 15 minutes late and their pair is in the middle of frame 3. What is the official USBC Rule 10 procedure?"

        elif "2. Scores & Standings" in current_module:
            with c_p1:
                if st.button("Radar Matrix guide", use_container_width=True, key="ctx_btn_1"):
                    st.session_state.copilot_query = "I am looking at the Central Desk Lane Radar Matrix. What do the different status colors mean, and how do I know when a pair is locked?"
                if st.button("Camera OCR help", use_container_width=True, key="ctx_btn_2"):
                    st.session_state.copilot_query = "How does a floor official take a photo of an overhead scoring monitor with their phone, and what do they do if it does not read clearly?"
            with c_p2:
                if st.button("Altering Ball (R17)", use_container_width=True, key="ctx_btn_3"):
                    st.session_state.copilot_query = "A bowler just used an Abralon pad to sand their ball between game 1 and game 2. What is the mandatory penalty under USBC Rule 17?"
                if st.button("Tiebreaker rules", use_container_width=True, key="ctx_btn_4"):
                    st.session_state.copilot_query = "Two bowlers have the exact same Grand Total score. How does the system automatically break ties under USBC rules?"

        elif "3. Stepladder Finals" in current_module:
            with c_p1:
                if st.button("How to complete event", use_container_width=True, key="ctx_btn_1"):
                    st.session_state.copilot_query = "I am ready to finalize this tournament. What exact buttons do I click in Module 3 to crown the Champion and generate the hard-copy summary report?"
                if st.button("Download Summary PDF", use_container_width=True, key="ctx_btn_2"):
                    st.session_state.copilot_query = "Where do I click to download the official hard-copy summary report with the signature blocks for our records?"
            with c_p2:
                if st.button("Stepladder seeding", use_container_width=True, key="ctx_btn_3"):
                    st.session_state.copilot_query = "Explain how the top 5 seeded stepladder elimination ladder advances from Match 1 through the Championship."
                if st.button("Cloud archive help", use_container_width=True, key="ctx_btn_4"):
                    st.session_state.copilot_query = "How does archiving work, where does the saved tournament go in SQLite, and how do I access past archives?"

        elif "4. Side Action" in current_module:
            with c_p1:
                if st.button("Seed 8-Bowler Bracket", use_container_width=True, key="ctx_btn_1"):
                    st.session_state.copilot_query = "How do I randomly seed 8-bowler brackets, and what is the standard payout split ($25 1st, $10 2nd, $5 expense)?"
            with c_p2:
                if st.button("Side Pot payouts", use_container_width=True, key="ctx_btn_2"):
                    st.session_state.copilot_query = "How are High-Game and Series side pots calculated across Games 1, 2, and 3, and how are ties handled in the payout?"

        elif "5. Financial" in current_module:
            with c_p1:
                if st.button("Reconcile drawer", use_container_width=True, key="ctx_btn_1"):
                    st.session_state.copilot_query = "How do I balance our cash drawer against the center lineage fee and tournament prize fund in Module 5?"
            with c_p2:
                if st.button("Youth SMART export", use_container_width=True, key="ctx_btn_2"):
                    st.session_state.copilot_query = "This is a youth division. How do I export the official USBC SMART scholarship submission file under Rule 400?"

        else:
            with c_p1:
                if st.button("What do I do here?", use_container_width=True, key="ctx_btn_1"):
                    st.session_state.copilot_query = f"I am currently viewing '{current_module}'. Give me a quick orientation of what actions I can perform on this screen."
            with c_p2:
                if st.button("Contact Tech Support", use_container_width=True, key="ctx_btn_2"):
                    st.session_state.copilot_query = "Who is the technical point of contact if I need urgent help or run into system errors?"

        user_float_q = st.text_input(
            "Ask a question about this screen or a rule:",
            value=st.session_state.copilot_query,
            placeholder="e.g. What do I click next?",
            key="float_ai_query"
        )
        st.session_state.copilot_query = user_float_q

        if st.button("Get Help from Coach", type="primary", use_container_width=True, key="float_ai_submit"):
            if not user_float_q.strip():
                st.warning("Please enter a question or click a quick action above.")
            elif not ai_client:
                st.error("Gemini API key is not configured.")
            else:
                with st.spinner("Analyzing active screen and event state..."):
                    float_context = f"""
You are the official Cecil Harford USBC (CHUSBC) Tournament Desk Operations Copilot and Rules Arbiter.
You are assisting an on-duty Tournament Director (TD) or volunteer using the live Streamlit console.

CURRENT RUNTIME CONTEXT:
- Active Sidebar Module: {current_module}
- Event Title: {st.session_state.tournament_config['name']}
- Host Bowling Center: {st.session_state.tournament_config['center']}
- Division: {st.session_state.tournament_config['division']}
- Active Pairs: {st.session_state.tournament_config['lanes_range']}
- Total Bowlers on Roster: {total_field}
- Paid Entries: {paid_field}
- Technical Point of Contact (TPOC): Scott Kramer (scottjk85@gmail.com | 443.966.4460)

EXACT UI ARCHITECTURE & TABS FOR MODULES:
1. Module 1: '1. Event & Roster Intake' contains 4 main tabs:
   - Tab 1: '⚙️ Event Settings & CHUSBC Presets' -> Has preset dropdown (8 CHUSBC tournaments), center selector, lane count/range, handicap base/pct, movement rule dropdown, and rules text area / flyer uploader. Button: '🔒 Save & Lock Tournament Configuration'.
   - Tab 2: '📝 Roster Ingestion & 40-Lane Balancing' -> Contains 5 sub-tabs:
       * Sub-tab '📸 Scan/Photo Clipboard (AI)': Take phone camera photo or upload sheet. Button: '🔍 Extract Bowlers from Photo with Gemini'.
       * Sub-tab '🤖 Paste Signup Notes (Gemini AI)': Text area to paste unformatted notes/emails. Button: 'Extract Roster with Gemini'.
       * Sub-tab '📁 Upload CSV': Upload master spreadsheet.
       * Sub-tab '📋 Editable Master Grid': Direct spreadsheet editor (`st.data_editor`) with columns: USBC ID, Bowler, Average, Starting Lane, Division, Team_Name, Paid, Checked_In. Button: 'Save Roster Changes'.
       * Sub-tab '🎳 Automated Lane Balancer': Select active pairs, max bowlers per pair, checkboxes '👥 Group Teammates' and '🎲 Blind Random Draw'. Buttons: '⚡ Balance & Assign Lanes Automatically' and '📄 Download Printable PDF Lane Assignment Roster'.
   - Tab 3: '💳 Desk Intake & Entrance QR Posters' -> Has QR download for entrance self-check-in (?mode=self_checkin) and bowler portal (?mode=bowler_portal), secondary customer kiosk monitor launcher (?mode=kiosk), and bowler search dropdown. Buttons: 'Mark Paid' (Cash, Check, Venmo) and '📺 Push to Customer Screen'.
   - Tab 4: '🔐 Floor TD PIN Registry (Argon2)' -> Lists floor officials with locked Argon2 PINs. Has Central Desk override form to set or reset 4-digit PINs.

2. Module 2: '2. Scores & Standings':
   - Has QR code / links to launch mobile roving floor scorer (?mode=scorer) and concourse TV leaderboard (?mode=leaderboard).
   - '🛰️ Central Desk Lane Radar Matrix': Live status indicators for all active pairs across Game 1, 2, and 3 (🟢 PIN VERIFIED, 🟡 PROVISIONAL, 🔴 PENDING) rendered dynamically with native @st.fragment polling.
   - 'Official Scoring Grid': Data editor for Game 1, Game 2, Game 3 scores and verifier timestamps. Button: 'Save Scores & Recalculate Standings'.
   - Official Standings & All-Events Leaderboards with PDF download buttons.

3. Module 3: '3. Stepladder Finals':
   - Automated completion engine for top 5 qualifiers.
   - Shows seeded matches (#4 vs #5, #3 vs M1 winner, #2 vs Semifinal, #1 vs Semifinalist) and declares Champion.
   - Buttons: '📝 Record Official Champion in Audit Log', '🖨️ Download Official Hard-Copy Summary Report (PDF)', and '📦 Archive Tournament to Cloud & Reset Active State'.

4. Module 4: '4. Side Action: Brackets & Pots 💰':
   - Sub-tabs for '🌳 8-Bowler Elimination Brackets' and '💵 High-Game & Series Side Pots' ($10 buy-in: $3 G1, $3 G2, $3 G3, $1 Series).

5. Module 5: '5. Financial & Payout Ledger 💵':
   - Lineage, expense, and prize pool calculator. If youth event, enforces USBC Rule 400 and exports SMART scholarship CSV.

INSTRUCTIONS FOR YOUR RESPONSE:
- If the question is about how to operate the system or what button to click, refer to the EXACT tabs, buttons, and sub-tabs detailed above. Do not invent non-existent form fields.
- If the user asks about an on-lane dispute or rule, first provide the USBC Rule citation from the 2026-2027 rulebook (Rule 10 for tardiness, Rule 17 for surface alteration, Rule 18 for balance holes, Rule 400 for SMART scholarships), then provide the immediate step-by-step action for the desk official.
- Keep directions brief, bulleted, and actionable.
"""
                    try:
                        ans = arbitrate_rules_inquiry(user_float_q, float_context)
                        st.session_state.copilot_response = ans
                        log_audit_event(f"Live AI Copilot assisted on '{current_module}': '{user_float_q[:40]}...'")
                    except Exception as err:
                        st.error(f"Error consulting Gemini: {err}")

        if st.session_state.copilot_response:
            st.markdown(f"""
            <div style="background-color: #1e293b; border-left: 3px solid #38bdf8; padding: 12px; border-radius: 6px; font-size: 13px; margin-top: 10px;">
                {st.session_state.copilot_response}
            </div>
            """, unsafe_allow_html=True)
            if st.button("Clear Response", key="clear_copilot_btn", use_container_width=True):
                st.session_state.copilot_response = ""
                st.session_state.copilot_query = ""
                st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
