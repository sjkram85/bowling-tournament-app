"""Finals and close-out hub: stepladder, tiebreaks, end-of-tournament actions."""

import streamlit as st

from components.styles import inject_styles
from components.tournament_picker import pick_tournament
from modules.db_state import get_connection, init_db
from modules.mailer import dispatch_bowler_recap_email
from modules.reports import (
    build_certified_pdf,
    build_smart_scholarship_csv,
    final_places,
    freeze_tournament,
    get_archive,
    ladder_size,
    scholarship_amounts,
    stepladder_matches,
)
from modules.standings import (
    MAX_GAME_SCORE,
    TIEBREAK_FINAL_GAME,
    TIEBREAK_ROLL_OFF,
    compute_standings,
    log_action,
    query,
    tie_groups,
)

TIEBREAK_LABELS = {
    TIEBREAK_FINAL_GAME: "Highest final game",
    TIEBREAK_ROLL_OFF: "9th/10th frame roll-off",
}


# -------------------------------------------------------------------- tiebreaks

def _save_roll_off(tournament_id: int, bowler_id: int, target_seed: int, frame_9: int, frame_10: int) -> None:
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO tiebreak_roll_offs (tournament_id, bowler_id, target_seed, frame_9, frame_10, "
                "roll_off_total) VALUES (?, ?, ?, ?, ?, ?)",
                (tournament_id, bowler_id, target_seed, str(frame_9), str(frame_10), frame_9 + frame_10),
            )
    finally:
        connection.close()


def _tiebreak_section(tournament: dict, standings: list[dict]) -> None:
    st.subheader("Tiebreaks")
    method = st.radio(
        "Tiebreak method",
        list(TIEBREAK_LABELS),
        format_func=TIEBREAK_LABELS.__getitem__,
        index=list(TIEBREAK_LABELS).index(tournament["tiebreak_type"] or TIEBREAK_FINAL_GAME),
        horizontal=True,
        key=f"tiebreak_method_{tournament['id']}",
    )
    if method != (tournament["tiebreak_type"] or TIEBREAK_FINAL_GAME):
        connection = get_connection()
        try:
            with connection:
                connection.execute("UPDATE tournaments SET tiebreak_type = ? WHERE id = ?", (method, tournament["id"]))
        finally:
            connection.close()
        st.rerun()

    groups = tie_groups(standings)
    if not groups:
        st.success("No ties affecting the finals seeds.")
        return
    for group in groups:
        names = ", ".join(m["name"] for m in group["members"])
        status = "⚠️ unresolved" if group["unresolved"] else "✅ resolved"
        with st.container(border=True):
            st.markdown(
                f"**Tied at {group['total']} for seed #{group['start_rank']}** — {names} ({status})"
            )
            if method == TIEBREAK_FINAL_GAME:
                st.caption(
                    "Final game: "
                    + ", ".join(f"{m['name']} {m['final_game']}" for m in group["members"])
                )
            if method == TIEBREAK_ROLL_OFF or group["unresolved"]:
                _roll_off_form(tournament["id"], group)


def _roll_off_form(tournament_id: int, group: dict) -> None:
    with st.form(f"rolloff_{tournament_id}_{group['start_rank']}"):
        entries = {}
        for member in group["members"]:
            cols = st.columns([2, 1, 1])
            cols[0].markdown(f"**{member['name']}**")
            entries[member["id"]] = (
                cols[1].number_input("9th frame", 0, 10, 0, key=f"f9_{group['start_rank']}_{member['id']}"),
                cols[2].number_input("10th frame", 0, 30, 0, key=f"f10_{group['start_rank']}_{member['id']}"),
            )
        if st.form_submit_button("Record roll-off"):
            for bowler_id, (frame_9, frame_10) in entries.items():
                _save_roll_off(tournament_id, bowler_id, group["start_rank"], int(frame_9), int(frame_10))
            st.rerun()


# ------------------------------------------------------------------- stepladder

