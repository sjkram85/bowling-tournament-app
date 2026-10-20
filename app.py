import os
import io
import time
import json
import random
from datetime import datetime
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

from google import genai
from google.genai import types

# Import all extracted engine components from engine_support.py
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
# 1. PAGE SETUP & CONTRAST THEME
# ---------------------------------------------------------
st.set_page_config(
    page_title="Prism Lane Control v1.1 — CHUSBC",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Platform detection script injection
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

# High-contrast accessible styling
st.markdown("""
<style>
    .stApp { background-color: #0b1120; color: #f8fafc !important; }
    h1, h2, h3, h4, h5, h6, p, span, div[data-testid="stMarkdownContainer"] p { color: #f8fafc !important; }
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: #1e293b !important; color: #f8fafc !important; border: 1.5px solid #334155 !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus { border-color: #38bdf8 !important; }
    .brand-banner {
        background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
        border: 1.5px solid #38bdf8; border-radius: 12px; padding: 20px 24px; margin-bottom: 20px;
    }
    .stat-card {
        background-color: #1e293b; border: 1.5px solid #475569; border-radius: 10px; padding: 16px; text-align: center;
    }
    .stat-value { font-size: 28px; font-weight: 800; color: #38bdf8 !important; line-height: 1.1; }
    .stat-label { font-size: 12px; font-weight: 700; color: #f1f5f9 !important; text-transform: uppercase; margin-top: 4px; }
    .match-box {
        background-color: #1e293b; border: 1px solid #475569; border-left: 4px solid #38bdf8; border-radius: 8px; padding: 16px; margin-bottom: 14px;
    }
    .choice-card {
        background-color: #1e293b; border: 2px solid #334155; border-radius: 12px; padding: 20px; height: 100%;
    }
    .choice-card:hover { border-color: #38bdf8; }
    section[data-testid="stSidebar"] { background-color: #0f172a; border-right: 1px solid #1e293b; }
    .badge-td { background: #0284c725; color: #7dd3fc !important; border: 1px solid #0284c780; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. BRAND & PRESET DICTIONARIES
# ---------------------------------------------------------
CENTER_PROFILES = {
    "association": {"name": "Cecil-Harford USBC", "tagline": "Association Operations", "accent": "#38bdf8", "badge": "🏛️ CHUSBC Central Desk", "logo_path": LOGO_CHUSBC_PATH, "has_logo": HAS_CHUSBC_LOGO},
    "forest_hill": {"name": "Forest Hill Bowling Center", "tagline": "Host Center • Forest Hill, MD", "accent": "#10b981", "badge": "🎳 Forest Hill Lanes", "logo_path": LOGO_FOREST_HILL_PATH, "has_logo": HAS_FOREST_HILL_LOGO},
    "harford": {"name": "Harford Lanes", "tagline": "Host Center • Aberdeen, MD", "accent": "#f59e0b", "badge": "🎳 Harford Lanes", "logo_path": LOGO_CHUSBC_PATH, "has_logo": HAS_CHUSBC_LOGO},
    "apg": {"name": "APG Bowling Center", "tagline": "Host Center • APG", "accent": "#ec4899", "badge": "🎳 APG Brewner Lanes", "logo_path": LOGO_CHUSBC_PATH, "has_logo": HAS_CHUSBC_LOGO}
}

CHUSBC_PRESET_PROFILES = {
    "Annual CHUSBC Open Championship Tournament": {"center": "Forest Hill Bowling Center", "lanes_count": 40, "lanes_range": "1-40", "division": "Adult Open", "hdcp_base": 220, "hdcp_pct": 0.90, "format_mode": "Team/Singles Standard", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)", "entry_fee": 50.0, "rules_text": "USBC Certified. 3 Games across pairs. Handicap: 90% of 220."},
    "CHUSBC Women’s Championship Tournament": {"center": "APG Bowling Center", "lanes_count": 24, "lanes_range": "1-24", "division": "Women's Certified", "hdcp_base": 220, "hdcp_pct": 0.90, "format_mode": "Women's Championship", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)", "entry_fee": 50.0, "rules_text": "USBC Certified. Open to female USBC members."},
    "Lighthouse Ladies Singles": {"center": "Harford Lanes", "lanes_count": 20, "lanes_range": "1-20", "division": "Women's Singles", "hdcp_base": 215, "hdcp_pct": 0.90, "format_mode": "Ladies Singles Invitational", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)", "entry_fee": 40.0, "rules_text": "3 qualifying games moving pairs into top 5 stepladder."},
    "Senior Singles Championship": {"center": "Forest Hill Bowling Center", "lanes_count": 40, "lanes_range": "1-40", "division": "Seniors (Age 50+)", "hdcp_base": 220, "hdcp_pct": 0.90, "format_mode": "Senior Age-Bracketed", "games_count": 3, "movement_rule": "Move Right 1 Pair (+2 Lanes)", "entry_fee": 45.0, "rules_text": "USBC Certified Senior Singles. Age 50+."}
}

# ---------------------------------------------------------
# 3. CLOUD SHEETS & RUNTIME DATA HELPERS
# ---------------------------------------------------------
def get_db_connection():
    try:
        return st.connection("gsheets", type=GSheetsConnection)
    except Exception:
        return None

def fetch_users_df():
    conn = get_db_connection()
    if conn:
        try:
            df = conn.read(worksheet="Sheet1", ttl=0)
            if df is not None and not df.empty:
                df.columns = [str(c).strip().lower() for c in df.columns]
                return df
        except Exception:
            pass
    return pd.DataFrame([{"username": "skramer", "name": "Scott Kramer", "email": "scottjk85@gmail.com", "password_hash": "7e754bbef03e005db3d5089312104526685ba227e7f8e77a1fc9b6460fae2b1b", "role": "admin", "status": "active", "center_id": "association", "preferred_mode": "Advanced", "must_change_password": False}])

def write_users_df(df):
    conn = get_db_connection()
    if conn:
        try:
            conn.update(worksheet="Sheet1", data=df)
            st.cache_data.clear()
            return True
        except Exception:
            pass
    return False

def write_active_tournament_state(config, roster_df, brackets, sync_to_cloud=False):
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
                payload = {"config": config, "roster": roster_df.to_dict(orient="records"), "brackets": brackets, "td_pins": st.session_state.get("td_pins", {}), "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "saved_by": st.session_state.get("td_name", "Staff")}
                conn.update(worksheet="Active_Tournament", data=pd.DataFrame([{"id": "CURRENT_TOURNAMENT", "payload": json.dumps(payload)}]))
                st.cache_data.clear()
                return True
            except Exception:
                pass
    return True

def fetch_active_tournament_state():
    c = get_sqlite_conn()
    df_local = pd.read_sql_query("SELECT * FROM live_roster", c)
    c.close()
    if not df_local.empty:
        df_local = df_local.rename(columns={"usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "starting_lane": "Starting Lane", "division": "Division", "team_name": "Team_Name", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3", "game_4": "Game 4", "paid": "Paid", "checked_in": "Checked_In", "g1_verified_by": "G1_Verified_By", "g1_verified_at": "G1_Verified_At", "g2_verified_by": "G2_Verified_By", "g2_verified_at": "G2_Verified_At", "g3_verified_by": "G3_Verified_By", "g3_verified_at": "G3_Verified_At"})
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
    if conn:
        try:
            df = conn.read(worksheet="Archived_Tournaments", ttl=0)
            if df is not None and not df.empty:
                df.columns = [str(c).strip().lower() for c in df.columns]
                return df
        except Exception:
            pass
    return pd.DataFrame(columns=["tournament_name", "center", "division", "date", "entries", "champion", "pdf_data", "archived_by"])

# Runtime State Setup
if "tournament_config" not in st.session_state:
    st.session_state.tournament_config = dict(CHUSBC_PRESET_PROFILES["Annual CHUSBC Open Championship Tournament"])
if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame(columns=["USBC ID", "Bowler", "Average", "Starting Lane", "Division", "Team_Name", "Game 1", "Game 2", "Game 3", "Game 4", "Paid", "Checked_In"])
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
        nav_options = ["1. Event & Roster Intake", "2. Visual Lane Matrix & Subs", "3. Scores & Standings", "4. Stepladder Finals", "5. Side Action: Brackets & Pots 💰", "6. Financial & SMART Ledger 💵", "7. Past Tournaments Archive 📂", "8. Board SOP & Manual 📖", "9. TD Audit Log"]
        if st.session_state.td_role == "admin":
            nav_options.append("10. TD User Management ⚙️")

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

# ==============================================================================
# VIEW: EASY MODE (ACCESSIBLE TOURNAMENT DIRECTOR)
# ==============================================================================
if desk_mode.startswith("Volunteer") or desk_mode.startswith("Easy"):
    st.markdown(f"<div class='brand-banner' style='border-color:{active_brand['accent']};'><h2>{st.session_state.tournament_config['name']} — Director Quick-Desk</h2></div>", unsafe_allow_html=True)
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
# VIEW: ADVANCED MODE (FULL SUITE)
# ==============================================================================
else:
    if nav == "1. Event & Roster Intake":
        t1, t2, t3 = st.tabs(["⚙️ Settings", "📝 Ingestion", "🎳 Balancer"])
        with t1:
            t_name = st.text_input("Event Name:", value=st.session_state.tournament_config["name"])
            t_lanes = st.text_input("Active Lanes:", value=st.session_state.tournament_config.get("lanes_range", "1-40"))
            if st.button("Save Configuration", type="primary"):
                st.session_state.tournament_config["name"] = t_name
                st.session_state.tournament_config["lanes_range"] = t_lanes
                st.success("Updated!")
        with t2:
            txt = st.text_area("Paste Roster CSV (USBC ID, Bowler, Avg, Team):")
            if st.button("Parse Roster", type="primary") and txt.strip():
                records = []
                for idx, line in enumerate(txt.strip().split("\n")):
                    p = [item.strip() for item in line.split(",")]
                    records.append({"USBC ID": p[0] if len(p) > 0 else f"B-{idx}", "Bowler": p[1] if len(p) > 1 else f"Bowler {idx}", "Average": int(p[2]) if len(p) > 2 and p[2].isdigit() else 200, "Starting Lane": 1, "Team_Name": p[3] if len(p) > 3 else "Singles", "Paid": True, "Checked_In": True})
                st.session_state.roster = pd.DataFrame(records)
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success("Ingested!"); st.rerun()
        with t3:
            pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"))
            if st.button("⚡ Balance Lanes", type="primary"):
                b_df, _ = auto_assign_lanes(st.session_state.roster, pairs)
                st.session_state.roster = b_df
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success("Balanced!"); st.rerun()

    elif nav == "2. Visual Lane Matrix & Subs":
        c = get_sqlite_conn()
        r_df = pd.read_sql_query("SELECT * FROM live_roster", c)
        c.close()
        st.subheader("Sub-In Workflow")
        if not r_df.empty:
            orig = st.selectbox("Sub Out:", r_df["bowler"].tolist())
            sub_n = st.text_input("Replacement Name:").strip()
            sub_a = st.number_input("Sub Avg:", 50, 300, 190)
            if st.button("Execute Substitution", type="primary") and sub_n:
                lane = int(r_df[r_df["bowler"] == orig].iloc[0]["starting_lane"])
                c = get_sqlite_conn()
                c.execute("UPDATE live_roster SET checked_in = 0 WHERE bowler = ?", (orig,))
                c.execute("INSERT INTO live_roster (usbc_id, bowler, average, starting_lane, paid, checked_in) VALUES (?, ?, ?, ?, 1, 1)", (f"SUB-{datetime.now().strftime('%M%S')}", sub_n, sub_a, lane))
                c.commit(); c.close()
                st.success(f"{sub_n} subbed on Lane {lane}!"); st.rerun()

    elif nav == "3. Scores & Standings":
        c = get_sqlite_conn()
        df = pd.read_sql_query("SELECT * FROM live_roster", c)
        c.close()
        if not df.empty:
            stds = compile_standings(df.rename(columns={"bowler": "Bowler", "average": "Average", "starting_lane": "Starting Lane", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"}), st.session_state.tournament_config)
            st.dataframe(stds[["Bowler", "Average", "Starting Lane", "Game 1", "Game 2", "Game 3", "Grand_Total"]], use_container_width=True)
            st.download_button("📄 Download PDF Standings", export_standings_pdf(stds, st.session_state.tournament_config), "Standings.pdf", "application/pdf")

    elif nav == "4. Stepladder Finals":
        c = get_sqlite_conn()
        df = pd.read_sql_query("SELECT * FROM live_roster", c)
        c.close()
        stds = compile_standings(df.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"}), st.session_state.tournament_config)
        if len(stds) >= 5:
            top = stds.head(5)["Bowler"].tolist()
            st.markdown(f"<div class='match-box' style='text-align:center;'><h1>👑 #1 Seed: {top[0]}</h1><p>Advancing to Championship Match</p></div>", unsafe_allow_html=True)
            st.write(f"**Match 1:** {top[3]} vs {top[4]} | **Match 2:** {top[2]} vs Winner M1 | **Semi:** {top[1]} vs Winner M2")

    elif nav == "5. Side Action: Brackets & Pots 💰":
        c = get_sqlite_conn()
        paid = pd.read_sql_query("SELECT usbc_id FROM live_roster WHERE paid = 1", c)["usbc_id"].tolist()
        c.close()
        if len(paid) >= 8 and st.button("Seed 8-Bowler Bracket", type="primary"):
            st.session_state.brackets.append({"id": f"B-{len(st.session_state.brackets)+1:02d}", "seeds": random.sample(paid, 8)})
            st.success("Bracket seeded!")
        st.write(f"Active Brackets: **{len(st.session_state.brackets)}**")

    elif nav == "6. Financial & SMART Ledger 💵":
        c = get_sqlite_conn()
        df = pd.read_sql_query("SELECT * FROM live_roster", c).rename(columns={"paid": "Paid"})
        c.close()
        fin = calculate_financial_summary(df, st.session_state.tournament_config)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Paid", fin["paid_count"]); c2.metric("Gross", f"${fin['gross_revenue']:,.2f}"); c3.metric("Lineage", f"${fin['total_lineage']:,.2f}"); c4.metric("Prize Fund", f"${fin['net_prize_fund']:,.2f}")
        if "youth" in str(st.session_state.tournament_config.get("division", "")).lower():
            st.download_button("Download SMART CSV", generate_smart_scholarship_csv(df.rename(columns={"bowler": "Bowler"}), fin["net_prize_fund"], st.session_state.tournament_config["name"]), "SMART.csv", "text/csv")

    elif nav == "7. Past Tournaments Archive 📂":
        st.dataframe(fetch_archives_df()[["tournament_name", "date", "center", "champion", "entries"]], use_container_width=True)

    elif nav == "8. Board SOP & Manual 📖":
        c1, c2 = st.columns(2)
        c1.download_button("📝 Download SOP (.docx)", generate_sop_docx(st.session_state.tournament_config), "SOP.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        c2.download_button("📄 Download SOP (.pdf)", generate_sop_pdf(st.session_state.tournament_config), "SOP.pdf", "application/pdf")

    elif nav == "9. TD Audit Log":
        st.dataframe(pd.DataFrame(st.session_state.audit_trail), use_container_width=True)

    elif "TD User Management" in nav:
        st.dataframe(fetch_users_df()[["username", "name", "role", "center_id", "preferred_mode", "status"]], use_container_width=True)
