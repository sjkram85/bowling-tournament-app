import streamlit as st


DESK_VIEWS = [
    "Intake Gateway",
    "Floor Scoring",
    "Public Portal",
    "Concourse TV",
    "Closeout",
]


def render_desk_sidebar():
    with st.sidebar:
        st.markdown("## Prism Lane Control")
        st.caption(f"Signed in as {st.session_state.get('td_name', 'Staff')}")
        selected_view = st.radio("Tournament view", DESK_VIEWS, key="desk_view")
        st.divider()
        if st.button("Sign out", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()
    return selected_view