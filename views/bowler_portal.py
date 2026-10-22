"""Bowler portal, reached with ?mode=bowler."""

from html import escape

import streamlit as st

from components.leaderboard import render_leaderboard
from components.styles import inject_styles
from components.tournament_picker import pick_tournament
from modules.db_state import init_db
from modules.reports import ladder_size, payout_equity, stepladder_matches
from modules.standings import (
    CUT_SEED,
    bowler_brackets,
    compute_standings,
    lane_count,
    lane_for_game,
    pair_of_lane,
    query,
    squad_pairs,
)

REFRESH_SECONDS = 20


def _movement_banner(tournament: dict, me: dict, lanes: int) -> None:
    if me["lane_assignment"] is None:
        body, sub = "Lane not yet assigned", "See the tournament desk"
    elif me["games_bowled"] >= tournament["game_count"]:
        body, sub = "All games complete", "Check the standings for your finish"
    else:
        game = me["games_bowled"] + 1
        lane = lane_for_game(me["lane_assignment"], game, lanes)
        pair = pair_of_lane(lane)
        lanes_text = f"Lanes {2 * pair - 1}-{2 * pair}"
        if game == 1:
            body = f"Game 1: Go to {lanes_text}"
        else:
            shift = pair - pair_of_lane(lane_for_game(me["lane_assignment"], game - 1, lanes))
            if shift > 0:
                body = f"Game {game}: Move right {shift} pair{'s' if shift > 1 else ''} to {lanes_text}"
            else:
                body = f"Game {game}: Move to {lanes_text}"
        if game < tournament["game_count"]:
            following = pair_of_lane(lane_for_game(me["lane_assignment"], game + 1, lanes))
            sub = f"Then Game {game + 1}: Lanes {2 * following - 1}-{2 * following}"
        else:
            sub = "Final game"
    st.markdown(
        f'<div class="ptcc-banner">{escape(body)}<small>{escape(sub)}</small></div>',
        unsafe_allow_html=True,
    )


@st.fragment(run_every=REFRESH_SECONDS)
def _standings_tab(tournament_id: int, bowler_id: int) -> None:
    standings = compute_standings(tournament_id)
    me = next((row for row in standings if row["id"] == bowler_id), None)
    if me and len(standings) >= CUT_SEED:
        cut_total = standings[CUT_SEED - 1]["handicap_total"]
        gap = me["handicap_total"] - cut_total
        if me["rank"] <= CUT_SEED:
            status = f"You are in, {gap} pins above the line" if gap else "You are on the line"
        else:
            status = f"You are {-gap} pins below the line"
        st.markdown(
            '<div style="background:#DC2626;border-radius:12px;color:#FFFFFF;font-weight:700;'
            f'padding:10px 16px;margin-bottom:8px">Cut line: Seed #{CUT_SEED} at {cut_total} · '
            f"{escape(status)}</div>",
            unsafe_allow_html=True,
        )
    render_leaderboard(standings, highlight_bowler_id=bowler_id)


def _next_opponent(tournament: dict, me: dict, standings: list[dict]) -> tuple[str, list[tuple[str, str]]]:
    """Return (heading, [(opponent name, lane text)]) for the bowler's next matchup."""
    if me["games_bowled"] >= tournament["game_count"]:
        size = ladder_size(standings)
        if me["rank"] > size:
            return "Qualifying complete", []
        matches = stepladder_matches(tournament["id"])
        round_number = len(matches) + 1
        if round_number > size - 1:
            return "Stepladder complete", []
        seeds = {row["rank"]: row for row in standings[:size]}
        challenger_id = seeds[size]["id"] if round_number == 1 else matches[-1]["winner_id"]
        defender_id = seeds[size - round_number]["id"]
        if me["id"] not in (challenger_id, defender_id):
            return "Stepladder in progress — you are waiting for a later round", []
        other_id = defender_id if me["id"] == challenger_id else challenger_id
        other = next(row for row in standings if row["id"] == other_id)
        return f"Stepladder round {round_number}", [(other["name"], "lane posted at the desk")]

    game = me["games_bowled"] + 1
    for pair in squad_pairs(tournament["id"], game):
        if any(b["id"] == me["id"] for b in pair["bowlers"]):
            others = [(b["name"], f"Lane {b['lane']}") for b in pair["bowlers"] if b["id"] != me["id"]]
            return f"Game {game} on Lanes {pair['lanes'][0]}-{pair['lanes'][1]}", others
    return "Lane not yet assigned", []


def _my_action_tab(tournament: dict, me: dict, standings: list[dict]) -> None:
    brackets = bowler_brackets(tournament["id"], me["id"])
    alive = sum(b["alive"] for b in brackets)
    with st.container(border=True):
        st.subheader(f"{'🟢' if alive else '🔴'} Alive in {alive} of {len(brackets)} Brackets")
        for bracket in brackets:
            icon = "✅" if bracket["alive"] else "❌"
            st.markdown(f"{icon} **{bracket['name']}** — {escape(bracket['detail'])}")

    with st.container(border=True):
        heading, opponents = _next_opponent(tournament, me, standings)
        st.markdown(f"**Next matchup · {escape(heading)}**")
        for name, lane in opponents:
            st.write(f"vs **{name}** — {lane}")

    equity = payout_equity(tournament, standings, me["id"])
    with st.container(border=True):
        st.markdown("**Scholarship equity**")
        if not equity["pool"]:
            st.caption("The scholarship pool has not been set yet.")
        else:
            cols = st.columns(2)
            cols[0].metric("Guaranteed", f"${equity['guaranteed']:,.2f}")
            cols[1].metric("If standings hold", f"${equity['projected']:,.2f}")
            st.caption(
                f"Top {equity['paid_places']} places are paid. Guaranteed assumes you score nothing "
                f"more while everyone else bowls perfect games (worst finish: #{equity['worst_rank']})."
            )

    cut = standings[CUT_SEED - 1]["handicap_total"] if len(standings) >= CUT_SEED else None
    columns = st.columns(3)
    columns[0].metric("Rank", f"#{me['rank']}")
    columns[1].metric("Total", me["handicap_total"])
    if cut is not None:
        columns[2].metric(f"vs Seed #{CUT_SEED} cut", f"{me['handicap_total'] - cut:+d}")


def render_bowler_portal(tournament_id: int | None = None) -> None:
    init_db()
    inject_styles()
    st.title("Bowler Portal")
    tournament = pick_tournament(tournament_id, key="portal_tournament", statuses=("active", "completed"))
    if tournament is None:
        return
    standings = compute_standings(tournament["id"])
    if not standings:
        st.info("No bowlers registered yet.")
        return

    by_id = {row["id"]: row for row in standings}
    me_id = st.selectbox(
        "Who are you?",
        list(by_id),
        format_func=lambda i: (
            f"{by_id[i]['name']} ({by_id[i]['usbc_id']})" if by_id[i]["usbc_id"] else by_id[i]["name"]
        ),
        key=f"portal_bowler_{tournament['id']}",
    )
    me = by_id[me_id]
    bowlers = query("SELECT lane_assignment FROM bowlers WHERE tournament_id = ?", (tournament["id"],))
    _movement_banner(tournament, me, lane_count(tournament, bowlers))

    standings_tab, action_tab = st.tabs(["Standings", "My Action"])
    with standings_tab:
        _standings_tab(tournament["id"], me["id"])
    with action_tab:
        _my_action_tab(tournament, me, standings)