def _save_match(tournament_id: int, round_number: int, a: dict, b: dict, score_a: int, score_b: int, td: str) -> None:
    total_a = score_a + (a["handicap"] or 0)
    total_b = score_b + (b["handicap"] or 0)
    winner = a["id"] if total_a > total_b else b["id"]
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO stepladder_matches (tournament_id, round_number, bowler_a_id, bowler_b_id, "
                "score_a, score_b, winner_id, entered_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tournament_id, round_number, a["id"], b["id"], score_a, score_b, winner, f"TD: {td}"),
            )
    finally:
        connection.close()
    log_action(f"TD: {td}", "td", f"Stepladder round {round_number} entered (tournament {tournament_id})")


def _stepladder_section(tournament: dict, standings: list[dict], read_only: bool) -> None:
    size = ladder_size(standings)
    st.subheader("Stepladder Finals")
    if size < 2:
        st.info("At least two bowlers are needed for a stepladder.")
        return
    seeds = {row["rank"]: row for row in standings[:size]}
    matches = stepladder_matches(tournament["id"])
    st.caption("Winner is decided on scratch + handicap. Seeds: " + " · ".join(
        f"#{s} {r['name']}" for s, r in seeds.items()
    ))
    rounds_total = size - 1
    for round_number in range(1, rounds_total + 1):
        defender = seeds[size - round_number]
        challenger_label = f"#{size} {seeds[size]['name']}" if round_number == 1 else f"Winner of round {round_number - 1}"
        played = next((m for m in matches if m["round_number"] == round_number), None)
        if played:
            st.markdown(
                f"**Round {round_number}** — {played['name_a']} {played['score_a']} vs "
                f"{played['name_b']} {played['score_b']} → **{played['winner_name']}**"
            )
        else:
            st.markdown(f"**Round {round_number}** — {challenger_label} vs #{size - round_number} {defender['name']}")

    next_round = len(matches) + 1
    if next_round > rounds_total:
        st.success(f"🏆 Champion: {matches[-1]['winner_name']}")
        return
    if read_only:
        return
    if not matches and any(g["unresolved"] for g in tie_groups(standings)):
        st.warning("Resolve the seeding ties before starting the stepladder.")
        return
    challenger = seeds[size] if next_round == 1 else next(r for r in standings if r["id"] == matches[-1]["winner_id"])
    defender = seeds[size - next_round]
    st.markdown(f"**Next: Round {next_round}** — {challenger['name']} vs {defender['name']}")
    with st.form(f"match_{tournament['id']}_{next_round}"):
        td = st.text_input("TD name", value=st.session_state.get("td_name", ""))
        cols = st.columns(2)
        score_a = cols[0].number_input(f"{challenger['name']} (scratch)", 0, MAX_GAME_SCORE, 0)
        score_b = cols[1].number_input(f"{defender['name']} (scratch)", 0, MAX_GAME_SCORE, 0)
        if st.form_submit_button("Record match", type="primary"):
            total_a = score_a + (challenger["handicap"] or 0)
            total_b = score_b + (defender["handicap"] or 0)
            if not td.strip():
                st.error("Enter your TD name.")
            elif total_a == total_b:
                st.error("Match is tied after handicap — settle it and enter the deciding scores.")
            else:
                st.session_state["td_name"] = td.strip()
                _save_match(tournament["id"], next_round, challenger, defender, int(score_a), int(score_b), td.strip())
                st.rerun()


# ---------------------------------------------------------------- end tournament

def _send_recaps(tournament_id: int, prize_pool: float) -> tuple[int, int]:
    places = final_places(tournament_id)
    ranked = compute_standings(tournament_id)
    standings = {row["id"]: row for row in ranked}
    amounts = scholarship_amounts(len(ranked), prize_pool)
    sent = failed = 0
    for bowler in query(
        "SELECT id, name, email, handicap FROM bowlers WHERE tournament_id = ? AND email IS NOT NULL AND email != ''",
        (tournament_id,),
    ):
        scores = [
            {"game_number": g, "scratch_score": s} for g, s in sorted(standings[bowler["id"]]["game_scores"].items())
        ]
        rank = standings[bowler["id"]]["rank"]
        amount = amounts[rank - 1] if rank <= len(amounts) else 0
        totals = {
            "scratch_total": standings[bowler["id"]]["scratch_total"],
            "handicap_total": standings[bowler["id"]]["handicap_total"],
            "place": places.get(bowler["id"], ""),
            "prize_status": "SMART scholarship award" if amount else "No scholarship award",
            "prize_amount": amount,
        }
        try:
            ok = dispatch_bowler_recap_email(dict(bowler), scores, totals)
        except (KeyError, FileNotFoundError):
            ok = False
        sent += ok
        failed += not ok
    return sent, failed


