"""Intake Gateway — Squad initialization, AI roster ingestion (file upload or copy/paste), manual entry, and concourse check-in."""

import base64
import io
import time
import pandas as pd
import qrcode
import streamlit as st

# Safe import with fallback to prevent top-level app.py crash
try:
    from modules.ai_roster import (
        get_best_available_model,
        get_gemini_client,
        parse_roster_text_with_gemini,
        parse_roster_with_gemini,
    )
    AI_MODULE_LOADED = True
except Exception:
    AI_MODULE_LOADED = False
    get_best_available_model = lambda client=None: "gemini-3.8-flash"
    get_gemini_client = lambda: None
    parse_roster_text_with_gemini = lambda text: []
    parse_roster_with_gemini = lambda b, fn: []

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


def _run_with_bowling_animation(task_func, *args):
    """
    Executes the Gemini extraction directly on the active Streamlit thread
    with a visual bowling lane animation, eliminating thread-context freezes.
    """
    anim_box = st.empty()
    progress_bar = st.progress(0)

    stages = [
        (20, "🎳 Setting lane oil pattern & initializing Gemini Flash...", 20),
        (45, "🎳 Bowler on the approach... reading roster names & USBC IDs...", 40),
        (70, "🎳 Mid-lane roll... parsing entering averages & handicaps...", 65),
    ]

    def render_lane(stage_desc, pct, ball_pos):
        html_lane = (
            f'<div style="background:#0F172A; border:1px solid #1E293B; border-radius:10px; padding:16px 20px; margin-bottom:12px; box-shadow:0 4px 12px rgba(0,0,0,0.3);">'
            f'  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">'
            f'    <span style="color:#38BDF8; font-weight:600; font-size:14px;">{stage_desc}</span>'
            f'    <span style="color:#F8FAFC; font-family:monospace; font-weight:700; font-size:16px; background:#1E293B; padding:2px 8px; border-radius:4px;">{pct}%</span>'
            f'  </div>'
            f'  <div style="position:relative; width:100%; height:54px; background:linear-gradient(180deg, #78350F 0%, #B45309 40%, #78350F 100%); border-radius:6px; border:2px solid #92400E; overflow:hidden; display:flex; align-items:center;">'
            f'    <div style="position:absolute; left:20px; top:0; bottom:0; width:4px; background:#EF4444; box-shadow:0 0 6px #EF4444; z-index:2;"></div>'
            f'    <div style="position:absolute; left:25%; color:rgba(0,0,0,0.25); font-size:18px; pointer-events:none;">▲</div>'
            f'    <div style="position:absolute; left:45%; color:rgba(0,0,0,0.25); font-size:18px; pointer-events:none;">▲</div>'
            f'    <div style="position:absolute; left:65%; color:rgba(0,0,0,0.25); font-size:18px; pointer-events:none;">▲</div>'
            f'    <div style="position:absolute; left:{ball_pos}%; font-size:28px; line-height:1; transition:left 0.15s ease-out; filter:drop-shadow(0 4px 6px rgba(0,0,0,0.6)); z-index:3;">🎳</div>'
            f'    <div style="position:absolute; right:16px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:1px; z-index:2;">'
            f'      <div style="display:flex; gap:3px; font-size:9px; line-height:1;"><span>⚪</span><span>⚪</span><span>⚪</span><span>⚪</span></div>'
            f'      <div style="display:flex; gap:4px; font-size:9px; line-height:1;"><span>⚪</span><span>⚪</span><span>⚪</span></div>'
            f'      <div style="display:flex; gap:5px; font-size:9px; line-height:1;"><span>⚪</span><span>⚪</span></div>'
            f'      <div style="font-size:9px; line-height:1;"><span>⚪</span></div>'
            f'    </div>'
            f'  </div>'
            f'</div>'
        )
        anim_box.markdown(html_lane, unsafe_allow_html=True)
        progress_bar.progress(pct)

    # Initial delivery down the boards
    for pct, desc, b_pos in stages:
        render_lane(desc, pct, b_pos)
        time.sleep(0.08)

    # Hook phase directly before API call
    render_lane("🎳 Ball hooking into 1-3 pocket... parsing Rule 400 SMART tags...", 85, 78)

    try:
        # Direct execution on main thread with native access to st.secrets
        result = task_func(*args)
    except Exception as exc:
        anim_box.empty()
        progress_bar.empty()
        raise RuntimeError(f"Gemini API request failed: {exc}")

    # Strike state
    html_strike = (
        '<div style="background:#064E3B; border:1px solid #059669; border-radius:10px; padding:16px 20px; margin-bottom:12px; box-shadow:0 4px 12px rgba(6,78,59,0.3);">'
        '  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">'
        '    <span style="color:#6EE7B7; font-weight:700; font-size:15px;">💥 STRIKE! 10 in the Pit — Roster Extracted & Ready for Review!</span>'
        '    <span style="color:#F8FAFC; font-family:monospace; font-weight:700; font-size:16px; background:#047857; padding:2px 8px; border-radius:4px;">100%</span>'
        '  </div>'
        '  <div style="position:relative; width:100%; height:54px; background:linear-gradient(180deg, #78350F 0%, #B45309 40%, #78350F 100%); border-radius:6px; border:2px solid #059669; display:flex; align-items:center; justify-content:flex-end; padding-right:24px;">'
        '    <div style="color:#FEF08A; font-weight:900; font-size:18px; letter-spacing:1px; text-shadow:0 2px 4px rgba(0,0,0,0.8);">🎳 💥 💨 ALL 10 DOWN!</div>'
        '  </div>'
        '</div>'
    )
    anim_box.markdown(html_strike, unsafe_allow_html=True)
    progress_bar.progress(100)
    time.sleep(0.5)

    anim_box.empty()
    progress_bar.empty()
    return result


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
            SELECT id, name, usbc_id, email, entering_avg, handicap, lane_assignment,
                   lineup_position, is_pacer, is_youth, smart_account_id, paid_status, checked_in
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

    tab_roster, tab_entry, tab_concourse = st.tabs(
        ["📋 Squad Roster", "➕ Add Competitors (AI & Manual)", "📱 Concourse Access Badges"]
    )

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

    # --- TAB 2: ADD COMPETITORS (3-WAY CHOICE) ---
    with tab_entry:
        client = get_gemini_client() if AI_MODULE_LOADED else None
        active_model = get_best_available_model(client) if client else "gemini-3.8-flash"

        intake_mode = st.radio(
            "Select Intake Method:",
            [
                "📁 Upload Document (Word, Excel, PDF, CSV, Photo)",
                "📋 Copy & Paste Roster Text (Gemini Auto-Parser)",
                "✍️ Manual Entry (Single Walk-In Bowler)",
            ],
            horizontal=True,
        )

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

        # OPTION A: FILE UPLOAD
        if intake_mode.startswith("📁"):
            st.caption(f"Upload your roster document. Processed by **{active_model}**.")
            uploaded_file = st.file_uploader(
                "Upload Squad File",
                type=["docx", "xlsx", "xls", "pdf", "csv", "png", "jpg", "jpeg", "txt"],
                key="ai_roster_uploader",
            )
            if uploaded_file is not None:
                if st.button("🤖 Ingest File with Gemini", type="primary"):
                    try:
                        file_bytes = uploaded_file.getvalue()
                        extracted = _run_with_bowling_animation(
                            parse_roster_with_gemini, file_bytes, uploaded_file.name
                        )
                        if not extracted:
                            st.warning("No bowler records found in document.")
                        else:
                            st.session_state["parsed_ai_roster"] = extracted
                            st.success(f"Extracted {len(extracted)} bowler(s)!")
                    except Exception as e:
                        st.error(f"AI Extraction failed: {e}")

        # OPTION B: COPY & PASTE TEXT
        elif intake_mode.startswith("📋"):
            st.caption(f"Copy and paste roster text directly from Word, emails, Facebook posts, or notes. Powered by **{active_model}**.")
            pasted_text = st.text_area(
                "Paste Roster Content Here",
                placeholder="Example:\nLane 1: Marcus Vance (USBC 8412-10921, Avg 218) - Paid\nLane 1: Tyler Jenkins (USBC 8412-44102, Avg 192) - Paid\nLane 2: Dylan Cooper (USBC 8412-99014, Avg 174, Youth, SMART 4412)",
                height=180,
            )
            if st.button("🤖 Ingest Pasted Text with Gemini", type="primary"):
                if not pasted_text.strip():
                    st.warning("Please paste some text before clicking Ingest.")
                else:
                    try:
                        extracted = _run_with_bowling_animation(
                            parse_roster_text_with_gemini, pasted_text
                        )
                        if not extracted:
                            st.warning("No bowler records detected in pasted text.")
                        else:
                            st.session_state["parsed_ai_roster"] = extracted
                            st.success(f"Extracted {len(extracted)} bowler(s)!")
                    except Exception as e:
                        st.error(f"AI Parsing failed: {e}")

        # OPTION C: MANUAL ENTRY FORM
        else:
            st.caption("Standard direct manual entry for single competitor walk-ins.")
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
                                    (
                                        t_id,
                                        b_name.strip(),
                                        b_usbc.strip(),
                                        b_email.strip(),
                                        b_avg,
                                        b_hdcp,
                                        b_lane,
                                        1 if is_youth else 0,
                                        smart_id.strip(),
                                        paid,
                                    ),
                                )
                            log_desk_action(td_name, "td", f"Registered bowler '{b_name}' on Lane {b_lane} for squad #{t_id}")
                            st.success(f"Bowler {b_name} added to Squad #{t_id}!")
                            st.rerun()
                        finally:
                            conn.close()

        # SHARED REVIEW & COMMIT TABLE
        if "parsed_ai_roster" in st.session_state and st.session_state["parsed_ai_roster"]:
            st.markdown("---")
            st.markdown("##### 📝 Review & Edit Extracted Roster Before Committing")
            st.caption("You can edit cells, fix lane assignments, or delete rows directly in the grid below.")
            df_edit = pd.DataFrame(st.session_state["parsed_ai_roster"])
            edited_df = st.data_editor(df_edit, num_rows="dynamic", use_container_width=True, key="ai_editor")

            col_sub1, col_sub2 = st.columns([2, 5])
            with col_sub1:
                if st.button("📥 Commit Roster to Squad", type="primary", use_container_width=True):
                    conn = get_connection()
                    inserted = 0
                    try:
                        with conn:
                            for _, row in edited_df.iterrows():
                                b_name = str(row.get("name", "")).strip()
                                if not b_name or b_name.lower() == "nan":
                                    continue
                                conn.execute(
                                    """
                                    INSERT INTO bowlers (
                                        tournament_id, name, usbc_id, email, entering_avg, handicap,
                                        lane_assignment, lineup_position, is_youth, smart_account_id, paid_status
                                    )
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                                    """,
                                    (
                                        t_id,
                                        b_name,
                                        str(row.get("usbc_id") or "").strip(),
                                        str(row.get("email") or "").strip(),
                                        int(row.get("entering_avg") or 200),
                                        int(row.get("handicap") or 0),
                                        int(row.get("lane_assignment") or 1),
                                        1 if row.get("is_youth") else 0,
                                        str(row.get("smart_account_id") or "").strip(),
                                        str(row.get("paid_status") or "paid"),
                                    ),
                                )
                                inserted += 1
                        log_desk_action(td_name, "td", f"AI batch-registered {inserted} bowlers for squad #{t_id}")
                        st.session_state["parsed_ai_roster"] = []
                        st.success(f"Successfully registered {inserted} bowler(s) to Squad #{t_id}!")
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