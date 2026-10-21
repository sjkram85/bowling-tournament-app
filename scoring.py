# scoring.py
import streamlit as st
import pandas as pd

@st.fragment(run_every="8s")
def render_live_checkin_counters_fragment():
    """
    Zero-dimming auto-refreshing check-in count badges.
    Reads directly from st.session_state to avoid closure argument staleness.
    """
    roster_data = st.session_state.get("roster", pd.DataFrame())
    if isinstance(roster_data, list):
        roster_df = pd.DataFrame(roster_data)
    else:
        roster_df = roster_data
        
    if roster_df.empty:
        st.info("No active roster loaded.")
        return

    total = len(roster_df)
    checked_in = int(roster_df["Checked_In"].sum()) if "Checked_In" in roster_df.columns else 0
    paid = int(roster_df["Paid"].sum()) if "Paid" in roster_df.columns else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Field", f"{total} Bowlers")
    c2.metric("Checked In", f"{checked_in} / {total}", delta=f"{checked_in - total}")
    c3.metric("Paid Entries", f"{paid} / {total}")


@st.fragment(run_every="8s")
def render_live_radar_matrix_fragment(game_number=None):
    """
    Concourse Lane Status Matrix.
    Reads active game dynamically from st.session_state.
    """
    roster_data = st.session_state.get("roster", pd.DataFrame())
    active_game = game_number or st.session_state.get("active_radar_game", 1)
    
    if isinstance(roster_data, list):
        roster_df = pd.DataFrame(roster_data)
    else:
        roster_df = roster_data
        
    if roster_df.empty:
        return

    st.markdown(f"**Live Radar Status — Game {active_game}**")
    lane_col = "Starting Lane" if "Starting Lane" in roster_df.columns else "Lane"
    score_col = f"Game {active_game}"

    if lane_col in roster_df.columns and score_col in roster_df.columns:
        lanes = sorted(roster_df[lane_col].dropna().unique().astype(int))
        cols = st.columns(min(len(lanes), 8) or 1)
        for idx, lane in enumerate(lanes[:16]):
            lane_bowlers = roster_df[roster_df[lane_col] == lane]
            has_scores = (lane_bowlers[score_col].astype(int) > 0).all()
            badge_color = "#10b981" if has_scores else "#f59e0b"
            status_text = "COMPLETE" if has_scores else "ROLLING"
            
            with cols[idx % len(cols)]:
                st.markdown(f"""
                <div style='background-color:#1e293b; border-left: 3px solid {badge_color}; padding: 6px; border-radius: 4px; margin-bottom: 6px;'>
                    <b style='color:#f8fafc; font-size:12px;'>Lane {lane}</b><br/>
                    <span style='color:{badge_color}; font-size:11px; font-weight:700;'>{status_text}</span>
                </div>
                """, unsafe_allow_html=True)