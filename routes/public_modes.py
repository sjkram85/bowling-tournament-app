import html

import pandas as pd
import streamlit as st

from auth import verify_td_pin
from db_state import (
    check_in_bowler,
    fetch_active_tournament_state,
    fetch_kiosk_card,
    fetch_td_pins,
    log_audit_event,
    save_verified_game_scores,
)
from engine_support import (
    calculate_handicap,
    compile_standings,
    extract_scores_from_overhead_photo,
    generate_qr_image,
    get_bowler_lane_for_game,
    parse_active_pairs,
)


PUBLIC_MODES = {"kiosk", "checkin", "self_checkin", "bowler_portal", "scorer", "leaderboard"}


def _load_state(state_fetcher_fn=None):
    state = (state_fetcher_fn or fetch_active_tournament_state)()
    if state:
        st.session_state.tournament_config = state.get("config", {})
        st.session_state.roster = state.get("roster", pd.DataFrame())
        if not isinstance(st.session_state.roster, pd.DataFrame):
            st.session_state.roster = pd.DataFrame(st.session_state.roster)
        st.session_state.brackets = state.get("brackets", [])
        st.session_state.td_pins = state.get("td_pins", {})
    else:
        st.session_state.setdefault("tournament_config", {})
        st.session_state.setdefault("roster", pd.DataFrame())
        st.session_state.setdefault("brackets", [])
        st.session_state.setdefault("td_pins", {})
    return state


def _roster_frame(roster):
    frame = roster.copy() if isinstance(roster, pd.DataFrame) else pd.DataFrame(roster)
    aliases = {
        "usbc_id": "USBC ID",
        "bowler": "Bowler",
        "average": "Average",
        "starting_lane": "Starting Lane",
        "division": "Division",
        "team_name": "Team_Name",
        "paid": "Paid",
        "checked_in": "Checked_In",
        **{f"game_{game}": f"Game {game}" for game in range(1, 11)},
    }
    return frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns and value not in frame.columns})


def calc_over_under(row, active_game_cols):
    completed = [column for column in active_game_cols if int(pd.to_numeric(row.get(column, 0), errors="coerce") or 0) > 0]
    if not completed:
        return 0, "E"
    difference = sum(int(row.get(column, 0)) for column in completed) - (200 * len(completed))
    label = f"+{difference}" if difference > 0 else str(difference) if difference < 0 else "E"
    return difference, label


def get_standings_df(state_fetcher_fn=None):
    _load_state(state_fetcher_fn)
    roster = _roster_frame(st.session_state.get("roster", pd.DataFrame()))
    if roster.empty:
        return pd.DataFrame(), []

    config = st.session_state.get("tournament_config", {})
    games_count = max(1, min(10, int(config.get("games_count", 3))))
    active_games = [f"Game {game}" for game in range(1, games_count + 1)]
    for column in active_games:
        if column not in roster:
            roster[column] = 0
        roster[column] = pd.to_numeric(roster[column], errors="coerce").fillna(0).astype(int)
    if "Average" not in roster:
        roster["Average"] = 0
    standings = compile_standings(roster, config)
    if standings.empty:
        return standings, active_games

    standings["Total Scratch"] = standings["Scratch_Total"]
    standings["Total HDCP"] = standings["Grand_Total"]
    under_over = [calc_over_under(row, active_games) for _, row in standings.iterrows()]
    standings["+/- Value"] = [value for value, _ in under_over]
    standings["+/- 200"] = [label for _, label in under_over]
    return standings, active_games


