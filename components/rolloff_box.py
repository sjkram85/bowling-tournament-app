"""Hub 'Roll-off' box: shown when bowlers are tied for the last finals spot, and after a winner is picked so a misclick can be replaced."""

from html import escape

import streamlit as st

from modules.auth import current_user
from modules.divisions import grouped_results
from modules.rolloff import cut_situation, record_winner, remove_winner
from modules.standings import get_tournament
from modules.stepladder import max_match_score


def render_rolloff_box(t_id: int) -> None:
    try:
        groups = grouped_results(t_id)
    except Exception:
        return
    shown = []
    for g in groups:
        situation = cut_situation(g["rows"], g["finalists"], g.get("rolloff_recorded"))
        if situation:
            shown.append((g, situation))
    if not shown:
        return
    cap = max_match_score(get_tournament(t_id) or {})
    st.markdown("### 🎳 Roll-off")
    st.caption("The first click is not permanent. Undo a winner, or replace them, if you tapped the wrong bowler.")
    for g, ro in shown:
        with st.container(border=True):
            spots = ro["spots"]
            if ro["open_spots"]:
                st.markdown(f"**{escape(g['label'])}** — tied at **{ro['cut_total']}** for "
                            f"{ro['open_spots']} finals spot{'s' if ro['open_spots'] > 1 else ''}. "
                            "After the roll-off, press **Winner** next to the bowler who won.")
            else:
                st.markdown(f"**{escape(g['label'])}** — roll-off at **{ro['cut_total']}** is recorded "
                            f"({spots} spot{'s' if spots > 1 else ''}). Press **Replace** or **Undo** if that was a misclick.")
            for r in ro["tied"]:
                c1, c2, c3 = st.columns([3, 1, 1])
                won = r["id"] in ro["winner_ids"]
                c1.markdown(f"{'✅ ' if won else ''}{escape(r['name'])} — qualifying {r['total']}")
                score = c2.number_input("Roll-off score", 0, cap, 0, key=f"ro_sc_{t_id}_{g['group']}_{r['id']}",
                                        label_visibility="collapsed", help="Optional roll-off game score")
                user = current_user() or {}
                td = user.get("display_name") or user.get("username") or "TD"
                if won:
                    if c3.button("Undo", key=f"ro_undo_{t_id}_{g['group']}_{r['id']}", use_container_width=True):
                        if remove_winner(t_id, g["group"], r["id"]):
                            st.success(f"Removed {r['name']} as roll-off winner.")
                            st.rerun()
                        else:
                            st.error("Could not undo. Please try again.")
                elif ro["open_spots"]:
                    if c3.button("Winner", key=f"ro_{t_id}_{g['group']}_{r['id']}", use_container_width=True):
                        if record_winner(t_id, g["group"], r["id"], r["total"], td, score or None, replace=False):
                            st.success(f"{r['name']} recorded as roll-off winner.")
                            st.rerun()
                        else:
                            st.error("Could not save. Please try again.")
                elif spots == 1:
                    if c3.button("Replace", key=f"ro_rep_{t_id}_{g['group']}_{r['id']}", use_container_width=True):
                        if record_winner(t_id, g["group"], r["id"], r["total"], td, score or None, replace=True):
                            st.success(f"{r['name']} is now the roll-off winner.")
                            st.rerun()
                        else:
                            st.error("Could not replace the winner. Please try again.")
                else:
                    c3.caption("Undo one winner first")
            if spots > 1 and not ro["open_spots"]:
                st.caption("More than one spot was filled. Undo the wrong winner, then press Winner on the right bowler.")
