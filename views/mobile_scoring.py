"""Floor assistant 10-key mobile scoring pad and AI Overhead OCR photo ingest."""

import streamlit as st
from components.styles import inject_styles
from modules.constants import CENTERS
from modules.db_state import get_connection, log_desk_action
from modules.ocr_engine import extract_scores_from_overhead_photo
from modules.settings import ai_available, AI_OFF_MESSAGE


def _get_active_tournament_for_scoring() -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM tournaments WHERE status = 'active' ORDER BY COALESCE(is_practice, 0) ASC, id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_active_squad_lanes(tournament_id: int) -> list[int]:
    """Retrieve distinct lanes currently in play for this tournament."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT lane_assignment FROM bowlers WHERE tournament_id = ? AND lane_assignment IS NOT NULL ORDER BY lane_assignment ASC",
            (tournament_id,),
        ).fetchall()
        return [r["lane_assignment"] for r in rows if r["lane_assignment"]]
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


def _get_existing_lane_scores(tournament_id: int, game_num: int) -> dict[int, dict]:
    """Retrieve any existing recorded scores for this game."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT bowler_id, scratch_score, hdcp_score, total_score, recorded_by FROM scores "
            "WHERE tournament_id = ? AND game_number = ?",
            (tournament_id, game_num),
        ).fetchall()
        return {r["bowler_id"]: dict(r) for r in rows}
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
                ON CONFLICT(tournament_id, bowler_id, game_number) DO UPDATE SET
                    scratch_score = excluded.scratch_score,
                    hdcp_score = excluded.hdcp_score,
                    total_score = excluded.total_score,
                    recorded_by = excluded.recorded_by,
                    verified = 0, verified_by = NULL, verified_at = NULL,
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

    # Authentication Gate
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

    # Header status badge
    st.markdown(
        f"""
        <div style="background:#0F172A; border:1px solid #334155; border-radius:8px; padding:10px 14px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="color:#F8FAFC; font-weight:700; font-size:13px;">👤 {verifier_name}</span>
                <span style="color:#94A3B8; font-size:12px; margin-left:8px;">&bull; {tourney['name']}</span>
            </div>
            <span style="background:#1E3A8A; color:#93C5FD; font-size:10px; font-weight:800; padding:2px 8px; border-radius:4px;">
                PIN VERIFIED
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_manual, tab_camera = st.tabs(["🔢 10-Key Manual Input", "📸 AI Overhead Camera OCR"])

    # Determine selectable lanes from active roster
    active_lanes = _get_active_squad_lanes(tourney["id"])
    if not active_lanes:
        host_code = tourney.get("host_center", "FHL")
        max_lanes = CENTERS.get(host_code, {}).get("lanes", 40)
        active_lanes = list(range(1, max_lanes + 1))

    # --- TAB 1: 10-KEY MANUAL PAD ---
    with tab_manual:
        col_lane, col_game = st.columns([1, 1], gap="small")
        with col_lane:
            if len(active_lanes) <= 12:
                lane = st.radio(
                    "Select Lane",
                    options=active_lanes,
                    format_func=lambda l: f"Lane {l}",
                    horizontal=True,
                    index=0,
                    key="mobile_lane_radio",
                )
            else:
                lane = st.selectbox("Select Lane", options=active_lanes, index=0)

        with col_game:
            game_options = list(range(1, tourney["game_count"] + 1))
            game = st.radio(
                "Select Game",
                options=game_options,
                format_func=lambda g: f"Game {g}",
                horizontal=True,
                index=0,
                key="mobile_game_radio",
            )

        bowlers = _get_lane_bowlers(tourney["id"], int(lane))
        existing_scores = _get_existing_lane_scores(tourney["id"], game)

        if not bowlers:
            st.info(f"No bowlers assigned to Lane {lane}.")
        else:
            with st.form(f"score_form_lane_{lane}_gm_{game}"):
                all_recorded = True
                for b in bowlers:
                    pacer_tag = " (PACER)" if b["is_pacer"] else ""
                    b_id = b["id"]
                    prev_score = existing_scores.get(b_id, {})
                    default_scratch = prev_score.get("scratch_score", 0)

                    if default_scratch == 0:
                        all_recorded = False

                    st.markdown(f"**{b['name']}**{pacer_tag} — HDCP: `+{b['handicap']}`")
                    if default_scratch > 0:
                        st.caption(f"✅ Current Score: **{default_scratch}** (HDCP Total: **{prev_score.get('total_score')}**) &middot; By: {prev_score.get('recorded_by', 'Desk')}")

                    st.number_input(
                        f"Scratch Score for {b['name']}",
                        min_value=0,
                        max_value=300,
                        value=default_scratch,
                        step=1,
                        key=f"scratch_{b_id}_g{game}",
                    )

                btn_label = f"Update Lane {lane} Game {game} Scores" if all_recorded else f"Submit Lane {lane} Game {game} Scores"
                submitted = st.form_submit_button(btn_label, type="primary", use_container_width=True)
                if submitted:
                    for b in bowlers:
                        val = st.session_state.get(f"scratch_{b['id']}_g{game}", 0)
                        if val > 0:
                            _record_score(tourney["id"], b["id"], game, val, b["handicap"], verifier_name)
                    st.success(f"Scores for Lane {lane} Game {game} recorded!")
                    st.rerun()

    # --- TAB 2: AI OVERHEAD OCR CAMERA SNAP ---
    with tab_camera:
        st.subheader("Overhead Monitor Photo Ingest")
        st.caption("Take a photo of the lane monitor. Prism A.I will read the scores and queue them for verification.")

        if not ai_available():
            st.info(AI_OFF_MESSAGE + " Please use the 10-Key Manual Input tab.")
        uploaded_img = st.camera_input("Snap Monitor Screen", disabled=not ai_available())
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