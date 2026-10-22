"""Concourse TV kiosk, reached with ?mode=kiosk. Read-only and auto-refreshing."""

import streamlit as st

from components.header import render_header
from components.leaderboard import render_leaderboard
from components.tournament_picker import pick_tournament
from modules.standings import compute_standings, current_game, get_tournament

KIOSK_REFRESH_SECONDS = 8


@st.fragment(run_every=KIOSK_REFRESH_SECONDS)
def _kiosk_board(tournament_id: int) -> None:
    tournament = get_tournament(tournament_id)
    if tournament is None:
        st.info("Tournament not found.")
        return
    game = current_game(tournament_id, tournament["game_count"])
    render_header(
        tournament["name"],
        tournament["host_center"],
        active_game=game if tournament["status"] == "active" else None,
        total_games=tournament["game_count"],
        logo_path=tournament["logo_path"],
        squad_format=tournament["squad_format"],
    )
    render_leaderboard(compute_standings(tournament_id))


def render_kiosk() -> None:
    raw_id = st.query_params.get("tournament")
    tournament_id = int(raw_id) if raw_id and str(raw_id).isdigit() else None
    tournament = pick_tournament(tournament_id, key="kiosk_tournament")
    if tournament is not None:
        _kiosk_board(tournament["id"])
