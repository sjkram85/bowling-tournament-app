"""Intake Gateway — Squad initialization, CHUSBC Template Library, AI roster ingestion, manual entry, multi-event package registration, and concourse check-in."""

from modules.practice import create_practice_tournament, delete_practice_tournament
import base64
import io
import time
import pandas as pd
import qrcode
import streamlit as st

# Safe import with fallback to prevent top-level app.py crash
try:
    from modules.ai_roster import (
        parse_roster_text_with_gemini,
        parse_roster_with_gemini,
    )
    AI_MODULE_LOADED = True
except Exception:
    AI_MODULE_LOADED = False
    parse_roster_text_with_gemini = lambda text: []
    parse_roster_with_gemini = lambda b, fn: []

from modules.auth import current_user
from modules.constants import CENTERS, HOST_CENTERS
from modules.db_state import get_connection, log_desk_action
from modules import roster_import
from modules import auth as _auth
from modules.divisions import assign_all, clean_average, entry_handicap, entry_problems, normalize_birth
from modules.events import cancel_tournament, entry_package_labels, public_checkin_url
from components.preset_panel import render_preset_panel
from modules.tournament_templates import CHUSBC_TEMPLATES, create_tournament_from_template, save_tournament_as_template
from modules.settings import get_secret, ai_available, AI_OFF_MESSAGE, model_name

# Pure SVG bowling ball with 3D gradient & finger holes
BOWLING_BALL_SVG = (
    '<svg width="28" height="28" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" style="display:block;">'
    '  <defs>'
    '    <radialGradient id="ballGrad" cx="35%" cy="30%" r="65%">'
    '      <stop offset="0%" stop-color="#60A5FA"/>'
    '      <stop offset="45%" stop-color="#2563EB"/>'
    '      <stop offset="100%" stop-color="#0F172A"/>'
    '    </radialGradient>'
    '  </defs>'
    '  <circle cx="16" cy="16" r="14" fill="url(#ballGrad)" stroke="#1E3A8A" stroke-width="1"/>'
    '  <circle cx="20" cy="11" r="1.8" fill="#090D16"/>'
    '  <circle cx="23" cy="15" r="1.8" fill="#090D16"/>'
    '  <circle cx="18" cy="16" r="2.1" fill="#090D16"/>'
    '  <ellipse cx="11" cy="10" rx="3" ry="1.5" transform="rotate(-30 11 10)" fill="rgba(255,255,255,0.35)"/>'
    '</svg>'
)

MINI_BALL_SVG = (
    '<svg width="16" height="16" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" style="display:inline-block; vertical-align:middle; margin-right:6px;">'
    '  <circle cx="16" cy="16" r="14" fill="#3B82F6" stroke="#1D4ED8" stroke-width="1.5"/>'
    '  <circle cx="20" cy="11" r="2.2" fill="#0F172A"/>'
    '  <circle cx="23" cy="16" r="2.2" fill="#0F172A"/>'
    '  <circle cx="17" cy="16" r="2.4" fill="#0F172A"/>'
    '</svg>'
)

PIN_DOT = (
    '<span style="width:7px; height:7px; border-radius:50%; background:#FFFFFF; '
    'border:1px solid #DC2626; box-shadow:0 1px 2px rgba(0,0,0,0.65); display:inline-block;"></span>'
)


def _roster_handicap(tournament: dict, row) -> int:
    """Locked events follow the average rule. Otherwise keep the handicap typed on the roster."""
    avg = clean_average(row.get("entering_avg") if hasattr(row, "get") else row["entering_avg"])
    if tournament.get("rules_locked"):
        computed = entry_handicap(tournament, avg, bool(row.get("bowls_scratch")))
        if computed is not None:
            return int(computed)
    try:
        return int(row["handicap"] or 0)
    except (TypeError, ValueError):
        return 0


