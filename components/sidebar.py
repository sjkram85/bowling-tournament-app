from pathlib import Path

import pandas as pd
import streamlit as st

from db_state import fetch_active_tournament_state
from prism_ai import get_ai_client, stream_prism_ai


NAV_HUBS = {
    "🎳 Active Squad": [
        "Intake Gateway",
        "Floor Scoring & Matrix",
        "Lane Movement Guide",
    ],
    "💰 Action & Brackets": [
        "Side Pots & Brackets",
        "SMART & Financial Escrow",
    ],
    "📺 Concourse & Displays": [
        "Concourse TV (10s auto-refresh)",
        "Bowler Mobile Portal",
    ],
    "🏆 Finals & Closeout": [
        "Stepladder Finals & Closeout",
        "Tournament Archives",
    ],
    "⚙️ Desk Administration": [
        "Rules Arbiter (Prism AI)",
        "Prism AI Assistant",
        "Audit Log",
        "Staff Management & Manual",
    ],
}


def render_desk_sidebar():
    with st.sidebar:
        logo_path = Path(__file__).resolve().parent.parent / "CHUSBC.jpg"
        if logo_path.is_file():
            st.image(str(logo_path), width=84, alt="Cecil-Harford USBC")
        st.markdown("### Cecil-Harford USBC")
        st.caption("Prism Lane Control")
        st.markdown(f"**{st.session_state.get('td_name', 'Staff')}** · {st.session_state.get('td_role', 'staff').upper()}")

        live_state = fetch_active_tournament_state() or {}
        config = live_state.get("config") or st.session_state.get("tournament_config", {})
        roster_data = live_state.get("roster", st.session_state.get("roster", pd.DataFrame()))
        roster = roster_data if isinstance(roster_data, pd.DataFrame) else pd.DataFrame(roster_data)
        total = len(roster)
        paid = int(roster.get("Paid", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if total else 0
        checked = int(roster.get("Checked_In", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if total else 0
        squad = config.get("squad_number") or config.get("squad") or "—"
        st.markdown(
            f"<div class='stat-card' style='text-align:left;'>"
            f"<div class='stat-label'>Active Tournament</div>"
            f"<div style='font-size:15px;font-weight:800;color:#f8fafc;'>{config.get('name', 'No active event')}</div>"
            f"<div style='font-size:13px;color:#cbd5e1;'>{config.get('center', 'Center not set')}</div>"
            f"<div style='margin-top:8px;font-size:13px;color:#cbd5e1;'>Squad <b>{squad}</b> · "
            f"<b>{total}</b> bowlers · <b>{paid}</b> paid · <b>{checked}</b> checked in</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.divider()
        selected_hub = st.radio("Operations hub", list(NAV_HUBS), key="nav_hub")
        selected_view = st.radio("Tool", NAV_HUBS[selected_hub], key=f"nav_tool_{selected_hub}")
        st.divider()
        with st.expander("Prism AI quick assist"):
            quick_prompts = {
                "Custom question": "",
                "What should I do next?": f"What should I do next in {selected_view}?",
                "Explain this screen": f"Give me a short orientation to the {selected_view} screen and its safest next action.",
                "Check an event rule": "",
            }
            prompt_kind = st.selectbox("Prompt starter", list(quick_prompts), key="copilot_prompt_kind")
            question = st.text_area(
                "Ask about this screen or a tournament rule",
                value=quick_prompts[prompt_kind],
                key="copilot_question",
                height=90,
            )
            if st.button("Ask Prism", key="copilot_submit", width="stretch"):
                if not question.strip():
                    st.warning("Enter a question first.")
                else:
                    state_context = {
                        "user": st.session_state.get("td_name", "Staff"),
                        "mode": "Tournament Director",
                        "screen": selected_view,
                        "event_name": st.session_state.get("tournament_config", {}).get("name", "Tournament"),
                        "center": st.session_state.get("tournament_config", {}).get("center", ""),
                        "division": st.session_state.get("tournament_config", {}).get("division", ""),
                        "event_rules": st.session_state.get("tournament_config", {}).get("rules_text", ""),
                        "total_bowlers": len(st.session_state.get("roster", [])),
                    }
                    st.session_state.copilot_response = "".join(
                        stream_prism_ai(question.strip(), state_context, client=get_ai_client())
                    )
            response = st.session_state.get("copilot_response", "")
            if response:
                st.markdown(response)
                if st.button("Clear response", key="copilot_clear"):
                    st.session_state.copilot_response = ""
                    st.rerun()
        st.divider()
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            st.session_state.authenticated = False
            st.rerun()
    return selected_view