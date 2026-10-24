"""Leaderboard table with a red finals cut line, legible on the dark theme."""

from html import escape

import streamlit as st

from modules.standings import CUT_SEED

_TABLE_STYLE = (
    "width:100%;border-collapse:separate;border-spacing:0;background:#1E293B;color:#F1F5F9;"
    "border:1px solid #334155;border-radius:12px;overflow:hidden;font-size:0.95rem"
)
_CELL = "padding:8px 12px;color:#F1F5F9"


def render_leaderboard(
    standings: list[dict], cut: int = CUT_SEED, highlight_bowler_id: int | None = None
) -> None:
    if not standings:
        st.info("No scores yet.")
        return
    has_cut_line = len(standings) > cut
    rows = []
    for row in standings:
        is_cut_row = row["rank"] == cut
        if row["id"] == highlight_bowler_id:
            background, color = "#78350F", "#FEF3C7"
        elif row["rank"] <= cut:
            background, color = "#1E293B", "#F1F5F9"
        else:
            background, color = "#162033", "#CBD5E1"
        # Amber accent on the seed #cut row, red rule under it marks the cut line.
        accent = "border-left:5px solid #F59E0B;" if is_cut_row else "border-left:5px solid transparent;"
        bottom = "3px solid #EF4444" if is_cut_row and has_cut_line else "1px solid #334155"
        cell = f"padding:8px 12px;color:{color};border-bottom:{bottom};background:{background}"
        marker = "T" if row["tied"] else ""
        rows.append(
            "<tr>"
            f'<td style="{cell};{accent}">{marker}{row["rank"]}</td>'
            f'<td style="{cell}">{escape(row["name"])}</td>'
            f'<td style="{cell};text-align:right">{row["games_bowled"]}</td>'
            f'<td style="{cell};text-align:right">{row["scratch_total"]}</td>'
            f'<td style="{cell};text-align:right"><b>{row["handicap_total"]}</b></td>'
            "</tr>"
        )
    header = "".join(
        f'<th style="padding:10px 12px;text-align:{align};background:#0F172A;color:#E2E8F0;'
        f'border-bottom:1px solid #334155">{label}</th>'
        for label, align in (("#", "left"), ("Bowler", "left"), ("Gms", "right"), ("Scratch", "right"), ("Total", "right"))
    )
    st.markdown(f'<table style="{_TABLE_STYLE}"><tr>{header}</tr>{"".join(rows)}</table>', unsafe_allow_html=True)
    if has_cut_line:
        st.caption(f"Red line = Seed #{cut} cut line")


def render_standings_for(tournament_id: int, highlight_bowler_id: int | None = None) -> None:
    """Standings, split into one board per division/group when the tournament has divisions."""
    from modules.divisions import division_label, finalists_count, get_divisions, group_standings
    from modules.standings import compute_standings, get_tournament

    tournament = get_tournament(tournament_id) or {}
    standings = compute_standings(tournament_id)
    divs = get_divisions(tournament)
    if not divs:
        render_leaderboard(standings, highlight_bowler_id=highlight_bowler_id)
        return
    for name, rows in group_standings(standings, tournament):
        st.markdown(f"#### {escape(division_label(name, divs))}")
        if not rows:
            st.caption("No bowlers in this group yet.")
            continue
        render_leaderboard(rows, cut=finalists_count(len(rows)), highlight_bowler_id=highlight_bowler_id)
