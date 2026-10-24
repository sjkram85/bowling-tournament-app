"""Tournament selection widget shared by the hub and portal views."""

import streamlit as st

from modules.standings import query


def pick_tournament(
    tournament_id: int | None, key: str, statuses: tuple[str, ...] = ("active",)
) -> dict | None:
    """Return the tournament to display: the one given, else a selectbox of matching ones."""
    if tournament_id is not None:
        rows = query("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
        return rows[0] if rows else None
    marks = ",".join("?" * len(statuses))
    rows = query(f"SELECT * FROM tournaments WHERE status IN ({marks}) AND COALESCE(is_practice, 0) = 0 ORDER BY id DESC", statuses)
    if not rows:
        st.info("No tournaments available.")
        return None
    if len(rows) == 1:
        return rows[0]
    return st.selectbox("Tournament", rows, format_func=lambda t: t["name"], key=key)
