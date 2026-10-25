"""Finals Closeout: simple per-group stepladder (Start, enter each match score, winner shown)."""

from html import escape

import streamlit as st

from modules import stepladder
from modules.standings import get_tournament


def render_stepladder_box(t_id: int, td_name: str) -> None:
    st.subheader("🏁 Stepladder Finals")
    tourney = get_tournament(t_id) or {}
    cap = stepladder.max_match_score(tourney)
    handicap = stepladder.uses_handicap(tourney)
    if handicap:
        st.caption(f"One game per match. Enter the handicap total (scratch + handicap), up to {cap}. "
                   "Higher handicap total wins. Lowest seed bowls the next seed; the winner moves up until #1.")
    else:
        st.caption("One game per match, scratch. Lowest seed bowls the next seed; the winner moves up until #1.")
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
                else:
                    sure = st.checkbox("These seeds are final. I mean to start this stepladder.",
                                       key=f"sl_ok_{t_id}_{gname}")
                    if st.button("Start stepladder", key=f"sl_start_{t_id}_{gname}", disabled=not sure):
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
                    score_label = "handicap total" if handicap else "scratch"
                    s_low = c1.number_input(f"{low} ({score_label})", 0, cap, 0, key=k + "_l")
                    s_high = c2.number_input(f"{high} ({score_label})", 0, cap, 0, key=k + "_h")
                    r_low = r_high = None
                    if s_low == s_high and s_low > 0:
                        st.warning("Tie — enter the roll-off scores.")
                        r_low = c1.number_input(f"{low} roll-off", 0, cap, 0, key=k + "_rl")
                        r_high = c2.number_input(f"{high} roll-off", 0, cap, 0, key=k + "_rh")
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
            _render_clear(t_id, gname, matches, td_name)


def _render_clear(t_id: int, gname: str, matches: list[dict], td_name: str) -> None:
    scored = any(m.get("status") == "completed" or m.get("score_low") is not None for m in matches)
    with st.expander("Started too early?"):
        st.caption("Clears this ladder so you can seed it again. Qualifying scores are not changed.")
        if scored:
            st.warning("Match scores have been entered. Clearing removes those match scores only.")
        sure = st.checkbox("Yes, clear this stepladder", key=f"sl_clear_ok_{t_id}_{gname}")
        if st.button("Clear and re-seed", key=f"sl_clear_{t_id}_{gname}", disabled=not sure):
            result = stepladder.clear_stepladder(t_id, gname, td_name, force=scored)
            if result.get("ok"):
                st.success("Ladder cleared. Check the seeds, then start again.")
                st.rerun()
            else:
                st.error(result.get("reason") or "Could not clear the ladder.")