def _get_base_url() -> str:
    """Dynamically determine current host environment base URL."""
    return get_secret("APP_BASE_URL", "https://chusbc-desk.streamlit.app")


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
    anim_box = st.empty()
    progress_bar = st.progress(0)

    stages = [
        (20, "Setting lane oil pattern & initializing Gemini Flash...", 18),
        (45, "Bowler on the approach... reading roster names & USBC IDs...", 42),
        (70, "Mid-lane roll... parsing entering averages & handicaps...", 64),
    ]

    def render_lane(stage_desc, pct, ball_pos):
        html_lane = (
            f'<div style="background:#0F172A; border:1px solid #1E293B; border-radius:10px; padding:16px 20px; margin-bottom:12px; box-shadow:0 4px 12px rgba(0,0,0,0.3);">'
            f'  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">'
            f'    <span style="color:#38BDF8; font-weight:600; font-size:14px; display:flex; align-items:center;">{MINI_BALL_SVG}{stage_desc}</span>'
            f'    <span style="color:#F8FAFC; font-family:monospace; font-weight:700; font-size:16px; background:#1E293B; padding:2px 8px; border-radius:4px;">{pct}%</span>'
            f'  </div>'
            f'  <div style="position:relative; width:100%; height:58px; background:linear-gradient(180deg, #78350F 0%, #B45309 40%, #78350F 100%); border-radius:6px; border:2px solid #92400E; overflow:hidden; display:flex; align-items:center;">'
            f'    <div style="position:absolute; left:20px; top:0; bottom:0; width:4px; background:#EF4444; box-shadow:0 0 6px #EF4444; z-index:2;"></div>'
            f'    <div style="position:absolute; left:25%; color:rgba(0,0,0,0.28); font-size:13px; pointer-events:none;">▶</div>'
            f'    <div style="position:absolute; left:45%; color:rgba(0,0,0,0.28); font-size:13px; pointer-events:none;">▶</div>'
            f'    <div style="position:absolute; left:65%; color:rgba(0,0,0,0.28); font-size:13px; pointer-events:none;">▶</div>'
            f'    <div style="position:absolute; left:{ball_pos}%; transition:left 0.15s ease-out; filter:drop-shadow(0 4px 6px rgba(0,0,0,0.65)); z-index:3;">{BOWLING_BALL_SVG}</div>'
            f'    <div style="position:absolute; right:14px; display:flex; flex-direction:row; align-items:center; gap:5px; z-index:2;">'
            f'      <div style="display:flex; flex-direction:column; justify-content:center;">{PIN_DOT}</div>'
            f'      <div style="display:flex; flex-direction:column; gap:5px; justify-content:center;">{PIN_DOT}{PIN_DOT}</div>'
            f'      <div style="display:flex; flex-direction:column; gap:4px; justify-content:center;">{PIN_DOT}{PIN_DOT}{PIN_DOT}</div>'
            f'      <div style="display:flex; flex-direction:column; gap:3px; justify-content:center;">{PIN_DOT}{PIN_DOT}{PIN_DOT}{PIN_DOT}</div>'
            f'    </div>'
            f'  </div>'
            f'</div>'
        )
        anim_box.markdown(html_lane, unsafe_allow_html=True)
        progress_bar.progress(pct)

    for pct, desc, b_pos in stages:
        render_lane(desc, pct, b_pos)
        time.sleep(0.08)

    render_lane("Ball hooking into 1-3 pocket... parsing Rule 400 SMART tags...", 85, 83)

    try:
        result = task_func(*args)
    except Exception as exc:
        anim_box.empty()
        progress_bar.empty()
        raise RuntimeError(f"Gemini API request failed: {exc}")

    html_strike = (
        f'<div style="background:#064E3B; border:1px solid #059669; border-radius:10px; padding:16px 20px; margin-bottom:12px; box-shadow:0 4px 12px rgba(6,78,59,0.3);">'
        f'  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">'
        f'    <span style="color:#6EE7B7; font-weight:700; font-size:15px; display:flex; align-items:center;">{MINI_BALL_SVG}💥 STRIKE! 10 in the Pit — Roster Extracted & Ready for Review!</span>'
        f'    <span style="color:#F8FAFC; font-family:monospace; font-weight:700; font-size:16px; background:#047857; padding:2px 8px; border-radius:4px;">100%</span>'
        f'  </div>'
        f'  <div style="position:relative; width:100%; height:58px; background:linear-gradient(180deg, #78350F 0%, #B45309 40%, #78350F 100%); border-radius:6px; border:2px solid #059669; display:flex; align-items:center; justify-content:flex-end; padding-right:24px; gap:10px;">'
        f'    {BOWLING_BALL_SVG}'
        f'    <div style="color:#FEF08A; font-weight:900; font-size:18px; letter-spacing:1px; text-shadow:0 2px 4px rgba(0,0,0,0.8);">💥 💨 ALL 10 DOWN!</div>'
        f'  </div>'
        f'</div>'
    )
    anim_box.markdown(html_strike, unsafe_allow_html=True)
    progress_bar.progress(100)
    time.sleep(0.5)

    anim_box.empty()
    progress_bar.empty()
    return result


