"""Prism A.I dock: one assistant card shown on every desk screen."""

import json
import math
from datetime import datetime
from html import escape
from pathlib import Path

import streamlit as st

from modules.constants import CENTERS
from modules.db_state import DATABASE_PATH
from modules.prism_ai import get_prism_ai_guidance
from modules.reports import ladder_size, stepladder_matches
from modules.standings import CUT_SEED, compute_standings, current_game, query, squad_pairs, tie_groups

BOWLERS_PER_PAIR = 4
# Prefix that routes a TD question to the rulebook model (it matches the rule/dispute keywords).
DISPUTE_PREFIX = "Rule dispute: "

VIEW_SLUGS = {
    "Intake Gateway": "intake",
    "Active Squad Hub": "squad",
    "Finals Closeout": "finals",
    "Historical Archive Vault": "archive",
    "Staff Accounts": "staff",
}


# ------------------------------------------------------------------ view state

def _focus_tournament(statuses: tuple[str, ...]) -> dict | None:
    """The tournament just started on this desk, else the newest one with a matching status."""
    marks = ",".join("?" * len(statuses))
    chosen = st.session_state.get("active_tournament_id")
    if chosen is not None:
        rows = query(f"SELECT * FROM tournaments WHERE id = ? AND status IN ({marks})", (chosen, *statuses))
        if rows:
            return rows[0]
    rows = query(f"SELECT * FROM tournaments WHERE status IN ({marks}) ORDER BY id DESC LIMIT 1", statuses)
    return rows[0] if rows else None


def _intake_state() -> dict:
    summary = st.session_state.get("intake_summary") or {}
    bowlers = int(summary.get("bowlers", 0))
    host = CENTERS.get(summary.get("host_code", ""), {})
    state = {
        "bowlers": bowlers,
        "pairs_needed": math.ceil(bowlers / BOWLERS_PER_PAIR) if bowlers else 0,
        "bowlers_on_partial_pair": bowlers % BOWLERS_PER_PAIR,
        "pacers": int(summary.get("pacers", 0)),
        "unpaid": int(summary.get("unpaid", 0)),
        "host_center": host.get("name"),
        "host_pairs_available": host.get("pairs"),
        "mystery_doubles_side_pot": bool(summary.get("mystery_doubles")),
    }
    if not bowlers:
        hint = "💡 Load a BITS roster or add bowlers to the triage grid to begin."
    elif state["host_pairs_available"] and state["pairs_needed"] > state["host_pairs_available"]:
        hint = (
            f"💡 {bowlers} bowlers need {state['pairs_needed']} lane pairs but {state['host_center']} "
            f"has {state['host_pairs_available']}. Split the squad or pick a larger house."
        )
    elif state["bowlers_on_partial_pair"]:
        hint = f"💡 {bowlers} bowlers leave a pair partly filled. Add a pacer or a bowler to balance the lanes."
    elif not state["mystery_doubles_side_pot"]:
        hint = "💡 Lanes balance. Consider the $5 Mystery Doubles side pot, then set the PIN and start the squad."
    else:
        hint = "💡 Roster and lanes look good. Confirm the scoring PIN and tap Start Squad."
    state["local_hint"] = hint
    return state


def _squad_state() -> dict:
    tournament = _focus_tournament(("active",))
    if tournament is None:
        return {"local_hint": "💡 No active squad. Start one from the Intake Gateway."}
    tid = tournament["id"]
    game = current_game(tid, tournament["game_count"])
    pairs = squad_pairs(tid, game)
    pending = [p["pair"] for p in pairs if not p["complete"]]
    standings = compute_standings(tid)
    cut = standings[CUT_SEED - 1] if len(standings) >= CUT_SEED else None
    first_out = standings[CUT_SEED] if len(standings) > CUT_SEED else None
    state = {
        "tournament": tournament["name"],
        "game": game,
        "pairs_reported": len(pairs) - len(pending),
        "pairs_total": len(pairs),
        "pairs_pending": pending,
        "cut_line_seed": CUT_SEED,
        "cut_line_total": cut["handicap_total"] if cut else None,
        "pins_between_5th_and_6th": cut["handicap_total"] - first_out["handicap_total"] if cut and first_out else None,
        "top_seeds": [(r["rank"], r["name"], r["handicap_total"]) for r in standings[: CUT_SEED + 1]],
    }
    if pending:
        listed = ", ".join(str(p) for p in pending[:6]) + ("…" if len(pending) > 6 else "")
        state["local_hint"] = f"💡 Waiting on lane reports (pairs {listed}). Tap Enter Scores or use the mobile verifier."
    elif state["pins_between_5th_and_6th"] is not None and state["pins_between_5th_and_6th"] <= 20:
        state["local_hint"] = f"💡 Game {game} is in and the Seed #5 cut line is within {state['pins_between_5th_and_6th']} pins. Watch the bubble."
    else:
        state["local_hint"] = f"💡 All pairs reported Game {game}. Review the leaderboard and move to the next game."
    return state


