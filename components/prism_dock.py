"""Prism A.I Operational Assistant & Dedicated USBC Rule Arbitrator."""

import html
import streamlit as st
from modules.prism_ai import get_prism_ai_guidance


def _rolling_ball_loader(label: str = "Analyzing operations...") -> None:
    """Display an inline animated rolling bowling ball heading toward pins using clean vector SVGs."""
    ball_svg = (
        '<svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="16" cy="16" r="15" fill="#1E293B" stroke="#0EA5E9" stroke-width="2"/>'
        '<circle cx="12" cy="11" r="2.2" fill="#F8FAFC"/>'
        '<circle cx="18" cy="10" r="2.2" fill="#F8FAFC"/>'
        '<circle cx="16" cy="16" r="2.2" fill="#F8FAFC"/>'
        '</svg>'
    )
    pins_svg = (
        '<svg viewBox="0 0 28 36" fill="none" xmlns="http://www.w3.org/2000/svg">'
        # Headpin
        '<path d="M14 2C12 2 11 4 11 6C11 8 12 9 12 11C11.5 13 10 15 10 18C10 20 12 21 14 21C16 21 18 20 18 18C18 15 16.5 13 16 11C16 9 17 8 17 6C17 4 16 2 14 2Z" fill="#F8FAFC"/>'
        '<rect x="11.5" y="6.5" width="5" height="1.5" fill="#EF4444"/>'
        # Left Pin
        '<path d="M6 10C4.5 10 4 11.5 4 13C4 14.5 4.5 15.5 4.5 17C4 18.5 3 20 3 22.5C3 24 4.5 25 6 25C7.5 25 9 24 9 22.5C9 20 8 18.5 7.5 17C7.5 15.5 8 14.5 8 13C8 11.5 7.5 10 6 10Z" fill="#E2E8F0"/>'
        '<rect x="4.5" y="13.5" width="3.5" height="1.2" fill="#EF4444"/>'
        # Right Pin
        '<path d="M22 10C20.5 10 20 11.5 20 13C20 14.5 20.5 15.5 20.5 17C20 18.5 19 20 19 22.5C19 24 20.5 25 22 25C23.5 25 25 24 25 22.5C25 20 24 18.5 23.5 17C23.5 15.5 24 14.5 24 13C24 11.5 23.5 10 22 10Z" fill="#E2E8F0"/>'
        '<rect x="20.5" y="13.5" width="3.5" height="1.2" fill="#EF4444"/>'
        '</svg>'
    )

    st.markdown(
        f"""
        <div class="bowling-loading-container">
            <div class="bowling-lane-stage">
                <div class="bowling-ball-svg">{ball_svg}</div>
                <div class="pins-cluster-svg">{pins_svg}</div>
            </div>
            <div class="loading-text-glow">{label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _answer_box(text: str) -> None:
    """Show an A.I. answer as plain, escaped text in a large readable box."""
    st.markdown(
        '<div style="background:#1E293B; border-left:3px solid #38BDF8; border-radius:6px; '
        'padding:10px 12px; color:#F1F5F9; font-size:15px; margin-bottom:10px; line-height:1.5; '
        f'white-space:pre-wrap;">{html.escape(text or "")}</div>',
        unsafe_allow_html=True,
    )


def _stream_response(full_text: str) -> None:
    """Show the whole answer at once (easier to read than word-by-word animation)."""
    _answer_box(full_text)


def collect_view_state(current_view: str) -> dict:
    """Collect lightweight operational context for the active screen."""
    return {
        "view": current_view,
        "active_tournament_id": st.session_state.get("active_tournament_id"),
        "intake_summary": st.session_state.get("intake_summary", {}),
    }


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
                _rolling_ball_loader("Rolling analyzer ball...")
                guidance_text = get_prism_ai_guidance(state)
                st.session_state[cache_key] = guidance_text
                st.rerun()
        else:
            _answer_box(guidance_text)

        st.markdown("<p style='font-size:11px; font-weight:600; color:#94A3B8; margin-bottom:4px;'>Ask Prism about this screen:</p>", unsafe_allow_html=True)
        td_query = st.text_input(
            "Ask Prism",
            placeholder="e.g. Check roster balance or lane shift...",
            key="copilot_custom_query",
            label_visibility="collapsed",
        )
        if st.button("Ask Assistant", key="copilot_submit", use_container_width=True):
            if td_query.strip():
                _rolling_ball_loader("Delivering ball...")
                answer = get_prism_ai_guidance(state, user_prompt=td_query)
                _stream_response(answer)

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
                _rolling_ball_loader("Sifting USBC rules...")
                rule_answer = get_prism_ai_guidance(
                    {"view": "USBC Rules Engine"},
                    user_prompt=f"USBC Rule Arbitration Query: {rule_query.strip()}",
                )
                _stream_response(rule_answer)