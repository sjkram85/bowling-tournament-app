"""Finals closeout, prize payout audit, bracket/side-pot management, and USBC Rule 400 SMART compliance."""

from modules.practice import is_practice
from modules.standings import get_tournament as _get_t
import csv
import io
import pandas as pd
import streamlit as st

from modules.auth import current_user, is_admin
from modules.brackets import create_brackets_for_tournament, event_uses_brackets, get_bracket_financial_ledger
from modules.cde_bls_bridge import build_bls_streams
from modules.db_state import get_connection, log_desk_action
from modules.placement import closeout_standings
from modules.reports import (
    build_certified_pdf,
    certified_pdf_filename,
    freeze_tournament,
    latest_archive,
    reopen_tournament,
)
from modules.standings import get_tournament as _full_tournament


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


def _audit_rows(table: dict) -> list[dict]:
    rows = []
    for bowler in table["rows"]:
        if bowler["withheld"]:
            prize_txt, routing = "Withheld", bowler["withheld"]
        elif bowler["prize"] > 0 and bowler["is_youth"]:
            prize_txt, routing = f"${bowler['prize']:.2f}", "USBC SMART Scholarship"
        elif bowler["prize"] > 0:
            prize_txt, routing = f"${bowler['prize']:.2f}", "Direct Payout (Cash/Check)"
        else:
            prize_txt, routing = "—", "No Payout"
        if bowler["place"]:
            rank = f"#{bowler['place']}"
        elif bowler.get("qual_rank"):
            rank = f"Qual #{bowler['qual_rank']}"
        else:
            rank = "—"
        division = bowler["group_label"] or ("YOUTH (Rule 400)" if bowler["is_youth"] else "ADULT")
        if bowler["champion"]:
            division += " · CHAMPION"
        elif bowler["finalist"]:
            division += " · FINALIST"
        elif bowler["rolloff"]:
            division += " · TIE – ROLL-OFF"
        rows.append({
            "Place": rank,
            "Qual": f"#{bowler['qual_rank']}" if bowler.get("qual_rank") else "—",
            "Bowler": bowler["name"],
            "USBC ID": bowler["usbc_id"] or "N/A",
            "Grand Total": bowler["grand_total"],
            "Division": division,
            "Prize": prize_txt,
            "Payout Routing": routing,
        })
    return rows


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

    # Same placement as the certified PDF: stepladder champion is 1st. Unfinished ladder/roll-off pays nothing.
    table = closeout_standings(t_id)
    audit_rows = _audit_rows(table)
    smart_total = table["smart_total"]
    cash_total = table["cash_total"]
    total_prize_fund = smart_total + cash_total
    standings = table["rows"]

    # --- TAB 1: FINAL STANDINGS ---
    with tab_standings:
        st.subheader("Official Standings & Prize Distribution")
        st.caption("Place matches the certified PDF and the SMART export. The stepladder champion is 1st. "
                   "Awards stay withheld until every roll-off and stepladder match is finished.")
        for warning in table["warnings"]:
            st.warning(warning)
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
        full = _full_tournament(t_id) or {}
        if not event_uses_brackets(full):
            st.info("This event does not include brackets. No bracket money is calculated, "
                    "so this screen cannot invent a side-pot payout.")
            ledger = None
        else:
            st.caption("Automatically generate 8-person single-elimination brackets and audit side pot collections.")
            if st.button("🎲 Generate 8-Person Brackets (Handicap)", type="primary", use_container_width=True):
                count = create_brackets_for_tournament(t_id, bracket_type="handicap")
                if count > 0:
                    log_desk_action(td_name, "td", f"Generated {count} handicap brackets for tournament #{t_id}")
                    st.success(f"Successfully generated {count} bracket(s)!")
                    st.rerun()
                else:
                    st.warning("Not enough bowlers on roster (minimum 8 required per bracket).")
            ledger = get_bracket_financial_ledger(t_id)

        if ledger is not None:
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
                    from modules.reports import save_tournament_archive
                    save_tournament_archive(t_id, td_name, pdf_bytes=pdf_bytes)
                    st.session_state[f"cert_pdf_{t_id}"] = pdf_bytes
                    st.success("Certified PDF saved to the Archive Vault.")
                except Exception as e:
                    st.error(f"Error compiling certified PDF: {e}")
            cached_pdf = st.session_state.get(f"cert_pdf_{t_id}")
            if cached_pdf:
                st.download_button(
                    label="⬇️ Download Certified PDF",
                    data=cached_pdf,
                    file_name=certified_pdf_filename(_get_t(t_id)),
                    mime="application/pdf",
                    use_container_width=True,
                )

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
        event_status = str((_full_tournament(t_id) or {}).get("status") or "").lower()
        if event_status == "closed":
            st.success("This event is frozen. Scores were not deleted. Floor scoring is locked until an admin reopens it.")
            archived = latest_archive(t_id)
            if archived and archived.get("certified_pdf"):
                st.download_button(
                    "⬇️ Download the certified PDF saved at freeze",
                    data=archived["certified_pdf"],
                    file_name=certified_pdf_filename(_get_t(t_id)),
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"frozen_pdf_{t_id}",
                )
            else:
                st.warning("No certified PDF is in the Archive Vault for this freeze. Generate one above before you rely on the vault.")
            if is_admin():
                reopen_ok = st.checkbox("I need scoring open again. Reopen this frozen event.", key=f"reopen_ok_{t_id}")
                st.caption("Reopen keeps every score and the vault copy. It only unlocks the event.")
                if st.button("Reopen event", disabled=not reopen_ok, key=f"reopen_btn_{t_id}"):
                    if reopen_tournament(t_id, td_name):
                        st.success("Event reopened. Scores are unchanged.")
                        st.rerun()
                    else:
                        st.error("This event could not be reopened.")
        else:
            st.warning(
                "Freeze locks floor and desk scoring. It does not delete scores. "
                "The certified PDF is saved into the Archive Vault when you freeze. "
                "Download it before you leave. If this is too early, an admin can reopen the event."
            )
            if table["warnings"]:
                st.error("Awards are still withheld: " + " ".join(table["warnings"])
                         + " You can still freeze, but the PDF will not show those awards.")
            if not st.session_state.get(f"cert_pdf_{t_id}") and not latest_archive(t_id):
                st.warning("No certified PDF has been saved yet. Freezing will generate one and store it in the vault. "
                           "Prefer that over cancelling the event.")
            freeze_ok = st.checkbox("I have checked the standings and want to freeze this event.", key=f"freeze_ok_{t_id}")
            if st.button("🏁 Freeze Tournament & Lock Ledger", type="primary", use_container_width=True,
                         disabled=not freeze_ok):
                try:
                    pdf_bytes = st.session_state.get(f"cert_pdf_{t_id}") or build_certified_pdf(t_id, certified_by=td_name)
                    freeze_tournament(t_id, td_name, pdf_bytes=pdf_bytes)
                    st.session_state[f"cert_pdf_{t_id}"] = pdf_bytes
                    st.success(f"Tournament #{t_id} is frozen. Scores were kept and the PDF is in the Archive Vault.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Freeze stopped before locking scores: {e}")