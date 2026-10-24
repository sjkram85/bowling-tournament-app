"""Finals closeout, prize payout audit, bracket/side-pot management, and USBC Rule 400 SMART compliance."""

from modules.practice import is_practice
import csv
import io
import pandas as pd
import streamlit as st

from modules.auth import current_user
from modules.brackets import create_brackets_for_tournament, get_bracket_financial_ledger
from modules.cde_bls_bridge import build_bls_streams
from modules.db_state import get_connection, log_desk_action
from modules.reports import (
    build_certified_pdf,
    build_smart_scholarship_csv,
    freeze_tournament,
)


def _get_active_tournaments() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, host_center, status, game_count, squad_format FROM tournaments ORDER BY id DESC"
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
    st.title("🏆 Tournament Closeout & Desk Ledger")
    tournaments = _get_active_tournaments()

    if not tournaments:
        st.info("No tournament records available to close out.")
        return

    tourney_map = {f"{t['name']} (#{t['id']}) - {t['status'].upper()}": t for t in tournaments}
    selected_label = st.selectbox("Active Event", list(tourney_map.keys()))
    tourney = tourney_map[selected_label]
    t_id = tourney["id"]

    user = current_user() or {}
    td_name = user.get("display_name") or "Tournament Director"

    tab_standings, tab_brackets, tab_audit = st.tabs(
        ["📋 Final Standings & Closeout", "🌿 Brackets & Side Pots Ledger", "🔒 Audit & Compliance Vault"]
    )

    # Calculate prize totals across standings
    standings = _get_final_standings(t_id)
    prize_template = [120.00, 80.00, 50.00, 30.00]
    audit_rows = []
    smart_total = 0.0
    cash_total = 0.0

    if standings:
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
                "Rank": f"#{rank}",
                "Bowler": bowler["name"],
                "USBC ID": bowler["usbc_id"] or "N/A",
                "Grand Total": bowler["grand_total"],
                "Division": "YOUTH (Rule 400)" if is_youth else "ADULT",
                "Prize": f"${prize:.2f}",
                "Payout Routing": routing,
            })

    total_prize_fund = smart_total + cash_total

    # --- TAB 1: FINAL STANDINGS ---
    with tab_standings:
        st.subheader("Official Standings & Prize Distribution")
        if not standings:
            st.info("No scores recorded yet for this event.")
        else:
            df = pd.DataFrame(audit_rows)
            st.dataframe(df, hide_index=True, use_container_width=True)

            m1, m2, m3 = st.columns(3)
            m1.metric("Total Prize Fund", f"${total_prize_fund:.2f}")
            m2.metric("Adult Cash Payouts", f"${cash_total:.2f}")
            m3.metric("USBC SMART Escrow", f"${smart_total:.2f}")

    # --- TAB 2: BRACKETS & SIDE POTS LEDGER ---
    with tab_brackets:
        st.subheader("🌿 Bracket Pairings & Side-Pot Accounting")
        st.caption("Automatically generate 8-person single-elimination brackets and audit side pot collections.")

        col_b_act1, col_b_act2 = st.columns(2)
        with col_b_act1:
            if st.button("🎲 Generate 8-Person Brackets (Handicap)", type="primary", use_container_width=True):
                count = create_brackets_for_tournament(t_id, bracket_type="handicap")
                if count > 0:
                    log_desk_action(td_name, "td", f"Generated {count} handicap brackets for tournament #{t_id}")
                    st.success(f"Successfully generated {count} bracket(s)!")
                    st.rerun()
                else:
                    st.warning("Not enough bowlers on roster (minimum 8 required per bracket).")

        ledger = get_bracket_financial_ledger(t_id)

        st.markdown("##### Active Brackets Summary")
        if not ledger["brackets"]:
            st.info("No brackets currently initialized for this tournament.")
        else:
            df_b = pd.DataFrame(ledger["brackets"])
            st.dataframe(df_b, hide_index=True, use_container_width=True)

        st.metric(
            "Total Bracket & Pot Liability Payout",
            f"${ledger['bracket_payout_liability'] + ledger['pot_payout_liability']:.2f}",
        )

    # --- TAB 3: AUDIT & COMPLIANCE VAULT ---
    with tab_audit:
        st.subheader("Official Audit Exports & Compliance Vault")
        st.caption("Generate raw data files, CDE BLS software bridge files, and USBC SMART scholarship upload spreadsheets.")

        if is_practice(t_id):
            st.warning("PRACTICE MODE: exports, certified results and archiving are turned off for practice tournaments.")
            return
        # Fixed call: pass prize_pool explicitly to avoid missing argument TypeError
        smart_csv_data = build_smart_scholarship_csv(t_id, prize_pool=total_prize_fund)
        st.download_button(
            label="📥 Download USBC SMART Upload CSV",
            data=smart_csv_data,
            file_name=f"smart_escrow_tournament_{t_id}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        col_pdf, col_bls = st.columns(2)
        with col_pdf:
            if st.button("📄 Generate Certified Final Results PDF", use_container_width=True):
                try:
                    pdf_bytes = build_certified_pdf(t_id, certified_by=td_name)
                    st.download_button(
                        label="⬇️ Download Certified PDF",
                        data=pdf_bytes,
                        file_name=f"certified_standings_t{t_id}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                except Exception as e:
                    st.error(f"Error compiling certified PDF: {e}")

        with col_bls:
            if st.button("💾 Export CDE BLS Tournament Archive", use_container_width=True):
                try:
                    bls_streams = build_bls_streams(t_id)
                    st.download_button(
                        label="⬇️ Download BLS Export (.zip)",
                        data=bls_streams,
                        file_name=f"cde_bls_export_t{t_id}.zip",
                        mime="application/zip",
                        use_container_width=True,
                    )
                except Exception as e:
                    st.error(f"Error exporting BLS bridge: {e}")

        st.markdown("---")
        st.markdown("##### 🔒 Final Event Certification & Archive")
        st.caption("Freezing the tournament locks all scores, roster details, and payout figures as permanent historical records.")
        if st.button("🏁 Freeze Tournament & Lock Ledger", type="primary", use_container_width=True):
            freeze_tournament(t_id)
            log_desk_action(td_name, "td", f"Certified and permanently froze tournament #{t_id}")
            st.success(f"Tournament #{t_id} is officially finalized and locked!")
            st.rerun()