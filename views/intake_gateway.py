# views/intake_gateway.py
import streamlit as st
import os
from config_profiles import CHUSBC_PRESET_PROFILES, CENTER_PROFILES
from db_state import write_active_tournament_state, log_audit_event

def render_intake_gateway():
    st.markdown("<h2 style='color:#38bdf8;'>🎯 Tournament Launchpad</h2>", unsafe_allow_html=True)
    st.caption("Select a standard CHUSBC championship preset or configure a custom event.")

    col1, col2, col3 = st.columns(3)

    # Card 1: Association Presets
    with col1:
        st.markdown("### 🏆 CHUSBC Presets")
        st.caption("Standard association championship rules.")
        selected_preset = st.selectbox(
            "Select Preset:", 
            list(CHUSBC_PRESET_PROFILES.keys()), 
            format_func=lambda k: CHUSBC_PRESET_PROFILES[k]["name"]
        )
        preset_center = st.selectbox("Host Center:", list(CENTER_PROFILES.keys()), key="preset_center_select")
        
        if st.button("⚡ Launch Preset", use_container_width=True):
            prof = CHUSBC_PRESET_PROFILES[selected_preset].copy()
            prof["center"] = CENTER_PROFILES[preset_center]["name"]
            st.session_state.tournament_config = prof
            log_audit_event("TOURNAMENT_LAUNCH", f"Launched {prof['name']} at {prof['center']}")
            st.success(f"Activated: {prof['name']}")
            st.rerun()

    # Card 2: Custom Event Setup (Memorial, Invitational, Youth Blocks)
    with col2:
        st.markdown("### 🛠️ Custom Event")
        st.caption("Independent sweeps, youth, or memorial blocks.")
        c_name = st.text_input("Event Name:", "Rose Murphy 2nd Annual Youth Tournament")
        c_center = st.selectbox("Center:", list(CENTER_PROFILES.keys()), key="custom_center_select")
        c_games = st.number_input("Total Games:", min_value=1, max_value=10, value=3)
        c_sanction = st.text_input("USBC Sanction / Cert # (Optional):", placeholder="e.g., 08123")
        c_logo = st.file_uploader("Custom Logo (.png/.jpg):", type=["png", "jpg", "jpeg"])

        if st.button("🚀 Launch Custom Event", use_container_width=True):
            logo_path = None
            if c_logo:
                os.makedirs("assets/custom", exist_ok=True)
                logo_path = os.path.join("assets/custom", c_logo.name)
                with open(logo_path, "wb") as f:
                    f.write(c_logo.getbuffer())

            custom_config = {
                "name": c_name,
                "center": CENTER_PROFILES[c_center]["name"],
                "games_count": c_games,
                "sanction_number": c_sanction,
                "custom_logo_path": logo_path,
                "is_youth_event": "youth" in c_name.lower()
            }
            st.session_state.tournament_config = custom_config
            log_audit_event("CUSTOM_EVENT_LAUNCH", f"Created custom event: {c_name}")
            st.success("Custom Event Created!")
            st.rerun()

    # Card 3: Active Event Cloud/Local Reconnection
    with col3:
        st.markdown("### 🔄 Active Event Sync")
        st.caption("Reconnect desk state to active SQLite store.")
        if st.button("📥 Pull Active Event", use_container_width=True):
            from db_state import fetch_active_tournament_state
            data = fetch_active_tournament_state()
            if data and data.get("config"):
                st.session_state.tournament_config = data["config"]
                st.session_state.roster = data["roster"]
                st.success("Successfully synchronized active tournament!")
                st.rerun()
            else:
                st.warning("No active tournament currently in progress.")