"""Public Bowler Self-Service Portal, Concourse Arrival Gate & 'My Action' Bracket Tracker."""

from datetime import datetime
import pandas as pd
import streamlit as st

from components.styles import inject_styles
from modules.brackets import init_bracket_tables
from modules.db_state import get_connection, log_desk_action


def _get_active_tournaments() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, host_center, status, game_count FROM tournaments "
            "WHERE status = 'active' ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_tournament_bowlers(tournament_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, usbc_id, entering_avg, handicap, lane_assignment, "
            "lineup_position, paid_status, checked_in, checked_in_at, is_youth "
            "FROM bowlers WHERE tournament_id = ? ORDER BY lane_assignment ASC, lineup_position ASC",
            (tournament_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _confirm_check_in(bowler_id: int, bowler_name: str) -> bool:
    """Updates bowler check-in state and records audit log without nested transaction deadlocks."""
    conn = get_connection()
    now_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    updated = False
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE bowlers SET checked_in = 1, checked_in_at = ? WHERE id = ?",
                (now_str, bowler_id),
            )
            updated = cursor.rowcount > 0
    finally:
        conn.close()

    if updated:
        try:
            log_desk_action(bowler_name, "bowler", "Bowler confirmed self check-in via mobile portal")
        except Exception:
            pass
        return True
    return False


def _render_checkin_flow(active_tourneys: list[dict]) -> None:
    """Dedicated arrival verification gate for bowlers."""
    st.markdown(
        """<div style="background: linear-gradient(135deg, #064E3B 0%, #0F172A 100%); border: 1px solid #10B981; border-radius: 12px; padding: 18px; text-align: center; margin-bottom: 20px;">
<span style="background: #10B981; color: #022C22; font-size: 11px; font-weight: 800; padding: 3px 10px; border-radius: 999px; text-transform: uppercase;">CHUSBC Arrival Gate</span>
<h2 style="color: #F8FAFC; margin: 10px 0 4px 0;">🎳 Bowler Self Check-In</h2>
<p style="color: #6EE7B7; font-size: 13px; margin-bottom: 0;">Confirm entry, verify entry fee payment & receive lane assignment</p>
</div>""",
        unsafe_allow_html=True,
    )

    if not active_tourneys:
        st.warning("No active tournament check-in is currently open. Check with tournament desk.")
        return

    tourney = active_tourneys[0] if len(active_tourneys) == 1 else None
    if not tourney:
        tourney_map = {f"{t['name']} ({t['host_center']})": t for t in active_tourneys}
        choice = st.selectbox("Select Your Tournament", list(tourney_map.keys()))
        tourney = tourney_map[choice]

    bowlers = _get_tournament_bowlers(tourney["id"])
    if not bowlers:
        st.info("Roster has not been ingested by the tournament desk yet.")
        return

    names = [b["name"] for b in bowlers]
    selected_name = st.selectbox("Find Your Name", ["-- Select Your Name --"] + names)

    if selected_name != "-- Select Your Name --":
        record = next(b for b in bowlers if b["name"] == selected_name)
        is_paid = record["paid_status"] == "paid"
        is_checked = bool(record["checked_in"])

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            col_l, col_r = st.columns([2, 1])
            with col_l:
                st.subheader(record["name"])
                usbc = record["usbc_id"] or "Not on file"
                st.caption(f"USBC ID: **{usbc}** | Entering Avg: **{record['entering_avg'] or 'N/A'}** | HDCP: **+{record['handicap']}**")
            with col_r:
                if is_paid:
                    st.markdown("<div style='text-align:right;'><span style='background:#064E3B; color:#6EE7B7; font-weight:700; padding:4px 10px; border-radius:6px;'>PAID IN FULL</span></div>", unsafe_allow_html=True)
                else:
                    st.markdown("<div style='text-align:right;'><span style='background:#7F1D1D; color:#FCA5A5; font-weight:700; padding:4px 10px; border-radius:6px;'>UNPAID BALANCE</span></div>", unsafe_allow_html=True)

            st.markdown("---")

            if not is_paid:
                st.error("⚠️ Entry fee balance required before starting lane can be assigned. Please step up to the tournament desk cash window.")
            elif is_checked:
                st.markdown(
                    f"""<div style="background:#0F172A; border:2px solid #10B981; border-radius:10px; padding:20px; text-align:center;">
<span style="color:#6EE7B7; font-weight:700; font-size:12px;">CHECK-IN VERIFIED</span>
<h1 style="color:#FFFFFF; margin:8px 0; font-size:36px;">LANE {record['lane_assignment']}</h1>
<p style="color:#94A3B8; font-size:12px; margin:0;">Arrival Timestamp: {record['checked_in_at'] or 'Registered'}</p>
</div>""",
                    unsafe_allow_html=True,
                )
            else:
                st.info("Your entry is verified and paid. Tap below to confirm arrival.")
                if st.button("Confirm Check-In & Get Lane", type="primary", use_container_width=True):
                    if _confirm_check_in(record["id"], record["name"]):
                        st.success(f"Checked in! Proceed to Lane {record['lane_assignment']}.")
                        st.rerun()


