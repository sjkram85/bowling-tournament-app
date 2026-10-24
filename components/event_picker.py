"""'Which event?' picker and 'Now working on' bar for staff. Each device keeps its own choice."""

from html import escape

import streamlit as st

from modules.events import active_events, center_name, resolve_event

KEY = "active_tournament_id"


def _picker(events: list[dict], title: str, on_pick) -> None:
    st.markdown(f"<div style='font-size:34px;font-weight:800;margin:6px 0 4px'>{escape(title)}</div>"
                "<div style='font-size:18px;opacity:.8;margin-bottom:12px'>Tap the event you are working on.</div>",
                unsafe_allow_html=True)
    for e in events:
        label = f"{'🧪 ' if e['is_practice'] else '🎳 '}{e['name']}  ·  {center_name(e['host_center'])}"
        if st.button(label, key=f"pick_event_{e['id']}", use_container_width=True, type="primary"):
            on_pick(e["id"])
            st.rerun()


def staff_event_bar(allow_no_event: bool = False) -> bool:
    """Show picker or 'Now working on' bar. Returns False if the page should wait for a choice."""
    if st.session_state.get("intake_new_event"):
        st.info("➕ Starting a new event. Fill in the form below.")
        if st.button("← Back to my events", key="cancel_new_event"):
            st.session_state.pop("intake_new_event", None)
            st.rerun()
        return True
    events = active_events()
    switching = st.session_state.pop("switching_event", False)
    event, need = resolve_event(events, None if switching else st.session_state.get(KEY))
    if switching and len(events) > 1:
        event, need = None, True
    if need:
        st.session_state.pop(KEY, None)
        _picker(events, "Which event?", lambda i: st.session_state.__setitem__(KEY, i))
        if st.button("➕ Start a new event", key="picker_new_event"):
            st.session_state["intake_new_event"] = True
            st.rerun()
        return False
    if event is None:
        st.session_state.pop(KEY, None)
        return True  # no active events: intake shows its create screen
    st.session_state[KEY] = event["id"]
    a, b, c = st.columns([5, 1.6, 1.4])
    a.markdown(
        f"<div style='background:#1E3A8A;color:#fff;padding:10px 16px;border-radius:8px'>"
        f"<span style='font-size:14px;opacity:.85'>NOW WORKING ON</span><br>"
        f"<span style='font-size:26px;font-weight:800'>{escape(event['name'])}</span>"
        f"<span style='font-size:18px;opacity:.85'> · {escape(center_name(event['host_center']))}</span></div>",
        unsafe_allow_html=True)
    if len(events) > 1 and b.button("🔁 Switch", key="switch_event", use_container_width=True):
        st.session_state["switching_event"] = True
        st.rerun()
    if c.button("➕ New", key="bar_new_event", use_container_width=True):
        st.session_state["intake_new_event"] = True
        st.rerun()
    return True


def public_event(param_value, title: str = "Which event are you scoring?") -> dict | None:
    """For no-login pages (floor phone): use ?t=<id>; old links work when only one event is active."""
    events = [e for e in active_events()]
    event, need = resolve_event(events, param_value)
    if need:
        real = [e for e in events if not e["is_practice"]] or events
        if len(real) == 1:
            return real[0]  # old link, one real event (+ maybe practice): behave like before
        _picker(real, title, lambda i: st.query_params.__setitem__("t", str(i)))
        return None
    return event
