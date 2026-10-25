"""Active Squad Hub — Live scoring matrix, lane movement, check-in status, quick QR codes, and 8-person bracket desk controls."""

import base64
import io
import pandas as pd
import qrcode
import streamlit as st

from modules.auth import current_user
from modules.brackets import event_uses_brackets, generate_eight_person_brackets
from modules.db_state import get_connection, log_desk_action
from modules.events import scoring_is_open
from modules.standings import current_lane, event_lane_pattern
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
    from modules.standings import get_tournament
    t_id = st.session_state.get("active_tournament_id")
    if t_id:
        row = get_tournament(t_id)
        if row:
            return row
    # No choice on this device: only fall back when exactly one event is active.
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM tournaments WHERE status = 'active'").fetchall()
        return dict(rows[0]) if len(rows) == 1 else None
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


def _matrix_snapshot(tournament_id: int, game_number: int) -> tuple[dict[int, dict], int]:
    """Scores for one game, plus how many bowlers have finished every game. One round trip.

    The lane heatmap and the score grid share this for a single page run. A later
    fragment poll is a new run, so it still reads fresh scores.
    """
    from modules.run_memo import memo
    return memo(("desk-matrix", int(tournament_id), int(game_number)),
                lambda: _matrix_snapshot_query(tournament_id, game_number))


