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
