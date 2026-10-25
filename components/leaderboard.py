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


def desk_standings_html(groups: list[dict]) -> str:
    """TD desk boards using the same rows, cut, and TIE – ROLL-OFF flags as the kiosk."""
    blocks = []
    empty = []
    saw_cut = saw_roll = saw_champ = False
    for group in groups:
        rows = group.get("rows") or []
        if not rows:
            if group.get("label"):
                empty.append(group["label"])
            continue
        last_cut = None
        for index, row in enumerate(rows):
            if row.get("finalist"):
                last_cut = index
            saw_roll = saw_roll or bool(row.get("rolloff"))
            saw_champ = saw_champ or bool(row.get("champion"))
            saw_cut = saw_cut or bool(row.get("finalist"))
        body = []
        for index, row in enumerate(rows):
            flags = []
            if row.get("champion"):
                flags.append("CHAMPION")
            elif row.get("finalist"):
                flags.append("IN CUT")
            if row.get("rolloff"):
                flags.append("TIE – ROLL-OFF")
            elif row.get("tied"):
                flags.append("TIED")
            cut = last_cut is not None and index == last_cut and group.get("stage") != "final"
            border = "3px solid #EF4444" if cut else "1px solid #334155"
            if row.get("rolloff"):
                background = "#451a03"
            elif row.get("champion") or row.get("finalist"):
                background = "#052e16"
            else:
                background = "#1E293B"
            cell = f"padding:8px 10px;color:#F8FAFC;background:{background};border-bottom:{border};"
            rank = f"{'T' if row.get('tied') else ''}{row.get('rank', '')}"
            body.append(
                "<tr>"
                f"<td style='{cell}'>{escape(str(rank))}</td>"
                f"<td style='{cell}'>{escape(str(row.get('name') or ''))}</td>"
                f"<td style='{cell}text-align:right'>{row.get('games', 0)}</td>"
                f"<td style='{cell}text-align:right'><b>{row.get('total', 0)}</b></td>"
                f"<td style='{cell}'>{escape(' · '.join(flags))}</td>"
                "</tr>"
            )
        title = escape(group.get("label") or "Standings")
        note = f"<div style='color:#FDE68A;font-size:15px;margin:2px 0 8px'>{escape(group['note'])}</div>" if group.get("note") else ""
        blocks.append(
            f"<div style='margin:0 0 16px'><div style='color:#FACC15;font-size:18px;font-weight:800'>{title}</div>"
            f"{note}<table style='{_TABLE_STYLE}'><tr>"
            "<th style='padding:8px 10px;text-align:left;background:#0F172A;color:#E2E8F0'>#</th>"
            "<th style='padding:8px 10px;text-align:left;background:#0F172A;color:#E2E8F0'>Bowler</th>"
            "<th style='padding:8px 10px;text-align:right;background:#0F172A;color:#E2E8F0'>Games</th>"
            "<th style='padding:8px 10px;text-align:right;background:#0F172A;color:#E2E8F0'>Total</th>"
            "<th style='padding:8px 10px;text-align:left;background:#0F172A;color:#E2E8F0'>Flag</th>"
            f"</tr>{''.join(body)}</table></div>"
        )
    if not blocks and not empty:
        return ""
    legend = []
    if saw_cut:
        legend.append("Green row = in the finals cut. Red line = last locked cut spot.")
    if saw_roll:
        legend.append("TIE – ROLL-OFF = tied for the last finals spot. A roll-off decides it.")
    if saw_champ:
        legend.append("CHAMPION = stepladder winner, shown as 1st.")
    legend_html = (
        f"<div style='color:#CBD5E1;font-size:14px;margin:0 0 10px'>{escape(' '.join(legend))}</div>" if legend else ""
    )
    empty_html = (
        f"<div style='color:#94A3B8;font-size:14px;margin-top:4px'>No bowlers yet in: {escape(', '.join(empty))}</div>"
        if empty else ""
    )
    return legend_html + "".join(blocks) + empty_html


def render_desk_division_standings(tournament_id: int) -> None:
    """Hub standings. Same board as the lobby kiosk, sized for the desk."""
    from modules.kiosk_data import public_groups
    try:
        groups = public_groups(tournament_id)
    except Exception:
        st.caption("Division standings could not be loaded.")
        return
    html = desk_standings_html(groups)
    if not html:
        st.caption("No standings yet.")
        return
    st.markdown(html, unsafe_allow_html=True)


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