def _render_my_action_tab(tournament_id: int) -> None:
    """Personalized Alive-In Bracket Tracker for bowlers."""
    init_bracket_tables()
    st.subheader("🎯 My Action — Live Bracket & Pot Status")
    bowlers = _get_tournament_bowlers(tournament_id)
    if not bowlers:
        st.info("No active bowlers found.")
        return

    selected_bowler_name = st.selectbox("Select Your Name to View Action", ["-- Select Name --"] + [b["name"] for b in bowlers])
    if selected_bowler_name == "-- Select Name --":
        st.caption("Select your name to check active brackets, match-up status, and guaranteed equity.")
        return

    bowler = next(b for b in bowlers if b["name"] == selected_bowler_name)
    b_id = bowler["id"]

    conn = get_connection()
    try:
        entries = conn.execute(
            """SELECT be.*, br.bracket_number, br.bracket_type, br.status as bracket_status
FROM bracket_entries be
JOIN brackets br ON be.bracket_id = br.id
WHERE be.bowler_id = ? AND br.tournament_id = ?""",
            (b_id, tournament_id),
        ).fetchall()

        if not entries:
            st.info(f"{bowler['name']} is not entered in any brackets for this squad.")
            return

        total_brackets = len(entries)
        alive_count = 0
        total_payout = sum(e["payout_amount"] for e in entries)

        for e in entries:
            if e["r3_advances"] == 1 or e["r2_advances"] == 1 or (e["r1_advances"] == 1 and e["r2_score"] is None) or (e["r1_score"] is None):
                alive_count += 1

        c1, c2 = st.columns(2)
        with c1:
            st.metric("Bracket Status", f"{alive_count} of {total_brackets} Alive", delta=f"{alive_count} Active")
        with c2:
            st.metric("Guaranteed Earnings", f"${total_payout:.2f}", delta="SMART" if bowler["is_youth"] else "Cash")

        st.markdown("---")
        st.markdown("#### Individual Bracket Cards")
        for e in entries:
            with st.container(border=True):
                col_info, col_status = st.columns([3, 1])
                with col_info:
                    st.markdown(f"**Bracket #{e['bracket_number']}** ({e['bracket_type'].upper()}) — Seed #{e['seed_position']}")
                    scores_str = f"R1: **{e['r1_score'] or '-'}** | R2: **{e['r2_score'] or '-'}** | R3: **{e['r3_score'] or '-'}**"
                    st.caption(scores_str)
                with col_status:
                    if e["payout_amount"] > 0:
                        st.success(f"🏆 Won ${e['payout_amount']:.0f}")
                    elif e["r1_score"] is not None and e["r1_advances"] == 0:
                        st.error("Eliminated (R1)")
                    elif e["r2_score"] is not None and e["r2_advances"] == 0:
                        st.error("Eliminated (R2)")
                    elif e["r3_score"] is not None and e["r3_advances"] == 0:
                        st.info("2nd Place")
                    else:
                        st.markdown("<span style='background:#064E3B; color:#6EE7B7; padding:4px 8px; border-radius:4px; font-weight:700;'>🟢 ALIVE</span>", unsafe_allow_html=True)
    finally:
        conn.close()


