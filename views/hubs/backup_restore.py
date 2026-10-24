"""Admin-only Backup & Restore page."""

import streamlit as st

from modules import auth, db_state


def render_backup_restore() -> None:
    if not auth.is_admin():
        st.error("Only admins can use Backup & Restore.")
        return
    st.title("💾 Backup & Restore")

    st.subheader("1. Download full backup")
    st.write("Saves everything (events, bowlers, scores, staff) to one file. "
             "Do this after every squad and keep the file somewhere safe.")
    if st.button("Prepare backup file", key="bk_prepare"):
        st.session_state["bk_data"] = (db_state.backup_filename(), db_state.backup_bytes())
    if st.session_state.get("bk_data"):
        name, data = st.session_state["bk_data"]
        st.download_button("⬇️ Download full backup", data, file_name=name,
                           mime="application/octet-stream", type="primary", key="bk_download")
        st.caption(f"File: {name}")

    st.markdown("---")
    st.subheader("2. Restore from backup")
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
        st.success(f"Restored. A safety copy of the old data was saved as {safety.name}.")
        st.download_button("⬇️ Download the safety copy (old data)", safety.read_bytes(),
                           file_name=safety.name, key="bk_safety")
