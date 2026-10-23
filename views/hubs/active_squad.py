"""Active Squad Hub — Live scoring matrix, lane movement, check-in status, quick QR codes, and 8-person bracket desk controls."""

import base64
import io
import pandas as pd
import qrcode
import streamlit as st

from modules.auth import current_user
from modules.brackets import generate_eight_person_brackets, score_bracket_round
from modules.constants import CENTERS
from modules.db_state import get_connection, log_desk_action
from views.hubs.finals_close import render_finals_close
from modules.settings import get_secret


def _get_base_url() -> str:
    """Dynamically determine current host environment base URL."""
    return get_secret("APP_BASE_URL", "https://chusbc-desk.streamlit.app")


def _generate_qr_base64(url: str) -> str:
    """Generate high-contrast QR code as a base64 data URI string."""
    qr = qrcode.QRCode(box_size=5, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"


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
                   lineup_position, is_pacer, is_youth, paid_status, checked_in, checked_in_at
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
            """
            SELECT bowler_id, scratch_score, total_score, recorded_by 
            FROM scores WHERE tournament_id = ? AND game_number = ?
            """,
            (tournament_id, game_number),
        ).fetchall()
        return {r["bowler_id"]: dict(r) for r in rows}
    finally:
        conn.close()


def _get_total_games_completed_count(tournament_id: int) -> int:
    """Returns how many bowlers have completed all required games."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) as count FROM (
                SELECT b.id FROM bowlers b
                JOIN scores s ON b.id = s.bowler_id
                WHERE b.tournament_id = ? AND b.is_pacer = 0 AND s.scratch_score > 0
                GROUP BY b.id
                HAVING COUNT(DISTINCT s.game_number) >= (SELECT game_count FROM tournaments WHERE id = ?)
            )
            """,
            (tournament_id, tournament_id),
        ).fetchone()
        return row["count"] if row else 0
    finally:
        conn.close()


def _save_score(tournament_id: int, bowler_id: int, game_number: int, scratch: int, hdcp: int, user_name: str) -> None:
    conn = get_connection()
    total = scratch + hdcp
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score, recorded_by)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tournament_id, bowler_id, game_number) DO UPDATE SET
                    scratch_score = excluded.scratch_score,
                    total_score = excluded.total_score,
                    recorded_by = excluded.recorded_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (tournament_id, bowler_id, game_number, scratch, total, user_name),
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


@st.fragment(run_every="8s")
def _render_live_scoring_matrix(t_id: int, active_game: int, total_lanes: int, bowlers: list[dict], td_name: str, tourney_game_count: int) -> None:
    """Auto-polling fragment executing every 8 seconds to reflect floor submissions in real time."""
    scores_map = _get_game_scores(t_id, active_game)

    # =========================================================
    # BIRDS-EYE HEATMAP MATRIX
    # =========================================================
    col_title, col_pulse = st.columns([3, 1])
    with col_title:
        st.markdown("### 🗺️ Birds-Eye Heatmap: Active Lane Scoring Status")
    with col_pulse:
        st.markdown(
            "<div style='text-align: right; padding-top: 10px;'><span style='color: #10B981; font-weight: 700; font-size: 11px;'>● LIVE AUTO-POLLING (8s)</span></div>",
            unsafe_allow_html=True,
        )

    st.caption("Displays score reporting progress across active lanes for the selected game.")
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

    # =========================================================
    # SQUAD COMPLETION & FINALS CLOSEOUT CALLOUT
    # =========================================================
    active_field_count = sum(1 for b in bowlers if not b.get("is_pacer"))
    fully_completed_count = _get_total_games_completed_count(t_id)

    if fully_completed_count >= active_field_count and active_field_count > 0:
        st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(
                f"""
                <div style="background: linear-gradient(135deg, #064E3B 0%, #0F172A 100%); border: 1px solid #10B981; border-radius: 10px; padding: 18px 20px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div>
                        <span style="background: #10B981; color: #022C22; font-size: 11px; font-weight: 800; padding: 3px 10px; border-radius: 999px; text-transform: uppercase;">
                            QUALIFYING ROUND COMPLETE
                        </span>
                        <h3 style="color: #ECFDF5; margin: 8px 0 2px 0;">🎉 All {active_field_count} Bowlers Finished ({tourney_game_count} Games)</h3>
                        <p style="color: #6EE7B7; font-size: 13px; margin: 0;">Scores are fully tallied. Advance to Finals Closeout to seed stepladders, verify SMART payouts, and seal the tournament.</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("🏆 Advance to Finals Closeout & Payouts ➔", type="primary", use_container_width=True):
                st.switch_page(st.Page(render_finals_close, url_path="finals"))


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
            index=min(2, tourney["game_count"] - 1),
            key="hub_active_game_select",
        )
    with top_col3:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("🎲 Manage Brackets", use_container_width=True):
            generate_eight_person_brackets(t_id)
            st.success("Brackets verified/generated!")

    st.markdown("---")
    bowlers = _get_squad_bowlers(t_id)
    if not bowlers:
        st.warning("No bowlers loaded on this squad roster yet. Go to the Intake Gateway to import competitors.")
        return

    _render_live_scoring_matrix(t_id, active_game, total_lanes, bowlers, "Tournament Director", tourney["game_count"])