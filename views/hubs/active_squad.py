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


def _get_base_url() -> str:
    """Dynamically determine current host environment base URL."""
    return st.secrets.get("APP_BASE_URL", "https://chusbc-desk.streamlit.app")


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
            "SELECT bowler_id, scratch_score, hdcp_score, total_score, recorded_by "
            "FROM scores WHERE tournament_id = ? AND game_number = ?",
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
                st.switch_page("views/hubs/finals_close.py")


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
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.rerun()

    # Dynamic Cross Lane Movement Banner
    st.markdown(
        f"""
        <div class="ptcc-banner" style="background:#1E293B; border:1px solid #334155; border-radius:8px; padding:12px 16px; margin-bottom:16px;">
            <div style="font-weight:700; color:#F8FAFC;">Game {active_game} Movement: Even Lanes Move Right 1 Pair (+2) | Odd Lanes Move Left 1 Pair (-2)</div>
            <small style="color:#94A3B8;">Host: {CENTERS.get(host_code, {}).get('name', 'Bowling Center')} (Total {total_lanes} Lanes)</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

    bowlers = _get_squad_bowlers(t_id)
    if not bowlers:
        st.warning("No bowlers registered on the squad roster.")
        return

    # =========================================================
    # ROSTER CHECK-IN & PADDOCK GATE CLEARANCE STATUS
    # =========================================================
    total_bowlers = len(bowlers)
    checked_in_count = sum(1 for b in bowlers if b.get("checked_in"))
    unchecked_bowlers = [b for b in bowlers if not b.get("checked_in")]

    if checked_in_count == total_bowlers and total_bowlers > 0:
        st.markdown(
            f"""
            <div style="background-color: #064E3B; border: 1px solid #10B981; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="color: #ECFDF5; font-size: 14px; font-weight: 800;">
                        ✅ Paddock Gate Cleared: All {total_bowlers} Bowlers Checked In
                    </span>
                    <div style="color: #6EE7B7; font-size: 12px; margin-top: 2px;">
                        All competitors confirmed on lane assignments and cleared for tournament competition.
                    </div>
                </div>
                <span style="background: #10B981; color: #022C22; font-size: 11px; font-weight: 800; padding: 4px 10px; border-radius: 4px; letter-spacing: 0.5px;">
                    100% ARRIVED
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        pct = int((checked_in_count / total_bowlers) * 100) if total_bowlers > 0 else 0
        st.markdown(
            f"""
            <div style="background-color: #451A03; border: 1px solid #F59E0B; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="color: #FEF3C7; font-size: 14px; font-weight: 800;">
                        ⚠️ Paddock Gate Active: {checked_in_count} of {total_bowlers} Checked In ({len(unchecked_bowlers)} Awaiting Arrival)
                    </span>
                    <div style="color: #FCD34D; font-size: 12px; margin-top: 2px;">
                        Bowlers may self-check-in at <code>?mode=bowler&action=checkin</code> or at the tournament desk.
                    </div>
                </div>
                <span style="background: #F59E0B; color: #451A03; font-size: 11px; font-weight: 800; padding: 4px 10px; border-radius: 4px; letter-spacing: 0.5px;">
                    {pct}% CHECKED IN
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.expander(f"👀 View Unchecked Bowlers ({len(unchecked_bowlers)})", expanded=False):
            u_cols = st.columns(2)
            for idx, ub in enumerate(unchecked_bowlers):
                col_target = u_cols[idx % 2]
                paid_label = "PAID" if ub.get("paid_status") == "paid" else "UNPAID BALANCE"
                paid_color = "#34D399" if ub.get("paid_status") == "paid" else "#F87171"
                with col_target:
                    st.markdown(
                        f"""
                        <div style="background:#0F172A; border:1px solid #334155; border-radius:6px; padding:8px 12px; margin-bottom:6px;">
                            <strong style="color:#F8FAFC;">{ub['name']}</strong> &middot; Starting Lane <b>{ub['lane_assignment']}</b><br>
                            <span style="font-size:11px; color:{paid_color}; font-weight:700;">{paid_label}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

    # =========================================================
    # QUICK QR ACCESS DRAWER (LIVE SCORER & BOWLER PORTAL)
    # =========================================================
    with st.expander("📱 Quick Scan: Floor Scorer Pad & Live Bowler Standings QR", expanded=False):
        base_url = _get_base_url()
        scorer_url = f"{base_url}/?mode=score"
        portal_url = f"{base_url}/?mode=bowler"

        b64_scorer = _generate_qr_base64(scorer_url)
        b64_portal = _generate_qr_base64(portal_url)

        _, qr_col1, qr_col2, _ = st.columns([1, 2, 2, 1], gap="medium")

        with qr_col1:
            st.markdown(
                f"""
                <div style="background: #0F172A; border: 1px solid #334155; border-radius: 10px; padding: 20px 16px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);">
                    <span style="background: #1E3A8A; color: #93C5FD; font-size: 11px; font-weight: 800; padding: 2px 10px; border-radius: 4px; letter-spacing: 0.5px;">
                        FLOOR SCORING PAD
                    </span>
                    <h4 style="color: #F8FAFC; margin: 10px 0 2px 0;">📱 Mobile Scorer</h4>
                    <p style="color: #10B981; font-weight: 700; font-size: 13px; margin: 0 0 14px 0;">🔑 PIN: {tourney['pin_verifier']}</p>
                    <div style="background: #FFFFFF; padding: 8px; border-radius: 8px; display: flex; align-items: center; justify-content: center; margin-bottom: 12px;">
                        <img src="{b64_scorer}" width="160" height="160" style="display: block; margin: 0 auto;" />
                    </div>
                    <span style="font-size: 12px; color: #94A3B8;">Floor Assistant 10-Key Input</span>
                    <a href="{scorer_url}" target="_blank" style="margin-top: 8px; color: #38BDF8; font-size: 13px; font-weight: 600; text-decoration: none;">Open Scorer Tab ↗</a>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with qr_col2:
            st.markdown(
                f"""
                <div style="background: #0F172A; border: 1px solid #334155; border-radius: 10px; padding: 20px 16px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);">
                    <span style="background: #0284C7; color: #BAE6FD; font-size: 11px; font-weight: 800; padding: 2px 10px; border-radius: 4px; letter-spacing: 0.5px;">
                        PUBLIC STANDINGS
                    </span>
                    <h4 style="color: #F8FAFC; margin: 10px 0 2px 0;">📊 Bowler Portal</h4>
                    <p style="color: #94A3B8; font-size: 13px; margin: 0 0 14px 0;">Live standings, cut line & brackets</p>
                    <div style="background: #FFFFFF; padding: 8px; border-radius: 8px; display: flex; align-items: center; justify-content: center; margin-bottom: 12px;">
                        <img src="{b64_portal}" width="160" height="160" style="display: block; margin: 0 auto;" />
                    </div>
                    <span style="font-size: 12px; color: #94A3B8;">Bowler Live Scoreboard</span>
                    <a href="{portal_url}" target="_blank" style="margin-top: 8px; color: #38BDF8; font-size: 13px; font-weight: 600; text-decoration: none;">Open Portal Tab ↗</a>
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

    user = current_user() or {}
    td_name = user.get("display_name", "Tournament Director")
    _render_live_scoring_matrix(t_id, active_game, total_lanes, bowlers, td_name, tourney["game_count"])