def _get_active_tournament() -> dict | None:
    """Open event for this rerun.

    The practice banner already loads this row through get_tournament. Reuse that
    read instead of a second SELECT *.
    """
    from modules.run_memo import memo
    from modules.standings import get_tournament

    t_id = st.session_state.get("active_tournament_id")
    if t_id:
        row = get_tournament(t_id)
        if row:
            return row
    conn = get_connection()
    try:
        # No choice on this device: only fall back when exactly one event is active.
        rows = conn.execute("SELECT * FROM tournaments WHERE status = 'active'").fetchall()
    finally:
        conn.close()
    if len(rows) != 1:
        return None
    found = dict(rows[0])
    memo(("tournament", str(found["id"])), lambda: dict(found))
    return dict(found)


def _get_squad_bowlers(tournament_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, usbc_id, email, entering_avg, handicap, lane_assignment,
                   lineup_position, is_pacer, is_youth, smart_account_id, paid_status, checked_in,
                   gender, birth_date, bowls_scratch, division, age_group
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

    active_tourney = None if st.session_state.get("intake_new_event") else _get_active_tournament()

    if not active_tourney:
        st.info("No active tournament squad is loaded. Select a CHUSBC Template or create a custom event below.")

        with st.container(border=True):
            st.markdown("### 🧪 Want to try things out first?")
            st.markdown("<p style='font-size:18px;'>A practice tournament fills in 12 pretend bowlers and some scores so you can try every screen. "
                        "Nothing in it is real, saved to the archive, exported, or sent to anyone.</p>", unsafe_allow_html=True)
            if st.button("🧪 Start Practice Tournament", key="start_practice", use_container_width=True):
                st.session_state["active_tournament_id"] = create_practice_tournament()
                st.session_state.pop("intake_new_event", None)
                log_desk_action(td_name, "td", "Started a practice tournament")
                st.rerun()

        # --- CHUSBC MASTER TOURNAMENT TEMPLATES ---
        with st.container(border=True):
            st.markdown("##### 🏆 CHUSBC Master Tournament Templates")
            st.caption("Quick-load standardized association tournament configurations.")

            selected_tmpl_key = st.selectbox("Select Association Template", list(CHUSBC_TEMPLATES.keys()))
            tmpl_info = CHUSBC_TEMPLATES[selected_tmpl_key]
            st.markdown(f"<small style='color: #94A3B8;'>{tmpl_info['description']} &middot; <b>{tmpl_info['game_count']} Games</b> &middot; Format: {tmpl_info['squad_format']}</small>", unsafe_allow_html=True)

            center_keys = list(CENTERS.keys())
            if tmpl_info.get("locked"):
                template_center = tmpl_info["locked"]["host_center"]
                st.markdown(f"**Host center:** {CENTERS.get(template_center, {}).get('name', template_center)} (set by preset)")
            else:
                template_center = st.selectbox("Template Host Center", center_keys, format_func=lambda k: CENTERS[k]["name"], key="tmpl_center")
            template_pin = st.text_input("Floor Scorer PIN", value="6199", max_chars=8, key="tmpl_pin")

            if st.button("🚀 Load Template & Unlock Intake", type="primary", use_container_width=True):
                new_id = create_tournament_from_template(selected_tmpl_key, template_center, template_pin)
                st.session_state["active_tournament_id"] = new_id
                st.session_state.pop("intake_new_event", None)
                log_desk_action(td_name, "td", f"Initialized tournament squad #{new_id} from template '{selected_tmpl_key}'")
                st.success(f"Template loaded successfully as Tournament #{new_id}!")
                st.rerun()

        st.markdown("---")
        st.markdown("##### 🛠️ Or Create Custom Tournament Squad")
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
                    st.session_state.pop("intake_new_event", None)
                    log_desk_action(td_name, "td", f"Created and initialized tournament squad #{new_id} '{t_name}'")
                    st.success(f"Squad #{new_id} successfully created!")
                    st.rerun()
                finally:
                    conn.close()
        return

    t_id = active_tourney["id"]
    st.session_state["active_tournament_id"] = t_id
    pin = active_tourney.get("pin_verifier", "6199")

    # Active event banner with Cancel / Purge Control
    if active_tourney.get("is_practice"):
        if st.button("🗑️ End & Delete Practice Tournament (removes all practice data)", key="end_practice", type="primary", use_container_width=True):
            delete_practice_tournament(t_id)
            log_desk_action(td_name, "td", "Ended and deleted the practice tournament")
            st.session_state.pop("active_tournament_id", None)
            st.rerun()

    col_banner_info, col_banner_action = st.columns([5, 1])
    with col_banner_info:
        st.markdown(
            f"""
            <div style="background:#1E293B; border-left:4px solid #3B82F6; padding:12px 16px; border-radius:6px; margin-bottom:16px;">
                <strong style="color:#F8FAFC; font-size:16px;">Active Event: {active_tourney['name']} (#{t_id})</strong><br/>
                <span style="color:#94A3B8; font-size:13px;">Host Center: {active_tourney['host_center']} | Format: {active_tourney['squad_format']} ({active_tourney['game_count']} Games) | Floor PIN: <code>{pin}</code></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_banner_action:
        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        cancel_sure = st.checkbox("Yes, cancel this event", key=f"cancel_ok_{t_id}")
        st.caption("Cancel keeps every score. It does not certify results. To lock the event, use Freeze on Finals Closeout after the PDF is saved.")
        if st.button("🛑 Cancel Event", type="secondary", use_container_width=True, disabled=not cancel_sure,
                     help="Cancel this squad. Scores stay in the database."):
            cancel_tournament(t_id, td_name)
            if "active_tournament_id" in st.session_state:
                del st.session_state["active_tournament_id"]
            st.success("Tournament squad cancelled. Scores were not deleted.")
            st.rerun()

    # Save active tournament as template expander
    with st.expander("📌 Save Active Squad as Reusable Template"):
        new_tmpl_title = st.text_input("Template Display Name", value=f"{active_tourney['name']} Template")
        if st.button("💾 Save to Master Template Library", type="secondary"):
            if not new_tmpl_title.strip():
                st.error("Please enter a valid template name.")
            else:
                save_tournament_as_template(t_id, new_tmpl_title.strip())
                log_desk_action(td_name, "td", f"Saved active tournament #{t_id} as template '{new_tmpl_title}'")
                st.success(f"Successfully saved '{new_tmpl_title}' to the CHUSBC Template Library!")
                st.rerun()

    render_preset_panel(active_tourney, td_name)
    override = not active_tourney.get("rules_locked")

    tab_roster, tab_entry, tab_concourse = st.tabs(
        ["📋 Squad Roster (Fully Editable)", "➕ Add Competitors (AI & Manual)", "📱 Concourse Access Badges"]
    )

    # --- TAB 1: SQUAD ROSTER (EDITABLE) ---
    with tab_roster:
        bowlers = _get_squad_bowlers(t_id)
        if not bowlers:
            st.info("No competitors currently entered on this squad roster.")
        else:
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("Field Size", f"{len(bowlers)} Bowlers")
            col_m2.metric("Checked In", f"{sum(1 for b in bowlers if b['checked_in'])} Bowlers")
            col_m3.metric("Paid Entries", f"{sum(1 for b in bowlers if b['paid_status'] == 'paid')} Entries")

            st.caption("💡 You can directly edit any field in the table below and click save.")
            
            df_bowlers = pd.DataFrame(bowlers)
            edited_roster = st.data_editor(
                df_bowlers,
                hide_index=True,
                use_container_width=True,
                key="editable_squad_roster",
                disabled=["id", "tournament_id", "division", "age_group"] + (["handicap"] if active_tourney.get("rules_locked") else [])
            )

            roster_problems = [] if override else [
                f"{r['name']}: {p}" for r in edited_roster.to_dict("records")
                for p in entry_problems({**active_tourney, "no_walkins": 0}, r)
            ]
            for msg in roster_problems[:6]:
                st.error(msg)
            if st.button("💾 Save Roster Changes", type="primary", disabled=bool(roster_problems)):
                conn = get_connection()
                try:
                    with conn:
                        for _, row in edited_roster.iterrows():
                            conn.execute(
                                """
                                UPDATE bowlers SET
                                    name = ?,
                                    usbc_id = ?,
                                    email = ?,
                                    entering_avg = ?,
                                    handicap = ?,
                                    lane_assignment = ?,
                                    lineup_position = ?,
                                    is_youth = ?,
                                    smart_account_id = ?,
                                    paid_status = ?,
                                    gender = ?,
                                    birth_date = ?,
                                    bowls_scratch = ?
                                WHERE id = ?
                                """,
                                (
                                    row["name"],
                                    row["usbc_id"],
                                    row["email"],
                                    clean_average(row["entering_avg"]),
                                    _roster_handicap(active_tourney, row),
                                    int(row["lane_assignment"]),
                                    int(row["lineup_position"]),
                                    int(row["is_youth"]),
                                    row["smart_account_id"],
                                    row["paid_status"],
                                    (row.get("gender") or None),
                                    normalize_birth(row.get("birth_date")),
                                    int(bool(row.get("bowls_scratch") or 0)),
                                    row["id"],
                                ),
                            )
                    log_desk_action(td_name, "td", f"Updated squad roster for tournament #{t_id}")
                    assign_all(t_id)
                    st.success("Roster changes saved successfully!")
                    st.rerun()
                finally:
                    conn.close()

    # --- TAB 2: ADD COMPETITORS (MULTI-EVENT PACKAGE & TEMPLATE) ---
    with tab_entry:
        active_model = model_name()

        package = entry_package_labels(active_tourney)
        st.markdown("##### 🏆 Event tags on this entry")
        st.caption(package["caption"])
        if package["show_picker"]:
            col_ev1, col_ev2, col_ev3, col_ev4 = st.columns(4)
            reg_singles = col_ev1.checkbox("Singles", value=True) if package["offer_singles"] else False
            reg_doubles = col_ev2.checkbox("Doubles", value=False) if package["offer_doubles"] else False
            reg_team = col_ev3.checkbox("Team", value=False) if package["offer_team"] else False
            reg_all_events = False
            col_ev4.caption("All-Events is not used. It does not create standings.")
        else:
            reg_singles, reg_doubles, reg_team, reg_all_events = True, False, False, False

        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)

        intake_mode = st.radio(
            "Select Intake Method:",
            [
                "📁 Upload Document (Excel, CSV, PDF, Photo)",
                "📋 Copy & Paste Roster Text (Gemini Auto-Parser)",
                "✍️ Manual Entry (Single Walk-In Bowler)",
            ],
            horizontal=True,
        )

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

        # OPTION A: FILE UPLOAD + CSV TEMPLATE DOWNLOAD
        if intake_mode.startswith("📁"):
            st.caption(f"Upload your roster document or spreadsheet. PDFs and photos are read by Prism A.I. ({active_model})." if ai_available() else "Upload your roster spreadsheet.")
            
            st.markdown(
                "**Fastest:** download the template, fill in one row per bowler, and upload it. "
                "Template files are read directly (no AI). Required columns: name, entering_avg, "
                "lane_assignment, paid_status (paid/unpaid)."
            )
            col_t1, col_t2 = st.columns(2)
            col_t1.download_button(
                "📥 Download Roster Template (.xlsx)",
                data=roster_import.template_xlsx(),
                file_name="prism_roster_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            col_t2.download_button(
                "📥 Download Roster Template (.csv)",
                data=roster_import.template_csv(),
                file_name="prism_roster_template.csv",
                mime="text/csv",
            )

            uploaded_file = st.file_uploader(
                "Upload Filled Squad File",
                type=["xlsx", "xls", "pdf", "csv", "png", "jpg", "jpeg", "txt"],
                key="ai_roster_uploader",
            )
            if uploaded_file is not None:
                file_bytes = uploaded_file.getvalue()
                table = roster_import.read_table(file_bytes, uploaded_file.name)
                use_ai = False
                new_file = st.session_state.get("roster_src") != uploaded_file.file_id
                if new_file:  # a different file was uploaded: drop any earlier preview
                    st.session_state["parsed_ai_roster"] = []
                    st.session_state["roster_src"] = uploaded_file.file_id
                if table is not None and roster_import.matches_template(table.columns):
                    st.success(f"✅ Template format recognized: {len(table)} row(s). Review them below.")
                    if new_file:
                        rows = roster_import.apply_mapping(table, roster_import.guess_mapping(table.columns))
                        st.session_state["parsed_ai_roster"] = roster_import.validate_rows(rows)
                elif table is not None:
                    st.warning("This spreadsheet doesn't match the template. Match its columns to Prism fields below.")
                    guess = roster_import.guess_mapping(table.columns)
                    options = ["— not in file —"] + list(table.columns)
                    mapping = {}
                    map_cols = st.columns(3)
                    for i, (key, label, required) in enumerate(roster_import.FIELDS):
                        choice = map_cols[i % 3].selectbox(
                            label + (" *" if required else ""),
                            options,
                            index=options.index(guess[key]) if guess[key] else 0,
                            key=f"map_{key}",
                        )
                        mapping[key] = None if choice == options[0] else choice
                    with st.expander("Show uploaded file"):
                        st.dataframe(table, use_container_width=True, hide_index=True)
                    col_m1, col_m2 = st.columns(2)
                    if col_m1.button("➡️ Use These Columns", type="primary"):
                        rows = roster_import.apply_mapping(table, mapping)
                        st.session_state["parsed_ai_roster"] = roster_import.validate_rows(rows)
                    use_ai = col_m2.button("🤖 Let Gemini Try Instead", disabled=not ai_available(), help=None if ai_available() else AI_OFF_MESSAGE)
                else:
                    if ai_available():
                        st.info("PDFs, photos, and text files are read with Gemini. Check every row in the review below.")
                    else:
                        st.warning(AI_OFF_MESSAGE + " Please upload an Excel or CSV file instead (use the template above).")
                    use_ai = st.button("🤖 Ingest File with Gemini", type="primary", disabled=not ai_available())
                if use_ai:
                    try:
                        extracted = _run_with_bowling_animation(
                            parse_roster_with_gemini, file_bytes, uploaded_file.name
                        )
                        if not extracted:
                            st.warning("No bowler records found in document.")
                        else:
                            st.session_state["parsed_ai_roster"] = roster_import.validate_rows(extracted)
                            st.success(f"Extracted {len(extracted)} bowler(s)!")
                    except Exception as e:
                        st.error(str(e))

        # OPTION B: COPY & PASTE TEXT WITH FORMAT GUIDE
        elif intake_mode.startswith("📋"):
            st.markdown(
                """
                <div style="background:#1E293B; padding:12px; border-radius:6px; margin-bottom:12px; border-left:4px solid #38BDF8;">
                    <strong style="color:#38BDF8;">📋 Copy & Paste Format Guide:</strong><br/>
                    <small style="color:#94A3B8;">Format each line with the <b>Name</b>, <b>USBC ID</b>, and <b>Average</b>:</small><br/>
                    <code style="color:#F8FAFC; background:#0F172A; padding:2px 6px; border-radius:4px; display:inline-block; margin-top:6px;">
                    Lane 1: Marcus Vance (USBC 8412-10921, Avg 218) - Paid<br/>
                    Lane 1: Tyler Jenkins (USBC 8412-44102, Avg 192) - Paid
                    </code>
                </div>
                """,
                unsafe_allow_html=True,
            )
            
            pasted_text = st.text_area(
                "Paste Roster Content Here",
                placeholder="Lane 1: Marcus Vance (USBC 8412-10921, Avg 218) - Paid\nLane 1: Tyler Jenkins (USBC 8412-44102, Avg 192) - Paid",
                height=180,
            )
            if not ai_available():
                st.caption("Prism A.I. is off, so pasted text is read by the built-in reader. Follow the format above exactly.")
            if st.button("🤖 Ingest Pasted Text with Gemini" if ai_available() else "📋 Read Pasted Text", type="primary"):
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
                            st.session_state["parsed_ai_roster"] = roster_import.validate_rows(extracted)
                            st.success(f"Extracted {len(extracted)} bowler(s)!")
                    except Exception as e:
                        st.error(str(e))

        # OPTION C: MANUAL ENTRY FORM
        else:
            st.caption("Standard direct manual entry for single competitor walk-ins.")
            with st.form("manual_bowler_entry_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    b_name = st.text_input("Bowler Full Name")
                    b_usbc = st.text_input("USBC Member ID")
                    b_email = st.text_input("Bowler Email")
                with c2:
                    b_avg = st.number_input(
                        "Entering Average", min_value=0, max_value=300, value=None, step=1,
                        placeholder="Leave blank if unknown",
                    )
                    st.caption("Blank is not 200. A missing average is not placed in Division 1.")
                    if active_tourney.get("handicap_pct") and active_tourney.get("handicap_base"):
                        st.caption(
                            f"Handicap is calculated from the average "
                            f"({int(active_tourney['handicap_pct'])}% of {int(active_tourney['handicap_base'])}). "
                            "Scratch bowlers get 0."
                        )
                        b_hdcp = None
                    else:
                        b_hdcp = st.number_input("Handicap", min_value=0, max_value=150, value=0)
                    b_lane = st.number_input("Assigned Lane", min_value=1, max_value=80, value=1)

                c3, c4 = st.columns(2)
                with c3:
                    is_youth = st.checkbox("Youth Competitor (USBC Rule 400 SMART Escrow)", value=bool(active_tourney.get("youth_only")))
                    gender = st.selectbox("Boys or Girls", ["", "Boys", "Girls"]) if active_tourney.get("require_gender") else ""
                    birth = st.text_input("Birth date (MM/DD/YYYY)", value="") if active_tourney.get("require_birthdate") else ""
                    scratch_flag = st.checkbox("Bowls scratch (no qualifying average)") if active_tourney.get("divisions_json") else False
                    smart_id = st.text_input("SMART Account # (if youth)", value="")
                with c4:
                    if active_tourney.get("fees_at_front_desk"):
                        paid = "paid"
                        st.info("Entry fees are collected by the Forest Hill Lanes front desk.")
                    else:
                        paid = st.selectbox("Payment Status", ["paid", "unpaid"])

                btn_add = st.form_submit_button("📥 Register Bowler to Squad", type="primary", use_container_width=True)
                if btn_add:
                    avg = clean_average(b_avg)
                    hdcp = entry_handicap(active_tourney, avg, bool(scratch_flag))
                    if hdcp is None:
                        hdcp = int(b_hdcp or 0)
                    problems = entry_problems(active_tourney, {"is_youth": is_youth, "smart_account_id": smart_id, "entering_avg": avg or 0,
                                                               "usbc_id": b_usbc, "gender": gender, "birth_date": birth, "bowls_scratch": scratch_flag})
                    if not b_name.strip():
                        st.error("Bowler name is required.")
                    elif problems:
                        for p_msg in problems:
                            st.error(p_msg)
                    else:
                        conn = get_connection()
                        try:
                            with conn:
                                cur = conn.execute(
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
                                        avg,
                                        int(hdcp),
                                        b_lane,
                                        1 if is_youth else 0,
                                        smart_id.strip(),
                                        paid,
                                    ),
                                )
                                b_db_id = cur.lastrowid
                                conn.execute("UPDATE bowlers SET gender = ?, birth_date = ?, bowls_scratch = ? WHERE id = ?",
                                             (gender or None, normalize_birth(birth), int(bool(scratch_flag)), b_db_id))
                                
                                selected_events = []
                                if reg_singles: selected_events.append("Singles")
                                if reg_doubles: selected_events.append("Doubles")
                                if reg_team: selected_events.append("Team")
                                if reg_all_events: selected_events.append("All-Events")

                                for ev in selected_events:
                                    conn.execute(
                                        "INSERT OR IGNORE INTO bowler_events (bowler_id, tournament_id, event_type, paid_status) VALUES (?, ?, ?, ?)",
                                        (b_db_id, t_id, ev, paid)
                                    )

                            assign_all(t_id)
                            log_desk_action(td_name, "td", f"Registered bowler '{b_name}' for squad #{t_id} across multi-event package")
                            st.success(f"Bowler {b_name} added to Squad #{t_id}!")
                            st.rerun()
                        finally:
                            conn.close()

        # SHARED REVIEW & COMMIT TABLE
        if st.session_state.get("parsed_ai_roster"):
            st.markdown("---")
            st.markdown("##### 📝 Review Roster Before Saving")
            st.caption("Fix any cell in the grid; problems are re-checked when you click Re-check. Nothing is saved until you click Save.")
            df_edit = pd.DataFrame(st.session_state["parsed_ai_roster"])
            df_edit = df_edit[["errors"] + roster_import.FIELD_KEYS]
            df_edit = df_edit.rename(columns={"errors": "problems"})
            edited_df = st.data_editor(
                df_edit, num_rows="dynamic", use_container_width=True, key="ai_editor",
                disabled=["problems"],
            )
            raw_rows = edited_df.drop(columns=["problems"]).to_dict("records")
            if active_tourney.get("fees_at_front_desk"):
                for r in raw_rows:
                    r["paid_status"] = "paid"
            checked = roster_import.validate_rows(raw_rows)
            for r in checked:
                extra = entry_problems(active_tourney, r)
                if extra:
                    r["errors"] = "; ".join([e for e in [r["errors"]] + extra if e])
            bad = [i + 1 for i, r in enumerate(checked) if r["errors"]]
            if bad:
                st.error(f"{len(bad)} row(s) have problems (rows {', '.join(map(str, bad[:15]))}). Fix them or delete those rows before saving.")
            else:
                st.success(f"All {len(checked)} row(s) look good.")

            col_sub1, col_sub2, col_sub3 = st.columns([2, 2, 3])
            if col_sub2.button("🔄 Re-check", use_container_width=True):
                st.session_state["parsed_ai_roster"] = checked
                st.rerun()
            if col_sub3.button("🗑️ Discard", use_container_width=True):
                st.session_state["parsed_ai_roster"] = []
                st.session_state.pop("roster_src", None)
                st.rerun()
            with col_sub1:
                if st.button(f"📥 Save {len(checked)} Bowler(s) to Squad", type="primary",
                             use_container_width=True, disabled=bool(bad) or not checked):
                    conn = get_connection()
                    inserted = 0
                    try:
                        with conn:
                            selected_events = []
                            if reg_singles: selected_events.append("Singles")
                            if reg_doubles: selected_events.append("Doubles")
                            if reg_team: selected_events.append("Team")
                            if reg_all_events: selected_events.append("All-Events")

                            for row in checked:
                                cur = conn.execute(
                                    """
                                    INSERT INTO bowlers (
                                        tournament_id, name, usbc_id, email, entering_avg, handicap,
                                        lane_assignment, lineup_position, is_youth, smart_account_id, paid_status
                                    )
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                                    """,
                                    (
                                        t_id, row["name"], row["usbc_id"], row["email"],
                                        row["entering_avg"], row["handicap"] or 0, row["lane_assignment"],
                                        1 if row["is_youth"] else 0, row["smart_account_id"], row["paid_status"],
                                    ),
                                )
                                b_db_id = cur.lastrowid
                                conn.execute("UPDATE bowlers SET gender = ?, birth_date = ?, bowls_scratch = ? WHERE id = ?",
                                             (row.get("gender") or None, normalize_birth(row.get("birth_date")),
                                              int(bool(row.get("bowls_scratch"))), b_db_id))
                                for ev in selected_events:
                                    conn.execute(
                                        "INSERT OR IGNORE INTO bowler_events (bowler_id, tournament_id, event_type, paid_status) VALUES (?, ?, ?, ?)",
                                        (b_db_id, t_id, ev, row["paid_status"])
                                    )
                                inserted += 1
                        assign_all(t_id)
                        log_desk_action(td_name, "td", f"Batch-registered {inserted} bowlers across multi-event package for squad #{t_id}")
                        st.session_state["parsed_ai_roster"] = []
                        st.session_state.pop("roster_src", None)
                        st.success(f"Successfully registered {inserted} bowler(s) across multi-event package!")
                        st.rerun()
                    finally:
                        conn.close()

    # --- TAB 3: CONCOURSE ACCESS BADGES ---
    with tab_concourse:
        st.subheader("Concourse Check-In, Live Portal & Floor Scoring Station")
        st.caption("Display or share these direct portals with bowlers and floor score verifiers prior to launching the squad.")

        base = _get_base_url()
        checkin_url = public_checkin_url(base, t_id)
        portal_url = f"{base}/?mode=bowler&t={t_id}"
        scorer_url = f"{base}/?mode=score&t={t_id}"

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