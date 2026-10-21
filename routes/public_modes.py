# routes/public_modes.py
import streamlit as st
import pandas as pd

def calc_over_under(row, active_game_cols):
    """
    Computes scratch +/- 200 par pace based strictly on completed games.
    """
    completed_games = sum(1 for col in active_game_cols if int(row.get(col, 0)) > 0)
    if completed_games == 0:
        return 0, "E"
    scratch = sum(int(row.get(col, 0)) for col in active_game_cols)
    diff = scratch - (200 * completed_games)
    diff_str = f"+{diff}" if diff > 0 else (f"{diff}" if diff < 0 else "E")
    return diff, diff_str


def get_standings_df():
    """
    Builds calculated standings from session state roster.
    """
    raw_roster = st.session_state.get("roster", [])
    if isinstance(raw_roster, list):
        df = pd.DataFrame(raw_roster)
    else:
        df = raw_roster.copy() if not raw_roster.empty else pd.DataFrame()

    if df.empty:
        return pd.DataFrame(), []

    config = st.session_state.get("tournament_config", {})
    games_count = int(config.get("games_count", 3))
    active_games = [f"Game {g}" for g in range(1, games_count + 1) if f"Game {g}" in df.columns]

    if not active_games:
        for g in range(1, games_count + 1):
            df[f"Game {g}"] = 0
        active_games = [f"Game {g}" for g in range(1, games_count + 1)]

    # Compute totals
    df["Total Scratch"] = df[active_games].astype(int).sum(axis=1)
    
    # Handicap calculation
    hdcp_base = float(config.get("hdcp_base", 220))
    hdcp_pct = float(config.get("hdcp_pct", 0.90))
    
    if "Average" in df.columns:
        df["HDCP_Game"] = df["Average"].apply(lambda avg: max(0, int((hdcp_base - int(avg)) * hdcp_pct)))
    else:
        df["HDCP_Game"] = 0

    # Total HDCP = scratch + (hdcp * games count)
    df["Total HDCP"] = df["Total Scratch"] + (df["HDCP_Game"] * games_count)

    # Calculate +/- 200
    ou_data = [calc_over_under(r, active_games) for _, r in df.iterrows()]
    df["+/- Value"] = [d[0] for d in ou_data]
    df["+/- 200"] = [d[1] for d in ou_data]

    return df, active_games


# =====================================================================
# VIEW 1: BOWLER MOBILE PORTAL (Live Tracking & Doubles Partner Card)
# =====================================================================
def render_bowler_portal_view():
    config = st.session_state.get("tournament_config", {})
    t_name = config.get("name", "Tournament Standings")
    
    st.markdown(f"<h2 style='text-align: center; color: #38bdf8;'>📱 {t_name}</h2>", unsafe_allow_html=True)
    st.caption("Live scores, cut-line bubble tracking, and doubles partner cards.")

    df_standings, active_games = get_standings_df()
    if df_standings.empty:
        st.info("Standings will appear once tournament play begins.")
        return

    # Sort Mode Toggle: Scratch vs Handicap
    sort_mode = st.radio("Leaderboard Sort:", ["Handicap Standings", "Scratch Standings"], horizontal=True)
    sort_col = "Total HDCP" if sort_mode == "Handicap Standings" else "Total Scratch"
    df_sorted = df_standings.sort_values(by=[sort_col, "Total Scratch"], ascending=False).reset_index(drop=True)
    df_sorted["Rank"] = df_sorted.index + 1

    # Doubles / Mystery Partner Pinned Card
    bowler_list = df_sorted["Bowler"].tolist()
    pinned_bowlers = st.multiselect(
        "👥 Pin Bowler(s) / Doubles Partner:",
        options=bowler_list,
        placeholder="Search and select your name or doubles partner..."
    )

    if pinned_bowlers:
        tracked_df = df_sorted[df_sorted["Bowler"].isin(pinned_bowlers)]
        team_scratch = tracked_df["Total Scratch"].sum()
        team_hdcp = tracked_df["Total HDCP"].sum()
        team_ou_val = tracked_df["+/- Value"].sum()
        team_ou_str = f"+{team_ou_val}" if team_ou_val > 0 else (f"{team_ou_val}" if team_ou_val < 0 else "E")
        team_color = "#34d399" if team_ou_val >= 0 else "#f87171"

        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 2px solid #38bdf8; border-radius: 10px; padding: 14px 18px; margin: 12px 0 16px 0;'>
            <div style='display: flex; justify-content: space-between; align-items: center;'>
                <div>
                    <span style='font-size: 11px; font-weight: 800; color: #38bdf8; text-transform: uppercase;'>⚡ Tracked Team / Doubles Status</span>
                    <h3 style='margin: 4px 0 0 0; color: #f8fafc; font-size: 20px;'>{' & '.join(pinned_bowlers)}</h3>
                </div>
                <div style='text-align: right;'>
                    <span style='font-size: 11px; color: #94a3b8; font-weight: 700;'>SCRATCH PAR</span>
                    <div style='font-size: 24px; font-weight: 900; color: {team_color};'>{team_ou_str}</div>
                </div>
            </div>
            <div style='margin-top: 8px; font-size: 13px; color: #cbd5e1; border-top: 1px solid #334155; padding-top: 8px;'>
                Combined Scratch: <b>{team_scratch}</b> &nbsp;|&nbsp; 
                Combined HDCP: <b>{team_hdcp}</b> &nbsp;|&nbsp; 
                +/- 200 Par: <b style='color:{team_color};'>{team_ou_str}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 5th-Place Cut Bubble Indicator (Standard 5-person stepladder cut)
    if len(df_sorted) >= 5:
        cut_score = df_sorted.iloc[4][sort_col]
        cut_bowler = df_sorted.iloc[4]["Bowler"]
        st.warning(f"🏁 **Current Cut Line (5th Place - Stepladder):** {cut_bowler} with **{cut_score}** pins")

    # Render Table
    lane_col = "Starting Lane" if "Starting Lane" in df_sorted.columns else "Lane"
    display_cols = ["Rank", "Bowler", lane_col] + active_games + ["+/- 200", "Total Scratch", "Total HDCP"]
    display_cols = [c for c in display_cols if c in df_sorted.columns]
    
    st.dataframe(df_sorted[display_cols], use_container_width=True, hide_index=True)