def render_bowler_portal_view(state_fetcher_fn=None):
    _load_state(state_fetcher_fn)
    config = st.session_state.get("tournament_config", {})
    st.title(config.get("name", "Tournament standings"))
    st.caption(f"Live standings · {config.get('center', '')}")
    standings, active_games = get_standings_df(state_fetcher_fn)
    if standings.empty:
        st.info("Standings will appear once tournament play begins.")
        return

    sort_mode = st.segmented_control(
        "Leaderboard sort", ["Handicap standings", "Scratch standings"],
        default="Handicap standings", key="public_sort_mode",
    )
    sort_column = "Total HDCP" if sort_mode != "Scratch standings" else "Total Scratch"
    ordered = standings.sort_values([sort_column, "Total Scratch"], ascending=False).reset_index(drop=True)
    ordered.insert(0, "Rank", range(1, len(ordered) + 1))

    bowler_names = ordered["Bowler"].fillna("").astype(str).tolist()
    pinned = st.multiselect("Track bowler(s)", bowler_names, key="public_tracked_bowlers")
    if pinned:
        selected = ordered[ordered["Bowler"].isin(pinned)]
        scratch = int(selected["Total Scratch"].sum())
        handicap_total = int(selected["Total HDCP"].sum())
        par_value = int(selected["+/- Value"].sum())
        st.metric("Tracked team", f"{scratch} scratch · {handicap_total} handicap", delta=f"{par_value:+d} vs 200/game")

    if len(ordered) >= 5:
        cut = ordered.iloc[4]
        st.warning(f"5th-place stepladder cutline: {cut['Bowler']} · {int(cut[sort_column])} pins")
    lane_column = "Starting Lane" if "Starting Lane" in ordered else "Lane"
    columns = ["Rank", "Bowler", lane_column] + active_games + ["+/- 200", "Total Scratch", "Total HDCP"]
    st.dataframe(ordered[[column for column in columns if column in ordered]], hide_index=True, alt="Live tournament standings")

    selected_bowler = st.selectbox("Personal tracker", ["Select a bowler"] + bowler_names, key="public_personal_tracker")
    if selected_bowler != "Select a bowler":
        personal = ordered[ordered["Bowler"] == selected_bowler].iloc[0]
        st.subheader(selected_bowler)
        current_rank = int(personal["Rank"])
        cut_gap = int(personal[sort_column] - ordered.iloc[4][sort_column]) if len(ordered) >= 5 else None
        metrics = st.columns(4)
        metrics[0].metric("Rank", f"#{current_rank}")
        metrics[1].metric("Scratch", int(personal["Total Scratch"]))
        metrics[2].metric("Handicap total", int(personal["Total HDCP"]))
        if cut_gap is not None:
            metrics[3].metric("Cutline margin", f"{cut_gap:+d}")
        movement_rule = str(config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)"))
        starting_lane = int(personal.get("Starting Lane", 1))
        max_lanes = int(config.get("lanes_count", 40))
        movement = []
        for game in range(1, len(active_games) + 1):
            lane = get_bowler_lane_for_game(starting_lane, game, movement_rule, max_lanes)
            partner = lane + 1 if lane % 2 else lane - 1
            movement.append({"Game": game, "Pair": f"{min(lane, partner)}-{max(lane, partner)}", "Lane": lane})
        st.dataframe(pd.DataFrame(movement), hide_index=True, alt="Personal lane movement schedule")


def render_tv_kiosk_display(state_fetcher_fn=None):
    render_tv_kiosk_fragment(state_fetcher_fn)


