"""Prism A.I Operational Assistant & Dedicated USBC Rule Arbitrator."""

import html
import streamlit as st
from components.ai_lane_feedback import call_with_lane_feedback, gutter_ball_html, rolling_ball_html
from modules.prism_ai import get_prism_ai_guidance, answer_rule_question
from modules.screen_context import build_screen_context


def _answer_box(text: str) -> None:
    """Show an A.I. answer as plain, escaped text in a large readable box."""
    st.markdown(
        '<div style="background:#1E293B; border-left:3px solid #38BDF8; border-radius:6px; '
        'padding:10px 12px; color:#F1F5F9; font-size:15px; margin-bottom:10px; line-height:1.5; '
        f'white-space:pre-wrap;">{html.escape(text or "")}</div>',
        unsafe_allow_html=True,
    )


def _present_answer(text: str) -> None:
    """Show an answer. A gutter-ball failure keeps the lane card plus any built-in tips."""
    if text and "Gutter ball." in text:
        head, _, tail = text.partition("\n\n")
        st.markdown(gutter_ball_html(head, settled=True), unsafe_allow_html=True)
        if tail.strip():
            _answer_box(tail)
        return
    _answer_box(text)


def _ask(fn, waiting_label: str):
    """Run a Co-Pilot call with the rolling ball, and gutter / approach if Gemini retries."""
    return call_with_lane_feedback(fn, waiting_html=rolling_ball_html(waiting_label))


def collect_view_state(current_view: str) -> dict:
    """Desk identity for this rerun. Does not query. Co-Pilot loads counts on click."""
    return {
        "view": current_view,
        "active_tournament_id": st.session_state.get("active_tournament_id"),
    }


def load_copilot_state(state: dict) -> dict:
    """Add screen counts. Call only when the director clicks Analyze or Ask."""
    if state.get("screen_context"):
        return state
    loaded = dict(state)
    loaded["screen_context"] = build_screen_context(
        loaded.get("view") or "",
        loaded.get("active_tournament_id"),
    )
    return loaded


def render_prism_dock(current_view: str = "Active Squad Hub", view_state: dict | None = None) -> None:
    """
    Renders two non-blocking tools in the sidebar without dimming the canvas.
    1. Prism A.I Co-Pilot (tied to the active operational screen).
    2. USBC Rule Arbitrator (dedicated tournament rule disputes).
    """
    st.markdown(
        """
        <style>
        div[data-testid="stAppViewContainer"],
        div[data-testid="stMain"],
        div[data-testid="stSidebar"],
        section[data-testid="stSidebar"] ~ section,
        div[data-testid="stVerticalBlock"],
        .stApp {
            opacity: 1 !important;
            filter: none !important;
            transition: none !important;
        }
        div[data-testid="stMain"] > div {
            opacity: 1 !important;
        }

        /* Sidebar tool styling */
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
                st.session_state[f"guidance_{current_view}"] = None
                st.rerun()

        cache_key = f"guidance_{current_view}"
        guidance_text = st.session_state.get(cache_key)

        if not guidance_text:
            if st.button("💡 Analyze This Screen", key=f"btn_analyze_{current_view}", use_container_width=True):
                guidance_text = _ask(
                    lambda: get_prism_ai_guidance(load_copilot_state(state)),
                    "Rolling analyzer ball...",
                )
                st.session_state[cache_key] = guidance_text
                st.rerun()
        else:
            _present_answer(guidance_text)

        st.markdown("<p style='font-size:11px; font-weight:600; color:#94A3B8; margin-bottom:4px;'>Ask Prism about this screen:</p>", unsafe_allow_html=True)
        td_query = st.text_input(
            "Ask Prism",
            placeholder="e.g. Check roster balance or lane shift...",
            key="copilot_custom_query",
            label_visibility="collapsed",
        )
        if st.button("Ask Assistant", key="copilot_submit", use_container_width=True):
            if td_query.strip():
                answer = _ask(
                    lambda: get_prism_ai_guidance(load_copilot_state(state), user_prompt=td_query),
                    "Delivering ball...",
                )
                _present_answer(answer)

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
                rule_answer = _ask(
                    lambda: answer_rule_question(rule_query.strip()),
                    "Sifting USBC rules...",
                )
                _present_answer(rule_answer)