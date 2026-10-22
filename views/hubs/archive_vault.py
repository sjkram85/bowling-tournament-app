"""Historical archive vault: read-only view of completed tournaments."""

import json

import streamlit as st

from components.styles import apply_clean_theme
from modules.db_state import init_db
from modules.standings import query


def render_archive_vault() -> None:
    init_db()
    apply_clean_theme()
    st.title("Historical Archive Vault")
    archives = query(
        "SELECT a.*, t.name, t.host_center FROM tournament_archives a "
        "JOIN tournaments t ON t.id = a.tournament_id ORDER BY a.archived_at DESC"
    )
    if not archives:
        st.info("No archived tournaments yet.")
        return

    archive = st.selectbox(
        "Archived tournament",
        archives,
        format_func=lambda a: f"{a['name']} · {a['archived_at'][:10]}",
    )
    snapshot = json.loads(archive["snapshot_json"])
    tournament = snapshot["tournament"]
    cols = st.columns(4)
    cols[0].metric("Host", tournament["host_center"])
    cols[1].metric("Format", tournament["squad_format"])
    cols[2].metric("Games", tournament["game_count"])
    cols[3].metric("Bowlers", len(snapshot["bowlers"]))
    st.caption(f"Archived by {archive['archived_by']} at {archive['archived_at']} (read-only)")

    st.subheader("Final standings")
    st.dataframe(
        [
            {
                "Rank": row["rank"],
                "Bowler": row["name"],
                "USBC ID": row["usbc_id"],
                "Scratch": row["scratch_total"],
                "Total": row["handicap_total"],
            }
            for row in snapshot["final_standings"]
        ],
        hide_index=True,
        width="stretch",
    )

    name = archive["name"].replace(" ", "_")
    cols = st.columns(4)
    cols[0].download_button("Certified PDF", archive["certified_pdf"], f"{name}_results.pdf", "application/pdf", width="stretch")
    cols[1].download_button("SMART CSV", archive["smart_csv"], f"{name}_smart.csv", "text/csv", width="stretch")
    cols[2].download_button("BITS CSV", archive["bls_bits_csv"], f"{name}_bits.csv", "text/csv", width="stretch")
    cols[3].download_button("AutoScoring .dat", archive["bls_autoscoring_dat"], f"{name}.dat", "text/plain", width="stretch")
