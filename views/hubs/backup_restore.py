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

    _render_turso_copy()

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


def _render_turso_copy() -> None:
    """Only shown when Turso is set up and there is local data that is not in Turso yet."""
    if not db_state.using_turso():
        return
    local = db_state.local_data_counts()
    if not local:
        return
    st.markdown("---")
    st.subheader("Copy current data to Turso (one time)")
    has = db_state.turso_has_data()
    st.write(f"This server still has local data ({local['tournaments']} events, {local['bowlers']} bowlers, "
             f"{local['scores']} scores, {local['staff_users']} staff). Copy it to Turso so it is kept permanently.")
    replace = False
    if has:
        st.warning("Turso already has data. Copying will replace it (a safety copy is saved first).")
        replace = st.checkbox("Yes, replace the Turso data with this local data", key="turso_replace")
    if st.button("Copy current data to Turso", disabled=has and not replace, key="turso_copy"):
        try:
            copied = db_state.copy_local_to_turso(replace=replace)
        except Exception as exc:
            st.error(f"Copy failed; nothing was changed. ({exc})")
            return
        st.success(f"Copied to Turso: {copied.get('tournaments', 0)} events, {copied.get('bowlers', 0)} bowlers, "
                   f"{copied.get('scores', 0)} scores.")