def _end_tournament(tournament: dict, td: str, prize_pool: float) -> None:
    tid = tournament["id"]
    pdf = build_certified_pdf(tid, td)
    smart_csv = build_smart_scholarship_csv(tid, prize_pool)
    freeze_tournament(tid, td, pdf, smart_csv)
    sent, failed = _send_recaps(tid, prize_pool)
    log_action(td, "td", f"Ended tournament {tid}; recap emails sent {sent}, failed {failed}")
    st.session_state[f"ended_{tid}"] = (sent, failed)
    st.rerun()


def _downloads(tournament: dict, archive: dict) -> None:
    cols = st.columns(4)
    name = tournament["name"].replace(" ", "_")
    cols[0].download_button("Certified PDF", archive["certified_pdf"], f"{name}_results.pdf", "application/pdf", width="stretch")
    cols[1].download_button("SMART CSV", archive["smart_csv"], f"{name}_smart.csv", "text/csv", width="stretch")
    cols[2].download_button("BITS CSV", archive["bls_bits_csv"], f"{name}_bits.csv", "text/csv", width="stretch")
    cols[3].download_button("AutoScoring .dat", archive["bls_autoscoring_dat"], f"{name}.dat", "text/plain", width="stretch")


def _close_section(tournament: dict, standings: list[dict]) -> None:
    st.subheader("Close Tournament")
    archive = get_archive(tournament["id"])
    if archive:
        st.success(f"Archived {archive['archived_at']} by {archive['archived_by']} (read-only).")
        ended = st.session_state.get(f"ended_{tournament['id']}")
        if ended:
            st.info(f"Recap emails: {ended[0]} sent, {ended[1]} failed.")
        _downloads(tournament, archive)
        return

    size = ladder_size(standings)
    blockers = []
    if any(g["unresolved"] for g in tie_groups(standings)):
        blockers.append("Resolve all unresolved ties first.")
    if size >= 2 and len(stepladder_matches(tournament["id"])) < size - 1:
        blockers.append("Finish the stepladder first.")
    for blocker in blockers:
        st.warning(blocker)

    td = st.text_input("TD name", value=st.session_state.get("td_name", ""), key="close_td")
    prize_pool = st.number_input(
        "SMART scholarship pool ($)",
        min_value=0.0,
        value=float(tournament.get("smart_pool") or 0),
        step=5.0,
        key=f"pool_{tournament['id']}",
    )
    if prize_pool != float(tournament.get("smart_pool") or 0):
        connection = get_connection()
        try:
            with connection:
                connection.execute("UPDATE tournaments SET smart_pool = ? WHERE id = ?", (prize_pool, tournament["id"]))
        finally:
            connection.close()
        st.rerun()
    certify = st.checkbox("I certify these results are final. This freezes the tournament permanently.")
    if st.button("End Tournament", type="primary", width="stretch", disabled=bool(blockers) or not certify):
        if not td.strip():
            st.error("Enter your TD name.")
        else:
            st.session_state["td_name"] = td.strip()
            _end_tournament(tournament, td.strip(), prize_pool)


def render_finals_close(tournament_id: int | None = None) -> None:
    init_db()
    inject_styles()
    st.title("Finals & Close-Out")
    tournament = pick_tournament(tournament_id, key="finals_tournament", statuses=("active", "completed"))
    if tournament is None:
        return
    standings = compute_standings(tournament["id"])
    if not standings:
        st.info("No bowlers in this tournament.")
        return
    completed = tournament["status"] == "completed"
    if not completed:
        _tiebreak_section(tournament, standings)
    _stepladder_section(tournament, standings, read_only=completed)
    _close_section(tournament, standings)
