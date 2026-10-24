"""About dialog."""

import streamlit as st

from modules import ai_provider

APP_VERSION = "1.0"
RELEASE_NOTES = [
    "Tournament, roster, score and audit-log database (SQLite, WAL mode).",
    "Mystery doubles draw and BITS / AutoScoring import and export.",
    "Prism AI guidance with USBC rulebook lookup.",
    "Bowler recap emails.",
]
DEVELOPER_CREDITS = "Developed by Scott for Cecil Harford USBC."
DEDICATION = (
    "This software is provided freely to the Cecil Harford United States Bowling "
    "Congress (CHUSBC) and dedicated to the bowlers of CHUSBC, may our sport provide "
    "friendly competition, enduring friendships and life long memories."
)


@st.dialog("About")
def show_about_dialog() -> None:
    """Open the About dialog."""
    st.subheader(f"CHUSBC Tournament Manager v{APP_VERSION}")
    st.markdown("**Release notes**")
    st.markdown("\n".join(f"- {note}" for note in RELEASE_NOTES))
    st.markdown("**Prism A.I.**")
    info = ai_provider.status_summary()
    if not info["key_set"]:
        st.write("Status: turned off (no Gemini key set up).")
    st.write(f"Model: {info['model']}  \nRule Arbitrator model: {info['rules_model']}")
    for label, name in (("GEMINI_MODEL", info["model"]), ("GEMINI_RULES_MODEL", info["rules_model"])):
        if ai_provider.is_retired(name):
            st.warning(ai_provider.retired_message(name, label))
    if info["last_ok"] is None:
        st.caption(info["last_message"])
    elif info["last_ok"]:
        st.success(f"Last A.I. request ({info['last_at']}, {info['last_model']}): worked.")
    else:
        st.error(f"Last A.I. request ({info['last_at']}, {info['last_model']}) failed: {info['last_message']}")
    st.markdown("**Credits**")
    st.write(DEVELOPER_CREDITS)
    st.markdown("**Dedication**")
    st.info(DEDICATION)
