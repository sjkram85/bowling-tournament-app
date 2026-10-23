"""Intake Gateway — Squad initialization, roster import, manual entry, and concourse check-in station."""

import base64
import io
import qrcode
import streamlit as st

from modules.auth import current_user
from modules.constants import CENTERS, HOST_CENTERS
from modules.db_state import get_connection, log_desk_action


def _get_base_url() -> str:
    """Dynamically determine current host environment base URL."""
    return st.secrets.get("APP_BASE_URL", "https://chusbc-desk.streamlit.app")


def _generate_qr_base64(url: str) -> str:
    """Generate high-contrast QR code as a base64 encoded PNG string."""
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


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


def render_intake_gateway() -> None:
    st.title("📥 Intake Gateway & Squad Roster Hub")
    user = current_user() or {}
    td_name = user.get("display_name") or "Tournament Director"

    active_tourney = _get_active_tournament()

    if not active_tourney:
        st.info("No active tournament squad is loaded. Create a new event or squad below.")
        with st.form("create_tournament_form"):
            t_name = st.text_input("Tournament Name", value="CHUSBC Championship Squad")
            center_keys = list(CENTERS.keys())
            h_center = st.selectbox("Host Center", center_keys, format_func=lambda k: CENTERS[k]["name"])
            s_format = st.selectbox("Squad Format", ["Singles", "Doubles", "Team", "Baker"])
            g_count = st.number_input("Game Count", min_value=1, max_value=12, value=3)
            pin = st.text_input("Floor Scorer PIN", value="6199", max_chars=8)

            submitted = st.form_submit_button("🚀 Initialize Squad & Unlock Intake", type="primary")
            if submitted:
                conn = get_connection()
                try:
                    with conn:
                        cur = conn.execute(
                            """
                            INSERT INTO tournaments (name, host_center, squad_format, game_count, pin_verifier, status)
                            VALUES (?, ?, ?, ?, ?, 'active')
                            """,
                            (t_name, h_center, s_format, g_count, pin),
                        )
                        new_id = cur.lastrowid
                    st.session_state["active_tournament_id"] = new_id
                    log_desk_action(td_name, "td", f"Created and initialized tournament squad #{new_id} '{t_name}'")
                    st.success(f"Squad #{new_id} successfully created!")
                    st.rerun()
                finally:
                    conn.close()
        return

    t_id = active_tourney["id"]
    st.session_state["active_tournament_id"] = t_id
    pin = active_tourney.get("pin_verifier", "6199")

    # Active event banner
    st.markdown(
        f"""
        <div style="background:#1E293B; border-left:4px solid #3B82F6; padding:12px 16px; border-radius:6px; margin-bottom:16px;">
            <strong style="color:#F8FAFC; font-size:16px;">Active Event: {active_tourney['name']} (#{t_id})</strong><br/>
            <span style="color:#94A3B8; font-size:13px;">Host Center: {active_tourney['host_center']} | Format: {active_tourney['squad_format']} ({active_tourney['game_count']} Games) | Floor PIN: <code>{pin}</code></span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Tabs for Roster Management and Concourse Station
    tab_roster, tab_manual, tab_concourse = st.tabs(["📋 Squad Roster", "➕ Add Competitor", "📱 Concourse Access Badges"])

    # --- TAB 1: SQUAD ROSTER ---
    with tab_roster:
        bowlers = _get_squad_bowlers(t_id)
        if not bowlers:
            st.info("No competitors currently entered on this squad roster.")
        else:
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("Field Size", f"{len(bowlers)} Bowlers")
            col_m2.metric("Checked In", f"{sum(1 for b in bowlers if b['checked_in'])} Bowlers")
            col_m3.metric("Paid Entries", f"{sum(1 for b in bowlers if b['paid_status'] == 'paid')} Entries")

            st.dataframe(bowlers, hide_index=True, use_container_width=True)

    # --- TAB 2: MANUAL COMPETITOR ENTRY ---
    with tab_manual:
        with st.form("manual_bowler_entry_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                b_name = st.text_input("Bowler Full Name")
                b_usbc = st.text_input("USBC Member ID")
                b_email = st.text_input("Bowler Email (for recap delivery)")
            with c2:
                b_avg = st.number_input("Entering Average", min_value=0, max_value=300, value=200)
                b_hdcp = st.number_input("Handicap", min_value=0, max_value=150, value=18)
                b_lane = st.number_input("Assigned Lane", min_value=1, max_value=80, value=1)

            c3, c4 = st.columns(2)
            with c3:
                is_youth = st.checkbox("Youth Competitor (USBC Rule 400 SMART Escrow)")
                smart_id = st.text_input("SMART Account # (if youth)", value="")
            with c4:
                paid = st.selectbox("Payment Status", ["paid", "unpaid"])

            btn_add = st.form_submit_button("📥 Register Bowler to Squad", type="primary", use_container_width=True)
            if btn_add:
                if not b_name.strip():
                    st.error("Bowler name is required.")
                else:
                    conn = get_connection()
                    try:
                        with conn:
                            conn.execute(
                                """
                                INSERT INTO bowlers (
                                    tournament_id, name, usbc_id, email, entering_avg, handicap,
                                    lane_assignment, lineup_position, is_youth, smart_account_id, paid_status
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                                """,
                                (t_id, b_name.strip(), b_usbc.strip(), b_email.strip(), b_avg, b_hdcp, b_lane, 1 if is_youth else 0, smart_id.strip(), paid),
                            )
                        log_desk_action(td_name, "td", f"Registered bowler '{b_name}' on Lane {b_lane} for squad #{t_id}")
                        st.success(f"Bowler {b_name} added to Squad #{t_id}!")
                        st.rerun()
                    finally:
                        conn.close()

    # --- TAB 3: CONCOURSE ACCESS BADGES ---
    with tab_concourse:
        st.subheader("Concourse Check-In, Live Portal & Floor Scoring Station")
        st.caption("Display or share these direct portals with bowlers and floor score verifiers prior to launching the squad.")

        base = _get_base_url()
        checkin_url = f"{base}/?mode=bowler&action=checkin"
        portal_url = f"{base}/?mode=bowler"
        scorer_url = f"{base}/?mode=score"

        b64_checkin = _generate_qr_base64(checkin_url)
        b64_portal = _generate_qr_base64(portal_url)
        b64_scorer = _generate_qr_base64(scorer_url)

        col1, col2, col3 = st.columns(3, gap="medium")

        with col1:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div style="text-align:center; min-height:85px;">
                        <span style="background:#064E3B; color:#6EE7B7; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;">
                            ARRIVAL GATE
                        </span>
                        <h4 style="color:#F8FAFC; margin:6px 0 2px 0;">🎳 Bowler Check-In</h4>
                        <p style="color:#94A3B8; font-size:12px; margin-bottom:0;">Verify paid status & unlock lane</p>
                    </div>
                    <div style="display:flex; justify-content:center; align-items:center; padding:12px 0;">
                        <img src="data:image/png;base64,{b64_checkin}" width="190" style="border-radius:8px; display:block; margin:0 auto;" />
                    </div>
                    <div style="text-align:center; margin-top:4px;">
                        <a href="{checkin_url}" target="_blank" style="font-size:13px; text-decoration:none; color:#38BDF8;">🔗 Open Check-In</a>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        with col2:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div style="text-align:center; min-height:85px;">
                        <span style="background:#0284C7; color:#BAE6FD; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;">
                            LIVE TRACKER
                        </span>
                        <h4 style="color:#F8FAFC; margin:6px 0 2px 0;">📊 Bowler Portal</h4>
                        <p style="color:#94A3B8; font-size:12px; margin-bottom:0;">Live standings, cut line & brackets</p>
                    </div>
                    <div style="display:flex; justify-content:center; align-items:center; padding:12px 0;">
                        <img src="data:image/png;base64,{b64_portal}" width="190" style="border-radius:8px; display:block; margin:0 auto;" />
                    </div>
                    <div style="text-align:center; margin-top:4px;">
                        <a href="{portal_url}" target="_blank" style="font-size:13px; text-decoration:none; color:#38BDF8;">🔗 Open Bowler Portal</a>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        with col3:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div style="text-align:center; min-height:85px;">
                        <span style="background:#1E3A8A; color:#93C5FD; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;">
                            STAFF / VERIFIERS
                        </span>
                        <h4 style="color:#F8FAFC; margin:6px 0 2px 0;">📱 Floor Scoring</h4>
                        <p style="color:#10B981; font-weight:700; font-size:12px; margin-bottom:0;">🔑 Active PIN: {pin}</p>
                    </div>
                    <div style="display:flex; justify-content:center; align-items:center; padding:12px 0;">
                        <img src="data:image/png;base64,{b64_scorer}" width="190" style="border-radius:8px; display:block; margin:0 auto;" />
                    </div>
                    <div style="text-align:center; margin-top:4px;">
                        <a href="{scorer_url}" target="_blank" style="font-size:13px; text-decoration:none; color:#38BDF8;">🔗 Open Scorer Pad</a>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )