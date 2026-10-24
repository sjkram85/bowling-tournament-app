"""Hub 'Roll-off' box: shown only when bowlers are tied for the last finals spot in a group."""

from html import escape

import streamlit as st

from modules.auth import current_user
from modules.divisions import grouped_results
from modules.rolloff import record_winner


def render_rolloff_box(t_id: int) -> None:
    try:
        groups = [g for g in grouped_results(t_id) if g.get("rolloff")]
    except Exception:
        return
    if not groups:
        return
    st.markdown("### 🎳 Roll-off needed")
    for g in groups:
        ro = g["rolloff"]
        with st.container(border=True):
            spots = ro["spots"]
            st.markdown(f"**{escape(g['label'])}** — tied at **{ro['bowlers'][0]['total']}** for "
                        f"{spots} finals spot{'s' if spots > 1 else ''}. After the roll-off, press **Winner** "
                        "next to the bowler who won.")
            for r in ro["bowlers"]:
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"{escape(r['name'])} — {r['total']}")
                if c2.button("Winner", key=f"ro_{t_id}_{g['group']}_{r['id']}", use_container_width=True):
                    user = current_user() or {}
                    td = user.get("display_name") or user.get("username") or "TD"
                    if record_winner(t_id, g["group"], r["id"], r["total"], td):
                        st.success(f"{r['name']} recorded as roll-off winner.")
                        st.rerun()
                    else:
                        st.error("Could not save. Please try again.")
