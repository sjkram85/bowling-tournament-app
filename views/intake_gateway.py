"""Tournament intake dashboard."""

import io
import os
import secrets

import pandas as pd
import qrcode
import streamlit as st

from modules.auth import current_user
from modules.cde_bls_bridge import parse_bls_bits_file
from modules.constants import (
    CENTERS,
    DEFAULT_HANDICAP_BASE,
    DEFAULT_HANDICAP_PERCENT,
    DEFAULT_MYSTERY_DOUBLES_FEE,
)
from modules.db_state import get_connection, init_db, log_desk_action
from modules.mystery_doubles import generate_mystery_doubles_draw

FORMATS = ["Singles", "Doubles", "Teams 3", "Teams 4", "Teams 5"]
HOST_OPTIONS = {code: CENTERS[code]["name"] for code in ("FHL", "HL", "APG")}
TRIAGE_COLUMNS = ["Bowler Name", "USBC ID", "Entering Avg", "Handicap", "Paid", "Pacer", "Youth"]


def default_handicap(
    average: int | None,
    base: int = DEFAULT_HANDICAP_BASE,
    pct: float = DEFAULT_HANDICAP_PERCENT,
) -> int:
    if average is None or average >= base:
        return 0
    return int((base - average) * pct)


def _get_base_url() -> str:
    """Dynamically determine current host environment base URL."""
    return st.secrets.get("APP_BASE_URL", "https://chusbc-desk.streamlit.app")


def _empty_roster() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Bowler Name": pd.Series(dtype="str"),
            "USBC ID": pd.Series(dtype="str"),
            "Entering Avg": pd.Series(dtype="Int64"),
            "Handicap": pd.Series(dtype="Int64"),
            "Paid": pd.Series(dtype="bool"),
            "Pacer": pd.Series(dtype="bool"),
            "Youth": pd.Series(dtype="bool"),
        }
    )


def _records_to_frame(records: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "Bowler Name": r["name"],
            "USBC ID": r["usbc_id"] or "",
            "Entering Avg": r["entering_avg"],
            "Handicap": r["handicap"] if r["handicap"] is not None else default_handicap(r["entering_avg"]),
            "Paid": False,
            "Pacer": False,
            "Youth": False,
        }
        for r in records
    ]
    return pd.DataFrame(rows, columns=TRIAGE_COLUMNS).astype(
        {"Entering Avg": "Int64", "Handicap": "Int64", "Paid": "bool", "Pacer": "bool", "Youth": "bool"}
    )


def _int_or_none(value) -> int | None:
    return None if pd.isna(value) else int(value)


def _generate_qr_buffer(url: str) -> io.BytesIO:
    """Generate high-contrast QR code image in memory."""
    qr = qrcode.QRCode(box_size=5, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _create_tournament(name, host_code, squad_format, game_count, roster, mystery_doubles, pin) -> int:
    lanes = CENTERS[host_code]["lanes"]
    connection = get_connection()
    try:
        with connection:
            tournament_id = connection.execute(
                "INSERT INTO tournaments (name, host_center, squad_format, game_count, handicap_base, "
                "handicap_pct, status, mystery_doubles_enabled, mystery_doubles_fee, pin_verifier) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (
                    name,
                    host_code,
                    squad_format,
                    game_count,
                    DEFAULT_HANDICAP_BASE,
                    DEFAULT_HANDICAP_PERCENT,
                    int(mystery_doubles),
                    DEFAULT_MYSTERY_DOUBLES_FEE,
                    pin,
                ),
            ).lastrowid
            for index, row in enumerate(roster.itertuples(index=False)):
                average = _int_or_none(row[2])
                handicap = _int_or_none(row[3])
                lane = (index // 2) % lanes + 1
                connection.execute(
                    "INSERT INTO bowlers (tournament_id, name, usbc_id, entering_avg, handicap, "
                    "lane_assignment, lineup_position, is_pacer, is_youth, paid_status, mystery_doubles_opt_in) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        tournament_id,
                        str(row[0]).strip(),
                        str(row[1]).strip() or None,
                        average,
                        handicap if handicap is not None else default_handicap(average),
                        lane,
                        index + 1,
                        int(bool(row[5])),
                        int(bool(row[6])),
                        "paid" if row[4] else "unpaid",
                        int(mystery_doubles),
                    ),
                )
        return tournament_id
    finally:
        connection.close()