@st.fragment(run_every="8s")
def _render_live_standings_table(tourney: dict) -> None:
    """Auto-polling broadcast-styled standings board with podium badges and cut lines."""
    conn = get_connection()
    try:
        bowler_rows = conn.execute(
            """SELECT id, name, lane_assignment, lineup_position, entering_avg, handicap, checked_in, is_pacer
FROM bowlers WHERE tournament_id = ? AND is_pacer = 0 ORDER BY lane_assignment ASC, lineup_position ASC""",
            (tourney["id"],),
        ).fetchall()

        sql = """SELECT b.id, b.name, b.lane_assignment, b.handicap,
COUNT(s.game_number) as games_bowled,
COALESCE(SUM(s.scratch_score), 0) as total_scratch,
COALESCE(SUM(s.total_score), 0) as grand_total
FROM bowlers b
LEFT JOIN scores s ON b.id = s.bowler_id
WHERE b.tournament_id = ? AND b.is_pacer = 0
GROUP BY b.id
ORDER BY grand_total DESC, total_scratch DESC"""
        rows = [dict(r) for r in conn.execute(sql, (tourney["id"],)).fetchall()]

        total_field = len(bowler_rows)
        checked_field = sum(1 for b in bowler_rows if b["checked_in"])
        all_checked = (checked_field == total_field) and total_field > 0

        # Pre-competition State
        if not rows or rows[0]["games_bowled"] == 0:
            if all_checked:
                st.markdown(
                    """<div style="background: linear-gradient(135deg, #064E3B 0%, #0F172A 100%); border: 1px solid #10B981; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
<div>
<h3 style="color: #ECFDF5; margin: 0 0 4px 0; font-size: 18px;">🎳 Squad In Progress &middot; Game 1 Scores Pending</h3>
<p style="color: #6EE7B7; font-size: 13px; margin: 0;">All bowlers confirmed on lanes. Standings board will update automatically.</p>
</div>
<span style="background: #10B981; color: #022C22; font-weight: 800; font-size: 11px; padding: 4px 10px; border-radius: 999px;">ON LANES</span>
</div>""",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"""<div style="background: #1E293B; border: 1px solid #334155; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px;">
<h4 style="color: #F8FAFC; margin: 0 0 4px 0;">⏳ Tournament Check-In Phase</h4>
<p style="color: #94A3B8; font-size: 13px; margin: 0;">Paddock gate open ({checked_field} of {total_field} bowlers confirmed). Scores will appear once competition commences.</p>
</div>""",
                    unsafe_allow_html=True,
                )

            if bowler_rows:
                st.markdown("#### Official Squad Lane Pairings")
                pair_data = []
                for b in bowler_rows:
                    pair_data.append({
                        "Lane": b["lane_assignment"],
                        "Position": f"#{b['lineup_position']}",
                        "Bowler Name": b["name"],
                        "Entering Avg": b["entering_avg"] or "N/A",
                        "HDCP / Game": f"+{b['handicap']}",
                        "Check-In Status": "✅ Checked In" if b["checked_in"] else "⏳ Awaiting Arrival",
                    })
                st.dataframe(pd.DataFrame(pair_data), hide_index=True, use_container_width=True)
            return

        # Active Competition Leaderboard
        leader = rows[0]

        # Top Leader Highlight Card
        st.markdown(
            f"""<div style="background: linear-gradient(135deg, #1E1B4B 0%, #0F172A 100%); border: 1px solid #6366F1; border-radius: 12px; padding: 16px 20px; margin-bottom: 18px; display: flex; justify-content: space-between; align-items: center;">
<div>
<span style="background: #4F46E5; color: #EEF2FF; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; text-transform: uppercase;">👑 CURRENT TOURNAMENT LEADER</span>
<h2 style="color: #FFFFFF; margin: 6px 0 2px 0; font-size: 24px;">{leader['name']}</h2>
<span style="color: #A5B4FC; font-size: 12px;">Lane {leader['lane_assignment']} &middot; Scratch: <b>{leader['total_scratch']}</b> (+{leader['handicap']} HDCP/gm)</span>
</div>
<div style="text-align: right;">
<div style="font-size: 32px; font-weight: 900; color: #38BDF8; line-height: 1;">{leader['grand_total']}</div>
<span style="color: #94A3B8; font-size: 11px; font-weight: 700; text-transform: uppercase;">Total Score ({leader['games_bowled']}/{tourney['game_count']} Gms)</span>
</div>
</div>""",
            unsafe_allow_html=True,
        )

        st.markdown(
            """<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
<h4 style="color: #F8FAFC; margin: 0;">Live Cut-Line Standings</h4>
<span style="color: #10B981; font-weight: 700; font-size: 11px;">● LIVE (8s AUTO-UPDATE)</span>
</div>""",
            unsafe_allow_html=True,
        )

        table_rows_html = []
        for rank, r in enumerate(rows, start=1):
            if rank == 1:
                badge_html = "<span style='background:#F59E0B; color:#451A03; font-weight:900; padding:3px 8px; border-radius:6px; font-size:12px;'>🥇 1ST</span>"
                row_bg = "background: rgba(245, 158, 11, 0.08);"
            elif rank == 2:
                badge_html = "<span style='background:#94A3B8; color:#0F172A; font-weight:900; padding:3px 8px; border-radius:6px; font-size:12px;'>🥈 2ND</span>"
                row_bg = "background: rgba(148, 163, 184, 0.06);"
            elif rank == 3:
                badge_html = "<span style='background:#D97706; color:#451A03; font-weight:900; padding:3px 8px; border-radius:6px; font-size:12px;'>🥉 3RD</span>"
                row_bg = "background: rgba(217, 119, 6, 0.06);"
            else:
                badge_html = f"<span style='color:#94A3B8; font-weight:800; font-size:13px;'>#{rank}</span>"
                row_bg = ""

            diff_to_leader = r["grand_total"] - leader["grand_total"]
            diff_label = "LEADER" if diff_to_leader == 0 else f"{diff_to_leader}"
            diff_color = "#10B981" if diff_to_leader == 0 else "#94A3B8"

            row_markup = (
                f"<tr style='border-bottom: 1px solid #1E293B; {row_bg}'>"
                f"<td style='padding: 12px 14px; text-align: center;'>{badge_html}</td>"
                f"<td style='padding: 12px 14px;'><div style='font-weight: 700; color: #F8FAFC; font-size: 14px;'>{r['name']}</div>"
                f"<small style='color: #64748B;'>Lane {r['lane_assignment']} &bull; HDCP +{r['handicap']}</small></td>"
                f"<td style='padding: 12px 14px; text-align: center; color: #CBD5E1; font-weight: 600;'>{r['games_bowled']}</td>"
                f"<td style='padding: 12px 14px; text-align: right; color: #E2E8F0; font-weight: 600;'>{r['total_scratch']}</td>"
                f"<td style='padding: 12px 14px; text-align: right;'><span style='font-size: 16px; font-weight: 800; color: #38BDF8;'>{r['grand_total']}</span></td>"
                f"<td style='padding: 12px 14px; text-align: right; color: {diff_color}; font-weight: 700; font-size: 12px;'>{diff_label}</td>"
                "</tr>"
            )
            table_rows_html.append(row_markup)

        joined_rows = "".join(table_rows_html)
        full_table_html = (
            "<div style='background: #0B1120; border: 1px solid #334155; border-radius: 10px; overflow: hidden; margin-bottom: 24px;'>"
            "<table style='width: 100%; border-collapse: collapse; text-align: left; font-family: sans-serif;'>"
            "<thead>"
            "<tr style='background: #1E293B; border-bottom: 2px solid #334155; color: #94A3B8; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;'>"
            "<th style='padding: 10px 14px; text-align: center; width: 70px;'>Rank</th>"
            "<th style='padding: 10px 14px;'>Bowler</th>"
            "<th style='padding: 10px 14px; text-align: center; width: 80px;'>Games</th>"
            "<th style='padding: 10px 14px; text-align: right; width: 90px;'>Scratch</th>"
            "<th style='padding: 10px 14px; text-align: right; width: 110px;'>HDCP Total</th>"
            "<th style='padding: 10px 14px; text-align: right; width: 90px;'>+/- Cut</th>"
            "</tr>"
            "</thead>"
            f"<tbody>{joined_rows}</tbody>"
            "</table>"
            "</div>"
        )
        st.markdown(full_table_html, unsafe_allow_html=True)
    finally:
        conn.close()


