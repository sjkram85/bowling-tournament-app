"""Active Squad Hub — Live scoring matrix, lane movement, and 8-person bracket desk controls."""

import pandas as pd
import streamlit as st

from modules.auth import current_user
from modules.brackets import generate_eight_person_brackets, score_bracket_round
from modules.constants import CENTERS
from modules.db_state import get_connection, log_desk_action


def _get_active_tournament() -> dict | None:
    conn = get_connection()
    try:
        t_id = st.session_state.get("active_tournament_id")
        if t_id:
            row = conn.execute("SELECT * FROM tournaments WHERE id = ?", (t_id,)).fetchone()
            if row:
                return dict(row)
        row = conn.execute("SELECT * FROM tournaments WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_squad_bowlers(tournament_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, usbc_id, entering_avg, handicap, lane_assignment,
                   lineup_position, is_pacer, is_youth, paid_status, checked_in
            FROM bowlers
            WHERE tournament_id = ?
            ORDER BY lane_assignment ASC, lineup_position ASC
            """,
            (tournament_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_game_scores(tournament_id: int, game_number: int) -> dict[int, dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT bowler_id, scratch_score, hdcp_score, total_score, recorded_by "
            "FROM scores WHERE tournament_id = ? AND game_number = ?",
            (tournament_id, game_number),
        ).fetchall()
        return {r["bowler_id"]: dict(r) for r in rows}
    finally:
        conn.close()


def _save_score(tournament_id: int, bowler_id: int, game_number: int, scratch: int, hdcp: int, user_name: str) -> None:
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
                (tournament_id, bowler_id, game_number, scratch, hdcp, total, user_name),
            )
            log_desk_action(user_name, "td", f"Logged Game {game_number} score {scratch} (HDCP +{hdcp}) for Bowler #{bowler_id}")
    finally:
        conn.close()


def _calculate_lane_movement(starting_lane: int, current_game: int, total_lanes: int) -> int:
    """Calculates cross-lane movement: Even lanes move right 1 pair (+2), Odd lanes move left 1 pair (-2)."""
    if current_game <= 1:
        return starting_lane
    shifts = current_game - 1
    if starting_lane % 2 == 0:
        new_lane = ((starting_lane - 1 + (shifts * 2)) % total_lanes) + 1
    else:
        new_lane = ((starting_lane - 1 - (shifts * 2)) % total_lanes) + 1
    return new_lane


def render_active_squad() -> None:
    st.title("🎳 Active Squad Hub")

    tourney = _get_active_tournament()
    if not tourney:
        st.info("No active squad currently in progress. Start an event from the Intake Gateway.")
        return

    t_id = tourney["id"]
    st.session_state["active_tournament_id"] = t_id
    host_code = tourney["host_center"]
    total_lanes = CENTERS.get(host_code, {}).get("lanes", 24)

    # Top Control Header Bar
    top_col1, top_col2, top_col3 = st.columns([2, 1, 1])
    with top_col1:
        st.subheader(f"{tourney['name']} ({tourney['host_center']})")
        st.caption(f"Format: **{tourney['squad_format']}** | Scoring PIN: **{tourney['pin_verifier']}**")
    with top_col2:
        active_game = st.selectbox(
            "Active Game",
            options=list(range(1, tourney["game_count"] + 1)),
            index=0,
            key="hub_active_game_select",
        )
    with top_col3:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.rerun()

    # Dynamic Cross Lane Movement Banner
    st.markdown(
        f"""
        <div class="ptcc-banner">
            <div>Game {active_game} Movement: Even Lanes Move Right 1 Pair (+2) | Odd Lanes Move Left 1 Pair (-2)</div>
            <small>Host: {CENTERS.get(host_code, {}).get('name', 'Bowling Center')} (Total {total_lanes} Lanes)</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # =========================================================
    # 8-PERSON BRACKET & SIDE POT CONTROLS
    # =========================================================
    with st.expander("🌿 8-Person Bracket Desk Engine", expanded=False):
        b_c1, b_c2, b_c3 = st.columns(3)
        with b_c1:
            if st.button("Generate Handicap Brackets", key="btn_gen_hdcp_b", type="primary", use_container_width=True):
                num_b = generate_eight_person_brackets(t_id, bracket_type="handicap")
                if num_b > 0:
                    st.success(f"Generated {num_b} Handicap 8-Person Brackets!")
                else:
                    st.warning("Need at least 8 paid, non-pacer bowlers to generate an 8-person bracket.")
        with b_c2:
            if st.button("Generate Scratch Brackets", key="btn_gen_scratch_b", use_container_width=True):
                num_s = generate_eight_person_brackets(t_id, bracket_type="scratch")
                if num_s > 0:
                    st.success(f"Generated {num_s} Scratch 8-Person Brackets!")
                else:
                    st.warning("Need at least 8 paid, non-pacer bowlers to generate an 8-person bracket.")
        with b_c3:
            if st.button(f"Advance Round (Game {active_game})", key="btn_adv_b_round", use_container_width=True):
                score_bracket_round(t_id, game_round=active_game)
                st.success(f"Advanced brackets using Game {active_game} scores!")

    # Bowler roster and game scores
    bowlers = _get_squad_bowlers(t_id)
    if not bowlers:
        st.warning("No bowlers registered on the squad roster.")
        return

    scores_map = _get_game_scores(t_id, active_game)

    # =========================================================
    # BIRDS-EYE HEATMAP MATRIX
    # =========================================================
    st.markdown("### 🗺️ Birds-Eye Heatmap: Active Lane Status")
    lane_status_cols = st.columns(6)

    assigned_lanes = sorted(list({b["lane_assignment"] for b in bowlers}))
    for i, lane_num in enumerate(assigned_lanes):
        lane_bowlers = [b for b in bowlers if b["lane_assignment"] == lane_num]
        reported_count = sum(1 for b in lane_bowlers if b["id"] in scores_map)
        all_reported = (reported_count == len(lane_bowlers)) and len(lane_bowlers) > 0

        bg_color = "#064E3B" if all_reported else "#78350F" if reported_count > 0 else "#1E293B"
        border_color = "#10B981" if all_reported else "#F59E0B" if reported_count > 0 else "#334155"
        label = "COMPLETED" if all_reported else f"{reported_count}/{len(lane_bowlers)} ENTERED" if reported_count > 0 else "PENDING"

        col = lane_status_cols[i % 6]
        with col:
            st.markdown(
                f"""
                <div style="background:{bg_color}; border:1px solid {border_color}; border-radius:6px; padding:6px; text-align:center; margin-bottom:8px;">
                    <strong style="color:#F8FAFC; font-size:12px;">Lane {lane_num}</strong><br>
                    <span style="font-size:10px; color:#E2E8F0; font-weight:700;">{label}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # =========================================================
    # DUAL-ROLE DIRECT TD DESK SCORE ENTRY TABLE
    # =========================================================
    st.subheader(f"Direct Desk Score Entry — Game {active_game}")
    st.caption("Enter scratch scores directly from physical recap sheets or review mobile verifier inputs.")

    user = current_user() or {}
    td_name = user.get("display_name", "Tournament Director")

    triage_rows = []
    for b in bowlers:
        b_id = b["id"]
        sc = scores_map.get(b_id, {})
        current_lane = _calculate_lane_movement(b["lane_assignment"], active_game, total_lanes)
        pacer_str = " (PACER)" if b["is_pacer"] else ""
        triage_rows.append({
            "Bowler ID": b_id,
            "Bowler Name": f"{b['name']}{pacer_str}",
            "Start Lane": b["lane_assignment"],
            "Current Lane": current_lane,
            "Entering Avg": b["entering_avg"],
            "HDCP": b["handicap"],
            "Scratch": sc.get("scratch_score", 0),
            "Total Score": sc.get("total_score", 0),
            "Verifier": sc.get("recorded_by", "Pending"),
        })

    df_scores = pd.DataFrame(triage_rows)
    edited_scores = st.data_editor(
        df_scores,
        hide_index=True,
        use_container_width=True,
        key=f"editor_scores_g{active_game}",
        disabled=["Bowler ID", "Bowler Name", "Start Lane", "Current Lane", "Entering Avg", "HDCP", "Total Score", "Verifier"],
        column_config={
            "Scratch": st.column_config.NumberColumn(
                "Scratch Score",
                min_value=0,
                max_value=300,
                step=1,
                required=True,
            )
        },
    )

    if st.button(f"💾 Save Desk Score Adjustments for Game {active_game}", type="primary", use_container_width=True):
        count_updated = 0
        for row in edited_scores.itertuples():
            b_id = row._1  # Bowler ID
            scratch = int(row.Scratch)
            hdcp = int(row.HDCP)
            if scratch > 0:
                _save_score(t_id, b_id, active_game, scratch, hdcp, td_name)
                count_updated += 1
        st.success(f"Successfully recorded and audited {count_updated} scores for Game {active_game}!")
        st.rerun()