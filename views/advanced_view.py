import io
import base64
import json
import math
import random
from datetime import datetime
import pandas as pd
import streamlit as st
from pypdf import PdfReader

from engine_support import (
    parse_active_pairs, auto_assign_lanes,
    generate_qr_image, compile_standings, export_standings_pdf,
    export_lane_assignments_pdf, resolve_bracket_match, calculate_financial_summary,
    generate_smart_scholarship_csv, generate_sop_docx, generate_sop_pdf, notify_user_account_approved
)
from prism_ai import arbitrate_rules_inquiry, stream_prism_ai, parse_roster_text_with_gemini
from scoring import render_cross_pair_progression_matrix, render_live_scoring_floor_grid
from auth import hash_secret, register_td_pin
from db_state import clear_active_tournament_state, clear_kiosk_card, fetch_audit_trail, get_sqlite_conn, write_kiosk_card


def _load_live_roster():
    conn = get_sqlite_conn()
    try:
        roster = pd.read_sql_query("SELECT * FROM live_roster", conn)
    finally:
        conn.close()
    return roster.rename(columns={
        "usbc_id": "USBC ID",
        "bowler": "Bowler",
        "average": "Average",
        "starting_lane": "Starting Lane",
        "division": "Division",
        "team_name": "Team_Name",
        "paid": "Paid",
        "checked_in": "Checked_In",
        "entry_status": "Entry Status",
        "entry_fee": "Entry Fee",
        "usbc_verified": "USBC Verified",
        **{f"game_{game}": f"Game {game}" for game in range(1, 11)},
    })


def _game_score_available(bowler_row, game_number):
    try:
        frame_data = json.loads(bowler_row.get("score_frames_json") or "{}")
        frames = frame_data.get(str(game_number), [])
        if len(frames) == 10 and any(value is not None for value in frames):
            return all(value is not None for value in frames)
    except (AttributeError, TypeError, json.JSONDecodeError):
        pass
    verified_by = str(bowler_row.get(f"g{game_number}_verified_by", "") or "").strip()
    return bool(verified_by) or int(bowler_row.get(f"Game {game_number}", 0) or 0) > 0


def _render_lane_movement_guide():
    config = st.session_state.tournament_config
    roster = _load_live_roster()
    pairs = parse_active_pairs(config.get("lanes_range", "1-40"), max_lanes=40)
    if roster.empty:
        st.info("Load a roster before building a lane schedule.")
        return
    if not pairs:
        st.error("The configured lane range does not contain a valid pair.")
        return

    st.subheader("Lane movement schedule")
    st.caption("Pair movement wraps through the configured active pairs. Lane sides alternate to balance odd/even starts.")
    move_col, direction_col, balance_col = st.columns(3)
    move_count = move_col.number_input(
        "Pairs moved per game", min_value=1, max_value=max(1, len(pairs) - 1), value=1,
        key="movement_pair_skip",
    )
    direction = direction_col.selectbox("Movement direction", ["Right", "Left"], key="movement_direction")
    balance_sides = balance_col.toggle("Balance odd/even lanes", value=True, key="movement_balance_sides")
    games_count = int(config.get("games_count", 3))
    game_number = st.selectbox("Schedule game", range(1, games_count + 1), key="movement_schedule_game")

    direction_sign = 1 if direction == "Right" else -1
    scheduled = []
    for _, bowler in roster.iterrows():
        start_lane = int(bowler.get("Starting Lane", 1) or 1)
        pair_index = next(
            (index for index, pair in enumerate(pairs) if start_lane in pair),
            (start_lane - 1) // 2 % len(pairs),
        )
        target_index = (pair_index + direction_sign * int(move_count) * (game_number - 1)) % len(pairs)
        target_pair = pairs[target_index]
        scheduled.append({
            "USBC ID": str(bowler.get("USBC ID", "")),
            "Bowler": str(bowler.get("Bowler", "")),
            "Average": int(bowler.get("Average", 200) or 200),
            "Starting Lane": start_lane,
            "Division": str(bowler.get("Division", "Open")),
            "Team_Name": str(bowler.get("Team_Name", "Singles")),
            "Paid": bool(bowler.get("Paid", False)),
            "Checked_In": bool(bowler.get("Checked_In", False)),
            "Pair": f"{target_pair[0]}-{target_pair[1]}",
            "_pair": target_pair,
            "_start_odd": start_lane % 2 == 1,
        })
        for game in range(1, games_count + 1):
            scheduled[-1][f"Game {game}"] = int(bowler.get(f"Game {game}", 0) or 0)

    frame = pd.DataFrame(scheduled)
    lane_assignments = {}
    for pair in pairs:
        pair_rows = frame.index[frame["_pair"] == pair].tolist()
        for index, row_index in enumerate(pair_rows):
            start_odd = bool(frame.at[row_index, "_start_odd"])
            odd_lane = (index % 2 == 0) if balance_sides else start_odd
            if balance_sides and game_number % 2 == 0:
                odd_lane = not odd_lane
            lane_assignments[row_index] = pair[0] if odd_lane else pair[1]
    frame["Lane"] = pd.Series(lane_assignments)
    display = frame[["Lane", "Pair", "Bowler", "USBC ID", "Average"]].sort_values(["Lane", "Bowler"])
    st.dataframe(display, hide_index=True, alt=f"Game {game_number} lane assignments")

    pdf_columns = ["USBC ID", "Bowler", "Average", "Division", "Team_Name", "Paid", "Checked_In"] + [
        f"Game {game}" for game in range(1, games_count + 1)
    ]
    pdf_roster = frame[pdf_columns].copy()
    pdf_roster["Starting Lane"] = frame["Lane"]
    pdf_config = {**config, "name": f"{config.get('name', 'Tournament')} - Game {game_number}"}
    pdf_bytes = export_lane_assignments_pdf(pdf_roster, pdf_config, st.session_state.get("td_name", "Staff"))
    st.download_button(
        "Download printable lane assignments", pdf_bytes,
        file_name=f"lane_assignments_game_{game_number}.pdf", mime="application/pdf",
        icon=":material/picture_as_pdf:",
    )


def _persist_tournament_config(write_active_tournament_state):
    write_active_tournament_state(
        st.session_state.tournament_config,
        st.session_state.roster,
        st.session_state.brackets,
    )


def _smart_awards(standings, pool_amount):
    if standings.empty or pool_amount <= 0:
        return []
    award_count = max(1, math.ceil(len(standings) * 0.25))
    if award_count < 3:
        base_weights = [0.40, 0.25, 0.15][:award_count]
        weight_total = sum(base_weights)
        weights = [weight / weight_total for weight in base_weights]
    else:
        weights = [0.40, 0.25, 0.15]
        weights.extend([0.20 / (award_count - 3)] * (award_count - 3))
    amounts = [round(pool_amount * weight, 2) for weight in weights]
    if amounts:
        amounts[-1] = round(pool_amount - sum(amounts[:-1]), 2)
    return [
        {
            "Place": rank,
            "USBC ID": bowler.get("USBC ID", ""),
            "Bowler": bowler.get("Bowler", ""),
            "Scholarship Amount": amounts[rank - 1],
        }
        for rank, (_, bowler) in enumerate(standings.head(award_count).iterrows(), start=1)
    ]


