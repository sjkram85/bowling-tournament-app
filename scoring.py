# scoring.py
import streamlit as st
import pandas as pd
import json

from db_state import fetch_active_tournament_state, get_sqlite_conn, log_audit_event
from engine_support import (
    calculate_handicap,
    compile_all_events_leaderboard,
    export_standings_pdf,
    get_bowler_lane_for_game,
    parse_active_pairs,
)
from prism_ai import get_ai_client, parse_score_recap


def _refresh_active_roster():
    state = fetch_active_tournament_state()
    if state:
        st.session_state.tournament_config = state.get("config", st.session_state.get("tournament_config", {}))
        st.session_state.roster = state.get("roster", pd.DataFrame())
        st.session_state.brackets = state.get("brackets", st.session_state.get("brackets", []))
        st.session_state.td_pins = state.get("td_pins", st.session_state.get("td_pins", {}))
    roster = st.session_state.get("roster", pd.DataFrame())
    return roster.copy() if isinstance(roster, pd.DataFrame) else pd.DataFrame(roster)

@st.fragment(run_every="8s")
def render_live_checkin_counters_fragment():
    """
    Zero-dimming auto-refreshing check-in count badges.
    Reads directly from st.session_state to avoid closure argument staleness.
    """
    roster_df = _refresh_active_roster()
        
    if roster_df.empty:
        st.info("No active roster loaded.")
        return

    total = len(roster_df)
    checked_in = int(roster_df["Checked_In"].sum()) if "Checked_In" in roster_df.columns else 0
    paid = int(roster_df["Paid"].sum()) if "Paid" in roster_df.columns else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Field", f"{total} Bowlers")
    c2.metric("Checked In", f"{checked_in} / {total}", delta=f"{checked_in - total}")
    c3.metric("Paid Entries", f"{paid} / {total}")


@st.fragment(run_every="8s")
def render_live_radar_matrix_fragment(game_number=None):
    """
    Concourse Lane Status Matrix.
    Reads active game dynamically from st.session_state.
    """
    active_game = game_number or st.session_state.get("active_radar_game", 1)
    roster_df = _refresh_active_roster()
    if roster_df.empty:
        return

    st.markdown(f"**Live Radar Status — Game {active_game}**")
    lane_col = "Starting Lane" if "Starting Lane" in roster_df.columns else "Lane"
    score_col = f"Game {active_game}"
    if lane_col not in roster_df.columns or score_col not in roster_df.columns:
        return
    config = st.session_state.get("tournament_config", {})
    max_lanes = int(config.get("lanes_count", 40))
    pairs = parse_active_pairs(config.get("lanes_range", f"1-{max_lanes}"), max_lanes=max_lanes)
    movement_rule = str(config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)"))
    roster_df["Active Game Lane"] = pd.to_numeric(roster_df[lane_col], errors="coerce").fillna(1).astype(int).apply(
        lambda lane: get_bowler_lane_for_game(lane, int(active_game), movement_rule, max_lanes)
    )
    cols = st.columns(min(len(pairs), 8) or 1)
    verifier_column = f"g{active_game}_verified_by"
    for index, pair in enumerate(pairs):
        lane_bowlers = roster_df[roster_df["Active Game Lane"].isin(pair)]
        if lane_bowlers.empty:
            status_text, badge_color = "EMPTY", "#334155"
        else:
            score_entered = pd.to_numeric(lane_bowlers[score_col], errors="coerce").fillna(0).gt(0)
            verified_flags = lane_bowlers[verifier_column].fillna("").astype(str).str.strip().ne("") if verifier_column in lane_bowlers else pd.Series(False, index=lane_bowlers.index)
            has_scores = bool((score_entered | verified_flags).any())
            all_verified = bool(verified_flags.all())
            status_text, badge_color = ("VERIFIED", "#10b981") if all_verified else ("ROLLING" if has_scores else "PENDING", "#f59e0b" if has_scores else "#ef4444")
        names = ", ".join(lane_bowlers.get("Bowler", pd.Series(dtype=str)).astype(str).tolist())
        with cols[index % len(cols)]:
            st.markdown(f"**Lanes {pair[0]}-{pair[1]}** · {status_text}")
            if names:
                st.caption(names)


