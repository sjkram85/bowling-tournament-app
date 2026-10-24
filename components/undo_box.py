"""'Saved – Undo' after a save, and the hub's 'Undo last change' list."""

from html import escape

import streamlit as st

from modules import score_history
from modules.td_team import to_eastern


def saved_undo_button(state_key: str, who: str, device: str | None = None) -> None:
    """Show 'Saved – Undo' for the batch just saved (ids in session_state[state_key])."""
    ids = st.session_state.get(state_key) or []
    if not ids:
        return
    c1, c2 = st.columns([3, 1])
    c1.success(f"Saved {len(ids)} score{'s' if len(ids) != 1 else ''}.")
    if c2.button("↩️ Undo", key=f"{state_key}_btn", use_container_width=True):
        msgs = []
        for hid in reversed(ids):
            # A phone undoes its own changes newest-first, so each one is its 'last change' in turn.
            ok, msg = score_history.undo(hid, who, device=device)
            if not ok:
                msgs.append(msg)
        st.session_state[state_key] = []
        if msgs:
            st.warning(msgs[0])
        else:
            st.rerun()


def render_undo_box(t_id: int, td_name: str) -> None:
    changes = score_history.recent(t_id, 5)
    if not changes:
        return
    with st.expander("↩️ Undo last change"):
        st.caption("The latest score changes for this event. Undo puts the old score back (it goes back to Verify).")
        for h in changes:
            old = "new score" if h["old_scratch"] is None else f"was {h['old_scratch']}"
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{escape(h['name'])}** · Game {h['game_number']}: **{h['new_scratch']}** ({old}) "
                        f"— {escape(h['changed_by'] or '')}, {h['source']}, {to_eastern(h['changed_at'] or '')} ET")
            if c2.button("Undo", key=f"undo_{h['id']}", use_container_width=True):
                ok, msg = score_history.undo(h["id"], td_name)
                (st.success if ok else st.warning)(msg)
                if ok:
                    st.rerun()
