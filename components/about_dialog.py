"""About dialog."""

import streamlit as st

APP_VERSION = "0.1.0"
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
    st.markdown("**Credits**")
    st.write(DEVELOPER_CREDITS)
    st.markdown("**Dedication**")
    st.info(DEDICATION)