def render_cross_pair_progression_matrix(roster_data=None, config=None):
    roster_data = roster_data if roster_data is not None else st.session_state.get("roster", pd.DataFrame())
    config = config or st.session_state.get("tournament_config", {})
    roster = roster_data.copy() if isinstance(roster_data, pd.DataFrame) else pd.DataFrame(roster_data)
    if roster.empty:
        st.info("Load a roster to preview cross-pair movement.")
        return

    max_lanes = int(config.get("lanes_count", 40))
    movement_rule = str(config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)"))
    games_count = max(1, min(10, int(config.get("games_count", 3))))
    movement_rows = []
    for _, bowler in roster.iterrows():
        start_lane = int(pd.to_numeric(bowler.get("Starting Lane", 1), errors="coerce") or 1)
        row = {"Bowler": bowler.get("Bowler", ""), "Starting lane": start_lane}
        for game in range(1, games_count + 1):
            lane = get_bowler_lane_for_game(start_lane, game, movement_rule, max_lanes)
            partner = lane + 1 if lane % 2 else lane - 1
            row[f"Game {game}"] = f"{min(lane, partner)}-{max(lane, partner)} (L{lane})"
        movement_rows.append(row)
    st.dataframe(
        pd.DataFrame(movement_rows),
        hide_index=True,
        alt="Cross-pair lane progression by game",
    )


