"""Floor assistant 10-key mobile scoring pad and AI Overhead OCR photo ingest."""

import streamlit as st
from components.styles import inject_styles
from modules.db_state import get_connection, log_desk_action
from modules.ocr_engine import extract_scores_from_overhead_photo


def _get_active_tournament_for_scoring() -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM tournaments WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_lane_bowlers(tournament_id: int, lane: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, handicap, is_pacer FROM bowlers WHERE tournament_id = ? AND lane_assignment = ? ORDER BY lineup_position",
            (tournament_id, lane),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _record_score(tournament_id: int, bowler_id: int, game_num: int, scratch: int, hdcp: int, verifier_name: str) -> None:
    conn = get_connection()
    total = scratch + hdcp
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, hdcp_score, total_score, recorded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bowler_id, game_number) DO UPDATE SET
                    scratch_score = excluded.scratch_score,
                    hdcp_score = excluded.hdcp_score,
                    total_score = excluded.total_score,
                    recorded_by = excluded.recorded_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (tournament_id, bowler_id, game_num, scratch, hdcp, total, verifier_name),
            )
            log_desk_action(verifier_name, "floor_verifier", f"Entered Game {game_num} score {scratch} (Total {total}) for Bowler #{bowler_id}")
    finally:
        conn.close()


def render_mobile_scoring() -> None:
    inject_styles()
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #1E3A8A 0%, #0F172A 100%); border: 1px solid #3B82F6; border-radius: 12px; padding: 16px; text-align: center; margin-bottom: 16px;">
            <h3 style="color: #F8FAFC; margin: 0 0 4px 0;">📱 Floor Scoring Pad</h3>
            <p style="color: #93C5FD; font-size: 12px; margin: 0;">Verified 10-Key Score Entry & Overhead Camera Snap</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tourney = _get_active_tournament_for_scoring()
    if not tourney:
        st.warning("No active tournament available for scoring.")
        return

    # PIN Authentication
    if not st.session_state.get("scorer_authenticated"):
        with st.container(border=True):
            st.subheader("Floor Assistant Access")
            verifier = st.text_input("Your Name / Identifier", placeholder="e.g. Mike R.")
            entered_pin = st.text_input("4-Digit Scoring PIN", type="password", max_chars=4)
            if st.button("Unlock Scoring Pad", type="primary", use_container_width=True):
                if entered_pin == tourney["pin_verifier"] and verifier.strip():
                    st.session_state["scorer_authenticated"] = True
                    st.session_state["verifier_name"] = verifier.strip()
                    st.rerun()
                else:
                    st.error("Invalid PIN or missing Verifier Name.")
        return

    verifier_name = st.session_state.get("verifier_name", "Floor Verifier")
    st.caption(f"Authenticated as: **{verifier_name}** | Tournament: **{tourney['name']}**")

    tab_manual, tab_camera = st.tabs(["🔢 10-Key Manual Input", "📷 AI Overhead Camera OCR"])

    # --- TAB 1: 10-KEY MANUAL PAD ---
    with tab_manual:
        col_lane, col_game = st.columns(2)
        lane = col_lane.number_input("Lane Number", min_value=1, max_value=40, value=1, step=1)
        game = col_game.slider("Game Number", min_value=1, max_value=tourney["game_count"], value=1)

        bowlers = _get_lane_bowlers(tourney["id"], int(lane))
        if not bowlers:
            st.info(f"No bowlers assigned to Lane {lane}.")
        else:
            with st.form(f"score_form_lane_{lane}_gm_{game}"):
                for b in bowlers:
                    pacer_tag = " (PACER)" if b["is_pacer"] else ""
                    st.markdown(f"**{b['name']}**{pacer_tag} — HDCP: `+{b['handicap']}`")
                    st.number_input(
                        f"Scratch Score for {b['name']}",
                        min_value=0,
                        max_value=300,
                        value=0,
                        step=1,
                        key=f"scratch_{b['id']}_g{game}",
                    )
                submitted = st.form_submit_button("Submit Lane Scores", type="primary", use_container_width=True)
                if submitted:
                    for b in bowlers:
                        val = st.session_state.get(f"scratch_{b['id']}_g{game}", 0)
                        if val > 0:
                            _record_score(tourney["id"], b["id"], game, val, b["handicap"], verifier_name)
                    st.success(f"Scores for Lane {lane} Game {game} recorded!")

    # --- TAB 2: AI OVERHEAD OCR CAMERA SNAP ---
    with tab_camera:
        st.subheader("Overhead Monitor Photo Ingest")
        st.caption("Take a photo of the lane monitor. Prism A.I will read the scores and queue them for verification.")

        uploaded_img = st.camera_input("Snap Monitor Screen")
        if uploaded_img is not None:
            if st.button("Transcribe Monitor via Gemini Vision", type="primary", use_container_width=True):
                with st.spinner("Prism A.I Vision reading overhead frames..."):
                    result = extract_scores_from_overhead_photo(uploaded_img.getvalue())
                    if result["status"] == "error":
                        st.error(result["message"])
                    else:
                        st.success("Scores Extracted Successfully!")
                        for item in result["extracted_data"]:
                            st.write(f"🎳 **{item.get('name')}**: Score **{item.get('game_score')}**")