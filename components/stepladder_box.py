"""Finals Closeout: simple per-group stepladder (Start, enter each match score, winner shown)."""

from html import escape

import streamlit as st

from modules import stepladder


def render_stepladder_box(t_id: int, td_name: str) -> None:
    st.subheader("🏁 Stepladder Finals")
    st.caption("One game per match. Lowest seed bowls the next seed; the winner moves up until #1.")
    try:
        info = stepladder.seeds(t_id)
    except Exception:
        st.info("Stepladder is not available for this event.")
        return
    for gname, g in info.items():
        if not g["seeds"] and not g["ready"]:
            continue
        with st.container(border=True):
            st.markdown(f"**{escape(g['label'])}**")
            matches = stepladder.get_stepladder_state(t_id, gname)
            if not matches:
                st.caption("Seeds: " + ", ".join(f"#{i + 1} {r['name']}" for i, r in enumerate(g["seeds"])))
                if not g["ready"]:
                    st.info(g["reason"])
                elif st.button("Start stepladder", key=f"sl_start_{t_id}_{gname}"):
                    stepladder.initialize_stepladder(t_id, gname, td_name)
                    st.rerun()
                continue
            for m in matches:
                low, high = m["low_name"] or "TBD", m["high_name"] or "TBD"
                if m["status"] == "completed":
                    st.markdown(f"✅ {escape(m['match_name'])}: {escape(low)} {m['score_low']} – "
                                f"{m['score_high']} {escape(high)} → **{escape(m['winner_name'] or '')}**")
                elif m["status"] == "active":
                    st.markdown(f"▶️ **{escape(m['match_name'])}**: {escape(low)} vs {escape(high)}")
                    c1, c2, c3 = st.columns([2, 2, 1])
                    k = f"sl_{m['id']}"
                    s_low = c1.number_input(low, 0, 300, 0, key=k + "_l")
                    s_high = c2.number_input(high, 0, 300, 0, key=k + "_h")
                    r_low = r_high = None
                    if s_low == s_high and s_low > 0:
                        st.warning("Tie — enter the roll-off scores.")
                        r_low = c1.number_input(f"{low} roll-off", 0, 300, 0, key=k + "_rl")
                        r_high = c2.number_input(f"{high} roll-off", 0, 300, 0, key=k + "_rh")
                    if c3.button("Save", key=k + "_save"):
                        if stepladder.record_stepladder_score(m["id"], s_low, s_high, r_low, r_high, td_name):
                            st.rerun()
                        else:
                            st.error("Scores are tied. Enter different roll-off scores.")
                else:
                    st.caption(f"⏳ {m['match_name']}: winner vs {high}")
            champ = stepladder.champion(t_id, gname)
            if champ:
                st.success(f"🏆 Champion: {champ}")