def _render_standings_flow(active_tourneys: list[dict]) -> None:
    """Public live standings & cut-line leaderboard."""
    st.markdown(
        """<div style="display: flex; align-items: center; margin-bottom: 8px;">
<h2 style="color: #F8FAFC; margin: 0; font-size: 26px;">🎳 Live Bowler Portal & Standings</h2>
</div>""",
        unsafe_allow_html=True,
    )

    if not active_tourneys:
        st.info("No live tournament results currently available.")
        return

    tourney = active_tourneys[0]
    st.caption(f"Viewing: **{tourney['name']}** ({tourney['host_center']})")

    _render_live_standings_table(tourney)


def render_bowler_portal() -> None:
    """Entry point for all public bowler devices."""
    inject_styles()
    action = st.query_params.get("action")
    active_tourneys = _get_active_tournaments()

    if action == "checkin":
        _render_checkin_flow(active_tourneys)
    else:
        tab_standings, tab_my_action, tab_checkin = st.tabs(["📊 Live Standings", "🎯 My Action (Brackets)", "✅ Check-In"])
        with tab_standings:
            _render_standings_flow(active_tourneys)
        with tab_my_action:
            if active_tourneys:
                _render_my_action_tab(active_tourneys[0]["id"])
            else:
                st.info("No active tournament available.")
        with tab_checkin:
            _render_checkin_flow(active_tourneys)