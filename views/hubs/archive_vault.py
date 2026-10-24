"""Historical archive vault: read-only audit vault and compliance export center."""

import json
from html import escape

import streamlit as st

from components.styles import apply_clean_theme
from modules.db_state import init_db
from modules.standings import query


def render_archive_vault() -> None:
    """Renders the official CHUSBC Historical Tournament Archive and Compliance Vault."""
    init_db()
    apply_clean_theme()

    st.markdown(
        """
        <div style="margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 28px;">🗄️</span>
                <div>
                    <h2 style="margin: 0; color: #F8FAFC; font-weight: 800; font-size: 24px;">Historical Archive Vault</h2>
                    <p style="margin: 0; color: #94A3B8; font-size: 13px;">
                        Read-only tournament audit records, certified standings, and USBC compliance exports
                    </p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Fetch all archived tournament events
    archives = query(
        """
        SELECT a.*, t.name, t.host_center, t.squad_format, t.game_count, t.created_at
        FROM tournament_archives a
        JOIN tournaments t ON t.id = a.tournament_id
        WHERE COALESCE(t.is_practice, 0) = 0
        ORDER BY a.archived_at DESC
        """
    )

    if not archives:
        with st.container(border=True):
            st.info(
                "No completed tournaments have been archived into the vault yet.\n\n"
                "When a tournament director closes out an event from **Finals Closeout**, the certified snapshot, "
                "SMART scholarship allocations, and scoring exports will be permanently preserved here."
            )
        return

    # House and Tournament Filter controls
    filter_col1, filter_col2 = st.columns([2, 3])
    with filter_col1:
        centers = ["All Centers"] + sorted(list({a["host_center"] for a in archives}))
        selected_center = st.selectbox("Filter by Host House", centers)

    filtered_archives = (
        archives
        if selected_center == "All Centers"
        else [a for a in archives if a["host_center"] == selected_center]
    )

    if not filtered_archives:
        st.warning(f"No archived events found for host house: {selected_center}")
        return

    with filter_col2:
        archive = st.selectbox(
            "Select Tournament Archive",
            filtered_archives,
            format_func=lambda a: f"{a['name']} — {a['host_center']} ({str(a['archived_at'])[:10]})",
        )

    # Parse archive JSON snapshot
    try:
        snapshot = json.loads(archive["snapshot_json"])
    except (json.JSONDecodeError, TypeError):
        st.error("Error decoding tournament archive snapshot.")
        return

    tournament = snapshot.get("tournament") or {}
    standings = snapshot.get("final_standings") or []
    bowlers = snapshot.get("bowlers") or []
    scores = snapshot.get("scores") or []

    st.markdown("---")

    # High-level overview metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Host House", tournament.get("host_center", archive["host_center"]))
    m2.metric("Format", tournament.get("squad_format", "Standard"))
    m3.metric("Games Bowled", tournament.get("game_count", 3))
    m4.metric("Field Size", f"{len(bowlers)} Bowlers")
    m5.metric("Archived By", archive.get("archived_by", "TD"))

    st.caption(
        f"🔒 **Audit Record Sealed:** {archive['archived_at']} &middot; "
        f"Database ID: #{archive['tournament_id']} &middot; Read-Only State Enforced"
    )

    # Compliance Exports Section
    with st.container(border=True):
        st.markdown(
            """
            <div style="margin-bottom: 12px;">
                <span style="color: #F59E0B; font-weight: 800; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">
                    Official Sanction & Compliance Re-Exports
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        name_slug = archive["name"].replace(" ", "_")
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            if archive.get("certified_pdf"):
                st.download_button(
                    "📄 Certified PDF Sheet",
                    data=archive["certified_pdf"],
                    file_name=f"{name_slug}_certified_results.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            else:
                st.button("📄 Certified PDF", disabled=True, use_container_width=True)

        with c2:
            if archive.get("smart_csv"):
                st.download_button(
                    "🎓 USBC SMART CSV",
                    data=archive["smart_csv"],
                    file_name=f"{name_slug}_SMART_Rule400.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.button("🎓 SMART CSV", disabled=True, use_container_width=True)

        with c3:
            if archive.get("bls_bits_csv"):
                st.download_button(
                    "📊 BLS BITS CSV",
                    data=archive["bls_bits_csv"],
                    file_name=f"{name_slug}_bits.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.button("📊 BLS BITS CSV", disabled=True, use_container_width=True)

        with c4:
            if archive.get("bls_autoscoring_dat"):
                st.download_button(
                    "💾 AutoScoring .DAT",
                    data=archive["bls_autoscoring_dat"],
                    file_name=f"{name_slug}_scores.dat",
                    mime="text/plain",
                    use_container_width=True,
                )
            else:
                st.button("💾 AutoScoring .DAT", disabled=True, use_container_width=True)

    # Standings & Scores Tabbed Breakdown
    tab_standings, tab_scores, tab_audit = st.tabs(
        ["🏆 Certified Final Standings", "🎳 Roster & Game Matrix", "🛡️ Audit Metadata"]
    )

    with tab_standings:
        if standings:
            formatted_standings = []
            for row in standings:
                formatted_standings.append(
                    {
                        "Rank": f"#{row.get('rank', '-')}",
                        "Bowler Name": row.get("name", "Unknown"),
                        "USBC ID": row.get("usbc_id") or "N/A",
                        "Average": row.get("entering_avg") or "N/A",
                        "HDCP / Game": f"+{row.get('handicap', 0)}",
                        "Scratch Total": row.get("scratch_total", 0),
                        "Handicap Total": row.get("handicap_total", 0),
                    }
                )
            st.dataframe(formatted_standings, hide_index=True, use_container_width=True)
        else:
            st.info("No final standings table found in this archive snapshot.")

    with tab_scores:
        if bowlers:
            roster_rows = []
            for b in bowlers:
                # Bowler's individual game scores
                b_scores = [s for s in scores if s.get("bowler_id") == b.get("id")]
                b_scores.sort(key=lambda x: x.get("game_number", 0))
                game_str = " - ".join(str(s.get("scratch_score", 0)) for s in b_scores) or "None recorded"

                roster_rows.append(
                    {
                        "Bowler Name": b.get("name"),
                        "USBC ID": b.get("usbc_id") or "N/A",
                        "Lane": b.get("lane_assignment", "-"),
                        "Entry Paid": "Paid" if b.get("paid_status") == "paid" else "Unpaid",
                        "Youth (SMART)": "Yes" if b.get("is_youth") else "No",
                        "Game Scores": game_str,
                    }
                )
            st.dataframe(roster_rows, hide_index=True, use_container_width=True)
        else:
            st.info("No bowler roster records found.")

    with tab_audit:
        st.json(
            {
                "archive_id": archive["id"],
                "tournament_id": archive["tournament_id"],
                "archived_by": archive["archived_by"],
                "archived_at": archive["archived_at"],
                "handicap_base": tournament.get("handicap_base", 220),
                "handicap_percentage": f"{int((tournament.get('handicap_pct') or 0.90) * 100)}%",
                "mystery_doubles_enabled": bool(tournament.get("mystery_doubles_enabled")),
            }
        )