"""Prism A.I Tournament Assistant."""

import streamlit as st
from modules.prism_ai import get_prism_ai_guidance


def collect_view_state(current_view: str) -> dict:
    """Collect lightweight operational context for the active screen."""
    return {
        "view": current_view,
        "active_tournament_id": st.session_state.get("active_tournament_id"),
        "intake_summary": st.session_state.get("intake_summary", {}),
    }


@st.dialog("🎳 Prism A.I — Desk Assistant", width="large")
def _open_prism_dialog(current_view: str, view_state: dict | None = None) -> None:
    """Modal popup dialog triggered by clicking the assistant button."""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(
            f"""
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px;">
                <span style="background:#0F172A; border:1px solid #334155; border-radius:999px; color:#94A3B8; font-size:12px; padding:3px 12px;">
                    Active Screen: <strong style="color:#F8FAFC;">{current_view}</strong>
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        if st.button("🔄 Refresh", key="dialog_refresh_guidance", use_container_width=True):
            st.session_state["prism_guidance_cache"] = None
            st.rerun()

    # Routine Operational Guidance Block
    guidance_text = st.session_state.get("prism_guidance_cache")
    if not guidance_text:
        with st.spinner("Prism is analyzing desk operations..."):
            guidance_text = get_prism_ai_guidance(view_state or {"view": current_view})
            st.session_state["prism_guidance_cache"] = guidance_text

    st.markdown(
        f"""
        <div style="background:#0F172A; border-left:4px solid #F59E0B; border-radius:8px; padding:12px 16px; color:#E2E8F0; font-size:14px; margin-bottom:16px;">
            {guidance_text}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Collapsible USBC Rule Arbitrator
    with st.expander("⚖️ USBC Rule & Dispute Arbitrator (Official Rulebook Tool)", expanded=True):
        st.caption("Ask questions regarding dead balls (Rule 8), wrong lanes (Rule 9), foul sensors (Rule 10), surface adjustments (Rule 18), or Rule 400 SMART compliance.")
        rule_query = st.text_input(
            "Enter tournament dispute or rule question:",
            placeholder="e.g., Bowler delivered on the wrong lane...",
            key="modal_rule_query",
        )
        if st.button("Consult USBC Rulebook", key="modal_rule_submit", use_container_width=True):
            if rule_query.strip():
                with st.spinner("Arbitrating via official USBC Rulebook..."):
                    result = get_prism_ai_guidance(view_state or {"view": current_view}, user_prompt=rule_query)
                    st.info(result)


def render_prism_dock(current_view: str = "Active Squad Hub", view_state: dict | None = None) -> None:
    """
    Renders the dedicated Prism A.I button directly in the sidebar navigation rail.
    """
    st.sidebar.markdown(
        """
        <style>
        div[class*="st-key-sidebar_prism_dock"] button {
            background: #1E293B !important;
            border: 1.5px solid #F59E0B !important;
            color: #F8FAFC !important;
            border-radius: 8px !important;
            font-weight: 700 !important;
            padding: 8px 12px !important;
            margin-top: 10px !important;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
        }
        div[class*="st-key-sidebar_prism_dock"] button:hover {
            border-color: #FCD34D !important;
            background: #334155 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.sidebar.container(key="sidebar_prism_dock"):
        if st.button("🎳 Prism A.I Assistant", key="btn_prism_dock_trigger", use_container_width=True):
            _open_prism_dialog(current_view, view_state)