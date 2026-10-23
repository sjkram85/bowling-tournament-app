"""Prism A.I Tournament Assistant — Non-blocking Sidebar Drawer."""

import streamlit as st
from modules.prism_ai import get_prism_ai_guidance


def collect_view_state(current_view: str) -> dict:
    """Collect lightweight operational context for the active screen."""
    return {
        "view": current_view,
        "active_tournament_id": st.session_state.get("active_tournament_id"),
        "intake_summary": st.session_state.get("intake_summary", {}),
    }


def render_prism_dock(current_view: str = "Active Squad Hub", view_state: dict | None = None) -> None:
    """
    Renders Prism A.I as an interactive, non-blocking drawer inside the sidebar.
    Keeps the main triage canvas fully interactive while reading desk advice.
    """
    st.sidebar.markdown(
        """
        <style>
        div[data-testid="stSidebar"] div.stExpander {
            border: 1px solid #F59E0B !important;
            border-radius: 10px !important;
            background: #0F172A !important;
            margin-top: 12px !important;
        }
        div[data-testid="stSidebar"] div.stExpander details summary {
            font-weight: 700 !important;
            color: #F8FAFC !important;
            font-size: 13px !important;
            padding: 8px 12px !important;
        }
        div[data-testid="stSidebar"] div.stExpander details summary:hover {
            color: #FCD34D !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar.expander("🎳 Prism A.I Assistant", expanded=False):
        col_view, col_btn = st.columns([3, 1])
        with col_view:
            st.caption(f"Screen: **{current_view}**")
        with col_btn:
            if st.button("🔄", key="drawer_refresh_guidance", help="Refresh desk recommendations"):
                st.session_state["prism_guidance_cache"] = None
                st.rerun()

        # Operational Desk Guidance Box
        guidance_text = st.session_state.get("prism_guidance_cache")
        if not guidance_text:
            with st.spinner("Prism checking operations..."):
                guidance_text = get_prism_ai_guidance(view_state or {"view": current_view})
                st.session_state["prism_guidance_cache"] = guidance_text

        st.markdown(
            f"""
            <div style="background:#1E293B; border-left:3px solid #F59E0B; border-radius:6px; padding:10px 12px; color:#E2E8F0; font-size:12px; margin-bottom:12px; line-height:1.4;">
                {guidance_text}
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown("<p style='font-weight:700; font-size:12px; color:#FCD34D; margin-bottom:4px;'>⚖️ USBC Rule Arbitrator</p>", unsafe_allow_html=True)
        st.caption("Ask questions on wrong lanes, dead ball, surface sanding, or foul sensors.")

        rule_query = st.text_input(
            "USBC Dispute:",
            placeholder="e.g. Delivered on wrong lane...",
            key="sidebar_rule_query",
            label_visibility="collapsed",
        )
        if st.button("Arbitrate Rule", key="sidebar_rule_submit", use_container_width=True):
            if rule_query.strip():
                with st.spinner("Arbitrating..."):
                    result = get_prism_ai_guidance(view_state or {"view": current_view}, user_prompt=rule_query)
                    st.info(result)