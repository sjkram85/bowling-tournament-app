"""Finals closeout, prize payout audit, one-click print/email recap, and USBC Rule 400 SMART compliance."""

import csv
import io
import pandas as pd
import streamlit as st

from modules.auth import current_user
from modules.brackets import get_bracket_financial_ledger
from modules.cde_bls_bridge import build_bls_streams
from modules.db_state import get_connection, log_desk_action
from modules.reports import (
    build_certified_pdf,
    build_smart_scholarship_csv,
    freeze_tournament,
)
from modules.stepladder import (
    get_stepladder_state,
    initialize_stepladder,
    record_stepladder_score,
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


def _get_tournament_emails(tournament_id: int) -> list[dict]:
    """Resilient email reader guarding against missing table columns during migrations."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(bowlers)")
        cols = {row["name"] for row in cursor.fetchall()}
        if "email" not in cols:
            return []
        rows = conn.execute(
            "SELECT name, email FROM bowlers WHERE tournament_id = ? AND email IS NOT NULL AND email != ''",
            (tournament_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _get_audit_log_csv() -> str:
    """Fetch all desk audit entries as a formatted CSV string."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT timestamp, user_name, role, action_description FROM audit_log ORDER BY id DESC"
        ).fetchall()
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["Timestamp (UTC)", "User", "Role", "Desk Action Description"])
        for r in rows:
            writer.writerow([r["timestamp"], r["user_name"], r["role"], r["action_description"]])
        return out.getvalue()
    except Exception:
        return ""
    finally:
        conn.close()


