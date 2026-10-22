"""Active squad hub: live heatmap, leaderboard and TD desk scoring."""

import streamlit as st

from components.leaderboard import render_leaderboard
from components.styles import inject_styles
from components.tournament_picker import pick_tournament
from modules.db_state import init_db
from modules.prism_ai import get_prism_ai_guidance, query_usbc_rulebook
from modules.standings import (
    CUT_SEED,
    MAX_GAME_SCORE,
    commit_scores,
    compute_standings,
    current_game,
    squad_pairs,
)

TILES_PER_ROW = 5
REFRESH_SECONDS = 15
PENDING_DIALOG_KEY = "squad_pending_dialog"


@st.dialog("TD desk scoring")
def _desk_scoring_dialog(tournament_id: int, game_number: int, pair_number: int) -> None:
    pair = next((p for p in squad_pairs(tournament_id, game_number) if p["pair"] == pair_number), None)
    if pair is None:
        st.warning("Pair not found.")
        return
    st.caption(f"Pair {pair_number} · Lanes {pair['lanes'][0]}–{pair['lanes'][1]} · Game {game_number}")
    td_name = st.text_input("TD name", value=st.session_state.get("td_name", ""))
    entries = {
        bowler["id"]: st.number_input(
            f"Lane {bowler['lane']} – {bowler['name']}",
            min_value=0,
            max_value=MAX_GAME_SCORE,
            value=bowler["score"],
            step=1,
            key=f"desk_{game_number}_{bowler['id']}",
        )
        for bowler in pair["bowlers"]
    }
    if st.button("Save scores", type="primary", width="stretch"):
        if not td_name.strip():
            st.error("Enter your TD name so these scores can be attributed.")
            return
        scores = {bowler_id: int(score) for bowler_id, score in entries.items() if score is not None}
        if not scores:
            st.warning("Enter at least one score.")
            return
        st.session_state["td_name"] = td_name.strip()
        commit_scores(tournament_id, game_number, scores, f"TD: {td_name.strip()}", "td")
        st.rerun()


@st.fragment(run_every=REFRESH_SECONDS)
def _heatmap_panel(tournament_id: int, game_number: int) -> None:
    pairs = squad_pairs(tournament_id, game_number)
    st.subheader(f"Birds-Eye View · Game {game_number}")
    if not pairs:
        st.info("No lane assignments yet.")
    for start in range(0, len(pairs), TILES_PER_ROW):
        columns = st.columns(TILES_PER_ROW)
        for column, pair in zip(columns, pairs[start : start + TILES_PER_ROW]):
            color = "green" if pair["complete"] else "amber"
            low, high = pair["lanes"]
            if pair["complete"]:
                stat = f"{sum(b['score'] for b in pair['bowlers'])} total pinfall"
            else:
                stat = f"{pair['reported']}/{len(pair['bowlers'])} reported"
            with column, st.container(key=f"tile_{color}_{game_number}_{pair['pair']}"):
                st.markdown(
                    f'<div class="ptcc-tile-title">Pair {pair["pair"]} · Lanes {low}–{high}</div>'
                    f'<div class="ptcc-tile-stat">{stat}</div>',
                    unsafe_allow_html=True,
                )
                if st.button("Enter / Edit Scores", key=f"edit_{game_number}_{pair['pair']}", width="stretch"):
                    st.session_state[PENDING_DIALOG_KEY] = (tournament_id, game_number, pair["pair"])
                    st.rerun()
    st.caption("🟩 reported   🟧 still bowling")


@st.fragment(run_every=REFRESH_SECONDS)
def _leaderboard_panel(tournament_id: int) -> None:
    st.subheader("Live Leaderboard")
    render_leaderboard(compute_standings(tournament_id))


def _arbitrator(tournament_id: int) -> None:
    with st.expander("Dispute & Rule Arbitrator"):
        question = st.text_area(
            "Describe the dispute",
            placeholder="e.g. Foul on the first ball of frame 4 — what is the ruling?",
            key=f"arbitrator_q_{tournament_id}",
        )
        if st.button("Ask the rulebook", key=f"arbitrator_btn_{tournament_id}", width="stretch"):
            if not question.strip():
                st.warning("Enter a question.")
            else:
                with st.spinner("Searching the USBC rulebook..."):
                    st.session_state[f"arbitrator_a_{tournament_id}"] = query_usbc_rulebook(question.strip())
        if st.session_state.get(f"arbitrator_a_{tournament_id}"):
            st.markdown(st.session_state[f"arbitrator_a_{tournament_id}"])


def _prism_card(tournament_id: int, game_number: int) -> None:
    pairs = squad_pairs(tournament_id, game_number)
    reported = sum(p["complete"] for p in pairs)
    with st.container(border=True):
        st.markdown("**✨ Prism A.I · Next step**")
        st.write(f"{reported} of {len(pairs)} pairs have reported Game {game_number}.")
        # Re-ask only when the squad state changes, not on every refresh.
        key = f"prism_guidance_{tournament_id}_{game_number}_{reported}"
        refresh = st.button("Refresh guidance", key=f"prism_btn_{key}", width="stretch")
        if refresh or key not in st.session_state:
            standings = compute_standings(tournament_id)
            state = {
                "screen": "active_squad",
                "game": game_number,
                "pairs_reported": reported,
                "pairs_total": len(pairs),
                "pairs_pending": [p["pair"] for p in pairs if not p["complete"]],
                "cut_line_seed": CUT_SEED,
                "top_seeds": [(r["rank"], r["handicap_total"]) for r in standings[: CUT_SEED + 1]],
            }
            with st.spinner("Thinking..."):
                st.session_state[key] = get_prism_ai_guidance(state)
        st.info(st.session_state[key])
    _arbitrator(tournament_id)


def render_active_squad(tournament_id: int | None = None) -> None:
    init_db()
    inject_styles()
    tournament = pick_tournament(tournament_id, key="squad_tournament")
    if tournament is None:
        return
    tid = tournament["id"]

    default_game = current_game(tid, tournament["game_count"])
    game_number = (
        st.radio("Game", range(1, tournament["game_count"] + 1), index=default_game - 1, horizontal=True)
        if tournament["game_count"] > 1
        else 1
    )

    pending = st.session_state.pop(PENDING_DIALOG_KEY, None)
    if pending:
        _desk_scoring_dialog(*pending)

    _heatmap_panel(tid, game_number)
    left, right = st.columns([7, 3])
    with left:
        _leaderboard_panel(tid)
    with right:
        _prism_card(tid, game_number)
