"""Finals closeout, prize payout audit, bracket/side-pot management, and USBC Rule 400 SMART compliance."""

from modules.practice import is_practice
from modules.divisions import grouped_results
from modules.standings import get_tournament as _get_t
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
    certified_pdf_filename,
    freeze_tournament,
)


def _get_active_tournaments() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, host_center, status, game_count, squad_format, COALESCE(is_practice, 0) AS is_practice FROM tournaments ORDER BY id DESC"
        ).fetchall()
        from modules.event_delete import hide_in_closeout
        return [dict(r) for r in rows if not hide_in_closeout(dict(r))]
    finally:
        conn.close()


def _render_hidden_practice_cleanup(td_name: str) -> None:
    """Cancelled practice events are hidden from the picker; admins can clear them here in one go."""
    from modules.auth import is_admin
    from modules.event_delete import delete_event, hide_in_closeout
    if not is_admin():
        return
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, status, COALESCE(is_practice, 0) AS is_practice FROM tournaments").fetchall()]
    finally:
        conn.close()
    hidden = [r for r in rows if hide_in_closeout(r)]
    if not hidden:
        return
    with st.expander(f"🗑️ {len(hidden)} cancelled practice event(s) hidden from this list"):
        st.caption("Practice events are fake data. Removing them doesn't touch any real event.")
        for r in hidden:
            st.markdown(f"- {r['name']} (#{r['id']})")
        sure = st.checkbox("Yes, delete these practice events", key="del_hidden_ok")
        if st.button("Delete practice events", disabled=not sure, key="del_hidden_btn"):
            for r in hidden:
                delete_event(r["id"], td_name)
            st.success("Practice events deleted.")
            st.rerun()


def _render_delete_box(t_id: int, tourney: dict, td_name: str) -> None:
    """Admin-only. Practice events (any status) and cancelled real events only; two-step confirm."""
    from modules.auth import is_admin
    from modules.event_delete import delete_block_reason, delete_event
    if not is_admin() or delete_block_reason(t_id):
        return
    with st.expander("🗑️ Delete this event"):
        st.warning(f"This permanently removes **{tourney['name']}** (#{t_id}) and all its bowlers, scores, "
                   "chat, logos, finals and brackets. It can't be undone. "
                   "**Download a backup first** (Backup & Restore in the sidebar).")
        typed = st.text_input("Type the event name to confirm", key=f"del_name_{t_id}")
        sure = st.checkbox("Yes, delete this event for good", key=f"del_ok_{t_id}")
        ok = sure and typed.strip().lower() == (tourney["name"] or "").strip().lower()
        if st.button("Delete event", type="primary", disabled=not ok, key=f"del_btn_{t_id}"):
            if delete_event(t_id, td_name):
                if st.session_state.get("active_tournament_id") == t_id:
                    st.session_state.pop("active_tournament_id", None)
                st.success("Event deleted.")
                st.rerun()
            else:
                st.error("This event can't be deleted.")


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
    _render_hidden_practice_cleanup((current_user() or {}).get("display_name") or "Tournament Director")

    if not tournaments:
        st.info("No tournament records available to close out.")
        return

    tourney_map = {f"{t['name']} (#{t['id']}) - {t['status'].upper()}": t for t in tournaments}
    labels = list(tourney_map.keys())
    active_id = st.session_state.get("active_tournament_id")
    default_idx = next((i for i, k in enumerate(labels) if tourney_map[k]["id"] == active_id), 0)
    selected_label = st.selectbox("Active Event", labels, index=default_idx)
    tourney = tourney_map[selected_label]
    t_id = tourney["id"]

    user = current_user() or {}
    td_name = user.get("display_name") or "Tournament Director"
    _render_delete_box(t_id, tourney, td_name)

    tab_standings, tab_brackets, tab_audit = st.tabs(
        ["📋 Final Standings & Closeout", "🌿 Brackets & Side Pots Ledger", "🔒 Audit & Compliance Vault"]
    )

    # Calculate prize totals across standings
    standings = _get_final_standings(t_id)
    prize_template = [120.00, 80.00, 50.00, 30.00]
    audit_rows = []
    smart_total = 0.0
    cash_total = 0.0

    groups = grouped_results(t_id)
    group_info = {r["id"]: (g, r) for g in groups for r in g["rows"]}
    if groups:
        # Division tournaments: ranks and prizes are per group; order the table group by group.
        standings = [r for g in groups for r in g["rows"]]
    if standings:
        for rank, bowler in enumerate(standings, start=1):
            if groups:
                g, gr = group_info[bowler["id"]]
                rank = gr["rank"]
                prize = gr["prize"]
            else:
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
                "Division": (group_info[bowler["id"]][0]["group"] + (" · FINALIST" if group_info[bowler["id"]][1]["finalist"] else (" · TIE – ROLL-OFF" if group_info[bowler["id"]][1].get("rolloff") else "")))
                if groups else ("YOUTH (Rule 400)" if is_youth else "ADULT"),
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

        st.markdown("---")
        from components.stepladder_box import render_stepladder_box
        render_stepladder_box(t_id, td_name)

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
        from components.smart_export_box import render_smart_export_box
        render_smart_export_box(t_id)

        col_pdf, col_bls = st.columns(2)
        with col_pdf:
            if st.button("📄 Generate Certified Final Results PDF", use_container_width=True):
                try:
                    pdf_bytes = build_certified_pdf(t_id, certified_by=td_name)
                    st.download_button(
                        label="⬇️ Download Certified PDF",
                        data=pdf_bytes,
                        file_name=certified_pdf_filename(_get_t(t_id)),
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