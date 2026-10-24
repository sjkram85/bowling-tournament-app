"""Staff-only 'Team' panel: TDs on duty, scores needing a check, and TD chat. Never shown on public/kiosk pages."""

from html import escape

import streamlit as st

from modules import td_team
from modules.auth import current_user


def _me() -> str:
    user = current_user() or {}
    return user.get("display_name") or user.get("username") or "TD"


@st.fragment(run_every=8)
def _on_duty(t_id: int) -> None:
    people = td_team.tds_on_duty(t_id)
    if not people:
        st.caption("TDs on duty: just you right now.")
        return
    chips = ", ".join(
        f"{'🟢' if p['online'] else '⚪'} {escape(p['display_name'])}" for p in people
    )
    st.caption(f"TDs on duty: {chips}")


@st.fragment(run_every=8)
def _verify_queue(t_id: int) -> None:
    me = _me()
    queue, done = td_team.verification_board(t_id)
    st.markdown(f"### ✅ Needs verifying ({len(queue)})")
    if not queue:
        st.success("All scores are verified.")
    for s in queue[:15]:
        c1, c2, c3, c4 = st.columns([2.6, 1.1, 1, 0.9])
        c1.markdown(f"**{escape(s['name'])}** · Lane {s['lane_assignment']} · Game {s['game_number']}"
                    f"<br><span style='font-size:12px;opacity:.7'>entered by {escape(s['recorded_by'] or 'floor')}</span>",
                    unsafe_allow_html=True)
        new = c2.number_input("Score", 0, 300, int(s["scratch_score"]), key=f"vq_n_{s['id']}",
                              label_visibility="collapsed")
        if c3.button("Verify", key=f"vq_ok_{s['id']}", type="primary", use_container_width=True):
            td_team.verify_score(s["id"], me)
            st.rerun(scope="fragment")
        if c4.button("Fix", key=f"vq_fix_{s['id']}", use_container_width=True,
                     disabled=int(new) == int(s["scratch_score"])):
            td_team.verify_score(s["id"], me, new_scratch=int(new))
            st.rerun(scope="fragment")
    if len(queue) > 15:
        st.caption(f"…and {len(queue) - 15} more.")
    if done:
        st.caption("Recently verified: " + "; ".join(
            f"{d['name']} G{d['game_number']} {d['scratch_score']} by {d['verified_by']}" for d in done))


@st.fragment(run_every=6)
def _chat(t_id: int) -> None:
    me = _me()
    key = f"td_chat_read_{t_id}"
    msgs = td_team.get_messages(t_id)
    unread = td_team.unread_count(msgs, st.session_state.get(key, 0), me)
    with st.expander(f"💬 Chat ({unread} new)" if unread else "💬 Chat"):
        box = st.container(height=220)
        for m in msgs:
            box.markdown(f"**{escape(m['user'])}** <span style='font-size:11px;opacity:.6'>{td_team.to_eastern(m['created_at'])}</span><br>"
                         f"{escape(m['text'])}", unsafe_allow_html=True)
        if not msgs:
            box.caption("No messages yet.")
        with st.form(f"td_chat_form_{t_id}", clear_on_submit=True, border=False):
            a, b = st.columns([4, 1])
            text = a.text_input("Message", placeholder="Type a message to the other TDs…",
                                label_visibility="collapsed")
            if b.form_submit_button("Send", use_container_width=True) and text.strip():
                td_team.send_message(t_id, me, text)
                st.rerun(scope="fragment")
        if msgs:
            st.session_state[key] = msgs[-1]["id"]


def render_td_team_panel(t_id: int) -> None:
    """Full-width 'Needs verifying' (the main job) plus a compact chat + one-line TDs on duty."""
    if not current_user() or not t_id:
        return
    with st.container(border=True):
        _verify_queue(t_id)
    render_team_extras(t_id)


def render_team_extras(t_id: int) -> None:
    if not current_user() or not t_id:
        return
    _chat(t_id)
    _on_duty(t_id)
