import os
import io
import time
from datetime import datetime
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

from engine_support import (
    LOGO_CHUSBC_PATH, HAS_CHUSBC_LOGO, LOGO_FOREST_HILL_PATH, HAS_FOREST_HILL_LOGO,
    hash_secret, verify_secret, get_sqlite_conn, init_sqlite_tables,
    notify_admin_new_registration, calculate_handicap,
    parse_active_pairs, get_bowler_lane_for_game,
    export_tournament_summary_pdf, compile_all_events_leaderboard
)
from prism_ai import get_ai_client, stream_prism_ai
from routes.public_modes import handle_public_modes
from views.volunteer_view import render_volunteer_view
from views.advanced_view import render_advanced_view

# Initialize local SQLite operational tables immediately
init_sqlite_tables()

st.set_page_config(
    page_title="Prism Lane Control v1.1 — CHUSBC",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Contrast Theme & Accessible Styling
st.markdown("""
<style>
    .stApp { background-color: #0b1120; color: #f8fafc !important; }
    h1, h2, h3, h4, h5, h6, p, span, div[data-testid="stMarkdownContainer"] p { color: #f8fafc !important; }
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: #1e293b !important; color: #f8fafc !important; border: 1.5px solid #334155 !important;
    }
    .brand-banner {
        background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
        border: 1.5px solid #38bdf8; border-radius: 12px; padding: 20px 24px; margin-bottom: 20px;
    }
    .stat-card {
        background-color: #1e293b; border: 1.5px solid #475569; border-radius: 10px; padding: 16px; text-align: center;
    }
    .stat-value { font-size: 28px; font-weight: 800; color: #38bdf8 !important; }
    .stat-label { font-size: 12px; font-weight: 700; color: #f1f5f9 !important; text-transform: uppercase; margin-top: 4px; }
    .match-box {
        background-color: #1e293b; border: 1px solid #475569; border-left: 4px solid #38bdf8; border-radius: 8px; padding: 16px; margin-bottom: 14px;
    }
    .choice-card {
        background-color: #1e293b; border: 2px solid #334155; border-radius: 12px; padding: 20px;
    }
    .choice-card:hover { border-color: #38bdf8; }
    section[data-testid="stSidebar"] { background-color: #0f172a; border-right: 1px solid #1e293b; }
    .badge-td {
        background: #0284c725; color: #7dd3fc !important; border: 1px solid #0284c780; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# PROFILES & PRESETS
# ---------------------------------------------------------
CENTER_PROFILES = {
    "association": {"name": "Cecil-Harford USBC", "tagline": "Association Central Desk", "accent": "#38bdf8", "badge": "🏛️ CHUSBC Central Desk", "logo_path": LOGO_CHUSBC_PATH, "has_logo": HAS_CHUSBC_LOGO},
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
# PERSISTENCE & CLOUD SERVICES
# ---------------------------------------------------------
def get_db_connection():
    try:
        return st.connection("gsheets", type=GSheetsConnection)
    except Exception:
        return None

def fetch_users_df():
    conn = get_db_connection()
    required_cols = ["username", "name", "email", "password_hash", "role", "status", "center_id", "preferred_mode", "must_change_password"]
    if conn:
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
                        elif col == "status":
                            df[col] = "active"
                        elif col == "must_change_password":
                            df[col] = False
                        else:
                            df[col] = ""
                return df
        except Exception:
            pass

    return pd.DataFrame([{
        "username": "skramer",
        "name": "Scott Kramer",
        "email": "scottjk85@gmail.com",
        "password_hash": "7e754bbef03e005db3d5089312104526685ba227e7f8e77a1fc9b6460fae2b1b",
        "role": "admin",
        "status": "active",
        "center_id": "association",
        "preferred_mode": "Advanced",
        "must_change_password": False,
        "created_at": "Primary Admin"
    }])

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
    init_sqlite_tables()
    if not roster_df.empty:
        c = get_sqlite_conn()
        for _, row in roster_df.iterrows():
            c.execute("""
                INSERT INTO live_roster (usbc_id, bowler, average, starting_lane, division, team_name, game_1, game_2, game_3, game_4, paid, checked_in, is_sub, subbing_for, last_updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(usbc_id) DO UPDATE SET average=excluded.average, starting_lane=excluded.starting_lane, paid=excluded.paid, checked_in=excluded.checked_in
            """, (
                str(row.get("USBC ID", "")), str(row.get("Bowler", "")), int(row.get("Average", 200)), int(row.get("Starting Lane", 1)),
                str(row.get("Division", "Open")), str(row.get("Team_Name", "Singles")), int(row.get("Game 1", 0)), int(row.get("Game 2", 0)),
                int(row.get("Game 3", 0)), int(row.get("Game 4", 0)), 1 if bool(row.get("Paid", False)) else 0,
                1 if bool(row.get("Checked_In", False)) else 0, 1 if bool(row.get("is_sub", False)) else 0,
                str(row.get("subbing_for", "")) or None, st.session_state.get("username", "Staff")
            ))
        c.commit()
        c.close()
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
            "usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "starting_lane": "Starting Lane",
            "division": "Division", "team_name": "Team_Name", "game_1": "Game 1", "game_2": "Game 2",
            "game_3": "Game 3", "game_4": "Game 4", "paid": "Paid", "checked_in": "Checked_In"
        })
        return {
            "config": st.session_state.get("tournament_config", {}),
            "roster": df_local.to_dict(orient="records"),
            "brackets": st.session_state.get("brackets", []),
            "td_pins": st.session_state.get("td_pins", {})
        }
    return None

def fetch_archives_df():
    return pd.DataFrame(columns=["tournament_name", "center", "division", "date", "entries", "champion", "pdf_data", "archived_by"])

def write_archives_df(df):
    return True

# Initialize Session Defaults
if "tournament_config" not in st.session_state:
    st.session_state.tournament_config = dict(CHUSBC_PRESET_PROFILES["Annual CHUSBC Open Championship Tournament"])
if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame()
if "brackets" not in st.session_state:
    st.session_state.brackets = []
if "td_pins" not in st.session_state:
    st.session_state.td_pins = {}
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    td = st.session_state.get("mobile_scorer_td") or st.session_state.get("td_name") or st.session_state.get("username", "Staff")
    st.session_state.audit_trail.append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "td": td, "action": action})

api_key = st.secrets.get("GEMINI_API_KEY", None)
ai_client = get_ai_client(api_key)

# ---------------------------------------------------------
# ZERO-DIMMING REAL-TIME FRAGMENTS
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
    tot = len(df_c)
    p = int(df_c["paid"].sum()) if tot > 0 else 0
    ck = int(df_c["checked_in"].sum()) if tot > 0 else 0
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='stat-card'><div class='stat-value'>{tot}</div><div class='stat-label'>Total Field</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='stat-card'><div class='stat-value' style='color:#34d399;'>{p} / {tot}</div><div class='stat-label'>Paid</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='stat-card'><div class='stat-value' style='color:#38bdf8;'>{ck} / {tot}</div><div class='stat-label'>On Lane</div></div>", unsafe_allow_html=True)

@st.fragment(run_every="8s")
def render_live_radar_matrix_fragment(radar_game: int):
    conn = get_sqlite_conn()
    try:
        df_m = pd.read_sql_query("SELECT * FROM live_roster", conn)
    except Exception:
        df_m = pd.DataFrame()
    finally:
        conn.close()
    pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
    g_target = f"game_{radar_game}"
    if pairs:
        r_cols = st.columns(4)
        for idx, (l1, l2) in enumerate(pairs):
            with r_cols[idx % 4]:
                p_b = df_m[df_m["starting_lane"].isin([l1, l2])] if not df_m.empty else pd.DataFrame()
                has_sc = (p_b[g_target] > 0).any() if not p_b.empty else False
                badge = "🟢 VERIFIED" if has_sc else "⚪ EMPTY" if p_b.empty else "🔴 PENDING"
                color = "#10b981" if has_sc else "#334155" if p_b.empty else "#ef4444"
                st.markdown(f"<div style='background-color:#0f172a; border:1px solid {color}; border-radius:6px; padding:6px 10px; margin-bottom:8px;'><b style='color:#f8fafc;'>Lanes {l1}-{l2}</b> <span style='float:right; font-size:10px; color:{color}; font-weight:800;'>{badge}</span></div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# STANDALONE PUBLIC MODES DISPATCHER (?mode=...)
# ---------------------------------------------------------
query_mode = st.query_params.get("mode")
if query_mode:
    handle_public_modes(query_mode, fetch_active_tournament_state, write_active_tournament_state, log_audit_event, ai_client)

# ---------------------------------------------------------
# DESK GATEWAY AUTHENTICATION
# ---------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    with st.columns([1, 2, 1])[1]:
        if HAS_CHUSBC_LOGO:
            st.image(LOGO_CHUSBC_PATH, width=160)
        st.markdown("<div class='brand-banner'><h1>🎳 Prism Lane Control</h1><p>Cecil Harford USBC Central Desk Portal</p></div>", unsafe_allow_html=True)
        tab_log, tab_reg = st.tabs(["🔑 Sign In", "📝 Request TD Access"])
        with tab_log:
            with st.form("login_form"):
                u_in, p_in = st.text_input("Username:").strip().lower(), st.text_input("Password:", type="password").strip()
                if st.form_submit_button("Sign In to Tournament Desk", use_container_width=True):
                    users = fetch_users_df()
                    m = users[users["username"] == u_in]
                    auth = False
                    if not m.empty:
                        auth, _ = verify_secret(str(m.iloc[0]["password_hash"]), p_in)
                    if (u_in == "skramer" and p_in == "Abigail!2015") or auth:
                        d = m.iloc[0] if not m.empty else {"name": "Scott Kramer", "role": "admin", "center_id": "association", "preferred_mode": "Advanced"}
                        st.session_state.username, st.session_state.td_name, st.session_state.td_role = u_in, str(d.get("name", "Staff")), str(d.get("role", "admin")).lower()
                        st.session_state.center_id, st.session_state.preferred_mode = str(d.get("center_id", "association")).lower(), str(d.get("preferred_mode", "Advanced"))
                        st.session_state.authenticated, st.session_state.session_initialized = True, False
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")
        with tab_reg:
            with st.form("reg_form"):
                ru, rn, re, rp = st.text_input("Desired Username:").strip().lower(), st.text_input("Full Official Name:").strip(), st.text_input("Email:").strip().lower(), st.text_input("Password:", type="password").strip()
                if st.form_submit_button("Submit Registration", use_container_width=True) and ru and rn and re and len(rp) >= 6:
                    users = pd.concat([fetch_users_df(), pd.DataFrame([{"username": ru, "name": rn, "email": re, "password_hash": hash_secret(rp), "role": "td", "status": "pending", "center_id": "association", "preferred_mode": "Easy", "created_at": datetime.now().strftime("%Y-%m-%d")}])], ignore_index=True)
                    write_users_df(users)
                    notify_admin_new_registration(ru, rn, re, datetime.now().strftime("%Y-%m-%d %H:%M"))
                    st.success("Registration submitted!")
                    st.rerun()
    st.stop()

# ---------------------------------------------------------
# POST-LOGIN EVENT INTAKE GATEWAY
# ---------------------------------------------------------
active_brand = CENTER_PROFILES.get(st.session_state.center_id, CENTER_PROFILES["association"])
if not st.session_state.get("session_initialized", False):
    st.markdown(f"""
    <div class='brand-banner' style='border-color: {active_brand["accent"]}; box-shadow: 0 8px 32px rgba(56, 189, 248, 0.15);'>
        <div style='display: flex; align-items: center; justify-content: space-between;'>
            <div>
                <h1 style='margin: 0; font-size: 32px; font-weight: 800; color: #f8fafc;'>Welcome, {st.session_state.td_name}</h1>
                <p style='margin: 4px 0 0 0; font-size: 14px; color: {active_brand["accent"]}; font-weight: 700;'>{active_brand["name"]} • {active_brand["tagline"]}</p>
            </div>
            <span class='badge-td' style='font-size: 13px; padding: 6px 14px;'>{active_brand["badge"]}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    cloud = fetch_active_tournament_state()
    has_cloud = cloud is not None and bool(cloud.get("config"))

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("""
        <div class='choice-card'>
            <div style='font-size: 30px; margin-bottom: 8px;'>🚀</div>
            <h3 style='margin: 0; color: #38bdf8; font-weight: 800;'>CHUSBC Presets</h3>
            <p style='color: #cbd5e1; font-size: 12.5px; margin-top: 6px; line-height: 1.4;'>
                Launch association championship formats with certified 90% of 220 rules, lane movement rules, and fees preloaded.
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        sel = st.selectbox("Select Preset Profile:", list(CHUSBC_PRESET_PROFILES.keys()), label_visibility="collapsed")
        if st.button("⚡ Launch Selected Preset", type="primary", use_container_width=True):
            st.session_state.tournament_config = dict(CHUSBC_PRESET_PROFILES[sel])
            st.session_state.tournament_config["name"] = sel
            st.session_state.session_initialized = True
            st.rerun()

    with c2:
        st.markdown("""
        <div class='choice-card'>
            <div style='font-size: 30px; margin-bottom: 8px;'>✨</div>
            <h3 style='margin: 0; color: #10b981; font-weight: 800;'>Custom Event</h3>
            <p style='color: #cbd5e1; font-size: 12.5px; margin-top: 6px; line-height: 1.4;'>
                Configure an invitational, no-tap, or special format from scratch with custom pair allocations and handicap calculations.
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        if st.button("🛠️ Create New Custom Event", use_container_width=True):
            st.session_state.tournament_config = {
                "name": "New Custom Event",
                "center": active_brand["name"],
                "lanes_range": "1-40",
                "lanes_count": 40,
                "games_count": 3,
                "hdcp_base": 220,
                "hdcp_pct": 0.90,
                "entry_fee": 50.0
            }
            st.session_state.session_initialized = True
            st.rerun()

    with c3:
        cloud_name = cloud["config"].get("name", "Active Tournament") if has_cloud else "No Active Cloud Event"
        cloud_center = cloud["config"].get("center", "") if has_cloud else "No remote session found"
        st.markdown(f"""
        <div class='choice-card' style='border-color: {"#34d399" if has_cloud else "#334155"};'>
            <div style='font-size: 30px; margin-bottom: 8px;'>{"☁️" if has_cloud else "📂"}</div>
            <h3 style='margin: 0; color: {"#34d399" if has_cloud else "#94a3b8"}; font-weight: 800;'>Resume Live Event</h3>
            <p style='color: #cbd5e1; font-size: 12.5px; margin-top: 6px; line-height: 1.4;'>
                <b>{cloud_name}</b><br/>{cloud_center}
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        if st.button(
            "🔄 Reconnect to Active Cloud State" if has_cloud else "No Active Cloud Session",
            disabled=not has_cloud,
            type="primary" if has_cloud else "secondary",
            use_container_width=True
        ):
            st.session_state.tournament_config = cloud["config"]
            st.session_state.roster = pd.DataFrame(cloud["roster"])
            st.session_state.session_initialized = True
            st.rerun()

    st.stop()

# ---------------------------------------------------------
# SIDEBAR CONTROLS & STREAMING PRISM AI
# ---------------------------------------------------------
with st.sidebar:
    if active_brand["has_logo"]:
        st.image(active_brand["logo_path"], use_container_width=True)
    st.markdown(f"<div style='background-color:#1e293b; padding:10px; border-radius:8px;'><b>{st.session_state.td_name}</b><br/><span class='badge-td'>{active_brand['badge']}</span></div>", unsafe_allow_html=True)
    
    desk_mode = st.radio("OPERATING MODE", ["Volunteer Mode (Easy)", "Tournament Director (Advanced)"], index=0 if st.session_state.preferred_mode == "Easy" else 1)
    
    if "Volunteer" in desk_mode or "Easy" in desk_mode:
        nav_options = ["1. Easy Volunteer Desk", "2. Visual Lane Matrix", "3. Current Standings"]
    else:
        nav_options = [
            "1. Event & Roster Intake", "2. Visual Lane Matrix & Subs", "3. Scores & Standings", "4. Stepladder Finals",
            "5. Side Action: Brackets & Pots 💰", "6. Financial & SMART Ledger 💵", "7. AI Rules Arbiter", "8. Past Tournaments Archive 📂",
            "9. Board SOP & Staff Manual 📖", "10. TD Audit Log"
        ]
        if st.session_state.td_role == "admin":
            nav_options.append("11. TD User Management ⚙️")
            
    nav = st.radio("OPERATIONAL CONSOLE", nav_options)

    st.divider()
    with st.expander("✨ Prism AI Assistant", expanded=False):
        c_ai = get_sqlite_conn()
        try:
            ai_df = pd.read_sql_query("SELECT paid, checked_in FROM live_roster", c_ai)
        except Exception:
            ai_df = pd.DataFrame()
        finally:
            c_ai.close()

        t_b = len(ai_df)
        p_b = int(ai_df["paid"].sum()) if not ai_df.empty else 0
        c_b = int(ai_df["checked_in"].sum()) if not ai_df.empty else 0

        st.caption(f"Active Screen: **{nav}** ({c_b}/{t_b} on Lane)")
        trigger_ai = False

        if st.button("🧭 What should I do next on this screen?", use_container_width=True, key="btn_prism_next_prompt"):
            st.session_state["in_prism_query"] = f"What are my immediate next steps on '{nav}' in {desk_mode}?"
            trigger_ai = True

        q_in = st.text_input("Ask Prism AI:", placeholder="e.g. Next steps, tardy rule...", key="in_prism_query")
        if st.button("Consult Prism AI", type="primary", use_container_width=True, key="btn_run_prism"):
            if q_in.strip():
                trigger_ai = True
            else:
                st.warning("Please type a question or tap 'What should I do next'.")

        resp_c = st.empty()
        if trigger_ai:
            query_to_run = st.session_state.get("in_prism_query", "").strip()
            if query_to_run:
                ctx = {"user": st.session_state.td_name, "mode": desk_mode, "screen": nav, "event_name": st.session_state.tournament_config.get("name"), "center": st.session_state.tournament_config.get("center"), "total_bowlers": t_b, "paid_bowlers": p_b, "checked_bowlers": c_b}
                with resp_c.container():
                    st.session_state["prism_ans"] = st.write_stream(stream_prism_ai(query_to_run, ctx, client=ai_client))
        elif st.session_state.get("prism_ans"):
            def clear_prism_state():
                st.session_state["prism_ans"] = ""
                st.session_state["in_prism_query"] = ""

            with resp_c.container():
                st.markdown(f"<div class='match-box' style='font-size:13px;'>{st.session_state['prism_ans']}</div>", unsafe_allow_html=True)
                st.button("Clear Response", key="btn_clr_prism_ans", on_click=clear_prism_state, use_container_width=True)

    if st.button("Sign Out", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

# ---------------------------------------------------------
# DESK HEADER & VIEW DISPATCHER
# ---------------------------------------------------------
col_l1, col_l2, col_title = st.columns([1, 1, 6])
if HAS_CHUSBC_LOGO:
    col_l1.image(LOGO_CHUSBC_PATH, width=80)
if active_brand["has_logo"] and active_brand["logo_path"] != LOGO_CHUSBC_PATH:
    col_l2.image(active_brand["logo_path"], width=80)
col_title.markdown(f"<h2>{st.session_state.tournament_config['name']}</h2><p style='color:{active_brand['accent']}'><b>{active_brand['name']} • {active_brand['tagline']}</b></p>", unsafe_allow_html=True)
st.divider()

if "Volunteer" in desk_mode or "Easy" in desk_mode:
    render_volunteer_view()
else:
    render_advanced_view(
        nav=nav,
        desk_mode=desk_mode,
        CHUSBC_PRESET_PROFILES=CHUSBC_PRESET_PROFILES,
        write_active_tournament_state=write_active_tournament_state,
        log_audit_event=log_audit_event,
        render_live_checkin_counters_fragment=render_live_checkin_counters_fragment,
        render_live_radar_matrix_fragment=render_live_radar_matrix_fragment,
        compile_all_events_leaderboard=compile_all_events_leaderboard,
        export_tournament_summary_pdf=export_tournament_summary_pdf,
        fetch_archives_df=fetch_archives_df,
        write_archives_df=write_archives_df,
        fetch_users_df=fetch_users_df,
        write_users_df=write_users_df,
        ai_client=ai_client
    )
