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
        "rules_text": "Qualifying: 3 games across 3 pairs. Cut to top