def _finals_state() -> dict:
    tournament = _focus_tournament(("active", "completed"))
    if tournament is None:
        return {"local_hint": "💡 No tournament to close out yet."}
    tid = tournament["id"]
    standings = compute_standings(tid)
    rounds_total = max(ladder_size(standings) - 1, 0)
    rounds_done = len(stepladder_matches(tid))
    unresolved = [g for g in tie_groups(standings) if g["unresolved"]]
    state = {
        "tournament": tournament["name"],
        "status": tournament["status"],
        "stepladder_rounds_done": rounds_done,
        "stepladder_rounds_total": rounds_total,
        "unresolved_cut_line_ties": len(unresolved),
        "tiebreak_method": tournament["tiebreak_type"],
    }
    if tournament["status"] == "completed":
        hint = "💡 This tournament is archived. Download the closeout files from the Archive Vault."
    elif unresolved:
        hint = f"💡 {len(unresolved)} cut-line tie(s) need a roll-off or final-game decision before the stepladder."
    elif rounds_total and rounds_done < rounds_total:
        hint = f"💡 Stepladder round {rounds_done + 1} of {rounds_total} is next. Enter the match scores."
    elif rounds_total:
        hint = "💡 Stepladder is complete. Tap End Tournament to certify, export and email recaps."
    else:
        hint = "💡 Not enough bowlers for a stepladder yet."
    state["local_hint"] = hint
    return state


def _archive_state() -> dict:
    archives = query("SELECT COUNT(*) AS n, MAX(archived_at) AS latest FROM tournament_archives")[0]
    audit = query("SELECT COUNT(*) AS n, MAX(timestamp) AS latest FROM audit_log")[0]
    db_file = Path(DATABASE_PATH)
    wal_file = Path(f"{DATABASE_PATH}-wal")
    state = {
        "archived_tournaments": archives["n"],
        "latest_archive": archives["latest"],
        "audit_entries": audit["n"],
        "latest_audit_entry": audit["latest"],
        "database_mb": round(db_file.stat().st_size / 1_048_576, 2) if db_file.exists() else 0,
        "wal_pending_kb": round(wal_file.stat().st_size / 1024) if wal_file.exists() else 0,
        "database_last_written": datetime.fromtimestamp(db_file.stat().st_mtime).isoformat(timespec="minutes")
        if db_file.exists()
        else None,
    }
    if not archives["n"]:
        state["local_hint"] = "💡 No archived tournaments yet. Close out a tournament to create the first vault entry."
    elif state["wal_pending_kb"] > 1024:
        state["local_hint"] = "💡 Large write-ahead log pending. Keep the app running so it checkpoints, then back up prism_operational.db."
    else:
        state["local_hint"] = f"💡 {archives['n']} archived tournament(s), {audit['n']} audit entries. Copy prism_operational.db off-site for a backup."
    return state


def _staff_state() -> dict:
    counts = query(
        "SELECT SUM(is_approved = 0) AS pending, SUM(role = 'admin') AS admins, COUNT(*) AS total FROM staff_users"
    )[0]
    pending = int(counts["pending"] or 0)
    state = {"pending_requests": pending, "admins": int(counts["admins"] or 0), "accounts": counts["total"]}
    state["local_hint"] = (
        f"💡 {pending} access request(s) are waiting for approval."
        if pending
        else "💡 No pending access requests. Reset passwords or change roles from the table below."
    )
    return state


_COLLECTORS = {
    "intake": _intake_state,
    "squad": _squad_state,
    "finals": _finals_state,
    "archive": _archive_state,
    "staff": _staff_state,
}


def collect_view_state(current_view: str) -> dict:
    """Facts about the current screen, passed to Prism A.I and used for the offline fallback."""
    slug = VIEW_SLUGS.get(current_view, current_view)
    try:
        state = _COLLECTORS[slug]()
    except Exception:
        state = {"local_hint": "💡 Continue with the next step on this screen."}
    return {"screen": current_view, **state}


# ------------------------------------------------------------------------ dock

def _guidance(current_view: str, view_state: dict, force: bool) -> str:
    """Flash guidance, cached per screen and state so it is only requested when something changes."""
    signature = json.dumps({k: v for k, v in view_state.items() if k != "local_hint"}, default=str, sort_keys=True)
    key = f"prism_dock_guidance::{current_view}"
    cached = st.session_state.get(key)
    if force or cached is None or cached[0] != signature:
        with st.spinner("Prism A.I is thinking..."):
            st.session_state[key] = (signature, get_prism_ai_guidance(view_state))
    return st.session_state[key][1]


def _arbitrator(current_view: str, view_state: dict) -> None:
    answer_key = "prism_dock_answer"
    with st.expander("⚖️ USBC Rule & Dispute Arbitrator"):
        with st.form("prism_dock_dispute", clear_on_submit=False):
            question = st.text_input(
                "Describe the dispute",
                placeholder="e.g. Bowler bowled out of order in frame 4, what is the ruling?",
            )
            asked = st.form_submit_button("Ask the rulebook", width="stretch")
        if asked:
            if not question.strip():
                st.warning("Enter a question.")
            else:
                with st.spinner("Searching the USBC rulebook..."):
                    st.session_state[answer_key] = get_prism_ai_guidance(
                        view_state, DISPUTE_PREFIX + question.strip()
                    )
        if st.session_state.get(answer_key):
            st.markdown(st.session_state[answer_key])


def render_prism_dock(current_view: str, view_state: dict) -> None:
    """Render the assistant dock below the current screen."""
    with st.container(key="prism_dock"):
        title, refresh = st.columns([4, 1], vertical_alignment="center")
        title.markdown(
            f'<span class="ptcc-dock-title"><span class="ptcc-dock-spark">✨</span> Prism A.I</span>'
            f'<span class="ptcc-dock-view">{escape(current_view)}</span>',
            unsafe_allow_html=True,
        )
        force = refresh.button("Refresh Guidance", key="prism_dock_refresh", width="stretch")
        st.markdown(
            f'<div class="ptcc-dock-guidance">{escape(_guidance(current_view, view_state, force))}</div>',
            unsafe_allow_html=True,
        )
        _arbitrator(current_view, view_state)
