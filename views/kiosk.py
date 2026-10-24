"""Public kiosk screen: ?mode=kiosk&t=<tournament id>. Read-only, full-screen, auto-refreshing.

No logins, staff controls, chat, TD panel, fees or paid info ever appear here.
"""

from html import escape

import streamlit as st

from modules.kiosk_data import eastern_now, load_board, paginate, parse_tournament_id

KIOSK_REFRESH_SECONDS = 15

_CSS = """<style>
#MainMenu, header, footer, [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] {display:none !important;}
.stApp {background:#000 !important;}
.block-container {padding:1.2rem 2rem !important; max-width:100% !important;}
.k-top {display:flex; justify-content:space-between; align-items:flex-end; color:#fff; border-bottom:3px solid #FACC15; padding-bottom:8px;}
.k-name {font-size:46px; font-weight:800; line-height:1.1;}
.k-meta {font-size:22px; color:#E5E7EB; text-align:right;}
.k-practice {background:#B45309; color:#fff; font-size:34px; font-weight:800; text-align:center; padding:10px; border-radius:8px; margin:10px 0;}
.k-grid {display:flex; flex-wrap:wrap; gap:28px; margin-top:14px;}
.k-group {flex:1 1 560px;}
.k-glabel {color:#FACC15; font-size:32px; font-weight:800; margin-bottom:6px;}
.k-table {width:100%; border-collapse:collapse; color:#fff; font-size:30px;}
.k-table th {color:#9CA3AF; font-size:20px; text-align:left; border-bottom:2px solid #374151; padding:4px 8px;}
.k-table td {padding:6px 8px; border-bottom:1px solid #1F2937;}
.k-table td.n {text-align:right; font-variant-numeric:tabular-nums;}
.k-table th.n {text-align:right;}
.k-fin td {background:#052e16;}
.k-star {color:#4ADE80; font-weight:800;}
.k-foot {color:#9CA3AF; font-size:20px; margin-top:12px;}
</style>"""


def _group_html(g: dict) -> str:
    body = "".join(
        f"<tr class='{'k-fin' if r['finalist'] else ''}'><td class='n'>{r['rank']}</td>"
        f"<td>{escape(r['name'])}{' <span class=k-star>★ FINALIST</span>' if r['finalist'] else ''}</td>"
        f"<td class='n'>{r['games']}</td><td class='n'>{r['total']}</td></tr>"
        for r in g["rows"]
    ) or "<tr><td colspan=4>No bowlers yet</td></tr>"
    return (f"<div class='k-group'><div class='k-glabel'>{escape(g['label'])}</div><table class='k-table'>"
            "<tr><th class='n'>#</th><th>Bowler</th><th class='n'>Games</th><th class='n'>Total</th></tr>"
            f"{body}</table></div>")


def build_html(board: dict, page_idx: int, now_text: str) -> str:
    pages = paginate(board["groups"])
    idx = page_idx % len(pages)
    page_note = f" · Page {idx + 1} of {len(pages)}" if len(pages) > 1 else ""
    has_finalists = any(r["finalist"] for g in board["groups"] for r in g["rows"])
    return (
        f"<div class='k-top'><div class='k-name'>{escape(board['name'])}</div>"
        f"<div class='k-meta'>{escape(board['center'])}<br>Last updated {now_text}{page_note}</div></div>"
        + ("<div class='k-practice'>🧪 PRACTICE – not real results</div>" if board["practice"] else "")
        + "<div class='k-grid'>" + "".join(_group_html(g) for g in pages[idx]) + "</div>"
        + "<div class='k-foot'>" + ("★ = currently in the finals cut. " if has_finalists else "")
        + "Standings are unofficial until certified.</div>"
    )


@st.fragment(run_every=KIOSK_REFRESH_SECONDS)
def _board(tournament_id: int) -> None:
    board = load_board(tournament_id)
    if board is None:
        st.markdown("<div class='k-name' style='color:#fff'>Standings will appear here soon.</div>",
                    unsafe_allow_html=True)
        return
    idx = st.session_state.get("kiosk_page", -1) + 1
    st.session_state["kiosk_page"] = idx
    st.markdown(build_html(board, idx, eastern_now()), unsafe_allow_html=True)


def render_kiosk() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    tournament_id = parse_tournament_id(st.query_params)
    if tournament_id is None:  # old link: fine when exactly one real event is running
        from modules.events import active_events
        real = [e for e in active_events() if not e["is_practice"]]
        tournament_id = real[0]["id"] if len(real) == 1 else None
    if tournament_id is None:
        st.markdown("<div class='k-name' style='color:#fff'>This kiosk link is missing its event.<br>"
                    "<span style='font-size:26px'>Ask a TD to press “Open kiosk for this event”.</span></div>",
                    unsafe_allow_html=True)
        return
    _board(tournament_id)