def _matrix_snapshot_query(tournament_id: int, game_number: int) -> tuple[dict[int, dict], int]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT 'score' AS kind, bowler_id, scratch_score, total_score, recorded_by, NULL AS done
            FROM scores WHERE tournament_id = ? AND game_number = ?
            UNION ALL
            SELECT 'done', NULL, NULL, NULL, NULL, (
                SELECT COUNT(*) FROM (
                    SELECT b.id FROM bowlers b
                    JOIN scores s ON b.id = s.bowler_id
                    WHERE b.tournament_id = ? AND b.is_pacer = 0 AND s.scratch_score > 0
                    GROUP BY b.id
                    HAVING COUNT(DISTINCT s.game_number) >= (SELECT game_count FROM tournaments WHERE id = ?)
                )
            )
            """,
            (tournament_id, game_number, tournament_id, tournament_id),
        ).fetchall()
    finally:
        conn.close()
    scores: dict[int, dict] = {}
    done = 0
    for r in rows:
        if r["kind"] == "score":
            scores[r["bowler_id"]] = {
                "bowler_id": r["bowler_id"], "scratch_score": r["scratch_score"],
                "total_score": r["total_score"], "recorded_by": r["recorded_by"],
            }
        else:
            done = int(r["done"] or 0)
    return scores, done


def _save_score(tournament_id: int, bowler_id: int, game_number: int, scratch: int, hdcp: int, user_name: str) -> int | None:
    """Write one scratch score onto the game the desk has selected. Refuses a frozen event."""
    if not scoring_is_open(tournament_id):
        return None
    from modules import score_history
    before = score_history.current(tournament_id, bowler_id, game_number)
    conn = get_connection()
    total = scratch + hdcp
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score, recorded_by,
                                    verified, verified_by, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tournament_id, bowler_id, game_number) DO UPDATE SET
                    scratch_score = excluded.scratch_score,
                    total_score = excluded.total_score,
                    recorded_by = excluded.recorded_by,
                    verified = 1, verified_by = excluded.verified_by, verified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (tournament_id, bowler_id, game_number, scratch, total, user_name, user_name),
            )
    finally:
        conn.close()
    log_desk_action(user_name, "td", f"Logged Game {game_number} score {scratch} (HDCP +{hdcp}) for Bowler #{bowler_id}")
    return score_history.log_change(tournament_id, bowler_id, game_number, before, scratch, "desk", user_name)


def _lane_now(bowler: dict, active_game: int, tourney: dict, bowlers: list[dict]) -> int:
    """Same lane the floor phone shows for this bowler and game."""
    return current_lane(bowler.get("lane_assignment") or 0, active_game, tourney, bowlers)


@st.fragment(run_every="8s")
def _render_lane_heatmap(t_id: int, active_game: int, tourney: dict, bowlers: list[dict]) -> None:
    """Auto-polling lane status. Score entry is outside this fragment so a save uses the selected game."""
    scores_map, _done = _matrix_snapshot(t_id, active_game)

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

    pattern = event_lane_pattern(tourney)
    if pattern == "same_pair":
        st.caption(f"Game {active_game}: same pair — bowlers stay on the assigned lane. Floor phones use this lane.")
    else:
        st.caption(f"Game {active_game}: lane after movement. Floor phones list this same lane.")
    lane_status_cols = st.columns(6)

    lane_of = {b["id"]: _lane_now(b, active_game, tourney, bowlers) for b in bowlers}
    assigned_lanes = sorted({lane for lane in lane_of.values() if lane})
    for i, lane_num in enumerate(assigned_lanes):
        lane_bowlers = [b for b in bowlers if lane_of[b["id"]] == lane_num]
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


def _render_score_entry(t_id: int, active_game: int, tourney: dict, bowlers: list[dict], td_name: str, tourney_game_count: int) -> None:
    """Desk score grid. Saves only to active_game — not to a fragment-captured game."""
    scores_map, fully_completed_count = _matrix_snapshot(t_id, active_game)
    st.subheader(f"Direct Desk Score Entry — Game {active_game}")
    st.caption("Enter scratch scores from the recap sheet. Save writes this game only, on the lane shown (same as the floor phone).")

    triage_rows = []
    for b in bowlers:
        b_id = b["id"]
        sc = scores_map.get(b_id, {})
        lane_shown = _lane_now(b, active_game, tourney, bowlers)
        pacer_str = " (PACER)" if b["is_pacer"] else ""
        triage_rows.append({
            "Bowler ID": b_id,
            "Bowler Name": f"{b['name']}{pacer_str}",
            "Start Lane": b["lane_assignment"],
            "Current Lane": lane_shown,
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
        if not scoring_is_open(t_id):
            st.error("This event is frozen. Scores were not changed. An admin can reopen it from Finals Closeout.")
        else:
            count_updated = 0
            changed = []
            for row in edited_scores.itertuples():
                b_id = row._1  # Bowler ID
                scratch = int(row.Scratch)
                hdcp = int(row.HDCP)
                if scratch > 0:
                    hid = _save_score(t_id, b_id, int(active_game), scratch, hdcp, td_name)
                    if hid:
                        changed.append(hid)
                    count_updated += 1
            st.session_state[f"desk_undo_{t_id}"] = changed
            st.success(f"Successfully recorded and audited {count_updated} scores for Game {active_game}!")
            st.rerun()

    from components.undo_box import saved_undo_button
    saved_undo_button(f"desk_undo_{t_id}", td_name)

    # =========================================================
    # SQUAD COMPLETION & FINALS CLOSEOUT CALLOUT
    # =========================================================
    active_field_count = sum(1 for b in bowlers if not b.get("is_pacer"))

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

    # Top: event bar (name, game, brackets), then the main job: Needs verifying.
    top_col1, top_col2, top_col3 = st.columns([2, 1, 1])
    with top_col1:
        st.subheader(f"{tourney['name']} ({tourney['host_center']})")
        st.caption(f"Format: **{tourney['squad_format']}**")
    with top_col2:
        game_options = list(range(1, int(tourney["game_count"]) + 1))
        game_key = f"hub_active_game_{t_id}"
        # Game 1 until the TD picks another. Do not open on the last game.
        if game_key not in st.session_state or st.session_state[game_key] not in game_options:
            st.session_state[game_key] = game_options[0]
        active_game = st.selectbox("Active Game", options=game_options, key=game_key)
    with top_col3:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if event_uses_brackets(tourney):
            if st.button("🎲 Manage Brackets", use_container_width=True):
                made = generate_eight_person_brackets(t_id)
                if made:
                    st.success(f"Brackets verified/generated ({made}).")
                else:
                    st.warning("Not enough bowlers for an 8-person bracket.")
        else:
            st.caption("No brackets for this event.")

    from components.td_team_panel import render_td_team_panel
    render_td_team_panel(t_id)  # 'Needs verifying (N)' + chat + TDs on duty line

    from components.rolloff_box import render_rolloff_box
    render_rolloff_box(t_id)  # only shows when a roll-off is needed
    from components.undo_box import render_undo_box
    _u = current_user() or {}
    render_undo_box(t_id, _u.get("display_name") or _u.get("username") or "TD")

    with st.expander("⚙️ Event setup (floor phones, kiosk)"):
        score_url = f"{_get_base_url().rstrip('/')}/?mode=score&t={t_id}"
        st.markdown(f"**📱 Floor-phone scoring** — Scoring PIN: **{tourney['pin_verifier']}**")
        st.caption("Floor helpers scan this code with their phone, then type the PIN.")
        st.code(score_url, language=None)
        st.markdown(f"<img src='{_generate_qr_base64(score_url)}' width='160'>", unsafe_allow_html=True)
        st.markdown("---")
        kiosk_url = f"{_get_base_url().rstrip('/')}/?mode=kiosk&t={t_id}"
        st.markdown("**📺 Lobby kiosk**")
        st.caption("Open this link on the lobby laptop, then press F11 for full screen.")
        st.code(kiosk_url, language=None)
        st.link_button("Open kiosk in a new tab", kiosk_url)
        st.markdown("---")
        _render_logo_setup(t_id, tourney)

    from modules.auth import is_admin
    if is_admin():
        st.caption("💾 After each squad, download a backup (Backup & Restore in the sidebar).")

    st.markdown("---")
    bowlers = _get_squad_bowlers(t_id)
    if not bowlers:
        st.warning("No bowlers loaded on this squad roster yet. Go to the Intake Gateway to import competitors.")
        return

    td_name = (current_user() or {}).get("display_name") or "Tournament Director"
    _render_lane_heatmap(t_id, int(active_game), tourney, bowlers)
    _render_score_entry(t_id, int(active_game), tourney, bowlers, td_name, tourney["game_count"])

def _render_logo_setup(t_id: int, tourney) -> None:
    """Optional logos for the certified PDF and the kiosk. Events without them look the same as before."""
    from modules.event_logos import get_logos, partner_heading, set_logo, set_partner_name, validate_image
    st.markdown("**🖼️ Logos (optional)** — shown on the certified results PDF and the lobby kiosk")
    logos = get_logos(t_id)
    partner = st.text_input("Host / partner name", value=(dict(tourney).get("partner_name") or ""),
                            key=f"partner_name_{t_id}", placeholder="e.g. Forest Hill Lanes")
    if partner.strip():
        st.caption(partner_heading(partner.strip()))
    labels = {"partner": "Host/partner logo (dark letters, for the white PDF)",
              "partner_kiosk": "Host/partner logo for the dark kiosk (light letters, optional)",
              "event": "Event logo (under the title)"}
    for kind, label in labels.items():
        c1, c2 = st.columns([3, 1])
        with c1:
            up = st.file_uploader(label, type=["png", "jpg", "jpeg"], key=f"logo_{kind}_{t_id}")
            if up is not None:
                try:
                    set_logo(t_id, kind, validate_image(up.getvalue()))
                    st.success("Logo saved.")
                except ValueError as e:
                    st.error(str(e))
        with c2:
            if logos.get(kind):
                st.image(logos[kind], width=120)
                if st.button("Remove", key=f"rm_logo_{kind}_{t_id}"):
                    set_logo(t_id, kind, None)
                    st.rerun()
    if st.button("Save partner name", key=f"save_partner_{t_id}"):
        set_partner_name(t_id, partner)
        st.success("Saved.")
