from datetime import datetime
import pandas as pd
import streamlit as st
from engine_support import get_sqlite_conn, compile_standings, export_standings_pdf, export_lane_assignments_pdf

def render_volunteer_view():
    """Renders the simplified, accessible Volunteer Quick-Desk."""
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
            if st.button("Save Scores", type="primary", width="stretch"):
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
            st.dataframe(stds[["Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Grand_Total"]], width="stretch")
            cp1, cp2 = st.columns(2)
            cp1.download_button("📄 Print Standings (PDF)", export_standings_pdf(stds, st.session_state.tournament_config), "Standings.pdf", "application/pdf", type="primary")
            cp2.download_button("📄 Print Lane Sheet (PDF)", export_lane_assignments_pdf(df.rename(columns={"bowler": "Bowler", "starting_lane": "Starting Lane", "average": "Average"}), st.session_state.tournament_config), "Lane_Sheet.pdf", "application/pdf")