@st.fragment(run_every="10s")
def render_tv_kiosk_fragment(state_fetcher_fn=None):
    _load_state(state_fetcher_fn)
    config = st.session_state.get("tournament_config", {})
    standings, active_games = get_standings_df(state_fetcher_fn)
    st.title(config.get("name", "Tournament leaderboard"))
    st.caption(f"{config.get('center', '')} · Live concourse standings · refreshes every 10 seconds")
    if standings.empty:
        st.info("Leaderboard active. Awaiting scores from the tournament desk.")
        return

    ordered = standings.sort_values(["Total HDCP", "Total Scratch"], ascending=False).reset_index(drop=True)
    ordered.insert(0, "Rank", range(1, len(ordered) + 1))
    metric_cols = st.columns(4)
    metric_cols[0].metric("Leader", int(ordered.iloc[0]["Total HDCP"]))
    metric_cols[1].metric("5th-place cut", int(ordered.iloc[4]["Total HDCP"]) if len(ordered) >= 5 else 0)
    metric_cols[2].metric("High scratch game", int(ordered["High_Scratch_Game"].max()))
    metric_cols[3].metric("Field", len(ordered))
    if len(ordered) >= 5:
        cut = ordered.iloc[4]
        st.warning(f"Stepladder cutline · {cut['Bowler']} · {int(cut['Total HDCP'])}")
    lane_column = "Starting Lane" if "Starting Lane" in ordered else "Lane"
    columns = ["Rank", "Bowler", lane_column, "Team_Name"] + active_games + ["Total Scratch", "Total HDCP"]
    st.dataframe(ordered[[column for column in columns if column in ordered]], hide_index=True, alt="Concourse tournament leaderboard")


def render_customer_kiosk(state_fetcher_fn=None):
    render_customer_kiosk_fragment(state_fetcher_fn)


