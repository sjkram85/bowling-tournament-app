import os
import io
import time
import math
import json
import base64
import random
import hashlib
from datetime import datetime
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection
from pypdf import PdfReader
import qrcode
from PIL import Image

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. PAGE SETUP & GLOBAL CUSTOM THEME
# ---------------------------------------------------------
st.set_page_config(
    page_title="CHUSBC Tournament Desk Ops",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded"
)

LOGO_PATH = "CHUSBC.jpg"
HAS_LOGO = os.path.exists(LOGO_PATH)

PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.5-flash"]

# Disk-backed Cross-Screen IPC Bridge (Guaranteed multi-tab sync)
KIOSK_FILE_PATH = os.path.join("/tmp", "chusbc_kiosk_state.json")

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

st.markdown("""
<style>
    .stApp {
        background-color: #0b1120;
    }
    .brand-banner {
        background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
        border: 1px solid #1e40af;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 24px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .brand-banner h1 {
        color: #f8fafc;
        margin: 0;
        font-size: 26px;
        font-weight: 800;
        letter-spacing: -0.5px;
    }
    .brand-banner p {
        color: #94a3b8;
        margin: 6px 0 0 0;
        font-size: 14px;
    }
    .stat-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2);
    }
    .stat-value {
        font-size: 28px;
        font-weight: 800;
        color: #38bdf8;
        line-height: 1.1;
    }
    .stat-label {
        font-size: 12px;
        font-weight: 600;
        color: #94a3b8;
        text-transform: uppercase;
        margin-top: 4px;
        letter-spacing: 0.5px;
    }
    .badge-admin {
        background: #f59e0b20;
        color: #fbbf24;
        border: 1px solid #f59e0b50;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        display: inline-block;
    }
    .badge-td {
        background: #0284c720;
        color: #38bdf8;
        border: 1px solid #0284c750;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        display: inline-block;
    }
    .badge-pending {
        background: #ec489920;
        color: #f472b6;
        border: 1px solid #ec489950;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        display: inline-block;
    }
    .match-box {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-left: 4px solid #38bdf8;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 14px;
    }
    div.stButton > button:first-child {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. PERSISTENT GOOGLE SHEETS REPOSITORY (USERS & ARCHIVES)
# ---------------------------------------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.strip().encode("utf-8")).hexdigest()

TARGET_ADMIN_HASH = "7e754bbef03e005db3d5089312104526685ba227e7f8e77a1fc9b6460fae2b1b"

def get_db_connection():
    try:
        return st.connection("gsheets", type=GSheetsConnection)
    except Exception:
        return None

def fetch_users_df() -> pd.DataFrame:
    conn = get_db_connection()
    required_cols = ["username", "name", "password_hash", "role", "status", "must_change_password", "created_at"]
    if conn is not None:
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
            
    return pd.DataFrame([{
        "username": "skramer",
        "name": "Scott Kramer",
        "password_hash": TARGET_ADMIN_HASH,
        "role": "admin",
        "status": "active",
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

# ---------------------------------------------------------
# 3. INITIALIZE TOURNAMENT STATE & ROSTER
# ---------------------------------------------------------
if "tournament_config" not in st.session_state:
    st.session_state.tournament_config = {
        "center": "Forest Hill Lanes",
        "name": "Cecil Harford Annual Championship",
        "lanes_count": 16,
        "lanes_range": "1-16",
        "division": "Adult Open",
        "rules_text": "Qualifying: 3 games across 3 pairs. Cut to top 5 for stepladder finals. Handicap based on 90% of 220 based on highest 2025-26 book average.",
        "intake_completed": False
    }

if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame([
        {"USBC ID": "11-12345", "Bowler": "Scott Kramer", "Average": 218, "Starting Lane": 1, "Game 1": 245, "Game 2": 238, "Game 3": 268, "Paid": True, "Checked_In": True},
        {"USBC ID": "11-23456", "Bowler": "Dave Miller", "Average": 205, "Starting Lane": 1, "Game 1": 210, "Game 2": 195, "Game 3": 215, "Paid": True, "Checked_In": True},
        {"USBC ID": "11-34567", "Bowler": "Chris Reynolds", "Average": 195, "Starting Lane": 2, "Game 1": 188, "Game 2": 220, "Game 3": 202, "Paid": True, "Checked_In": False},
        {"USBC ID": "11-45678", "Bowler": "Marcus Vance", "Average": 198, "Starting Lane": 2, "Game 1": 224, "Game 2": 215, "Game 3": 201, "Paid": True, "Checked_In": False},
        {"USBC ID": "11-56789", "Bowler": "Elena Rostova", "Average": 215, "Starting Lane": 3, "Game 1": 257, "Game 2": 248, "Game 3": 222, "Paid": True, "Checked_In": False},
        {"USBC ID": "11-67890", "Bowler": "Derek Jackson", "Average": 182, "Starting Lane": 3, "Game 1": 178, "Game 2": 195, "Game 3": 210, "Paid": True, "Checked_In": False},
        {"USBC ID": "11-78901", "Bowler": "Jason Taylor", "Average": 210, "Starting Lane": 4, "Game 1": 202, "Game 2": 235, "Game 3": 198, "Paid": True, "Checked_In": False},
        {"USBC ID": "11-89012", "Bowler": "Sarah Jenkins", "Average": 188, "Starting Lane": 4, "Game 1": 195, "Game 2": 204, "Game 3": 212, "Paid": True, "Checked_In": False},
    ])

if "Bowler_ID" in st.session_state.roster.columns and "USBC ID" not in st.session_state.roster.columns:
    st.session_state.roster["USBC ID"] = st.session_state.roster["Bowler_ID"]
    st.session_state.roster.drop(columns=["Bowler_ID"], inplace=True)

for col, default in [("USBC ID", "N/A"), ("Paid", False), ("Checked_In", False)]:
    if col not in st.session_state.roster.columns:
        st.session_state.roster[col] = default

if "brackets" not in st.session_state:
    st.session_state.brackets = []

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
# 4A. EXTERNAL MONITOR / BOWLER KIOSK DISPLAY (?mode=kiosk)
# ---------------------------------------------------------
query_params = st.query_params
if query_params.get("mode") == "kiosk":
    st.markdown("""
    <style>
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container {
            padding-top: 1.5rem;
            max-width: 900px;
        }
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
            checked = len(st.session_state.roster[st.session_state.roster["Checked_In"] == True])
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
# 4B. MOBILE-OPTIMIZED BOWLER SELF-CHECK-IN ROUTE (?mode=checkin)
# ---------------------------------------------------------
if query_params.get("mode") == "checkin":
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
# 5. TD AUTHENTICATION & LOGIN GATE
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
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.audit_trail.append({
        "timestamp": timestamp,
        "td": st.session_state.td_name or st.session_state.username,
        "action": action
    })

if not st.session_state.authenticated:
    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        if HAS_LOGO:
            st.image(LOGO_PATH, width=160)

        users_df = fetch_users_df()

        if st.session_state.pending_password_change:
            st.markdown("""
            <div class="brand-banner">
                <h1>🔒 Account Activation</h1>
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
                            users_df.loc[idx[0], "password_hash"] = hash_password(new_pwd)
                            users_df.loc[idx[0], "must_change_password"] = False
                            write_users_df(users_df)
                        st.session_state.pending_password_change = False
                        st.session_state.authenticated = True
                        log_audit_event(f"User '{u}' completed initial password change.")
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
                        if not match_row.empty:
                            stored_hash = str(match_row.iloc[0]["password_hash"])
                            if stored_hash == hash_password(password_input):
                                authenticated_match = True

                        if is_skramer or authenticated_match:
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
                                    log_audit_event(f"User '{username_input}' ({st.session_state.td_name}) logged in.")
                                    st.rerun()
                        else:
                            st.error("Invalid username or password.")

            with auth_tab_register:
                with st.form("td_self_register"):
                    st.caption("Apply for Tournament Director access. An administrator must approve your application.")
                    req_user = st.text_input("Desired Username:").strip().lower()
                    req_name = st.text_input("Full Name:").strip()
                    req_pwd = st.text_input("Desired Password:", type="password").strip()
                    submit_req = st.form_submit_button("Submit Registration for Approval", use_container_width=True)

                    if submit_req:
                        current_df = fetch_users_df()
                        if not req_user or not req_name or not req_pwd:
                            st.error("Username, Full Name, and Password are all required.")
                        elif len(req_pwd) < 6:
                            st.error("Password must be at least 6 characters.")
                        elif req_user in current_df["username"].values:
                            st.error(f"Username '{req_user}' is already registered or requested.")
                        else:
                            new_row = pd.DataFrame([{
                                "username": req_user,
                                "name": req_name,
                                "password_hash": hash_password(req_pwd),
                                "role": "td",
                                "status": "pending",
                                "must_change_password": False,
                                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                            }])
                            updated_df = pd.concat([current_df, new_row], ignore_index=True)
                            write_users_df(updated_df)
                            log_audit_event(f"New self-registration submitted: '{req_user}' ({req_name}).")
                            st.success("Registration submitted! An administrator will review and approve your account.")

    st.stop()

# ---------------------------------------------------------
# 6. GEMINI API CLIENT & RETRY FAILOVER ENGINE
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

# ---------------------------------------------------------
# 7. DETERMINISTIC SCORING ENGINE & PDF GENERATOR
# ---------------------------------------------------------
def calculate_handicap(avg: int, base: int = 220, percentage: float = 0.90) -> int:
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

    calc_df["HDCP_Per_Game"] = calc_df["Average"].apply(calculate_handicap)
    calc_df["Total_HDCP"] = calc_df["HDCP_Per_Game"] * 3
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

def export_standings_pdf(standings_df: pd.DataFrame, config: dict, champion_name: str = "") -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=2
    )
    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["Normal"],
        fontSize=8.5,
        textColor=colors.HexColor("#475569"),
        spaceAfter=10
    )

    champ_str = f" | <b>CHAMPION: {champion_name}</b>" if champion_name else ""
    header_text = f"""
    <b>Cecil Harford USBC — {config['name']}</b><br/>
    <font size="8" color="#475569">
    Host: {config['center']} | Division: {config['division']} | Lanes: {config['lanes_range']}{champ_str}<br/>
    TD on Duty: {st.session_state.td_name} | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')}
    </font>
    """

    if HAS_LOGO:
        logo_img = RLImage(LOGO_PATH, width=54, height=54)
        header_table = Table([[logo_img, Paragraph(header_text, title_style)]], colWidths=[64, 476])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(header_table)
    else:
        story.append(Paragraph(f"Cecil Harford USBC — {config['name']}", title_style))
        story.append(Paragraph(
            f"Center: {config['center']} | Division: {config['division']} | Lanes: {config['lanes_range']}{champ_str}<br/>"
            f"TD on Duty: {st.session_state.td_name} | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')}",
            meta_style
        ))

    table_data = [["Pos", "Bowler Name", "USBC ID", "Avg", "HDCP", "G1", "G2", "G3", "Scratch", "Total"]]
    for rank, row in standings_df.reset_index().iterrows():
        table_data.append([
            str(row["Rank"]),
            str(row["Bowler"]),
            str(row.get("USBC ID", "-")),
            str(row["Average"]),
            str(row["Total_HDCP"]),
            str(row["Game 1"]),
            str(row["Game 2"]),
            str(row["Game 3"]),
            str(row["Scratch_Total"]),
            str(row["Grand_Total"])
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
# 8. SIDEBAR NAVIGATION
# ---------------------------------------------------------
nav_options = [
    "1. Event & Roster Intake",
    "2. Scores & Standings",
    "3. Stepladder Finals",
    "4. Side Action: Brackets & Pots 💰",
    "5. AI Rules Arbiter",
    "6. Past Tournaments Archive 📂",
    "7. TD Audit Log"
]

users_df = fetch_users_df()
pending_count = len(users_df[users_df["status"] == "pending"])

if st.session_state.td_role == "admin":
    label = f"8. TD User Management ⚙️ ({pending_count} pending)" if pending_count > 0 else "8. TD User Management ⚙️"
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

    if st.button("Sign Out / Close Desk", use_container_width=True):
        log_audit_event("User logged out.")
        st.session_state.authenticated = False
        st.session_state.username = ""
        st.session_state.td_name = ""
        st.session_state.td_role = "td"
        st.session_state.pending_password_change = False
        st.rerun()

# ---------------------------------------------------------
# MODULE 1: COMPREHENSIVE INTAKE (SETTINGS -> ROSTER -> DESK TERMINAL)
# ---------------------------------------------------------
if nav == "1. Event & Roster Intake":
    st.markdown("""
    <div class="brand-banner">
        <h1>Step 1: Tournament Setup & Bowler Intake</h1>
        <p>Establish event metadata, rules parameters, bowler roster, and execute desk check-ins.</p>
    </div>
    """, unsafe_allow_html=True)

    intake_tab_settings, intake_tab_entry, intake_tab_terminal = st.tabs([
        "⚙️ Event Settings & Rules PDF",
        "📝 Roster Ingestion & Editing",
        "💳 Desk Intake & Payment Terminal"
    ])

    # TAB 1: EVENT SETTINGS & RULES PDF
    with intake_tab_settings:
        st.subheader("Tournament Identity & Parameters")
        c_name, c_center = st.columns([2, 1])
        with c_name:
            t_name = st.text_input("Tournament Name:", value=st.session_state.tournament_config["name"])
        with c_center:
            center = st.selectbox(
                "Host Bowling Center:",
                ["Forest Hill Lanes", "Harford Lanes", "APG Brewner Lanes", "Elk Lanes", "Other"],
                index=0
            )

        col_lanes1, col_lanes2, col_div = st.columns([1, 1, 1])
        with col_lanes1:
            lane_count = st.number_input("Total Lanes in Use:", min_value=2, max_value=60, value=16, step=2)
        with col_lanes2:
            lane_range = st.text_input("Active Pair Range (e.g., 1-16):", value=st.session_state.tournament_config["lanes_range"])
        with col_div:
            division = st.selectbox(
                "Division:",
                ["Mixed", "Youth", "Adult Open", "Women's", "Senior Singles / Doubles"],
                index=2
            )

        t_rules = st.text_area("Tournament Rules & Format:", value=st.session_state.tournament_config["rules_text"])
        uploaded_doc = st.file_uploader(
            "Upload Tournament Flyer / Rules Sheet (.pdf or .txt):", 
            type=["pdf", "txt"]
        )

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

            st.session_state.tournament_config = {
                "center": center,
                "name": t_name,
                "lanes_count": lane_count,
                "lanes_range": lane_range,
                "division": division,
                "rules_text": t_rules + uploaded_content,
                "intake_completed": True
            }
            log_audit_event(f"Configuration locked: {t_name} with {len(st.session_state.roster)} bowlers.")
            st.success("Configuration, roster, and tournament rules locked.")

    # TAB 2: ROSTER INGESTION & EDITING
    with intake_tab_entry:
        st.subheader("Bowler Entry & Roster Intake")
        st.caption("Ingest bowlers via clipboard photo/scan, Gemini text parsing, CSV upload, or the master grid.")

        tab_scan, tab_ai, tab_csv, tab_manual = st.tabs([
            "📸 Scan/Photo Clipboard (AI)",
            "🤖 Paste Signup Notes (Gemini AI)",
            "📁 Upload CSV",
            "📋 Editable Master Grid"
        ])

        with tab_scan:
            st.markdown("#### Snap or Upload Handwritten / Printed Roster Sheet")
            st.caption("Point your device camera at the signup sheet, or upload an image file.")

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
You are an expert bowling tournament assistant. Analyze this image of a tournament signup sheet (handwritten or printed).

Extract all bowler entries into standard CSV format with these exact columns:
USBC ID,Bowler,Average,Starting Lane,Paid

Rules:
1. 'USBC ID': Bowler USBC sanction ID number. If missing or illegible, format as 'TBD'.
2. 'Bowler': Full name of bowler.
3. 'Average': Numeric average. If missing or illegible, default to 200.
4. 'Starting Lane': Assigned lane number. If missing, default to 1.
5. 'Paid': True if there is a checkmark, 'paid', cash notation, or amount; otherwise False.
6. If names are scribbled or partially abbreviated, decipher them cleanly.
7. Output strictly the CSV text with headers, no conversational text or markdown code fences.
"""
                            try:
                                content_part = types.Part.from_bytes(
                                    data=captured_image,
                                    mime_type=mime_type
                                )
                                
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

                                st.session_state.roster = parsed_df
                                log_audit_event(f"Gemini scanned and extracted {len(parsed_df)} bowlers from photo.")
                                st.success(f"Successfully extracted {len(parsed_df)} bowlers! Check the 'Editable Master Grid' tab to review.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error analyzing image: {e}")

        with tab_ai:
            raw_bowler_text = st.text_area(
                "Paste bowler signups (e.g., USBC ID, names, averages, lanes):",
                placeholder="11-12345 Scott Kramer (218 avg, lane 1)\n11-23456 Dave Miller (205 avg, lane 1)\nChris Reynolds (195 avg, lane 2)\nMarcus Vance (198 avg, lane 2)",
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
Extract bowler USBC ID (default 'TBD' if not given), names, entry average (default 200), and starting lane (default 1).
Output strictly CSV formatted text with headers:
USBC ID,Bowler,Average,Starting Lane,Game 1,Game 2,Game 3
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
                            st.session_state.roster = new_roster_df
                            log_audit_event(f"Gemini parsed {len(new_roster_df)} bowler entries.")
                            st.success(f"Parsed and added {len(new_roster_df)} bowlers!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to parse entries: {e}")

        with tab_csv:
            csv_file = st.file_uploader("Select Roster CSV (USBC ID, Bowler, Average, Starting Lane):", type=["csv"])
            if csv_file is not None:
                try:
                    df_upload = pd.read_csv(csv_file)
                    for col in ["Game 1", "Game 2", "Game 3"]:
                        if col not in df_upload.columns:
                            df_upload[col] = 0
                    if "USBC ID" not in df_upload.columns:
                        if "Bowler_ID" in df_upload.columns:
                            df_upload["USBC ID"] = df_upload["Bowler_ID"]
                        else:
                            df_upload["USBC ID"] = [f"11-{10000+i+1}" for i in range(len(df_upload))]
                    if "Paid" not in df_upload.columns:
                        df_upload["Paid"] = False
                    if "Checked_In" not in df_upload.columns:
                        df_upload["Checked_In"] = False
                    st.session_state.roster = df_upload
                    st.success("CSV Imported successfully.")
                except Exception as err:
                    st.error(f"Error loading CSV: {err}")

        with tab_manual:
            edited_roster = st.data_editor(
                st.session_state.roster[["USBC ID", "Bowler", "Average", "Starting Lane", "Paid", "Checked_In"]],
                num_rows="dynamic",
                use_container_width=True,
                key="manual_roster_grid"
            )
            if st.button("Save Roster Changes"):
                for col in ["Game 1", "Game 2", "Game 3"]:
                    if col not in edited_roster.columns:
                        edited_roster[col] = 0
                st.session_state.roster = edited_roster
                log_audit_event("TD updated roster grid.")
                st.success("Roster updated.")

    # TAB 3: DESK INTAKE & PAYMENT TERMINAL (WITH EXTERNAL KIOSK SUPPORT)
    with intake_tab_terminal:
        st.subheader("Payment Gate & QR Check-In Terminal")
        st.caption("Bowlers present at the desk. Confirm payment before revealing the official check-in QR code.")

        detected_base = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")
        kiosk_launch_url = f"{detected_base}/?mode=kiosk"

        col_kiosk_btn, col_kiosk_clear = st.columns([2, 1])
        with col_kiosk_btn:
            st.link_button("🖥️ Open External Bowler Kiosk Window", kiosk_launch_url, use_container_width=True)
            st.caption("Drag that window to the monitor facing the bowlers and press F11 for fullscreen.")
        with col_kiosk_clear:
            if st.button("🔄 Reset External Display (Show Welcome)", use_container_width=True):
                clear_kiosk_state()
                log_audit_event("TD reset customer kiosk display to idle banner.")
                st.rerun()

        st.divider()

        total_bowlers = len(st.session_state.roster)
        paid_bowlers = len(st.session_state.roster[st.session_state.roster["Paid"] == True])
        checked_bowlers = len(st.session_state.roster[st.session_state.roster["Checked_In"] == True])

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
                <div class="stat-value" style="color: {'#34d399' if paid_bowlers == total_bowlers else '#fbbf24'};">{paid_bowlers} / {total_bowlers}</div>
                <div class="stat-label">Paid Entries</div>
            </div>
            """, unsafe_allow_html=True)
        with c_t3:
            st.markdown(f"""
            <div class="stat-card">
                <div class="stat-value" style="color: {'#34d399' if checked_bowlers == total_bowlers else '#38bdf8'};">{checked_bowlers} / {total_bowlers}</div>
                <div class="stat-label">Confirmed On-Lane</div>
            </div>
            """, unsafe_allow_html=True)

        st.write("")

        bowler_names = st.session_state.roster["Bowler"].tolist()
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
                                log_audit_event(f"TD manually checked in {search_query}.")
                                st.rerun()

# ---------------------------------------------------------
# MODULE 2: SCORES & STANDINGS
# ---------------------------------------------------------
elif nav == "2. Scores & Standings":
    standings = compile_standings(st.session_state.roster)

    st.markdown(f"""
    <div class="brand-banner">
        <h1>{st.session_state.tournament_config['name']}</h1>
        <p>{st.session_state.tournament_config['center']} | {st.session_state.tournament_config['division']} Division | Lanes {st.session_state.tournament_config['lanes_range']}</p>
    </div>
    """, unsafe_allow_html=True)

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
USBC ID,Bowler,Average,Starting Lane,Game 1,Game 2,Game 3,Paid,Checked_In
"""
                    try:
                        raw_csv_text = generate_with_failover(prompt, temperature=0.0)
                        cleaned = raw_csv_text.replace("```csv", "").replace("```", "").strip()
                        st.session_state.roster = pd.read_csv(io.StringIO(cleaned))
                        log_audit_event("Gemini updated scores from live recap.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error parsing scores: {e}")

    st.subheader("Official Scoring Grid")
    display_scoring = st.session_state.roster[[
        "USBC ID", "Bowler", "Average", "Starting Lane", "Paid", "Checked_In", "Game 1", "Game 2", "Game 3"
    ]]
    edited_scores = st.data_editor(
        display_scoring,
        num_rows="dynamic",
        use_container_width=True,
        key="official_scoring_grid"
    )
    if st.button("Save Scores & Recalculate Standings", type="primary"):
        st.session_state.roster = edited_scores
        log_audit_event("Scores saved and recalculated.")
        st.rerun()

    if not standings.empty:
        st.subheader("Live Standings (Handicap: 90% of 220)")
        st.dataframe(
            standings[[
                "Bowler", "USBC ID", "Average", "HDCP_Per_Game", "Game 1", "Game 2",
                "Game 3", "Scratch_Total", "Total_HDCP", "Grand_Total", "High_Scratch_Game"
            ]],
            use_container_width=True
        )

        pdf_bytes = export_standings_pdf(standings, st.session_state.tournament_config)
        st.download_button(
            "📄 Download Current Official PDF Standings",
            data=pdf_bytes,
            file_name=f"{st.session_state.tournament_config['name'].replace(' ', '_')}_Standings.pdf",
            mime="application/pdf"
        )

# ---------------------------------------------------------
# MODULE 3: STEP-LADDER FINALS BRACKET & ARCHIVING
# ---------------------------------------------------------
elif nav == "3. Stepladder Finals":
    st.markdown("""
    <div class="brand-banner">
        <h1>Championship Stepladder Finals</h1>
        <p>Top 5 qualifying cut-line elimination bracket and tournament completion.</p>
    </div>
    """, unsafe_allow_html=True)

    standings = compile_standings(st.session_state.roster)
    if len(standings) < 5:
        st.warning(f"Stepladder finals require at least 5 registered bowlers (Current field: {len(standings)}).")
    else:
        top_5 = standings.head(5)["Bowler"].tolist()

        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("Seeded Qualifiers")
            st.markdown(f"""
            <div class="match-box"><strong>#1 Seed (Championship Match):</strong> {top_5[0]}</div>
            <div class="match-box"><strong>#2 Seed (Semifinal Match):</strong> {top_5[1]}</div>
            <div class="match-box"><strong>#3 Seed (Match 2):</strong> {top_5[2]}</div>
            <div class="match-box"><strong>#4 Seed (Match 1):</strong> {top_5[3]}</div>
            <div class="match-box"><strong>#5 Seed (Match 1):</strong> {top_5[4]}</div>
            """, unsafe_allow_html=True)

        with c2:
            st.subheader("Match Play Adjudication")
            m1_winner = st.selectbox(f"Match 1: #4 {top_5[3]} vs #5 {top_5[4]}", [top_5[3], top_5[4]])
            m2_winner = st.selectbox(f"Match 2: #3 {top_5[2]} vs Winner ({m1_winner})", [top_5[2], m1_winner])
            semi_winner = st.selectbox(f"Semifinal: #2 {top_5[1]} vs Winner ({m2_winner})", [top_5[1], m2_winner])
            champion = st.selectbox(f"Championship: #1 {top_5[0]} vs Winner ({semi_winner})", [top_5[0], semi_winner])

            st.markdown(f"""
            <div style="background-color: #10b98120; border: 1px solid #10b981; border-radius: 8px; padding: 16px; text-align: center; margin-top: 16px;">
                <span style="font-size: 20px; font-weight: 800; color: #34d399;">🏆 TOURNAMENT CHAMPION: {champion}</span>
            </div>
            """, unsafe_allow_html=True)

            st.write("")
            col_lock, col_archive = st.columns(2)
            with col_lock:
                if st.button("Lock Champion in Audit Log", type="primary", use_container_width=True):
                    log_audit_event(f"Stepladder complete. Champion declared: {champion}.")
                    st.success("Official result recorded.")

            with col_archive:
                if st.button("📦 Archive Tournament & Save Official PDF", use_container_width=True):
                    pdf_bytes = export_standings_pdf(standings, st.session_state.tournament_config, champion_name=champion)
                    encoded_pdf = base64.b64encode(pdf_bytes).decode("utf-8")

                    archive_df = fetch_archives_df()
                    new_archive_record = pd.DataFrame([{
                        "tournament_name": st.session_state.tournament_config["name"],
                        "center": st.session_state.tournament_config["center"],
                        "division": st.session_state.tournament_config["division"],
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "entries": len(st.session_state.roster),
                        "champion": champion,
                        "pdf_data": encoded_pdf,
                        "archived_by": st.session_state.td_name
                    }])

                    updated_archives = pd.concat([archive_df, new_archive_record], ignore_index=True)
                    write_archives_df(updated_archives)
                    log_audit_event(f"Tournament '{st.session_state.tournament_config['name']}' officially archived with Champion: {champion}.")
                    st.success("Official PDF and tournament record permanently archived to Google Sheets!")

# ---------------------------------------------------------
# MODULE 4: SIDE ACTION: 8-BOWLER BRACKETS & SIDE POTS
# ---------------------------------------------------------
elif "Brackets & Pots" in nav:
    st.markdown("""
    <div class="brand-banner">
        <h1>Side Action: 8-Bowler Brackets & Side Pots</h1>
        <p>Manage single-elimination bracket trees and high-game side pot payouts synchronized with live scores.</p>
    </div>
    """, unsafe_allow_html=True)

    tab_brackets, tab_pots = st.tabs(["🌳 8-Bowler Elimination Brackets", "💵 High-Game & Series Side Pots"])

    # TAB 1: 8-BOWLER BRACKETS
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
                    log_audit_event(f"Generated {num_brackets_to_gen} {b_type} 8-bowler bracket(s).")
                    st.success(f"Generated {num_brackets_to_gen} bracket(s) successfully.")
                    st.rerun()

        with col_clear:
            if st.button("🗑️ Reset All Brackets", use_container_width=True):
                st.session_state.brackets = []
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

                # Round 1 (Game 1)
                r1_m1_b1, r1_m1_s1, r1_m1_b2, r1_m1_s2, r1_m1_win = resolve_bracket_match(seeds[0], seeds[7], "Game 1", b_mode, st.session_state.roster)
                r1_m2_b1, r1_m2_s1, r1_m2_b2, r1_m2_s2, r1_m2_win = resolve_bracket_match(seeds[3], seeds[4], "Game 1", b_mode, st.session_state.roster)
                r1_m3_b1, r1_m3_s1, r1_m3_b2, r1_m3_s2, r1_m3_win = resolve_bracket_match(seeds[2], seeds[5], "Game 1", b_mode, st.session_state.roster)
                r1_m4_b1, r1_m4_s1, r1_m4_b2, r1_m4_s2, r1_m4_win = resolve_bracket_match(seeds[1], seeds[6], "Game 1", b_mode, st.session_state.roster)

                # Round 2 (Game 2)
                r2_m1_b1, r2_m1_s1, r2_m1_b2, r2_m1_s2, r2_m1_win = resolve_bracket_match(r1_m1_win, r1_m2_win, "Game 2", b_mode, st.session_state.roster)
                r2_m2_b1, r2_m2_s1, r2_m2_b2, r2_m2_s2, r2_m2_win = resolve_bracket_match(r1_m3_win, r1_m4_win, "Game 2", b_mode, st.session_state.roster)

                # Round 3 (Game 3)
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

    # TAB 2: HIGH-GAME & SERIES POTS
    with tab_pots:
        st.subheader("High-Game & Series Pots Engine")
        st.caption("Select participants who bought into the side pot ($10 standard buy-in: $3 Game 1, $3 Game 2, $3 Game 3, $1 Series).")

        pot_fee = st.number_input("Side Pot Entry Fee ($):", value=10, min_value=1, step=1)
        
        paid_roster = st.session_state.roster[st.session_state.roster["Paid"] == True]
        all_paid_names = paid_roster["Bowler"].tolist()

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

            pot_df["HDCP_Per_Game"] = pot_df["Average"].apply(calculate_handicap)
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
# MODULE 5: AI RULES ARBITER
# ---------------------------------------------------------
elif nav == "5. AI Rules Arbiter":
    st.markdown("""
    <div class="brand-banner">
        <h1>USBC & Tournament Rules Arbiter</h1>
        <p>Gemini AI official decision support grounded on USBC Playing Rules.</p>
    </div>
    """, unsafe_allow_html=True)

    if not ai_client:
        st.warning("Gemini API key is required to query the Rules Arbiter.")
    else:
        division_alert = ""
        if st.session_state.tournament_config["division"] == "Youth":
            division_alert = "\nCRITICAL DIVISION MANDATE: Enforce USBC Rule 400 (all awards must be SMART scholarships; cash is prohibited)."

        rules_context = f"""
HOST BOWLING CENTER: {st.session_state.tournament_config['center']}
TOURNAMENT NAME: {st.session_state.tournament_config['name']}
DIVISION: {st.session_state.tournament_config['division']}
ACTIVE LANES: {st.session_state.tournament_config['lanes_range']}
RULES TEXT:
{st.session_state.tournament_config['rules_text']}
{division_alert}

USBC BASELINE RULES:
Rule 10 - Tardy Bowlers: An individual late for competition can begin only if the frame has not been completed by all bowlers on their pair. No warm-up frames.
Rule 17 - Altering Ball Surface: Surface adjustments via abrasive pads or chemical cleaners are prohibited once tournament competition has begun.
Rule 18 - Equipment Specs: Balance holes are prohibited. All drilled finger holes must be occupied on every delivery.
Rule 111 - Practice: No practice balls permitted on assigned pairs outside scheduled practice sessions.
Rule 329 - Protest Procedures: Protests must be filed in writing before prize distribution.
"""
        query = st.text_area("Describe the on-lane situation or protest:")
        if st.button("Generate Official Arbiter Ruling", type="primary"):
            if not query.strip():
                st.warning("Please describe the dispute.")
            else:
                with st.spinner("Analyzing USBC statutes..."):
                    prompt = f"""
You are the Cecil Harford USBC Official Rules Arbiter.
Ground your decision strictly on the rules below:
{rules_context}

Inquiry:
{query}

Format:
1. **Official Ruling:**
2. **Applicable USBC Rule:**
3. **TD Actionable Next Step:**
"""
                    try:
                        decision_text = generate_with_failover(prompt, temperature=0.1)
                        st.markdown("### Official Decision")
                        st.markdown(decision_text)
                        log_audit_event(f"Rules dispute adjudicated: '{query[:50]}...'")
                    except Exception as err:
                        st.error(f"Error querying Gemini: {err}")

# ---------------------------------------------------------
# MODULE 6: PAST TOURNAMENTS ARCHIVE (PERSISTENT PDF STORAGE)
# ---------------------------------------------------------
elif nav == "6. Past Tournaments Archive 📂":
    st.markdown("""
    <div class="brand-banner">
        <h1>Historical Tournament Archive</h1>
        <p>Official final results and downloadable PDF documents permanently stored on Google Sheets.</p>
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
# MODULE 7: AUDIT LOG
# ---------------------------------------------------------
elif nav == "7. TD Audit Log":
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
# MODULE 8: ADMIN USER MANAGEMENT
# ---------------------------------------------------------
elif "TD User Management" in nav:
    st.markdown("""
    <div class="brand-banner">
        <h1>Tournament Director & Staff Management</h1>
        <p>Admin console synchronized with Google Sheets for permanent account storage.</p>
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
            with st.container():
                st.markdown(f"""
                <div style="background-color: #1e293b; padding: 14px 18px; border-radius: 8px; border: 1px solid #ec489950; margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 16px; font-weight: 700; color: #f8fafc;">{real_name} (<code style="color: #38bdf8;">{uname}</code>)</span>
                        <span class="badge-pending">PENDING APPROVAL</span>
                    </div>
                    <div style="font-size: 13px; color: #94a3b8; margin-top: 6px;">
                        <strong>Submitted:</strong> {row.get('created_at', 'Recent')}
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
                        log_audit_event(f"Admin approved registration for '{uname}' ({real_name}) as {selected_role}.")
                        st.success(f"Account '{uname}' approved.")
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

    st.subheader("Active Staff Registry (Live from Google Sheets)")
    active_df = users_df[users_df["status"] == "active"].copy()
    display_df = pd.DataFrame({
        "Username": active_df["username"],
        "Full Name": active_df["name"],
        "Role": active_df["role"].str.upper(),
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
            new_pw = st.text_input("Initial Password:", type="password").strip()
            new_role = st.selectbox("Role Assignment:", ["td", "admin"])
            force_change = st.checkbox("Require pwd change on 1st login", value=True)
            submit_td = st.form_submit_button("Create Account Directly", type="primary", use_container_width=True)

            if submit_td:
                latest_df = fetch_users_df()
                if not new_user or not new_name or not new_pw:
                    st.error("All fields are required.")
                elif new_user in latest_df["username"].values:
                    st.error(f"User '{new_user}' already exists.")
                else:
                    new_entry = pd.DataFrame([{
                        "username": new_user,
                        "name": new_name,
                        "password_hash": hash_password(new_pw),
                        "role": new_role,
                        "status": "active",
                        "must_change_password": force_change,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                    }])
                    updated_df = pd.concat([latest_df, new_entry], ignore_index=True)
                    write_users_df(updated_df)
                    flag_note = "with mandatory password change" if force_change else "without mandatory password change"
                    log_audit_event(f"Admin registered new user: '{new_user}' ({new_name}) as {new_role} {flag_note}.")
                    st.success(f"Official '{new_name}' registered.")
                    st.rerun()

    with col_reset:
        st.subheader("Reset / Override Password")
        active_users = users_df[users_df["status"] == "active"]["username"].tolist()
        with st.form("reset_pwd_form"):
            target_user = st.selectbox("Select Account to Reset:", active_users)
            new_admin_pw = st.text_input("New Password:", type="password").strip()
            target_force = st.checkbox("Require user to change on next login", value=True)
            submit_reset = st.form_submit_button("Update Password", use_container_width=True)

            if submit_reset:
                if not new_admin_pw:
                    st.error("Password cannot be blank.")
                elif len(new_admin_pw) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    latest_df = fetch_users_df()
                    target_idx = latest_df.index[latest_df["username"] == target_user].tolist()
                    if target_idx:
                        latest_df.loc[target_idx[0], "password_hash"] = hash_password(new_admin_pw)
                        latest_df.loc[target_idx[0], "must_change_password"] = target_force
                        write_users_df(latest_df)
                    log_audit_event(f"Admin reset password for user '{target_user}'.")
                    st.success(f"Password for '{target_user}' updated.")
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
