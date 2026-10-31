"""Admin-only Backup & Restore page."""

import streamlit as st

from modules import auth, db_state
from modules.tournament_vault import notice as tournament_vault_notice

SAFETY_COPY_PROMPT = (
    "Download the safety copy now, before you leave this page. "
    "It is the data this restore just replaced. Keep that file somewhere safe. "
    "Do not continue until the download finishes."
)


def render_backup_restore() -> None:
    if not auth.is_admin():
        st.error("Only admins can use Backup & Restore.")
        return
    st.title("💾 Backup & Restore")
    st.caption(tournament_vault_notice())

    st.subheader("1. Download full backup")
    st.write("Saves everything (events, bowlers, scores, staff) to one file. "
             "When auto-backup is on, the mailbox copy updates after scores and event changes. "
             "Download this file after every squad anyway and keep it somewhere safe.")
    if st.button("Prepare backup file", key="bk_prepare"):
        st.session_state["bk_data"] = (db_state.backup_filename(), db_state.backup_bytes())
    if st.session_state.get("bk_data"):
        name, data = st.session_state["bk_data"]
        st.download_button("⬇️ Download full backup", data, file_name=name,
                           mime="application/octet-stream", type="primary", key="bk_download")
        st.caption(f"File: {name}")

    st.markdown("---")
    st.subheader("2. Restore from backup")
    if st.session_state.get("bk_safety_file"):
        name, payload = st.session_state["bk_safety_file"]
        st.error(SAFETY_COPY_PROMPT)
        st.download_button(
            "⬇️ Download the safety copy now",
            payload,
            file_name=name,
            mime="application/octet-stream",
            type="primary",
            key="bk_safety_download",
        )
        st.caption(f"Safety copy: {name}. This button stays here until you confirm the file is on your computer.")
        if st.button("I downloaded the safety copy", key="bk_safety_done"):
            st.session_state.pop("bk_safety_file", None)
            st.rerun()
        return
    st.write("Only use this if data was lost. It **replaces all current data** with the backup.")
    up = st.file_uploader("Choose a Prism backup file (.db)", type=["db"], key="bk_upload")
    if not up:
        return
    data = up.getvalue()
    try:
        info = db_state.inspect_backup(data)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.success("This is a valid Prism backup. It contains:")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Events", info["events"])
    c2.metric("Bowlers", info["bowlers"])
    c3.metric("Scores", info["scores"])
    c4.metric("Staff accounts", info["staff"])
    if info["event_names"]:
        st.caption("Events: " + ", ".join(info["event_names"]))
    st.warning("Restoring replaces ALL current events, bowlers, scores and staff accounts. "
               "A safety copy of the current data is saved first.")
    sure = st.checkbox("Yes, replace all current data with this backup", key="bk_confirm")
    if st.button("Restore now", disabled=not sure, type="primary", key="bk_restore"):
        try:
            safety = db_state.restore_from_bytes(data)
        except Exception as exc:
            st.error(f"Restore failed; nothing was changed. ({exc})")
            return
        st.session_state.pop("bk_data", None)
        st.session_state["bk_safety_file"] = (safety.name, safety.read_bytes())
        st.rerun()