def render_intake_gateway() -> None:
    init_db()
    st.title("Tournament Intake")

    with st.container(border=True):
        st.subheader("Event setup")
        name = st.text_input("Tournament name")
        col_format, col_host = st.columns(2)
        squad_format = col_format.selectbox("Squad format", FORMATS)
        host_code = col_host.selectbox(
            "Host center", list(HOST_OPTIONS), format_func=HOST_OPTIONS.__getitem__
        )
        game_count = st.slider("Game count", 1, 10, 3)

    with st.container(border=True):
        st.subheader("Roster ingestion")
        upload = st.file_uploader("Optional: CDE Software BLS BITS roster file", type=["csv", "txt", "dat"])
        if upload is not None and st.session_state.get("intake_upload_id") != upload.file_id:
            st.session_state["intake_upload_id"] = upload.file_id
            st.session_state["intake_roster"] = _records_to_frame(parse_bls_bits_file(upload.getvalue()))

    roster = st.session_state.setdefault("intake_roster", _empty_roster())
    st.subheader("Desk triage")
    edited = st.data_editor(
        roster,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key="intake_editor",
        column_config={
            "Bowler Name": st.column_config.TextColumn(required=True),
            "Entering Avg": st.column_config.NumberColumn(min_value=0, max_value=300, step=1),
            "Handicap": st.column_config.NumberColumn(min_value=0, max_value=200, step=1),
            "Paid": st.column_config.CheckboxColumn("Paid", default=False),
            "Pacer": st.column_config.CheckboxColumn("Is Pacer", default=False),
            "Youth": st.column_config.CheckboxColumn("Rule 400 Youth", default=False),
        },
    )
    st.caption(
        f"Handicap auto-defaults to {int(DEFAULT_HANDICAP_PERCENT * 100)}% of "
        f"{DEFAULT_HANDICAP_BASE} minus entering average."
    )

    valid_now = edited[edited["Bowler Name"].fillna("").astype(str).str.strip() != ""]
    mystery = st.toggle(
        f"Run ${DEFAULT_MYSTERY_DOUBLES_FEE:.0f} Mystery Doubles side pot draw on start",
        help="Bowlers are randomly paired when the squad starts.",
    )
    st.session_state["intake_summary"] = {
        "bowlers": len(valid_now),
        "pacers": int(valid_now["Pacer"].fillna(False).astype(bool).sum()),
        "youth": int(valid_now["Youth"].fillna(False).astype(bool).sum()),
        "unpaid": int((~valid_now["Paid"].fillna(False).astype(bool)).sum()),
        "host_code": host_code,
        "mystery_doubles": mystery,
    }

    pin = st.text_input(
        "Scoring PIN (4 digits, for ?mode=score)",
        value=st.session_state.setdefault("intake_pin", f"{secrets.randbelow(10000):04d}"),
        max_chars=4,
    )

    # --- UNIFIED 3-PORTAL CONCOURSE ACCESS STATION ---
    st.markdown("---")
    st.markdown("### 📲 Concourse Check-In, Live Portal & Floor Scoring Station")
    st.caption("Display or share these direct portals with bowlers and floor score verifiers prior to launching the squad.")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    base = _get_base_url()
    checkin_url = f"{base}/?mode=bowler&action=checkin"
    portal_url = f"{base}/?mode=bowler"
    scorer_url = f"{base}/?mode=score"

    buf_checkin = _generate_qr_buffer(checkin_url)
    buf_portal = _generate_qr_buffer(portal_url)
    buf_scorer = _generate_qr_buffer(scorer_url)

    col1, col2, col3 = st.columns(3, gap="medium")

    with col1:
        with st.container(border=True):
            st.markdown(
                """
                <div style="text-align:center; min-height:110px;">
                    <span style="background:#064E3B; color:#6EE7B7; font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px;">
                        ARRIVAL GATE
                    </span>
                    <h4 style="color:#F8FAFC; margin:10px 0 4px 0;">🎳 Bowler Check-In</h4>
                    <p style="color:#94A3B8; font-size:12px; margin-bottom:0;">Verify paid status & unlock starting lane</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
            st.image(buf_checkin.getvalue(), caption="Scan to Check In", use_container_width=True)
            st.markdown(f"[🔗 Open Check-In]({checkin_url})")

    with col2:
        with st.container(border=True):
            st.markdown(
                """
                <div style="text-align:center; min-height:110px;">
                    <span style="background:#0284C7; color:#BAE6FD; font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px;">
                        LIVE TRACKER
                    </span>
                    <h4 style="color:#F8FAFC; margin:10px 0 4px 0;">📊 Bowler Portal</h4>
                    <p style="color:#94A3B8; font-size:12px; margin-bottom:0;">Live standings, cut line & brackets</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
            st.image(buf_portal.getvalue(), caption="Scan for Live Standings", use_container_width=True)
            st.markdown(f"[🔗 Open Bowler Portal]({portal_url})")

    with col3:
        with st.container(border=True):
            st.markdown(
                f"""
                <div style="text-align:center; min-height:110px;">
                    <span style="background:#1E3A8A; color:#93C5FD; font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px;">
                        STAFF / VERIFIERS
                    </span>
                    <h4 style="color:#F8FAFC; margin:10px 0 4px 0;">📱 Floor Scoring</h4>
                    <p style="color:#10B981; font-weight:700; font-size:12px; margin-bottom:0;">🔑 Active PIN: {pin}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
            st.image(buf_scorer.getvalue(), caption="Floor 10-Key Pad", use_container_width=True)
            st.markdown(f"[🔗 Open Scorer Pad]({scorer_url})")

    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

    with st.expander("🖨️ Concourse Display / Printable Placard Mode", expanded=False):
        st.markdown(
            f"""
            <div style="background:#0F172A; border:2px dashed #475569; border-radius:12px; padding:24px; text-align:center;">
                <h2 style="color:#F8FAFC; margin-bottom:4px;">CECIL HARFORD USBC TOURNAMENT ACCESS</h2>
                <p style="color:#94A3B8; font-size:14px; margin-bottom:20px;">Point your smartphone camera at the code for your role</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        p_col1, p_col2, p_col3 = st.columns(3)
        with p_col1:
            st.markdown("<div style='text-align:center;'><strong style='color:#34D399;'>1. BOWLER CHECK-IN</strong><br><small style='color:#94A3B8;'>Confirm Arrival & Lane</small></div>", unsafe_allow_html=True)
            st.image(buf_checkin.getvalue(), width=180)
        with p_col2:
            st.markdown("<div style='text-align:center;'><strong style='color:#38BDF8;'>2. LIVE STANDINGS</strong><br><small style='color:#94A3B8;'>Scores, Cut Line & Pots</small></div>", unsafe_allow_html=True)
            st.image(buf_portal.getvalue(), width=180)
        with p_col3:
            st.markdown(f"<div style='text-align:center;'><strong style='color:#F59E0B;'>3. FLOOR SCORING</strong><br><small style='color:#94A3B8;'>PIN: <strong>{pin}</strong></small></div>", unsafe_allow_html=True)
            st.image(buf_scorer.getvalue(), width=180)

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    if st.button("Start Squad", type="primary", width="stretch"):
        valid = edited[edited["Bowler Name"].fillna("").astype(str).str.strip() != ""]
        if not name.strip():
            st.error("Enter a tournament name.")
        elif valid.empty:
            st.error("Add at least one bowler.")
        elif not (len(pin) == 4 and pin.isdigit()):
            st.error("The scoring PIN must be exactly 4 digits.")
        else:
            tournament_id = _create_tournament(
                name.strip(), host_code, squad_format, game_count, valid, mystery, pin
            )
            pairs = generate_mystery_doubles_draw(tournament_id) if mystery else []
            user = current_user() or {}
            log_desk_action(
                user.get("display_name") or "Desk",
                user.get("role") or "td",
                f"Started tournament {tournament_id} '{name.strip()}' at {HOST_OPTIONS[host_code]} "
                f"with {len(valid)} bowlers, {game_count} games"
                + (f", Mystery Doubles drew {len(pairs)} pairs" if mystery else ""),
            )
            st.session_state["active_tournament_id"] = tournament_id
            st.session_state["intake_roster"] = _empty_roster()
            st.session_state["intake_pin"] = f"{secrets.randbelow(10000):04d}"
            st.session_state.pop("intake_editor", None)
            st.success(
                f"Started '{name.strip()}' with {len(valid)} bowlers. Scoring PIN: {pin}."
                + (f" Mystery Doubles drew {len(pairs)} pairs." if mystery else "")
            )