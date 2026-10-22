"""Leaderboard table with a red finals cut line."""

from html import escape

import streamlit as st

from modules.standings import CUT_SEED

_TABLE_STYLE = (
    "width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E2E8F0;"
    "border-radius:12px;overflow:hidden;font-size:0.95rem"
)


def render_leaderboard(
    standings: list[dict], cut: int = CUT_SEED, highlight_bowler_id: int | None = None
) -> None:
    if not standings:
        st.info("No scores yet.")
        return
    rows = []
    for row in standings:
        background = "#FEF9C3" if row["id"] == highlight_bowler_id else "#FFFFFF"
        border = "3px solid #DC2626" if row["rank"] == cut and len(standings) > cut else "1px solid #E2E8F0"
        marker = "T" if row["tied"] else ""
        rows.append(
            f'<tr style="background:{background};border-bottom:{border}">'
            f'<td style="padding:6px 10px">{marker}{row["rank"]}</td>'
            f'<td style="padding:6px 10px">{escape(row["name"])}</td>'
            f'<td style="padding:6px 10px;text-align:right">{row["games_bowled"]}</td>'
            f'<td style="padding:6px 10px;text-align:right">{row["scratch_total"]}</td>'
            f'<td style="padding:6px 10px;text-align:right"><b>{row["handicap_total"]}</b></td>'
            "</tr>"
        )
    header = "".join(
        f'<th style="padding:8px 10px;text-align:{align};background:#334155;color:#FFFFFF">{label}</th>'
        for label, align in (("#", "left"), ("Bowler", "left"), ("Gms", "right"), ("Scratch", "right"), ("Total", "right"))
    )
    st.markdown(f'<table style="{_TABLE_STYLE}"><tr>{header}</tr>{"".join(rows)}</table>', unsafe_allow_html=True)
    if len(standings) > cut:
        st.caption(f"Red line = Seed #{cut} cut line")
