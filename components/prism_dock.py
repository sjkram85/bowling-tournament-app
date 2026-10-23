"""Prism A.I Operational Assistant & Dedicated USBC Rule Arbitrator."""

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
    Renders two distinct non-blocking tools in the sidebar:
    1. Prism A.I Operational Co-Pilot (tied to the current screen context).
    2. USBC Rule & Dispute Arbitrator (dedicated reference tool).
    """
    st.sidebar.markdown(
        """
        <style>
        div[data-testid="stSidebar"] div.stExpander {
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
            background: #0F172A !important;
            margin-top: 8px !important;
        }
        div[data-testid="stSidebar"] div.stExpander details summary {
            font-weight: 700 !important;
            color: #F8FAFC !important;
            font-size: 13px !important;
            padding: 8px 12px !important;
        }
        div[data-testid="stSidebar"] div.stExpander details summary:hover {
            color: #F59E0B !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    state = view_state or collect_view_state(current_view)

    # ==========================================
    # 1. SCREEN-AWARE OPERATIONAL DESK ASSISTANT
    # ==========================================
    with st.sidebar.expander("🎳 Prism A.I Co-Pilot", expanded=False):
        col_screen, col_refresh = st.columns([3, 1])
        with col_screen:
            st.caption(f"Active: **{current_view}**")
        with col_refresh:
            if st.button("🔄", key="copilot_refresh", help="Refresh desk context"):
                st.session_state["copilot_guidance_cache"] = None
                st.rerun()

        # Dynamic screen guidance
        guidance_text = st.session_state.get("copilot_guidance_cache")
        if not guidance_text:
            with st.spinner("Prism checking desk state..."):
                guidance_text = get_prism_ai_guidance(state)
                st.session_state["copilot_guidance_cache"] = guidance_text

        st.markdown(
            f"""
            <div style="background:#1E293B; border-left:3px solid #38BDF8; border-radius:6px; padding:8px 10px; color:#E2E8F0; font-size:12px; margin-bottom:10px; line-height:1.4;">
                {guidance_text}
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<p style='font-size:11px; font-weight:600; color:#94A3B8; margin-bottom:4px;'>Ask Prism about this screen:</p>", unsafe_allow_html=True)
        td_query = st.text_input(
            "Ask Prism",
            placeholder="e.g. Check roster balance or lane shift...",
            key="copilot_custom_query",
            label_visibility="collapsed",
        )
        if st.button("Ask Assistant", key="copilot_submit", use_container_width=True):
            if td_query.strip():
                with st.spinner("Analyzing operational state..."):
                    answer = get_prism_ai_guidance(state, user_prompt=td_query)
                    st.info(answer)

    # ==========================================
    # 2. DEDICATED USBC RULE ARBITRATOR SECTION
    # ==========================================
    with st.sidebar.expander("⚖️ USBC Rule Arbitrator", expanded=False):
        st.caption("Official rule interpretation for live tournament disputes.")
        rule_query = st.text_input(
            "Rule Dispute",
            placeholder="e.g. Delivered on wrong lane, dead ball pinfall, surface sanding...",
            key="rulebook_query",
            label_visibility="collapsed",
        )
        if st.button("Arbitrate USBC Rule", key="rulebook_submit", use_container_width=True):
            if rule_query.strip():
                with st.spinner("Consulting USBC Playing Rules..."):
                    rule_answer = get_prism_ai_guidance(
                        {"view": "USBC Rules Engine"},
                        user_prompt=f"USBC Rule Arbitration Query: {rule_query.strip()}",
                    )
                    st.success(rule_answer)