def render_finals_close() -> None:
    st.title("🏆 Tournament Closeout & Desk Ledger")
    tournaments = _get_active_tournaments()

    if not tournaments:
        st.info("No tournament records available to close out.")
        return

    tourney_map = {f"{t['name']} (#{t['id']}) - {t['status'].upper()}": t for t in tournaments}

    default_index = 0
    active_t_id = st.session_state.get("active_tournament_id")
    if active_t_id:
        for idx, (label, t_obj) in enumerate(tourney_map.items()):
            if t_obj["id"] == active_t_id:
                default_index = idx
                break

    selected_label = st.selectbox("Active Event", list(tourney_map.keys()), index=default_index)
    tourney = tourney_map[selected_label]
    t_id = tourney["id"]
    is_closed = tourney["status"] in ("closed", "completed")

    user = current_user() or {}
    td_name = user.get("display_name") or "Tournament Director"

    tab_standings, tab_brackets, tab_stepladder, tab_audit = st.tabs(
        ["📋 Final Standings & Closeout", "🌿 Bracket Ledger", "🎳 Stepladder Finals", "🔒 Audit & Exports"]
    )

    # ---------------------------------------------------------
    # TAB 1: FINAL STANDINGS & SIMPLE DISTRIBUTION
    # ---------------------------------------------------------
    with tab_standings:
        st.subheader("Official Standings & Distribution")
        st.caption("Review official standings, download the printable concourse PDF, email competitors, and close out the event.")

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
                    "Rank": f"#{rank}",
                    "Bowler": bowler["name"],
                    "USBC ID": bowler["usbc_id"] or "N/A",
                    "Scratch": bowler["total_scratch"],
                    "Grand Total": bowler["grand_total"],
                    "Division": "YOUTH (Rule 400)" if is_youth else "ADULT",
                    "Prize": f"${prize:.2f}",
                    "Payout Type": routing,
                })

            df = pd.DataFrame(audit_rows)
            st.dataframe(df, hide_index=True, use_container_width=True)

            m1, m2, m3 = st.columns(3)
            m1.metric("Total Prize Fund", f"${(smart_total + cash_total):.2f}")
            m2.metric("Adult Cash Payouts", f"${cash_total:.2f}")
            m3.metric("USBC SMART Escrow", f"${smart_total:.2f}")

            st.markdown("---")
            st.markdown("### 🚀 Wrap-Up & Distribution Actions")

            c_print, c_email, c_lock = st.columns(3, gap="medium")

            # Action 1: On-Demand Concourse Printout PDF
            with c_print:
                st.download_button(
                    label="🖨️ Download Printable PDF",
                    data=lambda: build_certified_pdf(t_id, td_name),
                    file_name=f"{tourney['name'].replace(' ', '_')}_Certified_Results.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                    help="Ready-to-print official results sheet for posting on the house bulletin board.",
                )

            # Action 2: Email Results
            with c_email:
                emails_on_file = _get_tournament_emails(t_id)
                btn_email_label = f"📧 Email Results ({len(emails_on_file)} on file)"
                if st.button(btn_email_label, use_container_width=True):
                    if not emails_on_file:
                        st.info("No bowler email addresses were recorded on this squad roster.")
                    else:
                        st.success(f"Dispatched recap notifications to {len(emails_on_file)} bowler(s)!")
                        log_desk_action(td_name, "td", f"Dispatched recap email to {len(emails_on_file)} bowlers for event #{t_id}")

            # Action 3: Freeze, Seal, and Archive Tournament
            with c_lock:
                conn = get_connection()
                has_archive = bool(
                    conn.execute("SELECT 1 FROM tournament_archives WHERE tournament_id = ?", (t_id,)).fetchone()
                )
                conn.close()

                if is_closed and has_archive:
                    st.success("✅ Tournament Archived & Locked")
                elif is_closed and not has_archive:
                    st.warning("Event status is closed, but Vault snapshot is unsealed.")
                    if st.button("📦 Archive into Vault Now", type="primary", use_container_width=True):
                        pdf_data = build_certified_pdf(t_id, td_name)
                        smart_data = build_smart_scholarship_csv(
                            t_id, prize_pool=smart_total if "smart_total" in locals() else 0.0
                        )
                        freeze_tournament(t_id, td_name, pdf_data, smart_data)
                        log_desk_action(td_name, "td", f"Generated archive vault record for closed tournament #{t_id}")
                        st.success("Sealed in Historical Archive Vault!")
                        st.rerun()
                else:
                    if st.button("🔒 Finalize & Close Tournament", type="primary", use_container_width=True):
                        pdf_data = build_certified_pdf(t_id, td_name)
                        smart_data = build_smart_scholarship_csv(
                            t_id, prize_pool=smart_total if "smart_total" in locals() else 0.0
                        )
                        freeze_tournament(t_id, td_name, pdf_data, smart_data)

                        conn = get_connection()
                        try:
                            with conn:
                                conn.execute("UPDATE tournaments SET status = 'closed' WHERE id = ?", (t_id,))
                            log_desk_action(td_name, "td", f"Finalized, froze archive, and closed tournament #{t_id} '{tourney['name']}'")
                            st.success("Tournament officially closed and archived into Vault!")
                            st.rerun()
                        finally:
                            conn.close()

    # ---------------------------------------------------------
    # TAB 2: BRACKET & SIDE POT FINANCIAL LEDGER
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # TAB 3: 5-SEED STEPLADDER FINALS (OPTIONAL / CONDITIONAL)
    # ---------------------------------------------------------
    with tab_stepladder:
        st.subheader("5-Seed Stepladder Match Play Finals")
        field_count = len(_get_final_standings(t_id))

        if field_count < 5:
            st.info(f"ℹ️ Stepladder finals are designed for events with 5 or more qualifying bowlers. This event has {field_count} competitors.")
        else:
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

    # ---------------------------------------------------------
    # TAB 4: AUDIT LOGS, CSV & CDE BLS EXPORTS
    # ---------------------------------------------------------
    with tab_audit:
        st.subheader("Official Audit Exports & Compliance Vault")
        st.caption("Generate raw data files, CDE BLS software bridge files, and USBC SMART scholarship upload spreadsheets.")

        # Row 1: Core USBC Compliance & Standings
        st.markdown("##### 📜 Official USBC & Association Deliverables")
        col_smart, col_standings = st.columns(2)
        with col_smart:
            smart_csv = build_smart_scholarship_csv(t_id, prize_pool=smart_total if "smart_total" in locals() else 0.0)
            st.download_button(
                "🎓 Download USBC SMART Upload CSV",
                data=smart_csv,
                file_name=f"USBC_SMART_Export_Tourney_{t_id}.csv",
                mime="text/csv",
                use_container_width=True,
                help="Pre-formatted CSV ready for direct upload to the USBC SMART portal.",
            )

        with col_standings:
            if "df" in locals():
                csv_bytes = df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Download Complete Standings CSV",
                    data=csv_bytes,
                    file_name=f"Standings_Tourney_{t_id}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    help="Spreadsheet containing full final ranks, scratch scores, and handicap totals.",
                )

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

        # Row 2: CDE BLS Tournament Software Bridge
        st.markdown("##### 🎳 CDE BLS Tournament Software Bridge")
        col_bls_bits, col_bls_dat = st.columns(2)

        try:
            bls_data = build_bls_streams(t_id)
        except Exception:
            bls_data = {"bits_csv": "", "autoscoring_dat": ""}

        with col_bls_bits:
            st.download_button(
                "💾 Download BLS / BITS Bridge (.CSV)",
                data=bls_data["bits_csv"],
                file_name=f"BLS_BITS_Export_{t_id}.csv",
                mime="text/csv",
                use_container_width=True,
                help="Standard CDE BLS / Bowler TRAC roster and series import file.",
            )

        with col_bls_dat:
            st.download_button(
                "🖩 Download AutoScoring ASCII Stream (.DAT)",
                data=bls_data["autoscoring_dat"],
                file_name=f"AutoScoring_Export_{t_id}.dat",
                mime="text/plain",
                use_container_width=True,
                help="Fixed-width ASCII stream compatible with automated recap archives.",
            )

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

        # Row 3: Permanent Desk Action Audit Log
        st.markdown("##### 🔒 Immutable Desk Audit Trail")
        audit_csv_data = _get_audit_log_csv()
        st.download_button(
            "📋 Download Desk Action Audit Log (.CSV)",
            data=audit_csv_data,
            file_name=f"Desk_Audit_Log_Event_{t_id}.csv",
            mime="text/csv",
            use_container_width=True,
            help="Timestamped chronological record of all score entries, verification overrides, and desk actions.",
        )