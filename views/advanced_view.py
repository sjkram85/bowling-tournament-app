import io
import base64
import random
from datetime import datetime
import pandas as pd
import streamlit as st
from pypdf import PdfReader

from engine_support import (
    get_sqlite_conn, parse_active_pairs, auto_assign_lanes, write_kiosk_state, clear_kiosk_state,
    generate_qr_image, hash_secret, compile_standings, export_standings_pdf,
    export_lane_assignments_pdf, resolve_bracket_match, calculate_financial_summary,
    generate_smart_scholarship_csv, generate_sop_docx, generate_sop_pdf, notify_user_account_approved
)
from prism_ai import stream_prism_ai, parse_roster_text_with_gemini

def render_advanced_view(
    nav: str,
    desk_mode: str,
    CHUSBC_PRESET_PROFILES: dict,
    write_active_tournament_state,
    log_audit_event,
    render_live_checkin_counters_fragment,
    render_live_radar_matrix_fragment,
    compile_all_events_leaderboard,
    export_tournament_summary_pdf,
    fetch_archives_df,
    write_archives_df,
    fetch_users_df,
    write_users_df,
    ai_client
):
    # MODULE 1: COMPREHENSIVE INTAKE
    if nav == "1. Event & Roster Intake":
        intake_tab_settings, intake_tab_entry, intake_tab_terminal, intake_tab_pins = st.tabs([
            "⚙️ Event Settings & CHUSBC Presets",
            "📝 Roster Ingestion & 40-Lane Balancing",
            "💳 Desk Intake & Entrance QR Posters",
            "🔐 Floor TD PIN Registry (Argon2)"
        ])

        with intake_tab_settings:
            st.subheader("Tournament Calibration & Presets")
            preset_choice = st.selectbox("Load Official CHUSBC Profile:", ["-- Select to Apply Preset --"] + list(CHUSBC_PRESET_PROFILES.keys()))
            if preset_choice != "-- Select to Apply Preset --" and st.button(f"Apply '{preset_choice}' Parameters", type="primary"):
                st.session_state.tournament_config.update(CHUSBC_PRESET_PROFILES[preset_choice])
                st.session_state.tournament_config["name"] = preset_choice
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success(f"Applied {preset_choice} presets!")
                st.rerun()

            st.divider()
            c_name, c_center = st.columns([2, 1])
            with c_name:
                t_name_val = st.text_input("Tournament Name:", value=st.session_state.tournament_config["name"])
            with c_center:
                center_options = ["Forest Hill Bowling Center", "Harford Lanes", "APG Bowling Center", "Elk Lanes"]
                cur_center = st.session_state.tournament_config.get("center", "Forest Hill Bowling Center")
                center_val = st.selectbox("Host Bowling Center:", center_options, index=center_options.index(cur_center) if cur_center in center_options else 0)

            col_lanes1, col_lanes2, col_div = st.columns(3)
            with col_lanes1:
                lane_count_val = st.number_input("Total Lanes in Center:", 2, 60, int(st.session_state.tournament_config.get("lanes_count", 40)), 2)
            with col_lanes2:
                lane_range_val = st.text_input("Active Pair Range (e.g. 1-40 or 1-16, 21-36):", value=st.session_state.tournament_config.get("lanes_range", "1-40"))
            with col_div:
                division_val = st.text_input("Division / Category:", value=st.session_state.tournament_config.get("division", "Adult Open"))

            col_h1, col_h2, col_h3 = st.columns(3)
            with col_h1:
                h_base_val = st.number_input("Handicap Base Average:", value=int(st.session_state.tournament_config.get("hdcp_base", 220)), step=5)
            with col_h2:
                h_pct_val = st.number_input("Handicap Percentage (0.90 = 90%):", value=float(st.session_state.tournament_config.get("hdcp_pct", 0.90)), step=0.05, format="%.2f")
            with col_h3:
                rule_options = ["Stay on Pair (No Movement)", "Move Right 1 Pair (+2 Lanes)", "Move Right 2 Pairs (+4 Lanes)", "Move Left 1 Pair (-2 Lanes)"]
                cur_rule = st.session_state.tournament_config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")
                rule_val = st.selectbox("Lane Rotation Rule:", rule_options, index=rule_options.index(cur_rule) if cur_rule in rule_options else 1)

            t_rules_val = st.text_area("Tournament Rules & Format Flyer:", value=st.session_state.tournament_config.get("rules_text", ""))
            uploaded_doc = st.file_uploader("Upload Tournament Flyer / Rules PDF (.pdf or .txt):", type=["pdf", "txt"])

            if st.button("🔒 Save & Lock Tournament Configuration", type="primary", use_container_width=True):
                uploaded_content = ""
                if uploaded_doc is not None:
                    if uploaded_doc.name.lower().endswith(".pdf"):
                        try:
                            reader = PdfReader(uploaded_doc)
                            uploaded_content = "\n[PDF RULES]:\n" + "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
                        except Exception as e:
                            st.error(f"Error reading PDF: {e}")
                    else:
                        uploaded_content = f"\n[RULES FILE]:\n{uploaded_doc.read().decode('utf-8', errors='ignore')}"

                st.session_state.tournament_config.update({
                    "center": center_val, "name": t_name_val, "lanes_count": lane_count_val,
                    "lanes_range": lane_range_val, "division": division_val, "hdcp_base": h_base_val,
                    "hdcp_pct": h_pct_val, "movement_rule": rule_val, "rules_text": t_rules_val + uploaded_content,
                    "intake_completed": True
                })
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                log_audit_event(f"Configuration locked: {t_name_val} at {center_val}.")
                st.success("Tournament settings locked & backed up.")

        with intake_tab_entry:
            st.subheader("Bowler Roster & Team-Aware 40-Lane Balancer")
            tab_ai, tab_csv, tab_grid, tab_bal = st.tabs(["🤖 Parse Signup Notes", "📁 Upload CSV", "📋 Master Grid", "🎳 40-Lane Balancer"])

            with tab_ai:
                raw_text = st.text_area("Paste bowler signups (USBC ID, Name, Avg, Team):", placeholder="11-12345 Scott Kramer 218 Striking Power\n11-23456 Dave Miller 205 Striking Power")
                if st.button("Extract Roster with Gemini", type="primary") and raw_text.strip():
                    cleaned_csv = parse_roster_text_with_gemini(raw_text, client=ai_client)
                    if cleaned_csv:
                        new_df = pd.read_csv(io.StringIO(cleaned_csv))
                        new_df["Paid"] = True
                        new_df["Checked_In"] = True
                        st.session_state.roster = new_df
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success(f"Parsed {len(new_df)} bowlers!")
                        st.rerun()
                    else:
                        st.error("Failed to parse roster. Check Gemini API key and try again.")

            with tab_csv:
                csv_file = st.file_uploader("Upload Roster CSV:", type=["csv"])
                if csv_file and st.button("Import CSV"):
                    df_up = pd.read_csv(csv_file)
                    st.session_state.roster = df_up
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success("CSV Imported successfully.")

            with tab_grid:
                edited = st.data_editor(st.session_state.roster, num_rows="dynamic", use_container_width=True)
                if st.button("Save Grid Changes"):
                    st.session_state.roster = edited
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success("Grid updated!")

            with tab_bal:
                st.markdown("### 🎳 Automated Team-Aware Lane Balancer")
                cb1, cb2, cb3, cb4 = st.columns([2, 1, 1, 1])
                with cb1:
                    custom_range = st.text_input("Active Range:", value=st.session_state.tournament_config.get("lanes_range", "1-40"))
                with cb2:
                    max_cap = st.selectbox("Max Bowlers per Pair:", [4, 5, 6, 8, 10], index=1)
                with cb3:
                    grp_teams = st.checkbox("👥 Keep Teammates Together", value=True)
                with cb4:
                    shuf = st.checkbox("🎲 Blind Random Draw", value=True)

                parsed_pairs = parse_active_pairs(custom_range, max_lanes=40)
                if st.button("⚡ Balance & Assign Lanes Automatically", type="primary", use_container_width=True):
                    b_roster, err = auto_assign_lanes(st.session_state.roster, parsed_pairs, max_per_pair=max_cap, shuffle=shuf, group_by_team=grp_teams)
                    if err:
                        st.error(err)
                    else:
                        st.session_state.roster = b_roster
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success("Lanes balanced!")
                        st.rerun()

                if not st.session_state.roster.empty:
                    st.download_button("📄 Download Printable PDF Lane Assignments", export_lane_assignments_pdf(st.session_state.roster, st.session_state.tournament_config, st.session_state.td_name), "Lane_Assignments.pdf", "application/pdf", use_container_width=True)

        with intake_tab_terminal:
            st.subheader("Payment Gate, Entrance QR & Check-In Terminal")
            detected_base = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")
            kiosk_url = f"{detected_base}/?mode=kiosk"
            self_checkin_url = f"{detected_base}/?mode=self_checkin"
            bowler_portal_url = f"{detected_base}/?mode=bowler_portal"

            col_q1, col_q2, col_q3 = st.columns(3)
            with col_q1:
                st.markdown("##### 🚪 Entrance Self-Check-In QR")
                st.image(generate_qr_image(self_checkin_url), width=130)
                st.link_button("🔗 Open Entrance Check-In", self_checkin_url, use_container_width=True)
            with col_q2:
                st.markdown("##### 📊 Bowler Live Portal QR")
                st.image(generate_qr_image(bowler_portal_url), width=130)
                st.link_button("🔗 Open Bowler Portal", bowler_portal_url, use_container_width=True)
            with col_q3:
                st.markdown("##### 🖥️ Desk Customer Monitor")
                st.link_button("🖥️ Launch Customer Screen", kiosk_url, use_container_width=True)
                if st.button("🔄 Reset Customer Screen", use_container_width=True):
                    clear_kiosk_state()
                    st.rerun()

            st.divider()
            render_live_checkin_counters_fragment()

            st.write("")
            b_list = st.session_state.roster["Bowler"].tolist() if not st.session_state.roster.empty else []
            s_bowler = st.selectbox("Search / Select Bowler at Desk:", ["-- Select Bowler Arriving at Desk --"] + b_list)

            if s_bowler != "-- Select Bowler Arriving at Desk --":
                b_row = st.session_state.roster[st.session_state.roster["Bowler"] == s_bowler].iloc[0]
                b_paid, b_checked = bool(b_row["Paid"]), bool(b_row["Checked_In"])
                b_lane = int(b_row["Starting Lane"])
                pair_partner = b_lane + 1 if b_lane % 2 != 0 else b_lane - 1
                pair_display_str = f"Lanes {min(b_lane, pair_partner)} & {max(b_lane, pair_partner)}"

                col_inf, col_act = st.columns(2)
                with col_inf:
                    st.markdown(f"<div class='match-box'><h3>{s_bowler}</h3>Lane: <b>{b_lane}</b> ({pair_display_str})<br/>Paid: <b>{'🟢 YES' if b_paid else '🔴 NO'}</b> | Checked In: <b>{'🟢 YES' if b_checked else '⚪ NO'}</b></div>", unsafe_allow_html=True)
                    if not b_paid:
                        p_method = st.radio("Payment Method:", ["Cash", "Check", "Venmo / Electronic"], horizontal=True)
                        if st.button(f"Mark Paid ({p_method}) & Push to Customer Screen", type="primary", use_container_width=True):
                            idx = st.session_state.roster.index[st.session_state.roster["Bowler"] == s_bowler].tolist()[0]
                            st.session_state.roster.loc[idx, "Paid"] = True
                            write_kiosk_state({"name": s_bowler, "usbc_id": str(b_row["USBC ID"]), "avg": int(b_row["Average"]), "lane": b_lane, "pair_display": pair_display_str})
                            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                            st.success("Payment logged & pushed to monitor!")
                            st.rerun()
                with col_act:
                    if st.button("Manual TD Check-In Override (No Phone)", use_container_width=True):
                        idx = st.session_state.roster.index[st.session_state.roster["Bowler"] == s_bowler].tolist()[0]
                        st.session_state.roster.loc[idx, "Checked_In"] = True
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success(f"{s_bowler} checked in!")
                        st.rerun()

        with intake_tab_pins:
            st.subheader("🔐 Floor TD Security PIN Registry (Argon2id)")
            if st.session_state.td_pins:
                st.dataframe(pd.DataFrame([{"Official": k, "Encryption": "Argon2id", "Status": "🟢 Locked"} for k in st.session_state.td_pins.keys()]), use_container_width=True)
            with st.form("pin_override"):
                ov_name = st.text_input("Official Name:").strip()
                ov_pin = st.text_input("Assign 4-Digit PIN:", type="password", max_chars=6).strip()
                if st.form_submit_button("Lock PIN (Argon2id)", type="primary"):
                    if ov_name and len(ov_pin) >= 4:
                        st.session_state.td_pins[ov_name] = hash_secret(ov_pin)
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success(f"PIN locked for {ov_name}!")
                        st.rerun()

    # MODULE 2: VISUAL MATRIX & SUBSTITUTIONS
    elif nav == "2. Visual Lane Matrix & Subs":
        st.markdown("### 🎳 Visual Center Pair Matrix & Mid-Event Substitutions")
        conn = get_sqlite_conn()
        roster_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        col_vm, col_sub = st.columns([2, 1])
        with col_vm:
            st.subheader("Active Center Lane Grid")
            parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
            grid_cols = st.columns(4)
            for idx, pair in enumerate(parsed_pairs):
                l_odd, l_even = pair
                bowlers_on_p = roster_live[roster_live["starting_lane"].isin([l_odd, l_even])]
                with grid_cols[idx % 4]:
                    status_css = "border: 1px solid #334155; background-color: #0f172a;" if bowlers_on_p.empty else "border: 1.5px solid #10b981; background-color: #064e3b20;"
                    st.markdown(f"<div style='{status_css} border-radius: 8px; padding: 10px; margin-bottom: 10px;'><strong style='color: #f8fafc;'>Lanes {l_odd} & {l_even}</strong><br/><span style='font-size: 11px; color: #38bdf8;'>{len(bowlers_on_p)} Bowlers</span></div>", unsafe_allow_html=True)

        with col_sub:
            st.subheader("🔄 Sub-In Bowler")
            if not roster_live.empty:
                orig_bowler = st.selectbox("Select Bowler to Sub Out:", roster_live["bowler"].tolist())
                sub_name = st.text_input("Replacement Bowler Name:").strip()
                sub_avg = st.number_input("Sub Entering Average:", value=190, step=1)
                if st.button("Execute Substitution", type="primary", use_container_width=True) and sub_name:
                    orig_lane = int(roster_live[roster_live["bowler"] == orig_bowler].iloc[0]["starting_lane"])
                    c = get_sqlite_conn()
                    c.execute("UPDATE live_roster SET checked_in = 0, team_name = team_name || ' (Subbed)' WHERE bowler = ?", (orig_bowler,))
                    c.execute("""
                        INSERT INTO live_roster (usbc_id, bowler, average, starting_lane, division, team_name, paid, checked_in, is_sub, subbing_for, last_updated_by)
                        VALUES (?, ?, ?, ?, 'Open', 'Singles', 1, 1, 1, ?, ?)
                    """, (f"SUB-{datetime.now().strftime('%M%S')}", sub_name, sub_avg, orig_lane, orig_bowler, st.session_state.username))
                    c.commit()
                    c.close()
                    log_audit_event(f"Substituted '{sub_name}' in place of '{orig_bowler}' on Lane {orig_lane}.")
                    st.success(f"{sub_name} subbed on Lane {orig_lane}!")
                    st.rerun()

    # MODULE 3: SCORES, STANDINGS & RADAR MATRIX
    elif nav == "3. Scores & Standings":
        st.subheader("🛰️ Central Desk Lane Radar Matrix")
        radar_game = st.radio("Display Radar for Game:", [1, 2, 3], horizontal=True)
        render_live_radar_matrix_fragment(radar_game)
        st.divider()

        conn = get_sqlite_conn()
        df_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        if not df_live.empty:
            df_for_calc = df_live.rename(columns={
                "usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "starting_lane": "Starting Lane",
                "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3", "game_4": "Game 4", "paid": "Paid", "checked_in": "Checked_In"
            })
            standings = compile_standings(df_for_calc, st.session_state.tournament_config)

            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f"<div class='stat-card'><div class='stat-value'>{len(df_for_calc)}</div><div class='stat-label'>Field Size</div></div>", unsafe_allow_html=True)
            c2.markdown(f"<div class='stat-card'><div class='stat-value'>{standings.iloc[0]['Grand_Total'] if not standings.empty else 0}</div><div class='stat-label'>Leader</div></div>", unsafe_allow_html=True)
            c3.markdown(f"<div class='stat-card'><div class='stat-value'>{standings.iloc[4]['Grand_Total'] if len(standings) >= 5 else 0}</div><div class='stat-label'>#5 Cut Line</div></div>", unsafe_allow_html=True)
            c4.markdown(f"<div class='stat-card'><div class='stat-value'>{standings['High_Scratch_Game'].max() if not standings.empty else 0}</div><div class='stat-label'>High Scratch</div></div>", unsafe_allow_html=True)

            st.write("")
            st.subheader("Official Scoring Grid")
            edited_scores = st.data_editor(df_for_calc[["USBC ID", "Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Game 4"]], use_container_width=True)
            if st.button("Save Scores & Recalculate Standings", type="primary"):
                c = get_sqlite_conn()
                for _, r in edited_scores.iterrows():
                    c.execute("UPDATE live_roster SET game_1=?, game_2=?, game_3=?, game_4=? WHERE usbc_id=?", (r["Game 1"], r["Game 2"], r["Game 3"], r["Game 4"], r["USBC ID"]))
                c.commit()
                c.close()
                st.success("Scores saved & standings recalculated!")
                st.rerun()

            st.subheader("Official Standings")
            st.dataframe(standings[["Bowler", "Starting Lane", "Average", "Game 1", "Game 2", "Game 3", "Scratch_Total", "Total_HDCP", "Grand_Total"]], use_container_width=True)
            st.download_button("📄 Download Official PDF Standings", export_standings_pdf(standings, st.session_state.tournament_config, td_name=st.session_state.td_name), "Official_Standings.pdf", "application/pdf", use_container_width=True)

            st.divider()
            st.subheader("🏆 Multi-Squad All-Events Aggregate Leaderboard")
            all_events = compile_all_events_leaderboard(df_for_calc, st.session_state.tournament_config)
            st.dataframe(all_events[["Bowler", "Average", "Total_Games_Bowled", "Scratch_Series", "Total_HDCP", "Grand_Total"]], use_container_width=True)

    # MODULE 4: STEPLADDER FINALS & TOURNAMENT COMPLETION
    elif nav == "4. Stepladder Finals":
        st.markdown("""
        <div class="brand-banner">
            <h1>Championship Stepladder Finals & Tournament Completion</h1>
            <p>Cut-line calculation, tiebreaker resolution, stepladder simulation, and official report generation.</p>
        </div>
        """, unsafe_allow_html=True)

        conn = get_sqlite_conn()
        df_sl = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        df_sl = df_sl.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3", "game_4": "Game 4"})
        standings = compile_standings(df_sl, st.session_state.tournament_config)

        if len(standings) < 5:
            st.warning(f"Stepladder finals require at least 5 bowlers with scores (Current: {len(standings)}).")
        else:
            top_5 = standings.head(5)["Bowler"].tolist()
            def get_sc(name):
                row = standings[standings["Bowler"] == name]
                return int(row.iloc[0]["Grand_Total"]) if not row.empty else 0

            m1_p1, m1_p2 = top_5[3], top_5[4]
            m1_s1, m1_s2 = get_sc(m1_p1), get_sc(m1_p2)
            m1_winner = m1_p1 if m1_s1 >= m1_s2 else m1_p2
            m1_score_str = f"{max(m1_s1, m1_s2)} - {min(m1_s1, m1_s2)}"

            m2_p1 = top_5[2]
            m2_s1, m2_s2 = get_sc(m2_p1), get_sc(m1_winner)
            m2_winner = m2_p1 if m2_s1 >= m2_s2 else m1_winner
            m2_score_str = f"{max(m2_s1, m2_s2)} - {min(m2_s1, m2_s2)}"

            semi_p1 = top_5[1]
            semi_s1, semi_s2 = get_sc(semi_p1), get_sc(m2_winner)
            semi_winner = semi_p1 if semi_s1 >= semi_s2 else m2_winner
            semi_score_str = f"{max(semi_s1, semi_s2)} - {min(semi_s1, semi_s2)}"

            champ_p1 = top_5[0]
            champ_s1, champ_s2 = get_sc(champ_p1), get_sc(semi_winner)
            champ_winner = champ_p1 if champ_s1 >= champ_s2 else semi_winner
            champ_score_str = f"{max(champ_s1, champ_s2)} - {min(champ_s1, champ_s2)}"

            stepladder_summary_dict = {
                "m1_p1": m1_p1, "m1_p2": m1_p2, "m1_winner": m1_winner, "m1_score": m1_score_str,
                "m2_p1": m2_p1, "m2_winner_prev": m1_winner, "m2_winner": m2_winner, "m2_score": m2_score_str,
                "semi_p1": semi_p1, "semi_winner_prev": m2_winner, "semi_winner": semi_winner, "semi_score": semi_score_str,
                "champ_p1": champ_p1, "champ_winner_prev": semi_winner, "champ_score": champ_score_str
            }

            st.markdown(f"<div style='background-color: #10b98120; border: 1.5px solid #10b981; border-radius: 10px; padding: 18px; text-align: center;'><h1 style='color: #f8fafc; margin: 0;'>👑 Champion: {champ_winner}</h1></div>", unsafe_allow_html=True)
            st.write("")

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.markdown("#### 🪵 Seeded Qualifiers")
                for i, name in enumerate(top_5):
                    st.markdown(f"<div class='match-box'><b>#{i+1} Seed:</b> {name} <span style='float:right; color:#38bdf8;'>{get_sc(name)} pins</span></div>", unsafe_allow_html=True)
            with col_s2:
                st.markdown("#### 🪜 Stepladder Advancement")
                st.markdown(f"""
                <div class="match-box" style="font-size: 13.5px;">
                    <div><b>Match 1:</b> {m1_p1} vs {m1_p2} ➔ <b style="color:#34d399;">{m1_winner}</b></div>
                    <div style="margin-top:6px;"><b>Match 2:</b> {m2_p1} vs {m1_winner} ➔ <b style="color:#34d399;">{m2_winner}</b></div>
                    <div style="margin-top:6px;"><b>Semifinal:</b> {semi_p1} vs {m2_winner} ➔ <b style="color:#34d399;">{semi_winner}</b></div>
                    <div style="margin-top:6px;"><b>Championship:</b> {champ_p1} vs {semi_winner} ➔ <b style="color:#34d399;">{champ_winner} Wins</b></div>
                </div>
                """, unsafe_allow_html=True)

            summary_pdf_bytes = export_tournament_summary_pdf(standings, st.session_state.tournament_config, champ_winner, stepladder_summary_dict)
            st.download_button("🖨️ Download Official Summary Report (PDF)", summary_pdf_bytes, "Tournament_Summary.pdf", "application/pdf", use_container_width=True)

            if st.button("📦 Archive Tournament to Cloud & Reset Active State", use_container_width=True):
                encoded_pdf = base64.b64encode(summary_pdf_bytes).decode("utf-8")
                arch_df = fetch_archives_df()
                new_rec = pd.DataFrame([{
                    "tournament_name": st.session_state.tournament_config["name"], "center": st.session_state.tournament_config["center"],
                    "division": st.session_state.tournament_config["division"], "date": datetime.now().strftime("%Y-%m-%d"),
                    "entries": len(df_sl), "champion": champ_winner, "pdf_data": encoded_pdf, "archived_by": st.session_state.td_name
                }])
                write_archives_df(pd.concat([arch_df, new_rec], ignore_index=True))
                c = get_sqlite_conn()
                c.execute("DELETE FROM live_roster")
                c.commit()
                c.close()
                st.success("Tournament archived to Google Sheets!")

    # MODULE 5: BRACKETS & POTS
    elif nav == "5. Side Action: Brackets & Pots 💰":
        t_brk, t_pots = st.tabs(["🌳 8-Bowler Elimination Brackets", "💵 High-Game & Series Side Pots"])
        with t_brk:
            conn = get_sqlite_conn()
            paid_b = pd.read_sql_query("SELECT usbc_id FROM live_roster WHERE paid = 1", conn)["usbc_id"].tolist()
            r_df = pd.read_sql_query("SELECT * FROM live_roster", conn).rename(columns={"usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"})
            conn.close()

            col_bc1, col_bc2 = st.columns(2)
            with col_bc1:
                brk_type = st.selectbox("Bracket Division:", ["Scratch", "Handicap"])
            with col_bc2:
                if st.button("🎲 Generate 8-Bowler Bracket", type="primary", use_container_width=True):
                    if len(paid_b) < 8:
                        st.error("Need at least 8 paid bowlers.")
                    else:
                        st.session_state.brackets.append({"id": f"B-{len(st.session_state.brackets)+1:02d}", "type": brk_type, "fee": 5, "seeds": random.sample(paid_b, 8)})
                        st.success("Bracket seeded!")

            if st.session_state.brackets:
                for brk in st.session_state.brackets:
                    seeds = brk["seeds"]
                    r1_1_b1, r1_1_s1, r1_1_b2, r1_1_s2, w1 = resolve_bracket_match(seeds[0], seeds[7], "Game 1", brk["type"], r_df)
                    r1_2_b1, r1_2_s1, r1_2_b2, r1_2_s2, w2 = resolve_bracket_match(seeds[3], seeds[4], "Game 1", brk["type"], r_df)
                    r1_3_b1, r1_3_s1, r1_3_b2, r1_3_s2, w3 = resolve_bracket_match(seeds[2], seeds[5], "Game 1", brk["type"], r_df)
                    r1_4_b1, r1_4_s1, r1_4_b2, r1_4_s2, w4 = resolve_bracket_match(seeds[1], seeds[6], "Game 1", brk["type"], r_df)

                    r2_1_b1, r2_1_s1, r2_1_b2, r2_1_s2, w_semi1 = resolve_bracket_match(w1, w2, "Game 2", brk["type"], r_df)
                    r2_2_b1, r2_2_s1, r2_2_b2, r2_2_s2, w_semi2 = resolve_bracket_match(w3, w4, "Game 2", brk["type"], r_df)

                    c_b1, c_s1, c_b2, c_s2, champ_w = resolve_bracket_match(w_semi1, w_semi2, "Game 3", brk["type"], r_df)
                    st.markdown(f"<div class='match-box'><h3>Bracket {brk['id']} ({brk['type']}) — Winner: <span style='color:#34d399;'>{c_b1 if champ_w == w_semi1 else c_b2}</span></h3></div>", unsafe_allow_html=True)

        with t_pots:
            st.subheader("High-Game & Series Pots Engine")
            pot_fee = st.number_input("Entry Fee ($):", value=10, min_value=1)
            conn = get_sqlite_conn()
            pot_df = pd.read_sql_query("SELECT * FROM live_roster WHERE paid = 1", conn)
            conn.close()

            if not pot_df.empty:
                pot_df = pot_df.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"})
                pot_total = len(pot_df) * pot_fee
                p_g1, p_g2, p_g3, p_ser = round(pot_total * 0.3, 2), round(pot_total * 0.3, 2), round(pot_total * 0.3, 2), round(pot_total * 0.1, 2)
                cp1, cp2, cp3, cp4 = st.columns(4)
                cp1.metric("Game 1 Pot", f"${p_g1:,.2f}")
                cp2.metric("Game 2 Pot", f"${p_g2:,.2f}")
                cp3.metric("Game 3 Pot", f"${p_g3:,.2f}")
                cp4.metric("Series Pot", f"${p_ser:,.2f}")

    # MODULE 6: FINANCIAL & SMART RECONCILIATION
    elif nav == "6. Financial & SMART Ledger 💵":
        st.markdown("<div class='brand-banner'><h1>Financial Reconciliation & Prize Ledger</h1></div>", unsafe_allow_html=True)
        conn = get_sqlite_conn()
        df_fin = pd.read_sql_query("SELECT * FROM live_roster", conn).rename(columns={"paid": "Paid", "bowler": "Bowler"})
        conn.close()

        fin = calculate_financial_summary(df_fin, st.session_state.tournament_config)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Paid Entries", fin["paid_count"])
        c2.metric("Gross Revenue", f"${fin['gross_revenue']:,.2f}")
        c3.metric("Lineage Owed", f"${fin['total_lineage']:,.2f}")
        c4.metric("Net Prize Pool", f"${fin['net_prize_fund']:,.2f}")

        if "youth" in str(st.session_state.tournament_config.get("division", "")).lower():
            st.divider()
            st.markdown("#### 🎓 USBC Rule 400 SMART Scholarship Submission")
            smart_csv = generate_smart_scholarship_csv(df_fin, fin["net_prize_fund"], st.session_state.tournament_config["name"])
            st.download_button("📄 Download SMART Scholarship Submission (.csv)", smart_csv, "SMART_Submittal.csv", "text/csv", type="primary", use_container_width=True)

    # MODULE 7: AI RULES ARBITER
    elif nav == "7. AI Rules Arbiter":
        st.markdown("<div class='brand-banner'><h1>USBC & Tournament Rules Arbiter</h1></div>", unsafe_allow_html=True)
        col_p1, col_p2 = st.columns(2)
        q_preset = ""
        with col_p1:
            if st.button("Rule 17: Altering Surface Mid-Game", use_container_width=True):
                q_preset = "What is the penalty under Rule 17 for sanding a ball during competition?"
            if st.button("Rule 10: Tardy Bowler Arrival", use_container_width=True):
                q_preset = "What is the procedure under Rule 10 if a bowler arrives in frame 3?"
        with col_p2:
            if st.button("Rule 18: Gripping / Balance Holes", use_container_width=True):
                q_preset = "What does Rule 18 require for gripping holes and balance holes?"
            if st.button("Rule 400: Youth SMART Eligibility", use_container_width=True):
                q_preset = "Can youth bowlers accept cash prizes or participate in adult side pots under Rule 400?"

        dispute_text = st.text_area("Describe the dispute:", value=q_preset)
        if st.button("Generate Official Arbiter Ruling", type="primary") and dispute_text.strip():
            ctx = {"user": st.session_state.td_name, "mode": desk_mode, "screen": "Rules Arbiter", "event_name": st.session_state.tournament_config.get("name"), "center": st.session_state.tournament_config.get("center")}
            arbiter_container = st.empty()
            with arbiter_container.container():
                st.write_stream(stream_prism_ai(dispute_text, ctx, client=ai_client))

    # MODULE 8: PAST TOURNAMENTS ARCHIVE
    elif nav == "8. Past Tournaments Archive 📂":
        st.markdown("<div class='brand-banner'><h1>Historical Tournament Archive</h1></div>", unsafe_allow_html=True)
        arch = fetch_archives_df()
        if arch.empty:
            st.info("No past tournaments archived yet.")
        else:
            for _, r in arch.iterrows():
                st.markdown(f"<div class='match-box'><h3>🏆 {r['tournament_name']} ({r['date']})</h3>Center: <b>{r['center']}</b> | Champion: <b>{r['champion']}</b> | Entries: <b>{r['entries']}</b></div>", unsafe_allow_html=True)

    # MODULE 9: BOARD SOP & STAFF MANUAL
    elif nav == "9. Board SOP & Staff Manual 📖":
        st.markdown("<div class='brand-banner'><h1>Board Standard Operating Procedure (SOP)</h1></div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        c1.download_button("📝 Download Official SOP (.docx for Word)", generate_sop_docx(st.session_state.tournament_config), "SOP.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
        c2.download_button("📄 Download Official SOP (.pdf for Print)", generate_sop_pdf(st.session_state.tournament_config), "SOP.pdf", "application/pdf", use_container_width=True)

    # MODULE 10: TD AUDIT LOG
    elif nav == "10. TD Audit Log":
        st.markdown("<div class='brand-banner'><h1>Official Tournament Audit Log</h1></div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(st.session_state.audit_trail), use_container_width=True)

    # MODULE 11: ADMIN USER MANAGEMENT (ARGON2ID)
    elif "TD User Management" in nav:
        st.markdown("<div class='brand-banner'><h1>Staff & Director Account Management (Argon2id)</h1></div>", unsafe_allow_html=True)
        users = fetch_users_df()
        pending = users[users["status"] == "pending"]

        if not pending.empty:
            st.subheader(f"Pending Approvals ({len(pending)})")
            for _, row in pending.iterrows():
                st.markdown(f"<div class='match-box'><b>{row['name']}</b> ({row['username']}) - {row.get('email', '')}</div>", unsafe_allow_html=True)
                col_a, col_d = st.columns(2)
                if col_a.button(f"Approve {row['username']}", type="primary"):
                    users.loc[users["username"] == row["username"], "status"] = "active"
                    write_users_df(users)
                    notify_user_account_approved(row["email"], row["name"], row["username"])
                    st.success("Approved!")
                    st.rerun()
                if col_d.button(f"Deny {row['username']}"):
                    users = users[users["username"] != row["username"]]
                    write_users_df(users)
                    st.warning("Denied.")
                    st.rerun()

        st.subheader("Active Staff Registry")
        st.dataframe(users[["username", "name", "email", "role", "center_id", "preferred_mode", "status"]], use_container_width=True)