def _render_stepladder_finals(write_active_tournament_state, log_audit_event, export_tournament_summary_pdf):
    config = st.session_state.tournament_config
    roster = _load_live_roster()
    if roster.empty:
        st.info("Load and score a roster before setting finals seeds.")
        return

    standings = compile_standings(roster, config)
    if len(standings) < 5:
        st.warning(f"Five scored qualifiers are required. Current field: {len(standings)}.")
        return

    with st.container(border=True):
        st.subheader("Five-seed stepladder")
        st.caption("Seed order is snapshotted from current handicap standings. Enter each finals match score to advance its winner.")
        completed = config.get("status") == "Completed"
        if st.button("Set or refresh top-five seeds", key="set_finals_seeds", disabled=completed):
            finals = {"seeds": [str(uid) for uid in standings.head(5)["USBC ID"]], "matches": {}}
            config["finals"] = finals
            config["status"] = "Active"
            _persist_tournament_config(write_active_tournament_state)
            log_audit_event("FINALS_SEEDS_SET", "Seeded five-player stepladder from current standings.")
            st.rerun()

    finals = config.get("finals", {})
    seeds = finals.get("seeds", [])
    if len(seeds) != 5:
        st.info("Set the top-five seeds to begin finals.")
        return

    bowler_by_id = roster.drop_duplicates("USBC ID").set_index("USBC ID")["Bowler"].to_dict()
    st.dataframe(
        pd.DataFrame([
            {"Seed": rank, "Bowler": bowler_by_id.get(uid, "Missing roster entry"), "USBC ID": uid}
            for rank, uid in enumerate(seeds, start=1)
        ]),
        hide_index=True,
        alt="Five seeded qualifiers",
    )

    match_order = ["match1", "match2", "semifinal", "championship"]
    stage_labels = {
        "match1": "Match 1: #5 vs #4",
        "match2": "Match 2: winner vs #3",
        "semifinal": "Semifinal: winner vs #2",
        "championship": "Championship: winner vs #1",
    }
    prior_winners = {}
    participants = {
        "match1": [seeds[3], seeds[4]],
        "match2": [seeds[2], None],
        "semifinal": [seeds[1], None],
        "championship": [seeds[0], None],
    }

    for stage_index, stage in enumerate(match_order):
        if stage_index:
            previous = match_order[stage_index - 1]
            participants[stage][1] = prior_winners.get(previous)
        match = finals.setdefault("matches", {}).get(stage, {})
        winner = match.get("winner") if match.get("complete") else None
        if winner and winner not in participants[stage]:
            winner = None
        prior_winners[stage] = winner
        bowler_ids = participants[stage]
        with st.container(border=True):
            st.markdown(f"**{stage_labels[stage]}**")
            if not all(bowler_ids):
                st.caption("Waiting for the previous match winner.")
                continue
            names = [bowler_by_id.get(uid, "Missing roster entry") for uid in bowler_ids]
            if match.get("complete") and match.get("score_a") == match.get("score_b"):
                st.warning("Match is tied. Enter a tiebreak score before the winner can advance.")
            elif winner:
                st.success(f"Advances: {bowler_by_id.get(winner, winner)}")
            with st.form(f"finals_form_{stage}"):
                score_a = st.number_input(
                    f"{names[0]} score", min_value=0, max_value=300,
                    value=int(match.get("score_a", 0)), key=f"finals_{stage}_score_a", disabled=completed,
                )
                score_b = st.number_input(
                    f"{names[1]} score", min_value=0, max_value=300,
                    value=int(match.get("score_b", 0)), key=f"finals_{stage}_score_b", disabled=completed,
                )
                tie_resolution = None
                if match.get("complete") and match.get("score_a") == match.get("score_b"):
                    tie_resolution = st.selectbox(
                        "TD tiebreak winner",
                        options=bowler_ids,
                        format_func=lambda identifier: bowler_by_id.get(identifier, identifier),
                        key=f"finals_{stage}_tiebreak_winner",
                        disabled=completed,
                    )
                submitted = st.form_submit_button("Save match scores", type="primary", disabled=completed)
            if submitted:
                if score_a == score_b and tie_resolution is None:
                    st.error("Select the TD-recorded tiebreak winner before advancing this tied match.")
                    continue
                updated_matches = finals.setdefault("matches", {})
                for downstream in match_order[stage_index + 1:]:
                    updated_matches.pop(downstream, None)
                updated_matches[stage] = {
                    "bowler_a": bowler_ids[0],
                    "bowler_b": bowler_ids[1],
                    "score_a": int(score_a),
                    "score_b": int(score_b),
                    "winner": bowler_ids[0] if score_a > score_b else bowler_ids[1] if score_b > score_a else tie_resolution,
                    "tiebreak_resolution": tie_resolution if score_a == score_b else None,
                    "complete": True,
                }
                config["finals"] = finals
                config["status"] = "Active"
                _persist_tournament_config(write_active_tournament_state)
                log_audit_event("FINALS_MATCH_SCORED", f"{stage_labels[stage]}: {score_a}-{score_b}.")
                st.rerun()

    champion_id = prior_winners.get("championship")
    if not champion_id:
        return

    champ_name = bowler_by_id.get(champion_id, champion_id)
    matches = finals["matches"]

    def score_label(stage):
        match = matches.get(stage, {})
        return f"{match.get('score_a', 0)} - {match.get('score_b', 0)}"

    report_results = {
        "m1_p1": bowler_by_id.get(seeds[3], seeds[3]),
        "m1_p2": bowler_by_id.get(seeds[4], seeds[4]),
        "m1_winner": bowler_by_id.get(prior_winners.get("match1"), ""),
        "m1_score": score_label("match1"),
        "m2_p1": bowler_by_id.get(seeds[2], seeds[2]),
        "m2_winner_prev": bowler_by_id.get(prior_winners.get("match1"), ""),
        "m2_winner": bowler_by_id.get(prior_winners.get("match2"), ""),
        "m2_score": score_label("match2"),
        "semi_p1": bowler_by_id.get(seeds[1], seeds[1]),
        "semi_winner_prev": bowler_by_id.get(prior_winners.get("match2"), ""),
        "semi_winner": bowler_by_id.get(prior_winners.get("semifinal"), ""),
        "semi_score": score_label("semifinal"),
        "champ_p1": bowler_by_id.get(seeds[0], seeds[0]),
        "champ_winner_prev": bowler_by_id.get(prior_winners.get("semifinal"), ""),
        "champ_score": score_label("championship"),
    }
    st.success(f"Tournament champion: {champ_name}")
    report = export_tournament_summary_pdf(standings, config, champ_name, report_results)
    st.download_button(
        "Download tournament completion report", report,
        file_name="Tournament_Completion_Report.pdf", mime="application/pdf",
        icon=":material/picture_as_pdf:",
    )
    if not completed and st.button("Mark tournament complete and lock results", type="primary"):
        config["status"] = "Completed"
        config["champion"] = champ_name
        config["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _persist_tournament_config(write_active_tournament_state)
        log_audit_event("TOURNAMENT_COMPLETED", f"Champion: {champ_name}.")
        st.rerun()
    elif completed:
        st.info(f"Results are locked. Official champion: {config.get('champion', champ_name)}.")
        if st.button("Reopen scoring (TD override)", key="reopen_tournament_scoring"):
            config["status"] = "Active"
            config.pop("champion", None)
            config.pop("completed_at", None)
            _persist_tournament_config(write_active_tournament_state)
            log_audit_event("TOURNAMENT_REOPENED", "Tournament scoring reopened by TD override.")
            st.rerun()


def _render_side_pots_and_brackets(write_active_tournament_state, log_audit_event):
    config = st.session_state.tournament_config
    roster = _load_live_roster()
    if roster.empty:
        st.info("Load a roster before creating brackets or side pots.")
        return
    roster["USBC ID"] = roster["USBC ID"].astype(str)
    roster["Paid"] = roster["Paid"].astype(bool)
    adult_bowlers = ~roster["Division"].astype(str).str.contains("youth|scholastic", case=False, na=False)
    eligible = roster[roster["Paid"] & adult_bowlers]
    youth_count = int((~adult_bowlers).sum())
    if youth_count:
        st.info(f"{youth_count} youth bowlers are excluded from cash brackets and cash pots under Rule 400.")
    if eligible.empty:
        st.warning("No paid adult bowlers are available for cash side action.")
        return

    bowler_names = eligible.set_index("USBC ID")["Bowler"].to_dict()
    game_count = int(config.get("games_count", 3))
    game_columns = [f"Game {game}" for game in range(1, game_count + 1)]

    st.subheader("Eight-person elimination brackets")
    bracket_fee = st.number_input(
        "Bracket entry fee per bowler", min_value=0.0, step=1.0,
        value=float(config.get("bracket_entry_fee", 5.0)), key="bracket_entry_fee_input",
    )
    bracket_mode_col, count_col = st.columns(2)
    bracket_type = bracket_mode_col.selectbox("Bracket scoring", ["Scratch", "Handicap"], key="bracket_scoring_type")
    bracket_count = count_col.number_input("Brackets to generate", min_value=1, max_value=20, value=1, step=1)
    seed_method = st.segmented_control(
        "Seeding", ["Manual selection", "Blind random draw"], default="Manual selection", key="bracket_seed_method",
    )
    selected_seeds = []
    if seed_method == "Manual selection":
        selected_seeds = st.multiselect(
            "Choose eight paid bowlers",
            options=eligible["USBC ID"].tolist(),
            format_func=lambda uid: f"{bowler_names.get(uid, uid)} ({uid})",
            max_selections=8,
            key="bracket_seed_selection",
        )
    generate_cols = st.columns(2)
    if generate_cols[0].button("Generate bracket(s)", type="primary", key="generate_brackets"):
        if len(eligible) < 8:
            st.error("An eight-person bracket requires at least eight paid adult bowlers.")
        elif seed_method == "Manual selection" and len(selected_seeds) != 8:
            st.error("Select exactly eight bowlers for the first manual bracket.")
        else:
            eligible_ids = eligible["USBC ID"].tolist()
            config["bracket_entry_fee"] = float(bracket_fee)
            for bracket_index in range(int(bracket_count)):
                seeds = list(selected_seeds) if bracket_index == 0 and seed_method == "Manual selection" else random.sample(eligible_ids, 8)
                next_id = len(st.session_state.brackets) + 1
                st.session_state.brackets.append({
                    "id": f"B-{next_id:02d}",
                    "type": bracket_type,
                    "fee": float(bracket_fee),
                    "seeds": seeds,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
            _persist_tournament_config(write_active_tournament_state)
            log_audit_event("BRACKETS_CREATED", f"Created {int(bracket_count)} {bracket_type.lower()} bracket(s).")
            st.rerun()
    if generate_cols[1].button("Reset all brackets", key="reset_all_brackets"):
        st.session_state.brackets = []
        _persist_tournament_config(write_active_tournament_state)
        log_audit_event("BRACKETS_RESET", "Cleared all active brackets.")
        st.rerun()

    if st.session_state.brackets:
        for bracket in st.session_state.brackets:
            with st.container(border=True):
                st.markdown(f"**Bracket {bracket['id']} · {bracket['type']}**")
                seeds = [str(uid) for uid in bracket.get("seeds", [])]
                prize_pool = float(bracket.get("fee", 5.0)) * len(seeds)
                payout_first = round(prize_pool * 0.625, 2)
                payout_second = round(prize_pool * 0.25, 2)
                payout_reserved = round(prize_pool - payout_first - payout_second, 2)
                st.caption(
                    f"Pool ${prize_pool:,.2f} · 1st ${payout_first:,.2f} · "
                    f"2nd ${payout_second:,.2f} · reserved ${payout_reserved:,.2f}"
                )

                def match_result(first_id, second_id, game_number):
                    rows = roster.set_index("USBC ID")
                    if first_id not in rows.index or second_id not in rows.index:
                        return None, "Roster entry missing"
                    first = rows.loc[first_id]
                    second = rows.loc[second_id]
                    first_score = int(first.get(f"Game {game_number}", 0) or 0)
                    second_score = int(second.get(f"Game {game_number}", 0) or 0)
                    if not _game_score_available(first, game_number) or not _game_score_available(second, game_number):
                        return None, f"{first_score} - {second_score} · awaiting complete game scores"
                    if bracket["type"] == "Handicap":
                        first_score += calculate_handicap(
                            int(first.get("Average", 200)),
                            int(config.get("hdcp_base", 220)),
                            float(config.get("hdcp_pct", 0.90)),
                        )
                        second_score += calculate_handicap(
                            int(second.get("Average", 200)),
                            int(config.get("hdcp_base", 220)),
                            float(config.get("hdcp_pct", 0.90)),
                        )
                    if first_score == second_score:
                        return None, f"{first_score} - {second_score} · tie requires TD tiebreak"
                    winner = first_id if first_score > second_score else second_id
                    return winner, f"{first_score} - {second_score} · advances {bowler_names.get(winner, winner)}"

                if len(seeds) == 8:
                    round_one = [
                        match_result(seeds[first], seeds[second], 1)
                        for first, second in ((0, 7), (1, 6), (2, 5), (3, 4))
                    ]
                    round_two = [
                        match_result(round_one[0][0], round_one[1][0], 2)
                        if round_one[0][0] and round_one[1][0] else (None, "Awaiting round-one winners"),
                        match_result(round_one[2][0], round_one[3][0], 2)
                        if round_one[2][0] and round_one[3][0] else (None, "Awaiting round-one winners"),
                    ]
                    final = (
                        match_result(round_two[0][0], round_two[1][0], 3)
                        if round_two[0][0] and round_two[1][0]
                        else (None, "Awaiting semifinal winners")
                    )
                    round_one_pairs = ((0, 7), (1, 6), (2, 5), (3, 4))
                    round_columns = st.columns([2, 1, 1])
                    with round_columns[0]:
                        st.markdown("#### Round 1")
                        for (first_index, second_index), result in zip(round_one_pairs, round_one):
                            with st.container(border=True):
                                st.markdown(f"**{bowler_names.get(seeds[first_index], seeds[first_index])}**")
                                st.caption("vs")
                                st.markdown(f"**{bowler_names.get(seeds[second_index], seeds[second_index])}**")
                                st.caption(result[1])
                    with round_columns[1]:
                        st.markdown("#### Semifinals")
                        for result in round_two:
                            with st.container(border=True):
                                st.markdown("**Advancing bowlers**")
                                st.caption(result[1])
                    with round_columns[2]:
                        st.markdown("#### Championship")
                        with st.container(border=True):
                            st.markdown("**Final match**")
                            st.caption(final[1])
                    if final[0]:
                        st.success(f"Bracket winner: {bowler_names.get(final[0], final[0])}")
                        runner_up_id = round_two[1][0] if final[0] == round_two[0][0] else round_two[0][0]
                        st.caption(
                            f"1st: ${payout_first:,.2f} · {bowler_names.get(final[0], final[0])} | "
                            f"2nd: ${payout_second:,.2f} · {bowler_names.get(runner_up_id, runner_up_id)} | "
                            f"Reserved: ${payout_reserved:,.2f}"
                        )

    st.divider()
    st.subheader("Per-game high-score pots")
    game_number = st.selectbox("Pot game", range(1, game_count + 1), key="sidepot_game_select")
    side_pots = config.setdefault("side_pots", {})
    game_key = str(game_number)
    saved_pot = side_pots.get(game_key, {})
    with st.form(f"sidepot_form_{game_number}"):
        fee = st.number_input(
            "Entry fee per bowler", min_value=0.0, step=1.0,
            value=float(saved_pot.get("fee", 10.0)), key=f"sidepot_fee_{game_number}",
        )
        entrants = st.multiselect(
            "Registered bowlers", options=eligible["USBC ID"].tolist(),
            default=[uid for uid in saved_pot.get("entrants", []) if uid in bowler_names],
            format_func=lambda uid: bowler_names.get(uid, uid),
            key=f"sidepot_entrants_{game_number}",
        )
        save_pot = st.form_submit_button("Save pot ledger")
    if save_pot:
        side_pots[game_key] = {"fee": float(fee), "entrants": list(entrants)}
        _persist_tournament_config(write_active_tournament_state)
        log_audit_event("SIDE_POT_SAVED", f"Saved Game {game_number} pot with {len(entrants)} entrants.")
        st.rerun()
    saved_entrants = [uid for uid in saved_pot.get("entrants", []) if uid in bowler_names]
    pot_total = float(saved_pot.get("fee", 0)) * len(saved_entrants)
    scores = {
        uid: int(eligible.loc[eligible["USBC ID"] == uid, f"Game {game_number}"].iloc[0] or 0)
        for uid in saved_entrants
    }
    score_rows = eligible.set_index("USBC ID")
    scored = {
        uid: score for uid, score in scores.items()
        if _game_score_available(score_rows.loc[uid], game_number)
    }
    st.metric("Game pot", f"${pot_total:,.2f}", f"{len(saved_entrants)} registered")
    if scored:
        high_score = max(scored.values())
        winners = [uid for uid, score in scored.items() if score == high_score]
        st.write(f"High game: {high_score} · {', '.join(bowler_names.get(uid, uid) for uid in winners)}")
        st.caption(f"Current tied share: ${pot_total / len(winners):,.2f} each. Unscored entrants remain in the ledger.")
    ledger = eligible[["USBC ID", "Bowler", f"Game {game_number}"]].copy()
    ledger["Registered"] = ledger["USBC ID"].isin(saved_entrants)
    st.dataframe(ledger[ledger["Registered"]], hide_index=True, alt=f"Game {game_number} side-pot ledger")

    st.subheader("Shared high-game and series payout pool")
    shared_pool = config.setdefault("high_game_series_pot", {})
    with st.form("high_game_series_pot_form"):
        shared_fee = st.number_input(
            "Side-pot buy-in per bowler", min_value=0.0, step=1.0,
            value=float(shared_pool.get("fee", 10.0)), key="shared_pot_fee",
        )
        shared_entrants = st.multiselect(
            "Shared-pool entrants", options=eligible["USBC ID"].tolist(),
            default=[uid for uid in shared_pool.get("entrants", []) if uid in bowler_names],
            format_func=lambda uid: bowler_names.get(uid, uid), key="shared_pot_entrants",
        )
        scoring_mode = st.selectbox("Payout standings", ["Scratch", "Handicap"], key="shared_pot_mode")
        save_shared_pool = st.form_submit_button("Save shared pot")
    if save_shared_pool:
        config["high_game_series_pot"] = {
            "fee": float(shared_fee),
            "entrants": list(shared_entrants),
            "scoring_mode": scoring_mode,
        }
        _persist_tournament_config(write_active_tournament_state)
        log_audit_event("HIGH_GAME_SERIES_POT_SAVED", f"Saved shared pot for {len(shared_entrants)} bowlers.")
        st.rerun()

    shared_pool = config.get("high_game_series_pot", {})
    shared_ids = [uid for uid in shared_pool.get("entrants", []) if uid in bowler_names]
    shared_total = float(shared_pool.get("fee", 0)) * len(shared_ids)
    game_share = round(shared_total * 0.90 / max(1, game_count), 2)
    series_share = round(shared_total - game_share * game_count, 2)
    split = st.columns(min(game_count + 1, 4))
    for game in range(1, game_count + 1):
        split[(game - 1) % len(split)].metric(f"Game {game} pool", f"${game_share:,.2f}")
    split[-1].metric("Series pool", f"${series_share:,.2f}")

    shared_scores = eligible[eligible["USBC ID"].isin(shared_ids)].copy()
    payout_rows = []
    if not shared_scores.empty:
        mode = str(shared_pool.get("scoring_mode", "Scratch"))
        all_games_complete = True
        for game in range(1, game_count + 1):
            complete_ids = [
                uid for uid in shared_ids
                if _game_score_available(score_rows.loc[uid], game)
            ]
            if not complete_ids:
                all_games_complete = False
                continue
            game_results = []
            for uid in complete_ids:
                bowler_row = score_rows.loc[uid]
                score = int(bowler_row.get(f"Game {game}", 0) or 0)
                if mode == "Handicap":
                    score += calculate_handicap(
                        int(bowler_row.get("Average", 200)),
                        int(config.get("hdcp_base", 220)),
                        float(config.get("hdcp_pct", 0.90)),
                        str(config.get("handicap_method", "percentage")),
                        int(config.get("fixed_handicap", 0)),
                    )
                game_results.append((uid, score))
            high = max(score for _, score in game_results)
            winners = [uid for uid, score in game_results if score == high]
            payout_rows.append({
                "Award": f"Game {game}",
                "Score": high,
                "Winner(s)": ", ".join(bowler_names.get(uid, uid) for uid in winners),
                "Share each": round(game_share / len(winners), 2),
            })

        if all(_game_score_available(score_rows.loc[uid], game) for uid in shared_ids for game in range(1, game_count + 1)):
            series_results = []
            for uid in shared_ids:
                bowler_row = score_rows.loc[uid]
                total = sum(int(bowler_row.get(f"Game {game}", 0) or 0) for game in range(1, game_count + 1))
                if mode == "Handicap":
                    total += calculate_handicap(
                        int(bowler_row.get("Average", 200)),
                        int(config.get("hdcp_base", 220)),
                        float(config.get("hdcp_pct", 0.90)),
                        str(config.get("handicap_method", "percentage")),
                        int(config.get("fixed_handicap", 0)),
                    ) * game_count
                series_results.append((uid, total))
            high_series = max(score for _, score in series_results)
            series_winners = [uid for uid, score in series_results if score == high_series]
            payout_rows.append({
                "Award": "Series",
                "Score": high_series,
                "Winner(s)": ", ".join(bowler_names.get(uid, uid) for uid in series_winners),
                "Share each": round(series_share / len(series_winners), 2),
            })
        else:
            all_games_complete = False
    if payout_rows:
        st.dataframe(pd.DataFrame(payout_rows), hide_index=True, alt="High-game and series pot payout ledger")
    if shared_ids and not all_games_complete:
        st.caption("Unscored games remain pending; series payout leaders appear after all entrants have complete scores.")

    st.divider()
    st.subheader("Survivor pot")
    survivor = config.setdefault("survivor_pot", {})
    with st.form("survivor_pot_form"):
        survivor_fee = st.number_input(
            "Survivor entry fee", min_value=0.0, step=1.0,
            value=float(survivor.get("fee", 10.0)), key="survivor_fee",
        )
        survivor_entrants = st.multiselect(
            "Survivor entrants", options=eligible["USBC ID"].tolist(),
            default=[uid for uid in survivor.get("entrants", []) if uid in bowler_names],
            format_func=lambda uid: bowler_names.get(uid, uid), key="survivor_entrants",
        )
        save_survivors = st.form_submit_button("Save survivor entrants")
    if save_survivors:
        config["survivor_pot"] = {"fee": float(survivor_fee), "entrants": list(survivor_entrants)}
        _persist_tournament_config(write_active_tournament_state)
        log_audit_event("SURVIVOR_POT_SAVED", f"Saved survivor pot with {len(survivor_entrants)} entrants.")
        st.rerun()
    active = [uid for uid in survivor.get("entrants", []) if uid in bowler_names]
    eliminated = []
    unresolved_game = None
    for game in range(1, game_count + 1):
        game_scores = {
            uid: int(eligible.loc[eligible["USBC ID"] == uid, f"Game {game}"].iloc[0] or 0)
            for uid in active
        }
        if len(active) <= 1 or not active or any(
            not _game_score_available(score_rows.loc[uid], game)
            for uid in active
        ):
            break
        lowest = min(game_scores.values())
        lowest_bowlers = [uid for uid, score in game_scores.items() if score == lowest]
        if len(lowest_bowlers) != 1:
            unresolved_game = game
            break
        eliminated.append((game, lowest_bowlers[0], lowest))
        active.remove(lowest_bowlers[0])
    survivor_pool = float(survivor.get("fee", 0)) * len(survivor.get("entrants", []))
    st.metric("Survivor pool", f"${survivor_pool:,.2f}", f"{len(survivor.get('entrants', []))} entries")
    if unresolved_game:
        st.warning(f"Game {unresolved_game} has a tie for the lowest score; TD resolution is required before elimination.")
    elif len(active) == 1:
        st.success(f"Survivor: {bowler_names.get(active[0], active[0])}")
    else:
        st.info(f"{len(active)} bowlers remain active; later game scores are still pending.")
    if eliminated:
        st.dataframe(pd.DataFrame([
            {"Game": game, "Eliminated bowler": bowler_names.get(uid, uid), "Score": score}
            for game, uid, score in eliminated
        ]), hide_index=True, alt="Survivor pot elimination history")


def _render_smart_escrow(write_active_tournament_state, log_audit_event):
    config = st.session_state.tournament_config
    roster = _load_live_roster()
    youth = roster[roster["Division"].astype(str).str.contains("youth|scholastic", case=False, na=False)].copy()
    is_youth_event = not youth.empty
    st.subheader("Financial reconciliation and prize ledger")
    if is_youth_event:
        st.warning("Rule 400 applies: youth awards must comply with USBC youth eligibility rules and scholarship funds must be handled through SMART.")
        st.link_button("Open USBC SMART provider resources", "https://bowl.com/youth/smart/providers", icon=":material/open_in_new:")

    with st.form("financial_assumptions_form"):
        input_cols = st.columns(3)
        entry_fee = input_cols[0].number_input("Entry fee per bowler", min_value=0.0, step=5.0, value=float(config.get("entry_fee", 50.0)))
        lineage_per_game = input_cols[1].number_input("Lineage per game", min_value=0.0, step=0.25, value=float(config.get("lineage_per_game", 3.75)))
        expense_per_bowler = input_cols[2].number_input("Expenses per paid bowler", min_value=0.0, step=1.0, value=float(config.get("expenses_per_bowler", 5.0)))
        save_financials = st.form_submit_button("Save financial assumptions")
    if save_financials:
        config.update({
            "entry_fee": float(entry_fee),
            "lineage_per_game": float(lineage_per_game),
            "expenses_per_bowler": float(expense_per_bowler),
        })
        _persist_tournament_config(write_active_tournament_state)
        log_audit_event("FINANCIAL_ASSUMPTIONS_UPDATED", "Updated entry fee, lineage, or expense assumptions.")
        st.rerun()

    financials = calculate_financial_summary(roster, config)
    metric_cols = st.columns(4)
    metric_cols[0].metric("Paid entries", financials["paid_count"])
    metric_cols[1].metric("Gross revenue", f"${financials['gross_revenue']:,.2f}")
    metric_cols[2].metric("Lineage owed", f"${financials['total_lineage']:,.2f}")
    metric_cols[3].metric("Net scholarship pool" if is_youth_event else "Net prize pool", f"${financials['net_prize_fund']:,.2f}")

    ratios = [0.40, 0.25, 0.15, 0.10, 0.05, 0.05]
    places = ["1st place", "2nd place", "3rd place", "4th place", "5th place", "6th place"]
    payout_rows = []
    for index, ratio in enumerate(ratios):
        if index * 4 > financials["paid_count"] and index >= 3:
            break
        amount = round(financials["net_prize_fund"] * ratio, 2)
        payout_rows.append({"Award": places[index], "Allocation": f"{ratio:.0%}", "Amount": amount})
    if payout_rows:
        st.dataframe(pd.DataFrame(payout_rows), hide_index=True, alt="Prize fund allocation by place")

    if not is_youth_event:
        if financials["net_prize_fund"] <= 0:
            st.info("No net prize pool is available yet; record paid entries and verify event assumptions.")
        return

    st.subheader("Youth scholarship escrow and recipient list")
    youth_financials = calculate_financial_summary(youth, config)
    calculated_pool = youth_financials["net_prize_fund"]
    saved = config.setdefault("smart_escrow", {})
    current_pool = float(saved.get("award_pool", calculated_pool))
    current_deposit = float(saved.get("deposited", 0))

    with st.form("smart_escrow_form"):
        award_pool = st.number_input(
            "Scholarship award pool", min_value=0.0, step=10.0,
            value=current_pool, help="Initial estimate uses paid/comp youth entry fees less configured lineage and expenses; adjust to the published prize rules.",
        )
        deposited = st.number_input(
            "Amount deposited with SMART", min_value=0.0, step=10.0,
            value=current_deposit,
        )
        save_escrow = st.form_submit_button("Save escrow and award breakdown")
    if save_escrow:
        if deposited > award_pool:
            st.error("The deposited amount cannot exceed the scholarship award pool.")
        else:
            config["smart_escrow"] = {
                "award_pool": float(award_pool),
                "deposited": float(deposited),
            }
            _persist_tournament_config(write_active_tournament_state)
            log_audit_event("SMART_ESCROW_UPDATED", f"Award pool ${award_pool:.2f}; deposited ${deposited:.2f}.")
            st.rerun()

    saved = config.get("smart_escrow", {})
    award_pool = float(saved.get("award_pool", calculated_pool))
    deposited = float(saved.get("deposited", 0))
    st.metric("Escrow remaining", f"${max(0.0, award_pool - deposited):,.2f}", f"${deposited:,.2f} deposited of ${award_pool:,.2f}")

    games_count = int(config.get("games_count", 3))
    scored_youth = youth[youth.apply(
        lambda bowler: any(
            _game_score_available(bowler, game)
            for game in range(1, games_count + 1)
        ),
        axis=1,
    )]
    standings = compile_standings(scored_youth, config)
    awards = _smart_awards(standings, award_pool)
    award_frame = pd.DataFrame(awards)
    if award_frame.empty:
        st.info("Awards will be calculated after youth scores are entered.")
        return
    st.dataframe(award_frame, hide_index=True, alt="Proposed youth scholarship awards")

    smart_csv = generate_smart_scholarship_csv(standings, award_pool, config.get("name", "Tournament"))
    st.warning("USBC’s public bulk-upload guide does not publish the recipient CSV headers; verify this draft against the portal’s upload help before submission.")
    st.download_button(
        "Download scholarship recipient CSV", smart_csv,
        file_name="SMART_Scholarship_Recipients.csv", mime="text/csv",
        icon=":material/download:",
    )

def render_external_broadcast_cards(context_key: str):
    """Renders the standard placeholder cards for chusbc.org sync and Facebook posting."""
    st.divider()
    st.markdown("### 📡 External Broadcast & Social Publishing")

    col_web, col_fb = st.columns(2)

    with col_web:
        st.markdown("""
        <div class='match-box' style='border-left-color: #38bdf8;'>
            <div style='display: flex; justify-content: space-between; align-items: center;'>
                <strong style='font-size: 15px; color: #f8fafc;'>🌐 chusbc.org Website Sync</strong>
                <span style='background: #0284c725; color: #7dd3fc; border: 1px solid #0284c780; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 800;'>UNDER CONSTRUCTION</span>
            </div>
            <p style='color: #94a3b8; font-size: 12px; margin-top: 6px; line-height: 1.4;'>
                Direct sync of verified standings and cut-lines to the Cecil-Harford USBC website.
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.button("🌐 Sync to chusbc.org (Under Construction)", disabled=True, width="stretch", key=f"btn_sync_web_{context_key}")

    with col_fb:
        st.markdown("""
        <div class='match-box' style='border-left-color: #1877f2;'>
            <div style='display: flex; justify-content: space-between; align-items: center;'>
                <strong style='font-size: 15px; color: #f8fafc;'>📘 Facebook Page Broadcast</strong>
                <span style='background: #1877f225; color: #60a5fa; border: 1px solid #1877f280; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 800;'>UNDER CONSTRUCTION</span>
            </div>
            <p style='color: #94a3b8; font-size: 12px; margin-top: 6px; line-height: 1.4;'>
                Automated post publishing tournament winners, top scores, and leaderboards to the official CHUSBC Page.
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.button("📘 Post to Facebook Page (Under Construction)", disabled=True, width="stretch", key=f"btn_post_fb_{context_key}")


def render_advanced_view(
    nav: str,
    desk_mode: str,
    CHUSBC_PRESET_PROFILES: dict,
    write_active_tournament_state,
    log_audit_event,
    render_live_checkin_counters_fragment,
    render_live_radar_matrix_fragment,
    compile_all_events_leaderboard,
    export_tournament_summary_pdf,
    fetch_archives_df,
    write_archives_df,
    fetch_users_df,
    write_users_df,
    ai_client
):
    num_games = int(st.session_state.tournament_config.get("games_count", 3))

    if nav == "12. Operations Dashboard":
        st.markdown(
            '<div class="brand-banner"><h1>Tournament Operations</h1>'
            '<p>Live scoring, championship progression, side action, and financial control</p></div>',
            unsafe_allow_html=True,
        )
        scoring_tab, finals_tab, brackets_tab, finance_tab = st.tabs([
            "Live Floor", "Stepladder Finals", "Brackets & Pots", "Finance & SMART",
        ])
        with scoring_tab:
            render_live_checkin_counters_fragment()
            render_live_radar_matrix_fragment()
            render_live_scoring_floor_grid(st.session_state.tournament_config, ai_client=ai_client)
        with finals_tab:
            _render_stepladder_finals(
                write_active_tournament_state,
                log_audit_event,
                export_tournament_summary_pdf,
            )
        with brackets_tab:
            _render_side_pots_and_brackets(write_active_tournament_state, log_audit_event)
        with finance_tab:
            _render_smart_escrow(write_active_tournament_state, log_audit_event)
        return

    if nav == "4. Stepladder Finals":
        _render_stepladder_finals(
            write_active_tournament_state,
            log_audit_event,
            export_tournament_summary_pdf,
        )
        return
    if nav == "3. Scores & Standings":
        render_live_scoring_floor_grid(st.session_state.tournament_config, ai_client=ai_client)
        return
    if nav == "5. Side Action: Brackets & Pots 💰":
        _render_side_pots_and_brackets(write_active_tournament_state, log_audit_event)
        return
    if nav == "6. Financial & SMART Ledger 💵":
        _render_smart_escrow(write_active_tournament_state, log_audit_event)
        return

    # MODULE 1: COMPREHENSIVE INTAKE
    if nav == "1. Event & Roster Intake":
        intake_tab_settings, intake_tab_entry, intake_tab_terminal, intake_tab_pins = st.tabs([
            "⚙️ Event Settings & CHUSBC Presets",
            "📝 Roster Ingestion & 40-Lane Balancing",
            "💳 Desk Intake & Entrance QR Posters",
            "🔐 Floor TD PIN Registry (Argon2)"
        ])

        with intake_tab_settings:
            st.subheader("Tournament Calibration & Presets")
            preset_choice = st.selectbox("Load Official CHUSBC Profile:", ["-- Select to Apply Preset --"] + list(CHUSBC_PRESET_PROFILES.keys()))
            if preset_choice != "-- Select to Apply Preset --" and st.button(f"Apply '{preset_choice}' Parameters", type="primary"):
                st.session_state.tournament_config.update(CHUSBC_PRESET_PROFILES[preset_choice])
                st.session_state.tournament_config["name"] = preset_choice
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                st.success(f"Applied {preset_choice} presets!")
                st.rerun()

            st.divider()
            c_name, c_center = st.columns([2, 1])
            with c_name:
                t_name_val = st.text_input("Tournament Name:", value=st.session_state.tournament_config["name"])
            with c_center:
                center_options = ["Forest Hill Bowling Center", "Harford Lanes", "APG Bowling Center", "Elk Lanes"]
                cur_center = st.session_state.tournament_config.get("center", "Forest Hill Bowling Center")
                center_val = st.selectbox("Host Bowling Center:", center_options, index=center_options.index(cur_center) if cur_center in center_options else 0)

            col_lanes1, col_lanes2, col_games, col_div = st.columns(4)
            with col_lanes1:
                lane_count_val = st.number_input("Total Lanes in Center:", 2, 60, int(st.session_state.tournament_config.get("lanes_count", 40)), 2)
            with col_lanes2:
                lane_range_val = st.text_input("Active Pair Range (e.g. 1-40):", value=st.session_state.tournament_config.get("lanes_range", "1-40"))
            with col_games:
                games_count_val = st.number_input("Number of Games (Qualifying Block):", min_value=1, max_value=6, value=int(st.session_state.tournament_config.get("games_count", 3)), step=1)
            with col_div:
                division_val = st.text_input("Division / Category:", value=st.session_state.tournament_config.get("division", "Adult Open"))

            col_h1, col_h2, col_h3 = st.columns(3)
            with col_h1:
                h_base_val = st.number_input("Handicap Base Average:", value=int(st.session_state.tournament_config.get("hdcp_base", 220)), step=5)
            with col_h2:
                h_pct_val = st.number_input("Handicap Percentage (0.90 = 90%):", value=float(st.session_state.tournament_config.get("hdcp_pct", 0.90)), step=0.05, format="%.2f")
            with col_h3:
                rule_options = [
                    "Stay on Pair (No Movement)",
                    "Move Right 1 Pair (+2 Lanes)",
                    "Move Right 2 Pairs (+4 Lanes)",
                    "Move Right 3 Pairs (+6 Lanes)",
                    "Move Left 1 Pair (-2 Lanes)",
                    "Move Left 2 Pairs (-4 Lanes)",
                    "Move Left 3 Pairs (-6 Lanes)",
                ]
                cur_rule = st.session_state.tournament_config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")
                rule_val = st.selectbox("Lane Rotation Rule:", rule_options, index=rule_options.index(cur_rule) if cur_rule in rule_options else 1)

            t_rules_val = st.text_area("Tournament Rules & Format Flyer:", value=st.session_state.tournament_config.get("rules_text", ""))
            uploaded_doc = st.file_uploader("Upload Tournament Flyer / Rules PDF (.pdf or .txt):", type=["pdf", "txt"])

            if st.button("🔒 Save & Lock Tournament Configuration", type="primary", width="stretch"):
                uploaded_content = ""
                if uploaded_doc is not None:
                    if uploaded_doc.name.lower().endswith(".pdf"):
                        try:
                            reader = PdfReader(uploaded_doc)
                            uploaded_content = "\n[PDF RULES]:\n" + "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
                        except Exception as e:
                            st.error(f"Error reading PDF: {e}")
                    else:
                        uploaded_content = f"\n[RULES FILE]:\n{uploaded_doc.read().decode('utf-8', errors='ignore')}"

                st.session_state.tournament_config.update({
                    "center": center_val, "name": t_name_val, "lanes_count": lane_count_val,
                    "lanes_range": lane_range_val, "games_count": games_count_val, "division": division_val,
                    "hdcp_base": h_base_val, "hdcp_pct": h_pct_val, "movement_rule": rule_val,
                    "rules_text": t_rules_val + uploaded_content, "intake_completed": True
                })
                write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                log_audit_event(f"Configuration locked: {t_name_val} at {center_val} ({games_count_val} Games).")
                st.success("Tournament settings locked & backed up.")
                st.rerun()

        with intake_tab_entry:
            st.subheader("Bowler Roster & Team-Aware Lane Balancer")
            tab_ai, tab_csv, tab_grid, tab_bal = st.tabs(["🤖 Parse Signup Notes", "📁 Upload CSV", "📋 Master Grid", "🎳 Lane Balancer"])

            with tab_ai:
                raw_text = st.text_area("Paste bowler signups (USBC ID, Name, Avg, Team):", placeholder="11-12345 Scott Kramer 218 Striking Power\n11-23456 Dave Miller 205 Striking Power")
                if st.button("Extract Roster with Gemini", type="primary") and raw_text.strip():
                    cleaned_csv = parse_roster_text_with_gemini(raw_text, client=ai_client)
                    if cleaned_csv:
                        new_df = pd.read_csv(io.StringIO(cleaned_csv))
                        new_df["Paid"] = True
                        new_df["Checked_In"] = True
                        st.session_state.roster = new_df
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success(f"Parsed {len(new_df)} bowlers!")
                        st.rerun()
                    else:
                        st.error("Failed to parse roster. Check Gemini API key and try again.")

            with tab_csv:
                csv_file = st.file_uploader("Upload Roster CSV:", type=["csv"])
                if csv_file and st.button("Import CSV"):
                    df_up = pd.read_csv(csv_file)
                    st.session_state.roster = df_up
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success("CSV Imported successfully.")

            with tab_grid:
                edited = st.data_editor(st.session_state.roster, num_rows="dynamic", width="stretch")
                if st.button("Save Grid Changes"):
                    st.session_state.roster = edited
                    write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                    st.success("Grid updated!")

            with tab_bal:
                st.markdown("### 🎳 Automated Team-Aware Lane Balancer")
                cb1, cb2, cb3, cb4 = st.columns([2, 1, 1, 1])
                with cb1:
                    custom_range = st.text_input("Active Range:", value=st.session_state.tournament_config.get("lanes_range", "1-40"))
                with cb2:
                    max_cap = st.selectbox("Max Bowlers per Pair:", [4, 5, 6, 8, 10], index=1)
                with cb3:
                    grp_teams = st.checkbox("👥 Keep Teammates Together", value=True)
                with cb4:
                    shuf = st.checkbox("🎲 Blind Random Draw", value=True)

                parsed_pairs = parse_active_pairs(custom_range, max_lanes=40)
                if st.button("⚡ Balance & Assign Lanes Automatically", type="primary", width="stretch"):
                    b_roster, err = auto_assign_lanes(st.session_state.roster, parsed_pairs, max_per_pair=max_cap, shuffle=shuf, group_by_team=grp_teams)
                    if err:
                        st.error(err)
                    else:
                        st.session_state.roster = b_roster
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success("Lanes balanced!")
                        st.rerun()

                if not st.session_state.roster.empty:
                    st.download_button("📄 Download Printable PDF Lane Assignments", export_lane_assignments_pdf(st.session_state.roster, st.session_state.tournament_config, st.session_state.td_name), "Lane_Assignments.pdf", "application/pdf", width="stretch")

        with intake_tab_terminal:
            st.subheader("Payment Gate, Entrance QR & Check-In Terminal")
            detected_base = st.secrets.get("APP_URL", "https://chusbc-desk.streamlit.app").rstrip("/")
            kiosk_url = f"{detected_base}/?mode=kiosk"
            self_checkin_url = f"{detected_base}/?mode=self_checkin"
            bowler_portal_url = f"{detected_base}/?mode=bowler_portal"

            col_q1, col_q2, col_q3 = st.columns(3)
            with col_q1:
                st.markdown("##### 🚪 Entrance Self-Check-In QR")
                st.image(generate_qr_image(self_checkin_url), width=130)
                st.link_button("🔗 Open Entrance Check-In", self_checkin_url, width="stretch")
            with col_q2:
                st.markdown("##### 📊 Bowler Live Portal QR")
                st.image(generate_qr_image(bowler_portal_url), width=130)
                st.link_button("🔗 Open Bowler Portal", bowler_portal_url, width="stretch")
            with col_q3:
                st.markdown("##### 🖥️ Desk Customer Monitor")
                st.link_button("🖥️ Launch Customer Screen", kiosk_url, width="stretch")
                if st.button("🔄 Reset Customer Screen", width="stretch"):
                    clear_kiosk_card()
                    st.rerun()

            st.divider()
            render_live_checkin_counters_fragment()

            st.write("")
            b_list = st.session_state.roster["Bowler"].tolist() if not st.session_state.roster.empty else []
            s_bowler = st.selectbox("Search / Select Bowler at Desk:", ["-- Select Bowler Arriving at Desk --"] + b_list)

            if s_bowler != "-- Select Bowler Arriving at Desk --":
                b_row = st.session_state.roster[st.session_state.roster["Bowler"] == s_bowler].iloc[0]
                b_paid, b_checked = bool(b_row["Paid"]), bool(b_row["Checked_In"])
                b_lane = int(b_row["Starting Lane"])
                pair_partner = b_lane + 1 if b_lane % 2 != 0 else b_lane - 1
                pair_display_str = f"Lanes {min(b_lane, pair_partner)} & {max(b_lane, pair_partner)}"

                col_inf, col_act = st.columns(2)
                with col_inf:
                    st.markdown(f"<div class='match-box'><h3>{s_bowler}</h3>Lane: <b>{b_lane}</b> ({pair_display_str})<br/>Paid: <b>{'🟢 YES' if b_paid else '🔴 NO'}</b> | Checked In: <b>{'🟢 YES' if b_checked else '⚪ NO'}</b></div>", unsafe_allow_html=True)
                    if not b_paid:
                        p_method = st.radio("Payment Method:", ["Cash", "Check", "Venmo / Electronic"], horizontal=True)
                        if st.button(f"Mark Paid ({p_method}) & Push to Customer Screen", type="primary", width="stretch"):
                            idx = st.session_state.roster.index[st.session_state.roster["Bowler"] == s_bowler].tolist()[0]
                            st.session_state.roster.loc[idx, "Paid"] = True
                            write_kiosk_card({"name": s_bowler, "usbc_id": str(b_row["USBC ID"]), "avg": int(b_row["Average"]), "lane": b_lane, "pair_display": pair_display_str})
                            write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                            st.success("Payment logged & pushed to monitor!")
                            st.rerun()
                with col_act:
                    if st.button("Manual TD Check-In Override (No Phone)", width="stretch"):
                        idx = st.session_state.roster.index[st.session_state.roster["Bowler"] == s_bowler].tolist()[0]
                        st.session_state.roster.loc[idx, "Checked_In"] = True
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        st.success(f"{s_bowler} checked in!")
                        st.rerun()

        with intake_tab_pins:
            st.subheader("🔐 Floor TD Security PIN Registry (Argon2id)")
            if st.session_state.td_pins:
                st.dataframe(pd.DataFrame([{"Official": k, "Encryption": "Argon2id", "Status": "🟢 Locked"} for k in st.session_state.td_pins.keys()]), width="stretch")
            with st.form("pin_override"):
                ov_name = st.text_input("Official Name:").strip()
                ov_pin = st.text_input("Assign 4-Digit PIN:", type="password", max_chars=6).strip()
                if st.form_submit_button("Lock PIN (Argon2id)", type="primary"):
                    if ov_name and len(ov_pin) >= 4:
                        if register_td_pin(ov_name, ov_pin):
                            st.success(f"PIN locked for {ov_name}!")
                            st.rerun()
                        st.error("PIN registration failed. Use 4–6 numeric digits.")

    # MODULE 2: VISUAL MATRIX & SUBSTITUTIONS
    elif nav == "2. Visual Lane Matrix & Subs":
        st.markdown("### Lane movement guide")
        _render_lane_movement_guide()
        st.subheader("Cross-pair progression")
        render_cross_pair_progression_matrix(st.session_state.roster, st.session_state.tournament_config)
        st.divider()
        st.markdown("### Visual center pair matrix & mid-event substitutions")
        conn = get_sqlite_conn()
        roster_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        col_vm, col_sub = st.columns([2, 1])
        with col_vm:
            st.subheader("Active Center Lane Grid")
            parsed_pairs = parse_active_pairs(st.session_state.tournament_config.get("lanes_range", "1-40"), max_lanes=40)
            grid_cols = st.columns(4)
            for idx, pair in enumerate(parsed_pairs):
                l_odd, l_even = pair
                bowlers_on_p = roster_live[roster_live["starting_lane"].isin([l_odd, l_even])]
                with grid_cols[idx % 4]:
                    status_css = "border: 1px solid #334155; background-color: #0f172a;" if bowlers_on_p.empty else "border: 1.5px solid #10b981; background-color: #064e3b20;"
                    st.markdown(f"<div style='{status_css} border-radius: 8px; padding: 10px; margin-bottom: 10px;'><strong style='color: #f8fafc;'>Lanes {l_odd} & {l_even}</strong><br/><span style='font-size: 11px; color: #38bdf8;'>{len(bowlers_on_p)} Bowlers</span></div>", unsafe_allow_html=True)

        with col_sub:
            st.subheader("🔄 Sub-In Bowler")
            if not roster_live.empty:
                orig_bowler = st.selectbox("Select Bowler to Sub Out:", roster_live["bowler"].tolist())
                sub_name = st.text_input("Replacement Bowler Name:").strip()
                sub_avg = st.number_input("Sub Entering Average:", value=190, step=1)
                if st.button("Execute Substitution", type="primary", width="stretch") and sub_name:
                    orig_lane = int(roster_live[roster_live["bowler"] == orig_bowler].iloc[0]["starting_lane"])
                    c = get_sqlite_conn()
                    c.execute("UPDATE live_roster SET checked_in = 0, team_name = team_name || ' (Subbed)' WHERE bowler = ?", (orig_bowler,))
                    c.execute("""
                        INSERT INTO live_roster (usbc_id, bowler, average, starting_lane, division, team_name, paid, checked_in, is_sub, subbing_for, last_updated_by)
                        VALUES (?, ?, ?, ?, 'Open', 'Singles', 1, 1, 1, ?, ?)
                    """, (f"SUB-{datetime.now().strftime('%M%S')}", sub_name, sub_avg, orig_lane, orig_bowler, st.session_state.username))
                    c.commit()
                    c.close()
                    log_audit_event(f"Substituted '{sub_name}' in place of '{orig_bowler}' on Lane {orig_lane}.")
                    st.success(f"{sub_name} subbed on Lane {orig_lane}!")
                    st.rerun()

    # MODULE 3: SCORES, STANDINGS & RADAR MATRIX
    elif nav == "3. Scores & Standings":
        st.subheader("🛰️ Central Desk Lane Radar Matrix")
        radar_game = st.radio("Display Radar for Game:", list(range(1, num_games + 1)), horizontal=True)
        render_live_radar_matrix_fragment(radar_game)
        st.divider()

        conn = get_sqlite_conn()
        df_live = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        if not df_live.empty:
            rename_dict = {
                "usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "starting_lane": "Starting Lane",
                "paid": "Paid", "checked_in": "Checked_In"
            }
            for i in range(1, 7):
                rename_dict[f"game_{i}"] = f"Game {i}"
            df_for_calc = df_live.rename(columns=rename_dict)

            standings = compile_standings(df_for_calc, st.session_state.tournament_config)

            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f"<div class='stat-card'><div class='stat-value'>{len(df_for_calc)}</div><div class='stat-label'>Field Size</div></div>", unsafe_allow_html=True)
            c2.markdown(f"<div class='stat-card'><div class='stat-value'>{standings.iloc[0]['Grand_Total'] if not standings.empty else 0}</div><div class='stat-label'>Leader</div></div>", unsafe_allow_html=True)
            c3.markdown(f"<div class='stat-card'><div class='stat-value'>{standings.iloc[4]['Grand_Total'] if len(standings) >= 5 else 0}</div><div class='stat-label'>#5 Cut Line</div></div>", unsafe_allow_html=True)
            c4.markdown(f"<div class='stat-card'><div class='stat-value'>{standings['High_Scratch_Game'].max() if not standings.empty else 0}</div><div class='stat-label'>High Scratch</div></div>", unsafe_allow_html=True)

            st.write("")
            st.subheader(f"Official Scoring Grid ({num_games} Games)")
            active_game_cols = [f"Game {i}" for i in range(1, num_games + 1)]
            editor_cols = ["USBC ID", "Bowler", "Starting Lane", "Average"] + active_game_cols
            edited_scores = st.data_editor(df_for_calc[editor_cols], width="stretch")

            if st.button("Save Scores & Recalculate Standings", type="primary"):
                c = get_sqlite_conn()
                for _, r in edited_scores.iterrows():
                    update_sql = "UPDATE live_roster SET " + ", ".join([f"game_{i}=?" for i in range(1, num_games + 1)]) + " WHERE usbc_id=?"
                    params = [int(r[f"Game {i}"]) for i in range(1, num_games + 1)] + [r["USBC ID"]]
                    c.execute(update_sql, tuple(params))
                c.commit()
                c.close()
                st.success("Scores saved & standings recalculated!")
                st.rerun()

            st.subheader("Official Standings")
            standings_cols = ["Bowler", "Starting Lane", "Average"] + active_game_cols + ["Scratch_Total", "Total_HDCP", "Grand_Total"]
            st.dataframe(standings[standings_cols], width="stretch")
            st.download_button("📄 Download Official PDF Standings", export_standings_pdf(standings, st.session_state.tournament_config, td_name=st.session_state.td_name), "Official_Standings.pdf", "application/pdf", width="stretch")

            render_external_broadcast_cards(context_key="standings")

            st.divider()
            st.subheader("🏆 Multi-Squad All-Events Aggregate Leaderboard")
            all_events = compile_all_events_leaderboard(df_for_calc, st.session_state.tournament_config)
            if not all_events.empty:
                st.dataframe(all_events[["Bowler", "Average", "Total_Games_Bowled", "Scratch_Series", "Total_HDCP", "Grand_Total"]], width="stretch")

    # MODULE 4: STEPLADDER FINALS & TOURNAMENT COMPLETION
    elif nav == "4. Stepladder Finals":
        st.markdown("""
        <div class="brand-banner">
            <h1>Championship Stepladder Finals & Tournament Completion</h1>
            <p>Cut-line calculation, tiebreaker resolution, stepladder simulation, and official report generation.</p>
        </div>
        """, unsafe_allow_html=True)

        conn = get_sqlite_conn()
        df_sl = pd.read_sql_query("SELECT * FROM live_roster", conn)
        conn.close()

        rename_dict = {"bowler": "Bowler", "average": "Average"}
        for i in range(1, 7):
            rename_dict[f"game_{i}"] = f"Game {i}"
        df_sl = df_sl.rename(columns=rename_dict)
        standings = compile_standings(df_sl, st.session_state.tournament_config)

        if len(standings) < 5:
            st.warning(f"Stepladder finals require at least 5 bowlers with scores (Current: {len(standings)}).")
        else:
            top_5 = standings.head(5)["Bowler"].tolist()
            def get_sc(name):
                row = standings[standings["Bowler"] == name]
                return int(row.iloc[0]["Grand_Total"]) if not row.empty else 0

            m1_p1, m1_p2 = top_5[3], top_5[4]
            m1_s1, m1_s2 = get_sc(m1_p1), get_sc(m1_p2)
            m1_winner = m1_p1 if m1_s1 >= m1_s2 else m1_p2
            m1_score_str = f"{max(m1_s1, m1_s2)} - {min(m1_s1, m1_s2)}"

            m2_p1 = top_5[2]
            m2_s1, m2_s2 = get_sc(m2_p1), get_sc(m1_winner)
            m2_winner = m2_p1 if m2_s1 >= m2_s2 else m1_winner
            m2_score_str = f"{max(m2_s1, m2_s2)} - {min(m2_s1, m2_s2)}"

            semi_p1 = top_5[1]
            semi_s1, semi_s2 = get_sc(semi_p1), get_sc(m2_winner)
            semi_winner = semi_p1 if semi_s1 >= semi_s2 else m2_winner
            semi_score_str = f"{max(semi_s1, semi_s2)} - {min(semi_s1, semi_s2)}"

            champ_p1 = top_5[0]
            champ_s1, champ_s2 = get_sc(champ_p1), get_sc(semi_winner)
            champ_winner = champ_p1 if champ_s1 >= champ_s2 else semi_winner
            champ_score_str = f"{max(champ_s1, champ_s2)} - {min(champ_s1, champ_s2)}"

            stepladder_summary_dict = {
                "m1_p1": m1_p1, "m1_p2": m1_p2, "m1_winner": m1_winner, "m1_score": m1_score_str,
                "m2_p1": m2_p1, "m2_winner_prev": m1_winner, "m2_winner": m2_winner, "m2_score": m2_score_str,
                "semi_p1": semi_p1, "semi_winner_prev": m2_winner, "semi_winner": semi_winner, "semi_score": semi_score_str,
                "champ_p1": champ_p1, "champ_winner_prev": semi_winner, "champ_score": champ_score_str
            }

            st.markdown(f"<div style='background-color: #10b98120; border: 1.5px solid #10b981; border-radius: 10px; padding: 18px; text-align: center;'><h1 style='color: #f8fafc; margin: 0;'>👑 Champion: {champ_winner}</h1></div>", unsafe_allow_html=True)
            st.write("")

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.markdown("#### 🪵 Seeded Qualifiers")
                for i, name in enumerate(top_5):
                    st.markdown(f"<div class='match-box'><b>#{i+1} Seed:</b> {name} <span style='float:right; color:#38bdf8;'>{get_sc(name)} pins</span></div>", unsafe_allow_html=True)
            with col_s2:
                st.markdown("#### 🪜 Stepladder Advancement")
                st.markdown(f"""
                <div class="match-box" style="font-size: 13.5px;">
                    <div><b>Match 1:</b> {m1_p1} vs {m1_p2} ➔ <b style="color:#34d399;">{m1_winner}</b></div>
                    <div style="margin-top:6px;"><b>Match 2:</b> {m2_p1} vs {m1_winner} ➔ <b style="color:#34d399;">{m2_winner}</b></div>
                    <div style="margin-top:6px;"><b>Semifinal:</b> {semi_p1} vs {m2_winner} ➔ <b style="color:#34d399;">{semi_winner}</b></div>
                    <div style="margin-top:6px;"><b>Championship:</b> {champ_p1} vs {semi_winner} ➔ <b style="color:#34d399;">{champ_winner} Wins</b></div>
                </div>
                """, unsafe_allow_html=True)

            summary_pdf_bytes = export_tournament_summary_pdf(standings, st.session_state.tournament_config, champ_winner, stepladder_summary_dict)
            st.download_button("🖨️ Download Official Summary Report (PDF)", summary_pdf_bytes, "Tournament_Summary.pdf", "application/pdf", width="stretch")

            render_external_broadcast_cards(context_key="finals")

            st.divider()
            st.subheader("🏁 Official Tournament Completion & Desk Closeout")

            is_completed = st.session_state.tournament_config.get("status") == "Completed"

            col_comp, col_arch = st.columns(2)

            with col_comp:
                if not is_completed:
                    if st.button("🏆 Mark Tournament Complete & Lock Scores", type="primary", width="stretch"):
                        st.session_state.tournament_config["status"] = "Completed"
                        st.session_state.tournament_config["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        st.session_state.tournament_config["champion"] = champ_winner
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        log_audit_event(f"Tournament '{st.session_state.tournament_config['name']}' officially completed. Champion: {champ_winner}.")
                        st.success(f"Tournament officially marked COMPLETE! Champion: {champ_winner}")
                        st.rerun()
                else:
                    completed_time = st.session_state.tournament_config.get("completed_at", "Verified")
                    st.markdown(f"""
                    <div style='background-color: #064e3b; border: 1.5px solid #10b981; border-radius: 8px; padding: 12px; text-align: center;'>
                        <strong style='color: #a7f3d0; font-size: 15px;'>✅ TOURNAMENT OFFICIALLY COMPLETE</strong><br/>
                        <span style='color: #f8fafc; font-size: 12.5px;'>Champion: <b>{st.session_state.tournament_config.get("champion", champ_winner)}</b> • Locked: {completed_time}</span>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("🔓 Reopen Tournament Scoring (TD Override)", width="stretch"):
                        st.session_state.tournament_config["status"] = "Active"
                        write_active_tournament_state(st.session_state.tournament_config, st.session_state.roster, st.session_state.brackets)
                        log_audit_event("TD reopened tournament scoring.")
                        st.warning("Tournament scoring unlocked.")
                        st.rerun()

            with col_arch:
                st.caption("Permanent archival stores final results and generated PDF reports in the local SQLite archive, then clears the active roster.")
                if st.button("📦 Archive Tournament to SQLite & Reset Desk", disabled=not is_completed, width="stretch"):
                    encoded_pdf = base64.b64encode(summary_pdf_bytes).decode("utf-8")
                    arch_df = fetch_archives_df()
                    new_rec = pd.DataFrame([{
                        "tournament_name": st.session_state.tournament_config["name"],
                        "center": st.session_state.tournament_config["center"],
                        "division": st.session_state.tournament_config["division"],
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "entries": len(df_sl),
                        "champion": champ_winner,
                        "pdf_data": encoded_pdf,
                        "archived_by": st.session_state.td_name
                    }])
                    write_archives_df(pd.concat([arch_df, new_rec], ignore_index=True))

                    clear_active_tournament_state()

                    # Reset memory state
                    st.session_state.roster = pd.DataFrame()
                    st.session_state.brackets = []
                    st.session_state.tournament_config["status"] = "Archived"
                    log_audit_event(f"Archived tournament '{st.session_state.tournament_config['name']}' to SQLite.")
                    st.success("Tournament archived to SQLite and the desk was reset.")
                    st.rerun()

    # MODULE 5: BRACKETS & POTS
    elif nav == "5. Side Action: Brackets & Pots 💰":
        t_brk, t_pots = st.tabs(["🌳 8-Bowler Elimination Brackets", "💵 High-Game & Series Side Pots"])
        with t_brk:
            conn = get_sqlite_conn()
            paid_b = pd.read_sql_query("SELECT usbc_id FROM live_roster WHERE paid = 1", conn)["usbc_id"].tolist()
            r_df = pd.read_sql_query("SELECT * FROM live_roster", conn).rename(columns={"usbc_id": "USBC ID", "bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"})
            conn.close()

            col_bc1, col_bc2 = st.columns(2)
            with col_bc1:
                brk_type = st.selectbox("Bracket Division:", ["Scratch", "Handicap"])
            with col_bc2:
                if st.button("🎲 Generate 8-Bowler Bracket", type="primary", width="stretch"):
                    if len(paid_b) < 8:
                        st.error("Need at least 8 paid bowlers.")
                    else:
                        st.session_state.brackets.append({"id": f"B-{len(st.session_state.brackets)+1:02d}", "type": brk_type, "fee": 5, "seeds": random.sample(paid_b, 8)})
                        st.success("Bracket seeded!")

            if st.session_state.brackets:
                for brk in st.session_state.brackets:
                    seeds = brk["seeds"]
                    r1_1_b1, r1_1_s1, r1_1_b2, r1_1_s2, w1 = resolve_bracket_match(seeds[0], seeds[7], "Game 1", brk["type"], r_df)
                    r1_2_b1, r1_2_s1, r1_2_b2, r1_2_s2, w2 = resolve_bracket_match(seeds[3], seeds[4], "Game 1", brk["type"], r_df)
                    r1_3_b1, r1_3_s1, r1_3_b2, r1_3_s2, w3 = resolve_bracket_match(seeds[2], seeds[5], "Game 1", brk["type"], r_df)
                    r1_4_b1, r1_4_s1, r1_4_b2, r1_4_s2, w4 = resolve_bracket_match(seeds[1], seeds[6], "Game 1", brk["type"], r_df)

                    r2_1_b1, r2_1_s1, r2_1_b2, r2_1_s2, w_semi1 = resolve_bracket_match(w1, w2, "Game 2", brk["type"], r_df)
                    r2_2_b1, r2_2_s1, r2_2_b2, r2_2_s2, w_semi2 = resolve_bracket_match(w3, w4, "Game 2", brk["type"], r_df)

                    c_b1, c_s1, c_b2, c_s2, champ_w = resolve_bracket_match(w_semi1, w_semi2, "Game 3", brk["type"], r_df)
                    st.markdown(f"<div class='match-box'><h3>Bracket {brk['id']} ({brk['type']}) — Winner: <span style='color:#34d399;'>{c_b1 if champ_w == w_semi1 else c_b2}</span></h3></div>", unsafe_allow_html=True)

        with t_pots:
            st.subheader("High-Game & Series Pots Engine")
            pot_fee = st.number_input("Entry Fee ($):", value=10, min_value=1)
            conn = get_sqlite_conn()
            pot_df = pd.read_sql_query("SELECT * FROM live_roster WHERE paid = 1", conn)
            conn.close()

            if not pot_df.empty:
                pot_df = pot_df.rename(columns={"bowler": "Bowler", "average": "Average", "game_1": "Game 1", "game_2": "Game 2", "game_3": "Game 3"})
                pot_total = len(pot_df) * pot_fee
                p_g1, p_g2, p_g3, p_ser = round(pot_total * 0.3, 2), round(pot_total * 0.3, 2), round(pot_total * 0.3, 2), round(pot_total * 0.1, 2)
                cp1, cp2, cp3, cp4 = st.columns(4)
                cp1.metric("Game 1 Pot", f"${p_g1:,.2f}")
                cp2.metric("Game 2 Pot", f"${p_g2:,.2f}")
                cp3.metric("Game 3 Pot", f"${p_g3:,.2f}")
                cp4.metric("Series Pot", f"${p_ser:,.2f}")

    # MODULE 6: FINANCIAL & SMART RECONCILIATION
    elif nav == "6. Financial & SMART Ledger 💵":
        st.markdown("<div class='brand-banner'><h1>Financial Reconciliation & Prize Ledger</h1></div>", unsafe_allow_html=True)
        conn = get_sqlite_conn()
        df_fin = pd.read_sql_query("SELECT * FROM live_roster", conn).rename(columns={"paid": "Paid", "bowler": "Bowler"})
        conn.close()

        fin = calculate_financial_summary(df_fin, st.session_state.tournament_config)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Paid Entries", fin["paid_count"])
        c2.metric("Gross Revenue", f"${fin['gross_revenue']:,.2f}")
        c3.metric("Lineage Owed", f"${fin['total_lineage']:,.2f}")
        c4.metric("Net Prize Pool", f"${fin['net_prize_fund']:,.2f}")

        if "youth" in str(st.session_state.tournament_config.get("division", "")).lower():
            st.divider()
            st.markdown("#### 🎓 USBC Rule 400 SMART Scholarship Submission")
            smart_csv = generate_smart_scholarship_csv(df_fin, fin["net_prize_fund"], st.session_state.tournament_config["name"])
            st.download_button("📄 Download SMART Scholarship Submission (.csv)", smart_csv, "SMART_Submittal.csv", "text/csv", type="primary", width="stretch")

    # MODULE 7: AI RULES ARBITER
    elif nav == "7. AI Rules Arbiter":
        st.markdown("<div class='brand-banner'><h1>USBC & Tournament Rules Arbiter</h1></div>", unsafe_allow_html=True)
        st.caption("Decision support grounded in the bundled 2026–27 rulebook when available. The tournament director remains responsible for the official ruling.")
        presets = {
            "Custom inquiry": "",
            "Rule 10 · Tardy bowler": "What procedure applies if a bowler arrives during frame 3?",
            "Rule 17 · Altering ball surface": "What is prohibited when altering a ball surface after competition starts?",
            "Rule 18 · Ball specifications": "What does Rule 18 require for gripping holes and balance holes?",
            "Rule 400 · Youth eligibility": "May a youth member bowl for cash, bonds, or adult side-pot prizes?",
        }
        preset = st.selectbox("Common rule inquiry", list(presets), key="arbiter_preset")
        dispute_text = st.text_area("Describe the rule question", value=presets[preset], key="arbiter_question")
        if st.button("Review against the rulebook", type="primary") and dispute_text.strip():
            context = {
                "user": st.session_state.td_name,
                "event": st.session_state.tournament_config.get("name"),
                "center": st.session_state.tournament_config.get("center"),
                "division": st.session_state.tournament_config.get("division"),
                "event_rules": st.session_state.tournament_config.get("rules_text", ""),
            }
            answer = arbitrate_rules_inquiry(dispute_text, context, client=ai_client)
            st.markdown(answer)

    # MODULE 8: PAST TOURNAMENTS ARCHIVE
    elif nav == "8. Past Tournaments Archive 📂":
        st.markdown("<div class='brand-banner'><h1>Historical Tournament Archive</h1></div>", unsafe_allow_html=True)
        arch = fetch_archives_df()
        if arch.empty:
            st.info("No past tournaments archived yet.")
        else:
            for _, r in arch.iterrows():
                st.markdown(f"<div class='match-box'><h3>🏆 {r['tournament_name']} ({r['date']})</h3>Center: <b>{r['center']}</b> | Champion: <b>{r['champion']}</b> | Entries: <b>{r['entries']}</b></div>", unsafe_allow_html=True)

    # MODULE 9: BOARD SOP & STAFF MANUAL
    elif nav == "9. Board SOP & Staff Manual 📖":
        st.markdown("<div class='brand-banner'><h1>Board Standard Operating Procedure (SOP)</h1></div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        c1.download_button("📝 Download Official SOP (.docx for Word)", generate_sop_docx(st.session_state.tournament_config), "SOP.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", width="stretch")
        c2.download_button("📄 Download Official SOP (.pdf for Print)", generate_sop_pdf(st.session_state.tournament_config), "SOP.pdf", "application/pdf", width="stretch")

    # MODULE 10: TD AUDIT LOG
    elif nav == "10. TD Audit Log":
        st.markdown("<div class='brand-banner'><h1>Official Tournament Audit Log</h1></div>", unsafe_allow_html=True)
        st.dataframe(fetch_audit_trail(), width="stretch")

    # MODULE 11: ADMIN USER MANAGEMENT (ARGON2ID)
    elif "TD User Management" in nav:
        st.markdown("<div class='brand-banner'><h1>Staff & Director Account Management (Argon2id)</h1></div>", unsafe_allow_html=True)
        users = fetch_users_df()

        req_cols = ["username", "name", "email", "password_hash", "role", "center_id", "preferred_mode", "status", "must_change_password"]
        for c in req_cols:
            if c not in users.columns:
                if c == "status":
                    users[c] = "active"
                elif c == "center_id":
                    users[c] = "association"
                elif c == "preferred_mode":
                    users[c] = "Advanced"
                elif c == "role":
                    users[c] = "td"
                elif c == "must_change_password":
                    users[c] = False
                else:
                    users[c] = ""

        tab_registry, tab_edit, tab_pending = st.tabs([
            "👥 Staff Registry",
            "🛠️ Administer User Account",
            f"⏳ Pending Approvals ({len(users[users['status'] == 'pending'])})"
        ])

        # TAB 1: MASTER DIRECTORY
        with tab_registry:
            st.subheader("Active Staff Registry")
            display_cols = [c for c in ["username", "name", "email", "role", "center_id", "preferred_mode", "status"] if c in users.columns]
            st.dataframe(users[display_cols], width="stretch")

        # TAB 2: ADMINISTRATIVE ACTIONS
        with tab_edit:
            st.subheader("Manage Staff Account & Credentials")
            usernames = users["username"].tolist()
            target_user = st.selectbox("Select Staff Account to Administer:", usernames)

            if target_user:
                user_row = users[users["username"] == target_user].iloc[0]
                user_idx = users.index[users["username"] == target_user].tolist()[0]

                c_info1, c_info2 = st.columns(2)
                with c_info1:
                    st.markdown(f"""
                    <div class='match-box'>
                        <b>User:</b> {user_row['name']} (<code>{user_row['username']}</code>)<br/>
                        <b>Email:</b> {user_row.get('email', 'N/A')}<br/>
                        <b>Current Status:</b> <code>{user_row['status']}</code>
                    </div>
                    """, unsafe_allow_html=True)
                with c_info2:
                    st.markdown(f"""
                    <div class='match-box'>
                        <b>Role:</b> {str(user_row['role']).upper()}<br/>
                        <b>Assigned Center:</b> {user_row['center_id']}<br/>
                        <b>Default Mode:</b> {user_row['preferred_mode']}
                    </div>
                    """, unsafe_allow_html=True)

                st.divider()

                col_pw, col_role = st.columns(2)

                # Password Reset (Argon2id)
                with col_pw:
                    st.markdown("#### 🔑 Reset Account Password")
                    with st.form(f"form_reset_pw_{target_user}"):
                        new_temp_pw = st.text_input("Enter New Password:", type="password")
                        force_change = st.checkbox("Require password change on next login", value=True)
                        if st.form_submit_button("Override Password", type="primary", width="stretch"):
                            if len(new_temp_pw) >= 6:
                                users.loc[user_idx, "password_hash"] = hash_secret(new_temp_pw)
                                users.loc[user_idx, "must_change_password"] = force_change
                                if write_users_df(users):
                                    log_audit_event(f"Admin reset password for user '{target_user}'.")
                                    st.success(f"Password updated for {target_user}!")
                                    st.rerun()
                                else:
                                    st.error("Failed to save updated credentials to SQLite.")
                            else:
                                st.warning("Password must be at least 6 characters.")

                # Role, Center & Permissions Configuration
                with col_role:
                    st.markdown("#### ⚙️ Edit Roles & Permissions")
                    with st.form(f"form_perms_{target_user}"):
                        role_opts = ["admin", "td", "volunteer"]
                        cur_role = str(user_row["role"]).lower()
                        new_role = st.selectbox(
                            "System Role:",
                            role_opts,
                            index=role_opts.index(cur_role) if cur_role in role_opts else 1
                        )

                        # Explicitly label CHUSBC alongside the centers
                        center_display_map = {
                            "association": "CHUSBC (Association Central Desk)",
                            "forest_hill": "Forest Hill Bowling Center",
                            "harford": "Harford Lanes",
                            "apg": "APG Bowling Center"
                        }
                        center_keys = list(center_display_map.keys())
                        cur_center = str(user_row.get("center_id", "association")).lower()
                        cur_idx = center_keys.index(cur_center) if cur_center in center_keys else 0

                        selected_center_display = st.selectbox(
                            "Assigned Center / Association:",
                            options=[center_display_map[k] for k in center_keys],
                            index=cur_idx
                        )
                        new_center = [k for k, v in center_display_map.items() if v == selected_center_display][0]

                        mode_opts = ["Advanced", "Easy"]
                        cur_mode = str(user_row["preferred_mode"])
                        new_mode = st.selectbox(
                            "Default UI Mode:",
                            mode_opts,
                            index=mode_opts.index(cur_mode) if cur_mode in mode_opts else 0
                        )

                        status_opts = ["active", "suspended"]
                        cur_status = str(user_row["status"]).lower()
                        new_status = st.selectbox(
                            "Account Status:",
                            status_opts,
                            index=status_opts.index(cur_status) if cur_status in status_opts else 0
                        )

                        if st.form_submit_button("Save Account Changes", type="primary", width="stretch"):
                            users.loc[user_idx, "role"] = new_role
                            users.loc[user_idx, "center_id"] = new_center
                            users.loc[user_idx, "preferred_mode"] = new_mode
                            users.loc[user_idx, "status"] = new_status
                            if write_users_df(users):
                                log_audit_event(f"Admin updated settings for '{target_user}' (Center: {selected_center_display}, Role: {new_role}).")
                                st.success(f"Account settings saved for {target_user}!")
                                st.rerun()
                            else:
                                st.error("Failed to save updated settings to SQLite.")

                # Account Deletion Safety Zone
                if target_user != st.session_state.get("username"):
                    st.divider()
                    with st.expander(f"⚠️ Danger Zone: Delete '{target_user}'"):
                        st.caption("Permanently removes this account from the local staff registry.")
                        if st.button(f"Permanently Delete {target_user}", type="secondary", width="stretch"):
                            users = users[users["username"] != target_user]
                            if write_users_df(users):
                                log_audit_event(f"Admin permanently deleted account '{target_user}'.")
                                st.warning(f"Account '{target_user}' has been deleted.")
                                st.rerun()

        # TAB 3: PENDING APPROVAL QUEUE
        with tab_pending:
            pending = users[users["status"] == "pending"]
            if pending.empty:
                st.info("No registrations currently awaiting review.")
            else:
                for _, row in pending.iterrows():
                    st.markdown(f"<div class='match-box'><b>{row['name']}</b> (<code>{row['username']}</code>) — {row.get('email', '')}</div>", unsafe_allow_html=True)
                    col_a, col_d = st.columns(2)
                    if col_a.button(f"Approve {row['username']}", key=f"app_{row['username']}", type="primary"):
                        users.loc[users["username"] == row["username"], "status"] = "active"
                        write_users_df(users)
                        notify_user_account_approved(row.get("email", ""), row["name"], row["username"])
                        log_audit_event(f"Admin approved account registration for '{row['username']}'.")
                        st.success(f"Approved {row['username']}!")
                        st.rerun()
                    if col_d.button(f"Deny {row['username']}", key=f"den_{row['username']}"):
                        users = users[users["username"] != row["username"]]
                        write_users_df(users)
                        log_audit_event(f"Admin denied account registration for '{row['username']}'.")
                        st.warning(f"Denied {row['username']}.")
                        st.rerun()
