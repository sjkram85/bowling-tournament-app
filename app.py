import pandas as pd
import streamlit as st

from auth import fetch_users_df, render_auth_portal, render_password_change_portal, write_users_df
from components.sidebar import render_desk_sidebar
from config_profiles import CHUSBC_PRESET_PROFILES
from db_state import (
    fetch_active_tournament_state,
    fetch_archives_df,
    init_sqlite_tables,
    log_audit_event,
    write_active_tournament_state,
    write_archives_df,
)
from engine_support import compile_all_events_leaderboard, export_tournament_summary_pdf
from prism_ai import get_ai_client, render_ai_assistant
from routes.public_modes import handle_public_modes, render_bowler_portal_view, render_tv_kiosk_display
from scoring import render_live_checkin_counters_fragment, render_live_radar_matrix_fragment
from views.advanced_view import render_advanced_view
from views.intake_gateway import render_intake_gateway


st.set_page_config(page_title="Prism Lane Control v1.1", page_icon="🎳", layout="wide")
st.markdown("""
<style>
    .stApp { background-color: #0b1120; color: #f8fafc !important; }
    h1, h2, h3, h4, h5, h6, p, span, div[data-testid="stMarkdownContainer"] p { color: #f8fafc !important; }
    .stTextInput label, .stSelectbox label, .stNumberInput label, .stTextArea label,
    .stRadio label, .stFileUploader label, .stMultiSelect label {
        color: #ffffff !important; font-weight: 700 !important; font-size: 14.5px !important;
        letter-spacing: 0.3px; margin-bottom: 4px !important;
    }
    .stCaption, small, .stCaption p, div[data-testid="stCaptionContainer"] {
        color: #cbd5e1 !important; font-size: 13.5px !important; line-height: 1.4 !important;
    }
    .brand-banner {
        background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
        border: 1.5px solid #38bdf8; border-radius: 12px; padding: 22px 26px;
        margin-bottom: 24px; box-shadow: 0 4px 16px rgba(0, 0, 0, 0.45);
    }
    .brand-banner h1 { color: #ffffff !important; margin: 0; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; }
    .brand-banner p { color: #e2e8f0 !important; margin: 6px 0 0 0; font-size: 15px; }
    .stat-card { background-color: #1e293b; border: 1.5px solid #475569; border-radius: 10px; padding: 16px; text-align: center; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3); }
    .stat-value { font-size: 28px; font-weight: 800; color: #38bdf8 !important; line-height: 1.1; }
    .stat-label { font-size: 12px; font-weight: 700; color: #f1f5f9 !important; text-transform: uppercase; margin-top: 4px; letter-spacing: 0.6px; }
    .match-box { background-color: #1e293b; border: 1px solid #475569; border-left: 4px solid #38bdf8; border-radius: 8px; padding: 16px; margin-bottom: 14px; color: #ffffff !important; }
    .match-box strong { color: #38bdf8 !important; }
    .choice-card { background-color: #1e293b; border: 2px solid #334155; border-radius: 12px; padding: 22px; height: 100%; transition: all .2s ease-in-out; }
    .choice-card:hover { border-color: #38bdf8; box-shadow: 0 6px 20px rgba(56,189,248,.2); }
    button[data-baseweb="tab"] { color: #94a3b8 !important; font-weight: 600 !important; font-size: 15px !important; background-color: transparent !important; }
    button[data-baseweb="tab"][aria-selected="true"] { color: #38bdf8 !important; font-weight: 800 !important; border-bottom-color: #38bdf8 !important; }
    section[data-testid="stSidebar"] { background-color: #0f172a; border-right: 1px solid #1e293b; }
    section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] div { color: #f1f5f9 !important; }
    .badge-admin { background: #f59e0b25; color: #fde047 !important; border: 1px solid #f59e0b80; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800; display: inline-block; }
    .badge-td { background: #0284c725; color: #7dd3fc !important; border: 1px solid #0284c780; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800; display: inline-block; }
    .badge-pending { background: #ec489925; color: #f9a8d4 !important; border: 1px solid #ec489980; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800; display: inline-block; }
    div.stButton > button:first-child { border-radius: 8px; font-weight: 700; }
    div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] { border: 1px solid #334155; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)
init_sqlite_tables()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "tournament_config" not in st.session_state:
    active_state = fetch_active_tournament_state()
    st.session_state.tournament_config = (
        active_state["config"] if active_state else dict(CHUSBC_PRESET_PROFILES["Annual CHUSBC Open Championship Tournament"])
    )
    st.session_state.roster = active_state["roster"] if active_state else pd.DataFrame()
    st.session_state.brackets = active_state["brackets"] if active_state else []
    st.session_state.td_pins = active_state["td_pins"] if active_state else {}
    st.session_state.audit_trail = []
st.session_state.setdefault("roster", pd.DataFrame())
st.session_state.setdefault("brackets", [])
st.session_state.setdefault("td_pins", {})
st.session_state.setdefault("audit_trail", [])

if handle_public_modes(
    st.query_params.get("mode"),
    state_fetcher_fn=fetch_active_tournament_state,
    ai_client=get_ai_client(),
):
    st.stop()

if not st.session_state.authenticated:
    render_auth_portal()
    st.stop()

if st.session_state.get("must_change_password", False):
    render_password_change_portal()
    st.stop()

if st.session_state.get("td_role") == "kiosk_tv":
    render_tv_kiosk_display(state_fetcher_fn=fetch_active_tournament_state)
    st.stop()

selected_view = render_desk_sidebar()

try:
    ai_client = get_ai_client()
except Exception:
    ai_client = None

advanced_kwargs = dict(
    desk_mode="Tournament Director",
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
    ai_client=ai_client,
)

ADVANCED_ROUTES = {
    "Floor Scoring & Matrix": "3. Scores & Standings",
    "Lane Movement Guide": "2. Visual Lane Matrix & Subs",
    "Side Pots & Brackets": "5. Side Action: Brackets & Pots 💰",
    "SMART & Financial Escrow": "6. Financial & SMART Ledger 💵",
    "Stepladder Finals & Closeout": "4. Stepladder Finals",
    "Tournament Archives": "8. Past Tournaments Archive 📂",
    "Rules Arbiter (Prism AI)": "7. AI Rules Arbiter",
    "Audit Log": "10. TD Audit Log",
}

if selected_view == "Intake Gateway":
    render_intake_gateway()
elif selected_view == "Bowler Mobile Portal":
    render_bowler_portal_view(fetch_active_tournament_state)
elif selected_view == "Concourse TV (10s auto-refresh)":
    render_tv_kiosk_display(state_fetcher_fn=fetch_active_tournament_state)
elif selected_view == "Prism AI Assistant":
    render_ai_assistant()
elif selected_view == "Staff Management & Manual":
    render_advanced_view(nav="9. Board SOP & Staff Manual 📖", **advanced_kwargs)
    if st.session_state.get("td_role") == "admin":
        st.divider()
        render_advanced_view(nav="11. TD User Management ⚙️", **advanced_kwargs)
    else:
        st.info("Staff account administration requires an admin role.")
elif selected_view in ADVANCED_ROUTES:
    render_advanced_view(nav=ADVANCED_ROUTES[selected_view], **advanced_kwargs)