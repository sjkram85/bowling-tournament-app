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
# 2. AUTHENTICATION & MULTI-TD USER REPOSITORY
# ---------------------------------------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# Initial user registry with admin default ("admin" / "admin")
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_HASH = "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918"

if "user_registry" not in st.session_state:
    st.session_state.user_registry = {
        DEFAULT_ADMIN_USER: {
            "name": "Association Admin",
            "password_hash": DEFAULT_ADMIN_HASH,
            "role": "admin",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
    }

# Sync with Streamlit Secrets if configured
if "TD_USER" in st.secrets and "TD_PASSWORD_HASH" in st.secrets:
    sec_user = st.secrets["TD_USER"]
    st.session_state.user_registry[sec_user] = {
        "name": "Primary TD",
        "password_hash": st.secrets["TD_PASSWORD_HASH"],
        "role": "admin",
        "created_at": "Secrets Config"
    }

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "td_name" not in st.session_state:
    st.session_state.td_name = ""
if "td_role" not in st.session_state:
    st.session_state.td_role = "td"
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.audit_trail.append({
        "timestamp": timestamp,
        "td": st.session_state.td_name or st.session_state.username,
        "action": action
    })

# Login Screen
if not st.session_state.authenticated:
    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        st.markdown("### 🎳 Cecil Harford USBC Desk Portal")
        st.caption("Authorized Tournament Directors & Officials Only")
        with st.form("td_login"):
            username = st.text_input("Username").strip()
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Verify & Open Desk")

            if submitted:
                reg = st.session_state.user_registry
                if username in reg and reg[username]["password_hash"] == hash_password(password):
                    st.session_state.authenticated = True
                    st.session_state.username = username
                    st.session_state.td_name = reg[username]["name"]
                    st.session_state.td_role = reg[username]["role"]
                    log_audit_event(f"User '{username}' ({st.session_state.td_name}) logged into desk session.")
                    st.success("Authorized.")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
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
    if avg >= base:
