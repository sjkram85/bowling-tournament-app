import pandas as pd
import streamlit as st

from auth import fetch_users_df, render_auth_portal, write_users_df
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
from prism_ai import get_ai_client
from routes.public_modes import render_bowler_portal_view, render_tv_kiosk_display
from scoring import render_live_checkin_counters_fragment, render_live_radar_matrix_fragment
from views.advanced_view import render_advanced_view
from views.intake_gateway import render_intake_gateway


st.set_page_config(page_title="Prism Lane Control v1.1", page_icon="🎳", layout="wide")
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

if not st.session_state.authenticated:
    render_auth_portal()
    st.stop()

if st.session_state.get("td_role") == "kiosk_tv":
    render_tv_kiosk_display(state_fetcher_fn=fetch_active_tournament_state)
    st.stop()

selected_view = render_desk_sidebar()
if selected_view == "Intake Gateway":
    render_intake_gateway()
elif selected_view == "Public Portal":
    render_bowler_portal_view()
elif selected_view == "Concourse TV":
    render_tv_kiosk_display(state_fetcher_fn=fetch_active_tournament_state)
else:
    navigation = {
        "Floor Scoring": "3. Scores & Standings",
        "Closeout": "4. Stepladder Finals",
    }
    try:
        ai_client = get_ai_client()
    except Exception:
        ai_client = None
    render_advanced_view(
        nav=navigation[selected_view],
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