# =====================================================================
# VIEW 2: CONCOURSE TV KIOSK DISPLAY (Zero-Timeout, 10s Live Fragment)
# =====================================================================
def render_tv_kiosk_display(state_fetcher_fn=None):
    # JavaScript client-side keep-alive to suppress monitor sleep
    st.markdown("""
        <script>
            if ('wakeLock' in navigator) {
                navigator.wakeLock.request('screen').catch((err) => {});
            }
        </script>
    """, unsafe_allow_html=True)

    render_tv_kiosk_fragment()


@st.fragment(run_every="10s")
def render_tv_kiosk_fragment():
    df_standings, active_games = get_standings_df()
    config = st.session_state.get("tournament_config", {})
    t_name = config.get("name", "CHUSBC Tournament Championship")
    center_name = config.get("center", "")

    st.markdown(f"""
        <div style='background-color: #0f172a; padding: 12px 20px; border-radius: 8px; border-bottom: 3px solid #38bdf8; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center;'>
            <div>
                <h1 style='color: #f8fafc; margin: 0; font-size: 32px;'>🎳 {t_name}</h1>
                <span style='color: #94a3b8; font-size: 16px;'>{center_name} &nbsp;•&nbsp; Official Live Concourse Leaderboard</span>
            </div>
            <div style='text-align: right;'>
                <span style='color: #10b981; font-weight: 800; font-size: 14px;'>● LIVE AUTO-REFRESH (10s)</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if df_standings.empty:
        st.info("Leaderboard active. Awaiting first game scores from the desk...")
        return

    df_sorted = df_standings.sort_values(by=["Total HDCP", "Total Scratch"], ascending=False).reset_index(drop=True)
    df_sorted["Rank"] = df_sorted.index + 1

    # Cut Line Banner
    if len(df_sorted) >= 5:
        cut_val = df_sorted.iloc[4]["Total HDCP"]
        c_name = df_sorted.iloc[4]["Bowler"]
        st.markdown(f"""
        <div style='background-color: #854d0e; color: #fef08a; padding: 6px 14px; border-radius: 6px; font-weight: 700; margin-bottom: 12px;'>
            ✂️ STEPLADDER CUT BUBBLE (5th Place): {c_name} at {cut_val}
        </div>
        """, unsafe_allow_html=True)

    lane_col = "Starting Lane" if "Starting Lane" in df_sorted.columns else "Lane"
    tv_cols = ["Rank", "Bowler", lane_col] + active_games + ["+/- 200", "Total Scratch", "Total HDCP"]
    tv_cols = [c for c in tv_cols if c in df_sorted.columns]

    st.dataframe(df_sorted[tv_cols], use_container_width=True, hide_index=True)