@st.fragment(run_every="8s")
def render_customer_kiosk_fragment(state_fetcher_fn=None):
    state = _load_state(state_fetcher_fn)
    card = fetch_kiosk_card()
    config = st.session_state.get("tournament_config", {})
    roster = _roster_frame(st.session_state.get("roster", pd.DataFrame()))
    st.title("Tournament check-in")
    if card:
        bowler_name = html.escape(str(card.get("name", "Bowler")))
        usbc_id = str(card.get("usbc_id", ""))
        lane = int(card.get("lane", 1))
        pair = html.escape(str(card.get("pair_display", "")))
        base_url = str(st.secrets.get("APP_URL", "http://localhost:8501")).rstrip("/")
        qr = generate_qr_image(f"{base_url}/?mode=checkin&usbc_id={usbc_id}")
        st.subheader(bowler_name)
        st.write(f"USBC ID: {usbc_id} · Average: {card.get('avg', 200)}")
        st.metric("Starting pair", pair, f"Lane {lane}")
        st.image(qr, caption="Scan to check in", width=220)
    else:
        checked = int(roster.get("Checked_In", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not roster.empty else 0
        st.subheader(config.get("name", "Tournament"))
        st.caption(config.get("center", ""))
        st.metric("Checked in", f"{checked} / {len(roster)}")
        st.info("Please see the tournament desk for your lane assignment.")


def _pair_label(starting_lane):
    lane = int(starting_lane)
    partner = lane + 1 if lane % 2 else lane - 1
    return f"Lanes {min(lane, partner)} & {max(lane, partner)}"


def render_id_checkin(usbc_id, state_fetcher_fn=None):
    _load_state(state_fetcher_fn)
    outcome = check_in_bowler(usbc_id)
    if outcome["status"] == "not_found":
        st.error("No active entry matches that USBC ID. Please see the tournament desk.")
        return
    if outcome["status"] == "invalid":
        st.error("A USBC ID is required for check-in.")
        return
    if outcome["status"] == "payment_required":
        bowler = outcome["bowler"]
        st.warning(f"Payment is due for {bowler['bowler']}. Please visit the tournament desk before bowling.")
        return
    bowler = outcome
    st.success(f"Checked in: {bowler['bowler']}")
    st.metric("Starting pair", _pair_label(bowler["starting_lane"]), f"Lane {bowler['starting_lane']}")
    st.write(f"USBC ID: {bowler['usbc_id']} · Entering average: {bowler['average']}")


def render_self_checkin(state_fetcher_fn=None):
    _load_state(state_fetcher_fn)
    roster = _roster_frame(st.session_state.get("roster", pd.DataFrame()))
    config = st.session_state.get("tournament_config", {})
    st.title("Express entrance check-in")
    st.caption(f"{config.get('name', 'Tournament')} · {config.get('center', '')}")
    if roster.empty:
        st.info("The desk is preparing the roster. Please see a tournament official.")
        return

    selector = roster[["Bowler", "USBC ID"]].dropna(subset=["Bowler"]).drop_duplicates()
    selector = selector.sort_values("Bowler")
    selected_id = st.selectbox(
        "Select your name",
        [""] + selector["USBC ID"].astype(str).tolist(),
        format_func=lambda identifier: "Choose a bowler" if not identifier else selector.loc[selector["USBC ID"].astype(str) == identifier, "Bowler"].iloc[0],
        key="self_checkin_bowler",
    )
    wants_side_action = st.checkbox("I want to enter side brackets or side pots")
    if st.button("Complete check-in", type="primary", disabled=not selected_id):
        result = check_in_bowler(selected_id)
        if result["status"] == "payment_required":
            st.error("Payment is due. Please visit the tournament desk; no check-in was recorded.")
        elif result["status"] in {"checked_in", "already_checked_in"}:
            st.success(f"Checked in on {_pair_label(result['starting_lane'])} · lead lane {result['starting_lane']}.")
            if wants_side_action:
                st.info("Your entry is checked in. Side-action entry and payment are handled by the desk.")
            else:
                base_url = str(st.secrets.get("APP_URL", "http://localhost:8501")).rstrip("/")
                st.link_button("Open live bowler portal", f"{base_url}/?mode=bowler_portal")
        else:
            st.error("Unable to check in; please see the tournament desk.")


def render_mobile_scorer(state_fetcher_fn=None, ai_client=None):
    _load_state(state_fetcher_fn)
    config = st.session_state.get("tournament_config", {})
    roster = _roster_frame(st.session_state.get("roster", pd.DataFrame()))
    st.title("Roving floor scorer")
    st.caption(f"{config.get('name', 'Tournament')} · PIN-verified game sign-off")
    st.session_state.setdefault("mobile_scorer_td", "")

    if not st.session_state.mobile_scorer_td:
        with st.form("mobile_scorer_auth"):
            name = st.text_input("Floor official name").strip()
            pin = st.text_input("PIN (4–6 digits)", type="password", max_chars=6).strip()
            submitted = st.form_submit_button("Authenticate scorer", type="primary")
        if submitted:
            if not name or not pin.isdigit() or not 4 <= len(pin) <= 6:
                st.error("Enter your name and a 4–6 digit PIN.")
            elif fetch_td_pins().get(name):
                if verify_td_pin(name, pin):
                    st.session_state.mobile_scorer_td = name
                    st.rerun()
                st.error("PIN does not match this floor official.")
            else:
                st.error("No PIN is registered for this official. Ask the authenticated tournament desk to enroll you.")
        return

    official = st.session_state.mobile_scorer_td
    st.caption(f"Authenticated as {official}")
    if st.button("Sign out scorer", key="mobile_scorer_signout"):
        st.session_state.mobile_scorer_td = ""
        st.rerun()
    if roster.empty:
        st.info("No bowlers have been assigned to lanes.")
        return

    max_lanes = int(config.get("lanes_count", 40))
    pairs = parse_active_pairs(config.get("lanes_range", f"1-{max_lanes}"), max_lanes=max_lanes)
    if not pairs:
        st.error("No valid lane pairs are configured.")
        return
    game_count = max(1, min(10, int(config.get("games_count", 3))))
    pair_col, game_col = st.columns(2)
    selected_pair = pair_col.selectbox("Active pair", pairs, format_func=lambda pair: f"Lanes {pair[0]} & {pair[1]}")
    game_number = game_col.selectbox("Game", range(1, game_count + 1))

    rotation_rule = str(config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)"))
    roster["Starting Lane"] = pd.to_numeric(roster.get("Starting Lane", 1), errors="coerce").fillna(1).astype(int)
    roster["Active Game Lane"] = roster["Starting Lane"].apply(
        lambda lane: get_bowler_lane_for_game(int(lane), game_number, rotation_rule, max_lanes)
    )
    on_pair = roster[roster["Active Game Lane"].isin(selected_pair)].copy()
    if on_pair.empty:
        st.warning("No bowlers are assigned to this pair for the selected game.")
        return

    previous_verifier = on_pair.iloc[0].get(f"g{game_number}_verified_by", "")
    if previous_verifier:
        st.info(f"This game was verified by {previous_verifier} at {on_pair.iloc[0].get(f'g{game_number}_verified_at', '')}.")

    with st.expander("Read overhead or recap photo with AI"):
        camera = st.camera_input("Capture scoring monitor", key=f"scorer_camera_{selected_pair[0]}_{game_number}")
        if camera and st.button("Extract scores from image", key=f"scorer_ocr_{selected_pair[0]}_{game_number}"):
            if not ai_client:
                st.error("AI score recognition is not configured.")
            else:
                extracted = extract_scores_from_overhead_photo(
                    ai_client,
                    camera.getvalue(),
                    on_pair["Bowler"].astype(str).tolist(),
                    game_number,
                )
                if extracted:
                    for bowler_id, row in on_pair.set_index("Bowler").iterrows():
                        if bowler_id in extracted:
                            st.session_state[f"scorer_{game_number}_{row['USBC ID']}"] = int(extracted[bowler_id])
                    st.success(f"Recognized {len(extracted)} score(s). Review before signing.")
                else:
                    st.warning("No scores could be read; enter scores manually.")

    with st.form(f"mobile_game_scores_{selected_pair[0]}_{game_number}"):
        score_map = {}
        for _, bowler in on_pair.iterrows():
            identifier = str(bowler["USBC ID"])
            score_map[identifier] = st.number_input(
                f"Lane {int(bowler['Active Game Lane'])}: {bowler['Bowler']} · avg {int(bowler.get('Average', 200))}",
                min_value=0,
                max_value=300,
                value=int(st.session_state.get(f"scorer_{game_number}_{identifier}", bowler.get(f"Game {game_number}", 0)) or 0),
                key=f"scorer_score_{game_number}_{identifier}",
            )
        pin = st.text_input("Re-enter PIN to sign and lock scores", type="password", max_chars=6, key=f"scorer_sign_pin_{selected_pair[0]}_{game_number}").strip()
        submit = st.form_submit_button("Sign and save scores", type="primary")

    if submit:
        if not verify_td_pin(official, pin):
            st.error("PIN verification failed; scores were not saved.")
            return
        try:
            save_verified_game_scores(game_number, score_map, official)
        except ValueError as error:
            st.error(str(error))
            return
        log_audit_event("MOBILE_GAME_VERIFIED", f"{official} verified Game {game_number} on lanes {selected_pair[0]}-{selected_pair[1]}.")
        st.success("Scores were signed and saved.")
        st.rerun()


def render_public_leaderboard(state_fetcher_fn=None):
    render_tv_kiosk_display(state_fetcher_fn)


def handle_public_modes(mode, state_fetcher_fn=None, ai_client=None):
    selected_mode = str(mode or "").strip().casefold()
    if selected_mode not in PUBLIC_MODES:
        return False
    if selected_mode == "kiosk":
        render_customer_kiosk(state_fetcher_fn)
    elif selected_mode == "checkin":
        render_id_checkin(st.query_params.get("usbc_id", ""), state_fetcher_fn)
    elif selected_mode == "self_checkin":
        render_self_checkin(state_fetcher_fn)
    elif selected_mode == "bowler_portal":
        render_bowler_portal_view(state_fetcher_fn)
    elif selected_mode == "scorer":
        render_mobile_scorer(state_fetcher_fn, ai_client)
    else:
        render_public_leaderboard(state_fetcher_fn)
    return True