def render_live_scoring_floor_grid(config=None, ai_client=None):
    config = config or st.session_state.get("tournament_config", {})
    games_count = max(1, min(10, int(config.get("games_count", 3))))
    game_number = st.selectbox("Game to score", range(1, games_count + 1), key="live_scoring_game")
    conn = get_sqlite_conn()
    try:
        live_roster = pd.read_sql_query(
            "SELECT usbc_id, bowler, average, starting_lane, division, team_name, "
            "entry_status, paid, checked_in, score_frames_json, "
            + ", ".join(f"game_{game}" for game in range(1, 11))
            + " FROM live_roster ORDER BY starting_lane, bowler",
            conn,
        )
    finally:
        conn.close()

    if live_roster.empty:
        st.info("No active bowlers. Add a roster in Intake Gateway before entering scores.")
        return

    frame_columns = [f"Frame {frame}" for frame in range(1, 11)]
    frame_state = []
    for _, bowler in live_roster.iterrows():
        try:
            saved_games = json.loads(bowler.get("score_frames_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            saved_games = {}
        values = saved_games.get(str(game_number), [None] * 10)
        values = (values + [None] * 10)[:10]
        imported_total = int(bowler.get(f"game_{game_number}", 0) or 0)
        frame_state.append({
            "USBC ID": str(bowler["usbc_id"]),
            "Bowler": str(bowler["bowler"]),
            "Average": int(bowler["average"] or 0),
            "Existing total": imported_total if not any(value is not None for value in values) and imported_total else None,
            **{
                frame_columns[index]: "" if values[index] is None else str(values[index])
                for index in range(10)
            },
        })
    score_input = pd.DataFrame(frame_state)

    st.subheader(f"Live scoring · Game {game_number}")
    st.caption("Enter each frame’s awarded pinfall (0–30). Empty frames are still pending; totals update as frames are entered.")
    column_config = {
        "USBC ID": st.column_config.TextColumn("USBC ID", disabled=True),
        "Bowler": st.column_config.TextColumn("Bowler", disabled=True),
        "Average": st.column_config.NumberColumn("Average", disabled=True),
        "Existing total": st.column_config.NumberColumn("Existing total", disabled=True),
    }
    column_config.update({
        frame: st.column_config.TextColumn(frame)
        for frame in frame_columns
    })
    completed_event = config.get("status") == "Completed"
    with st.form(f"live_scoring_form_{game_number}"):
        edited = st.data_editor(
            score_input,
            column_config=column_config,
            disabled=["USBC ID", "Bowler", "Average"] + (frame_columns if completed_event else []),
            hide_index=True,
            key=f"live_scoring_editor_{game_number}",
            alt=f"Game {game_number} per-frame scoring grid",
        )
        save_scores = st.form_submit_button("Save frame scores", type="primary", disabled=completed_event)

    staged_games = []
    frame_records = {}
    invalid_frames = []
    for index, row in edited.iterrows():
        raw_frames = [row.get(frame) for frame in frame_columns]
        values = []
        for frame, value in zip(frame_columns, raw_frames):
            if value is None or pd.isna(value) or not str(value).strip():
                values.append(None)
                continue
            try:
                score = int(str(value).strip())
            except ValueError:
                invalid_frames.append(f"{row['Bowler']} · {frame}")
                values.append(None)
                continue
            if not 0 <= score <= 30:
                invalid_frames.append(f"{row['Bowler']} · {frame}")
                values.append(None)
                continue
            values.append(score)
        partial = sum(value for value in values if value is not None)
        entered_frames = sum(value is not None for value in values)
        existing_score = int(live_roster.iloc[index].get(f"game_{game_number}", 0) or 0)
        frame_records[str(row["USBC ID"])] = values
        roster_row = live_roster.iloc[index]
        starting_lane = int(roster_row["starting_lane"] or 1)
        active_lane = get_bowler_lane_for_game(
            starting_lane,
            int(game_number),
            str(config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")),
            int(config.get("lanes_count", 40)),
        )
        pace_score = partial if entered_frames else existing_score
        projected_score = round(pace_score * 10 / entered_frames) if entered_frames else existing_score
        staged_games.append({
            "USBC ID": str(row["USBC ID"]),
            "Bowler": row["Bowler"],
            "Lane": active_lane,
            "Paid": "Paid" if bool(roster_row.get("paid", 0)) or str(roster_row.get("entry_status", "")).casefold() == "comp" else "Due",
            "Check-in": "Checked in" if bool(roster_row.get("checked_in", 0)) else "Pending",
            "Average": int(row["Average"]),
            "Partial Game": pace_score,
            "200 pace": f"{projected_score - 200:+d} ({projected_score})",
            "Frames entered": entered_frames,
            "Game complete": entered_frames == 10,
        })

    if invalid_frames:
        st.error("Frame scores must be whole pins from 0 to 30: " + ", ".join(invalid_frames[:8]))

    if save_scores:
        if invalid_frames:
            st.error("Correct the invalid frame values before saving.")
            return
        conn = get_sqlite_conn()
        try:
            with conn:
                for _, row in edited.iterrows():
                    usbc_id = str(row["USBC ID"])
                    values = frame_records[usbc_id]
                    score_frames = {}
                    match = live_roster[live_roster["usbc_id"].astype(str) == usbc_id]
                    previous_score = int(match.iloc[0].get(f"game_{game_number}", 0) or 0)
                    score = sum(value for value in values if value is not None) if any(value is not None for value in values) else previous_score
                    try:
                        score_frames = json.loads(match.iloc[0].get("score_frames_json") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        score_frames = {}
                    score_frames[str(game_number)] = values
                    conn.execute(
                        f"UPDATE live_roster SET game_{game_number}=?, score_frames_json=?, updated_at=CURRENT_TIMESTAMP WHERE usbc_id=?",
                        (score, json.dumps(score_frames), usbc_id),
                    )
        finally:
            conn.close()
        active = fetch_active_tournament_state()
        if active:
            st.session_state.roster = active["roster"]
        log_audit_event("SCORES_UPDATED", f"Saved per-frame scores for Game {game_number}.")
        st.rerun()

    st.dataframe(pd.DataFrame(staged_games), hide_index=True, alt=f"Game {game_number} running frame totals")

    with st.expander("Apply recap text with Prism AI"):
        recap_text = st.text_area(
            "Paste a recap with bowler names/USBC IDs and game scores",
            key="score_recap_text",
        )
        if st.button("Extract recap scores", key="extract_score_recap"):
            parsed_scores = parse_score_recap(
                recap_text,
                _refresh_active_roster(),
                games_count,
                client=ai_client or get_ai_client(),
            )
            if parsed_scores:
                st.session_state.score_recap_draft = parsed_scores
                st.success(f"Parsed scores for {len(parsed_scores)} bowlers. Review before applying.")
            else:
                st.warning("No unambiguous scores were extracted. Enter them manually instead.")
        recap_draft = st.session_state.get("score_recap_draft", {})
        if recap_draft:
            st.dataframe(pd.DataFrame([
                {"USBC ID": identifier, **{f"Game {game}": score for game, score in scores.items()}}
                for identifier, scores in recap_draft.items()
            ]), hide_index=True, alt="Preview of parsed score recap")
            if st.button("Apply parsed scores as provisional", key="apply_score_recap", disabled=completed_event):
                conn = get_sqlite_conn()
                try:
                    with conn:
                        for identifier, scores in recap_draft.items():
                            row_match = live_roster[live_roster["usbc_id"].astype(str) == str(identifier)]
                            if row_match.empty:
                                continue
                            try:
                                frame_detail = json.loads(row_match.iloc[0].get("score_frames_json") or "{}")
                            except (TypeError, json.JSONDecodeError):
                                frame_detail = {}
                            assignments = []
                            values = []
                            for game, score in scores.items():
                                assignments.extend([f"game_{game}=?", f"g{game}_verified_by=NULL", f"g{game}_verified_at=NULL"])
                                values.append(int(score))
                                frame_detail.pop(str(game), None)
                            assignments.extend(["score_frames_json=?", "updated_at=CURRENT_TIMESTAMP"])
                            values.extend([json.dumps(frame_detail), str(identifier)])
                            conn.execute(
                                f"UPDATE live_roster SET {', '.join(assignments)} WHERE usbc_id=?",
                                values,
                            )
                finally:
                    conn.close()
                log_audit_event("AI_RECAP_SCORES_IMPORTED", f"Applied provisional recap scores for {len(recap_draft)} bowlers.")
                st.session_state.score_recap_draft = {}
                st.rerun()

    standings_rows = []
    for _, bowler in live_roster.iterrows():
        try:
            saved_games = json.loads(bowler.get("score_frames_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            saved_games = {}
        if str(bowler["usbc_id"]) in frame_records:
            saved_games[str(game_number)] = frame_records[str(bowler["usbc_id"])]
        game_scores = []
        games_played = 0
        for game in range(1, games_count + 1):
            frames = saved_games.get(str(game), [None] * 10)
            has_frame_detail = any(value is not None for value in frames)
            aggregate_score = int(bowler.get(f"game_{game}", 0) or 0)
            total = sum(value for value in frames if value is not None) if has_frame_detail else aggregate_score
            game_scores.append(total)
            if has_frame_detail or aggregate_score > 0:
                games_played += 1
        handicap = calculate_handicap(
            int(bowler["average"] or 0),
            int(config.get("hdcp_base", 220)),
            float(config.get("hdcp_pct", 0.90)),
            str(config.get("handicap_method", "percentage")),
            int(config.get("fixed_handicap", 0)),
        )
        scratch_total = sum(game_scores)
        handicap_total = handicap * games_played
        standings_rows.append({
            "USBC ID": bowler["usbc_id"],
            "Bowler": bowler["bowler"],
            "Lane": int(bowler["starting_lane"]),
            "Games scored": games_played,
            "Scratch total": scratch_total,
            "Handicap total": handicap_total,
            "Total pinfall": scratch_total + handicap_total,
            "High_Scratch_Game": max(game_scores, default=0),
            **{f"Game {game}": game_scores[game - 1] for game in range(1, games_count + 1)},
        })
    standings = pd.DataFrame(standings_rows).sort_values(
        ["Total pinfall", "Scratch total"], ascending=False
    ).reset_index(drop=True)
    standings.insert(0, "Rank", range(1, len(standings) + 1))
    st.subheader("Live standings")
    st.dataframe(standings, hide_index=True, alt="Live scratch and handicap standings")
    if len(standings) >= 5:
        bubble = standings.iloc[4]
        st.info(f"5th-place cutline: {bubble['Bowler']} · {bubble['Total pinfall']} total pins")
    if completed_event:
        st.warning("Scoring is locked because this tournament is marked complete.")

    st.divider()
    st.subheader("Official standings and all-events")
    division_values = live_roster["division"].dropna().astype(str).unique().tolist()
    division_filter = st.selectbox("Standings division", ["All divisions"] + division_values, key="scoring_division_filter")
    visible_standings = standings if division_filter == "All divisions" else standings[
        standings["USBC ID"].isin(live_roster.loc[live_roster["division"].astype(str) == division_filter, "usbc_id"].astype(str))
    ]
    st.dataframe(visible_standings, hide_index=True, alt="Official ranked tournament standings")
    report_frame = visible_standings.rename(columns={
        "Lane": "Starting Lane",
        "Scratch total": "Scratch_Total",
        "Handicap total": "Total_HDCP",
        "Total pinfall": "Grand_Total",
    }).copy()
    if not report_frame.empty:
        pdf_bytes = export_standings_pdf(report_frame, config, st.session_state.get("td_name", "Tournament Desk"))
        st.download_button("Download official standings PDF", pdf_bytes, "Official_Standings.pdf", "application/pdf", icon=":material/picture_as_pdf:")

    all_events_source = live_roster.rename(columns={
        "usbc_id": "USBC ID",
        "bowler": "Bowler",
        "average": "Average",
        "team_name": "Team_Name",
        **{f"game_{game}": f"Game {game}" for game in range(1, 11)},
    })
    all_events = compile_all_events_leaderboard(all_events_source, config)
    if not all_events.empty:
        st.markdown("#### Multi-squad all-events leaderboard")
        st.dataframe(all_events, hide_index=False, alt="Cumulative all-events leaderboard")