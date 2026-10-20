import time
import pandas as pd
import streamlit as st
from engine_support import (
    read_kiosk_state, generate_qr_image, parse_active_pairs, 
    get_bowler_lane_for_game, hash_secret, extract_scores_from_overhead_photo,
    compile_standings
)

def handle_public_modes(mode: str, fetch_active_tournament_state, write_active_tournament_state, log_audit_event, ai_client):
    """Handles specialized standalone query routes like ?mode=kiosk, ?mode=display_tv, etc."""
    
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
