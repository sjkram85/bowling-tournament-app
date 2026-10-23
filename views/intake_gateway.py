"""Tournament intake dashboard."""

import io
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
TRIAGE_COLUMNS = ["Bowler Name", "USBC ID", "Entering Avg", "Handicap", "Paid", "Pacer"]


def default_handicap(
    average: int | None,
    base: int = DEFAULT_HANDICAP_BASE,
    pct: float = DEFAULT_HANDICAP_PERCENT,
) -> int:
    if average is None or average >= base:
        return 0
    return int((base - average) * pct)


def _empty_roster() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Bowler Name": pd.Series(dtype="str"),
            "USBC ID": pd.Series(dtype="str"),
            "Entering Avg": pd.Series(dtype="Int64"),
            "Handicap": pd.Series(dtype="Int64"),
            "Paid": pd.Series(dtype="bool"),
            "Pacer": pd.Series(dtype="bool"),
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
        }
        for r in records
    ]
    return pd.DataFrame(rows, columns=TRIAGE_COLUMNS).astype(
        {"Entering Avg": "Int64", "Handicap": "Int64", "Paid": "bool", "Pacer": "bool"}
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
                # Two bowlers per lane in roster order, wrapping at the center's lane count.
                lane = (index // 2) % lanes + 1
                connection.execute(
                    "INSERT INTO bowlers (tournament_id, name, usbc_id, entering_avg, handicap, "
                    "lane_assignment, lineup_position, is_pacer, paid_status, mystery_doubles_opt_in) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        tournament_id,
                        str(row[0]).strip(),
                        str(row[1]).strip() or None,
                        average,
                        handicap if handicap is not None else default_handicap(average),
                        lane,
                        index + 1,
                        int(bool(row[5])),
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
        },
    )
    st.caption(
        f"Leave Handicap blank to use {int(DEFAULT_HANDICAP_PERCENT * 100)}% of "
        f"{DEFAULT_HANDICAP_BASE} minus the entering average."
    )

    valid_now = edited[edited["Bowler Name"].fillna("").astype(str).str.strip() != ""]
    mystery = st.toggle(
        f"Run ${DEFAULT_MYSTERY_DOUBLES_FEE:.0f} Mystery Doubles side pot draw on start",
        help="Bowlers are randomly paired when the squad starts.",
    )
    st.session_state["intake_summary"] = {
        "bowlers": len(valid_now),
        "pacers": int(valid_now["Pacer"].fillna(False).astype(bool).sum()),
        "unpaid": int((~valid_now["Paid"].fillna(False).astype(bool)).sum()),
        "host_code": host_code,
        "mystery_doubles": mystery,
    }

    pin = st.text_input(
        "Scoring PIN (4 digits, for ?mode=score)",
        value=st.session_state.setdefault("intake_pin", f"{secrets.randbelow(10000):04d}"),
        max_chars=4,
    )

    # --- CONCOURSE & FLOOR ACCESS STATION ---
    st.markdown("---")
    st.markdown("### 📲 Concourse Check-In & Floor Scorer Access Station")
    st.caption("Display or share these QR codes with bowlers and floor score assistants prior to launching the squad.")

    qr_col1, qr_col2 = st.columns(2)

    bowler_url = "https://chusbc-desk.streamlit.app/?mode=bowler"
    scorer_url = "https://chusbc-desk.streamlit.app/?mode=score"

    with qr_col1:
        st.markdown(
            """
            <div style="background:#1E293B; border:1px solid #334155; border-radius:10px; padding:12px; text-align:center;">
                <h4 style="color:#F8FAFC; margin-bottom:4px;">Bowler Live Portal</h4>
                <p style="color:#94A3B8; font-size:12px; margin-bottom:8px;">Scan to view live standings, cuts & brackets</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        buf_b = _generate_qr_buffer(bowler_url)
        st.image(buf_b.getvalue(), caption="Bowler Live Tracker QR", width=220)
        st.markdown(f"[🔗 Open Bowler Portal Directly]({bowler_url})")

    with qr_col2:
        st.markdown(
            f"""
            <div style="background:#1E293B; border:1px solid #334155; border-radius:10px; padding:12px; text-align:center;">
                <h4 style="color:#F8FAFC; margin-bottom:4px;">Floor Verifier Portal</h4>
                <p style="color:#10B981; font-weight:700; font-size:14px; margin-bottom:8px;">🔑 Active PIN: {pin}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        buf_s = _generate_qr_buffer(scorer_url)
        st.image(buf_s.getvalue(), caption="Floor Assistant 10-Key Pad QR", width=220)
        st.markdown(f"[🔗 Open Mobile Scorer Directly]({scorer_url})")

    with st.expander("🖨️ Concourse Display / Printable Placard Mode", expanded=False):
        st.markdown(
            f"""
            <div style="background:#0F172A; border:2px dashed #475569; border-radius:12px; padding:20px; text-align:center;">
                <h2 style="color:#F8FAFC; margin-bottom:4px;">CECIL HARFORD USBC TOURNAMENT ACCESS</h2>
                <p style="color:#94A3B8; font-size:14px; margin-bottom:16px;">Scan either code below using your smartphone camera</p>
                <div style="display:flex; justify-content:space-around; align-items:center; flex-wrap:wrap; gap:20px;">
                    <div>
                        <h4 style="color:#38BDF8;">BOWLER LIVE PORTAL</h4>
                        <p style="color:#CBD5E1; font-size:12px;">Track Standings, High Pots & Cut Lines</p>
                    </div>
                    <div>
                        <h4 style="color:#34D399;">FLOOR SCORING PAD</h4>
                        <p style="color:#CBD5E1; font-size:12px;">Authorized Verifiers Only (PIN: <strong>{pin}</strong>)</p>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

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