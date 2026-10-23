"""Finals closeout, prize payout audit, 5-seed stepladder finals, and USBC Rule 400 SMART compliance."""

import pandas as pd
import streamlit as st

from modules.auth import current_user
from modules.brackets import get_bracket_financial_ledger
from modules.db_state import get_connection, log_desk_action
from modules.stepladder import (
    get_stepladder_state,
    initialize_stepladder,
    record_stepladder_score,
)


def _get_active_tournaments() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, host_center, status, game_count FROM tournaments ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_final_standings(tournament_id: int) -> list[dict]:
    conn = get_connection()
    try:
        query = """
            SELECT b.id, b.name, b.usbc_id, b.is_youth, b.smart_account_id,
                   COUNT(s.game_number) as games_bowled,
                   COALESCE(SUM(s.scratch_score), 0) as total_scratch,
                   COALESCE(SUM(s.total_score), 0) as grand_total
            FROM bowlers b
            LEFT JOIN scores s ON b.id = s.bowler_id
            WHERE b.tournament_id = ? AND b.is_pacer = 0
            GROUP BY b.id
            ORDER BY grand_total DESC, total_scratch DESC
        """
        rows = conn.execute(query, (tournament_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def render_finals_close() -> None:
    st.title("🏆 Finals Closeout & Tournament Desk Ledger")
    tournaments = _get_active_tournaments()

    if not tournaments:
        st.info("No tournament data exists to close out.")
        return

    tourney_map = {f"{t['name']} (#{t['id']}) - {t['status'].upper()}": t for t in tournaments}
    selected_label = st.selectbox("Select Tournament", list(tourney_map.keys()))
    tourney = tourney_map[selected_label]
    t_id = tourney["id"]

    tab_stepladder, tab_standings, tab_brackets, tab_audit = st.tabs(
        ["🎳 5-Seed Stepladder Finals", "📋 Final Standings & Payouts", "🌿 Bracket & Side Pot Ledger", "🔒 Audit & Close"]
    )

    # =========================================================
    # TAB 1: 5-SEED STEPLADDER FINALS PROGRESSION
    # =========================================================
    with tab_stepladder:
        st.subheader("5-Seed Stepladder Match Play Finals")
        st.caption("Progression: Match 1 (#5 vs #4) ➔ Match 2 (Winner vs #3) ➔ Semi-Final (Winner vs #2) ➔ Championship (Winner vs #1)")

        col_init, col_refresh = st.columns([3, 1])
        with col_init:
            if st.button("⚡ Seed Stepladder from Cut Line", type="primary", use_container_width=True):
                if initialize_stepladder(t_id):
                    st.success("Top 5 seeds loaded and Match 1 launched!")
                    st.rerun()
                else:
                    st.error("Need at least 5 qualifying bowlers with recorded scores to seed stepladder.")
        with col_refresh:
            if st.button("🔄 Refresh Matches", use_container_width=True):
                st.rerun()

        matches = get_stepladder_state(t_id)
        if not matches:
            st.info("Click 'Seed Stepladder from Cut Line' above once qualifying games are completed.")
        else:
            for m in matches:
                with st.container(border=True):
                    st.markdown(f"**{m['match_name']}** — Status: `{m['status'].upper()}`")
                    b_low = m["low_name"] or "TBD (Awaiting Previous Match)"
                    b_high = m["high_name"] or "TBD"

                    c1, c2, c3 = st.columns([3, 3, 2])
                    with c1:
                        st.markdown(f"**Challenger (Lower Seed):** {b_low}")
                        score_low = st.number_input(f"Score for {b_low}", min_value=0, max_value=300, value=m["score_low"] or 0, key=f"sl_low_{m['id']}")
                    with c2:
                        st.markdown(f"**Defender (Higher Seed):** {b_high}")
                        score_high = st.number_input(f"Score for {b_high}", min_value=0, max_value=300, value=m["score_high"] or 0, key=f"sl_high_{m['id']}")
                    with c3:
                        st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
                        if m["status"] == "active":
                            # Check for tie
                            if score_low > 0 and score_high > 0 and score_low == score_high:
                                st.warning("Tie detected! Enter 9th/10th Frame Roll-Off below.")
                                ro_low = st.number_input(f"Roll-off {b_low}", min_value=0, max_value=60, key=f"ro_l_{m['id']}")
                                ro_high = st.number_input(f"Roll-off {b_high}", min_value=0, max_value=60, key=f"ro_h_{m['id']}")
                                if st.button("Submit Tiebreak", key=f"btn_tb_{m['id']}", use_container_width=True):
                                    if record_stepladder_score(m["id"], score_low, score_high, ro_low, ro_high):
                                        st.success("Tiebreak recorded and winner advanced!")
                                        st.rerun()
                            else:
                                if st.button("Record Match & Advance", key=f"btn_rec_{m['id']}", type="primary", use_container_width=True):
                                    if score_low > 0 and score_high > 0:
                                        if record_stepladder_score(m["id"], score_low, score_high):
                                            st.success("Winner advanced!")
                                            st.rerun()
                        elif m["status"] == "completed":
                            winner_label = m["winner_name"] or "Recorded"
                            st.success(f"🏆 Winner: **{winner_label}**")

    # =========================================================
    # TAB 2: FINAL STANDINGS & PRIZE PAYOUT AUDIT
    # =========================================================
    with tab_standings:
        st.subheader("Official Standings & Prize Fund Reconciliation")
        standings = _get_final_standings(t_id)
        if not standings:
            st.info("No scores recorded yet.")
        else:
            prize_template = [120.00, 80.00, 50.00, 30.00]
            audit_rows = []
            smart_total = 0.0
            cash_total = 0.0

            for rank, bowler in enumerate(standings, start=1):
                prize = prize_template[rank - 1] if rank <= len(prize_template) else 0.0
                is_youth = bool(bowler["is_youth"])
                
                if is_youth and prize > 0:
                    routing = "USBC SMART Scholarship"
                    smart_total += prize
                elif prize > 0:
                    routing = "Direct Payout (Cash/Check)"
                    cash_total += prize
                else:
                    routing = "No Payout"

                audit_rows.append({
                    "Rank": rank,
                    "Bowler": bowler["name"],
                    "USBC ID": bowler["usbc_id"] or "N/A",
                    "Scratch": bowler["total_scratch"],
                    "Grand Total": bowler["grand_total"],
                    "Division": "YOUTH (Rule 400)" if is_youth else "ADULT",
                    "Prize Award": f"${prize:.2f}",
                    "Disbursement Routing": routing,
                })

            df = pd.DataFrame(audit_rows)
            st.dataframe(df, hide_index=True, use_container_width=True)

            c1, c2, c3 = st.columns(3)
            c1.metric("Total Main Prize Fund", f"${(smart_total + cash_total):.2f}")
            c2.metric("Adult Cash Disbursements", f"${cash_total:.2f}")
            c3.metric("USBC SMART Allocations", f"${smart_total:.2f}")

    # =========================================================
    # TAB 3: BRACKET & SIDE POT FINANCIAL LEDGER
    # =========================================================
    with tab_brackets:
        st.subheader("8-Person Brackets & Side Pot Audit Ledger")
        ledger = get_bracket_financial_ledger(t_id)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Active Brackets", f"{ledger['num_brackets']} ({ledger['num_brackets'] * 8} entries)")
        c2.metric("Total Collected", f"${ledger['total_collected']:.2f}")
        c3.metric("Total Payouts", f"${ledger['total_payouts']:.2f}")
        c4.metric("Admin / Expense Fee", f"${ledger['admin_expenses']:.2f}")

        st.markdown("---")
        bal_col1, bal_col2 = st.columns([3, 1])
        with bal_col1:
            if ledger["net_balance"] == 0.0:
                st.success(f"⚖️ **Penny-Perfect Balance Verified**: Net Ledger Variance is strictly **${ledger['net_balance']:.2f}**.")
            else:
                st.warning(f"Ledger Variance: ${ledger['net_balance']:.2f} remaining to balance.")
        with bal_col2:
            st.metric("SMART Scholarship Escrow", f"${ledger['smart_payouts']:.2f}")

    # =========================================================
    # TAB 4: AUDIT LOG, PDF EXPORT & LOCKDOWN
    # =========================================================
    with tab_audit:
        st.subheader("Official Tournament Lockdown & Exports")
        st.caption("Finalizing will permanently lock all scores and generate the certified record.")

        col_close, col_csv = st.columns(2)
        with col_close:
            if st.button("🔒 Finalize & Lock Tournament", type="primary", use_container_width=True):
                conn = get_connection()
                try:
                    with conn:
                        conn.execute("UPDATE tournaments SET status = 'closed' WHERE id = ?", (t_id,))
                    user = current_user() or {}
                    log_desk_action(
                        user.get("display_name") or "Desk",
                        user.get("role") or "admin",
                        f"Finalized tournament #{t_id} '{tourney['name']}'",
                    )
                    st.success("Tournament marked as CLOSED. Audit records permanently archived.")
                    st.rerun()
                finally:
                    conn.close()

        with col_csv:
            if "df" in locals():
                csv_bytes = df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Download Payout & Audit CSV",
                    data=csv_bytes,
                    file_name=f"ptcc_tournament_{t_id}_audit.csv",
                    mime="text/csv",
                    use_container_width=True,
                )