# views/intake_gateway.py
import streamlit as st
import io
import json
import pandas as pd
from auth import hash_secret, register_td_pin
from config_profiles import CHUSBC_PRESET_PROFILES, CENTER_PROFILES
from db_state import (
    clear_kiosk_card,
    fetch_active_tournament_state,
    fetch_archives_df,
    fetch_kiosk_card,
    fetch_master_book_df,
    lookup_master_book_record,
    log_audit_event,
    upsert_master_book_df,
    write_active_tournament_state,
    write_kiosk_card,
)
from engine_support import (
    auto_assign_lanes,
    calculate_handicap,
    export_lane_assignments_pdf,
    generate_qr_image,
    parse_active_pairs,
)
from prism_ai import get_ai_client, parse_roster_text_with_gemini
from scoring import render_live_checkin_counters_fragment


def _safe_int(value, default=0):
    try:
        return default if value is None or pd.isna(value) else int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        return default if value is None or pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value):
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "1", "y"}
    return bool(value)


def _is_youth_division(value):
    return "youth" in str(value).casefold() or "scholastic" in str(value).casefold()


def _merge_roster_import(current_roster, imported, config):
    frame = imported.copy() if isinstance(imported, pd.DataFrame) else pd.DataFrame(imported)
    frame.columns = [str(column).strip() for column in frame.columns]
    current = current_roster.copy() if isinstance(current_roster, pd.DataFrame) else pd.DataFrame(current_roster)
    if "Bowler" not in frame.columns:
        raise ValueError("Roster data must contain a Bowler column.")

    existing_ids = set(current.get("USBC ID", pd.Series(dtype=str)).dropna().astype(str))
    pairs = parse_active_pairs(config.get("lanes_range", "1-40"), max_lanes=60)
    lanes = [lane for pair in pairs for lane in pair] or list(range(1, 41))
    records = []
    rejected = 0
    for row_number, (_, row) in enumerate(frame.iterrows(), start=1):
        name_value = row.get("Bowler", "")
        name = "" if pd.isna(name_value) else str(name_value).strip()
        id_value = row.get("USBC ID", "")
        identifier = "" if pd.isna(id_value) else str(id_value).strip()
        if not identifier or identifier.casefold() == "tbd":
            identifier = f"LOCAL-IMPORT-{len(existing_ids) + row_number}"
        if not name or identifier in existing_ids:
            rejected += 1
            continue

        status_value = row.get("Entry Status", "")
        if pd.isna(status_value) or not str(status_value).strip():
            status_value = "Paid" if _as_bool(row.get("Paid", False)) else "Unpaid"
        status = str(status_value).strip().title()
        if status not in {"Paid", "Unpaid", "Comp"}:
            status = "Unpaid"
        division_value = row.get("Division", config.get("division", "Open"))
        division = config.get("division", "Open") if pd.isna(division_value) else str(division_value).strip()
        side_value = row.get("Side Pot Games", "")
        if isinstance(side_value, (list, tuple)):
            side_games = [_safe_int(value) for value in side_value]
        elif side_value is None or pd.isna(side_value):
            side_games = []
        else:
            side_games = [_safe_int(value) for value in str(side_value).split(",") if value.strip()]
        member_meta = row.get("Member Metadata", {})
        if not isinstance(member_meta, dict):
            member_meta = {}
        record = {
            "USBC ID": identifier,
            "Bowler": name,
            "Average": _safe_int(row.get("Average", 200), 200),
            "Starting Lane": _safe_int(row.get("Starting Lane", lanes[(len(current) + len(records)) % len(lanes)]), 1),
            "Division": division,
            "Team_Name": "Singles" if pd.isna(row.get("Team_Name", "Singles")) else str(row.get("Team_Name", "Singles")),
            "Paid": status == "Paid",
            "Checked_In": _as_bool(row.get("Checked_In", False)),
            "Entry Status": status,
            "Entry Fee": 0.0 if status == "Comp" else _safe_float(row.get("Entry Fee", config.get("entry_fee", 0)), float(config.get("entry_fee", 0))),
            "USBC Verified": _as_bool(row.get("USBC Verified", False)),
            "Member Metadata": member_meta,
            "Side Pot Games": [] if _is_youth_division(division) and not _as_bool(member_meta.get("rule400_scholarship_side_pot")) else side_games,
        }
        for game in range(1, 11):
            record[f"Game {game}"] = _safe_int(row.get(f"Game {game}", 0))
        records.append(record)
        existing_ids.add(identifier)
    return pd.concat([current, pd.DataFrame(records)], ignore_index=True), len(records), rejected


def evaluate_rule319(member_metadata, submitted_average, division, average_adjusted=False, prior_rerates_reported=False):
    flags = []
    youth = _is_youth_division(division)
    if youth or str(division).casefold() == "scratch":
        return flags

    prior_average = member_metadata.get("prior_season_average")
    current_average = member_metadata.get("current_average")
    current_games = int(member_metadata.get("current_average_games", 0) or 0)
    if prior_average is not None:
        required_average = float(prior_average)
        if current_average is not None and current_games >= 21 and float(current_average) >= required_average + 10:
            required_average = float(current_average)
            flags.append(f"Rule 319a: use current {current_games}-game average ({required_average:g}); it is at least 10 pins above prior season.")
        if float(submitted_average) < required_average:
            flags.append(f"Rule 319a: submitted average is below the review average of {required_average:g}; possible classification/handicap and disqualification issue.")
    elif not member_metadata.get("assigned_average_confirmed"):
        flags.append("Rule 319b: no acceptable average recorded; confirm scratch entry or a tournament-assigned average before participation.")

    if member_metadata.get("prior_rerates") and not prior_rerates_reported:
        flags.append("Rule 319c: prior assigned average adjustments/rerates are recorded but not marked as reported.")

    tournament_average = member_metadata.get("tournament_average")
    tournament_games = int(member_metadata.get("tournament_average_games", 0) or 0)
    if tournament_average is not None and tournament_games >= 21 and float(tournament_average) >= float(submitted_average) + 15 and not average_adjusted:
        flags.append(f"Rule 319e: current {tournament_games}-game tournament average is 15+ pins above entry average; review required.")
    return flags


def _save_roster(roster, config, event_name):
    st.session_state.roster = roster
    write_active_tournament_state(config, roster, st.session_state.brackets)
    log_audit_event("ROSTER_UPDATED", event_name)


def _apply_master_book_lookup():
    identifier = str(st.session_state.get("master_lookup_id", "")).strip()
    record = lookup_master_book_record(identifier)
    st.session_state.master_book_lookup_result = record
    if record:
        st.session_state.entry_usbc_id = record["USBC ID"]
        st.session_state.entry_bowler_name = record["Bowler"]
        st.session_state.entry_average = int(record["Average"])
        st.session_state.entry_prior_average = int(record["Average"])
        st.session_state.entry_current_average = int(record["Average"])
        st.session_state.entry_current_games = int(record.get("Games", 0))
        st.session_state.entry_usbc_verified = True


def render_intake_gateway():
    config = st.session_state.tournament_config
    st.markdown(
        '<div class="brand-banner"><h1>Cecil-Harford USBC · Tournament Intake</h1>'
        '<p>Event setup, verified check-in, and live roster operations</p></div>',
        unsafe_allow_html=True,
    )
    roster_snapshot = st.session_state.get("roster", pd.DataFrame())
    roster_snapshot = roster_snapshot if isinstance(roster_snapshot, pd.DataFrame) else pd.DataFrame(roster_snapshot)
    total_bowlers = len(roster_snapshot)
    paid_count = int(roster_snapshot.get("Paid", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if total_bowlers else 0
    checked_count = int(roster_snapshot.get("Checked_In", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if total_bowlers else 0
    event_card, checkin_card, roster_card = st.columns(3)
    with event_card, st.container(border=True):
        st.markdown("#### Association Event Setup")
        st.metric("Active event", config.get("name", "Tournament"))
        st.caption(f"{config.get('center', 'Center not selected')} · {config.get('games_count', 3)} games · ${float(config.get('entry_fee', 0)):,.2f} entry")
    with checkin_card, st.container(border=True):
        st.markdown("#### Manual Check-In")
        st.metric("Checked in", f"{checked_count} / {total_bowlers}", delta=f"{paid_count} paid")
        st.caption("Use the local Master Book ID lookup below to prefill member details.")
    with roster_card, st.container(border=True):
        st.markdown("#### Live Roster & CSV")
        st.metric("Bowlers", total_bowlers)
        st.caption(f"{total_bowlers - checked_count} awaiting check-in · {total_bowlers - paid_count} awaiting payment")

    with st.container(border=True):
        st.subheader("Event setup")
        preset_col, center_col, games_col = st.columns(3)
        selected_preset = preset_col.selectbox("CHUSBC preset", list(CHUSBC_PRESET_PROFILES))
        center_key = center_col.selectbox("Host center", list(CENTER_PROFILES))
        games_count = games_col.number_input("Games", min_value=1, max_value=10, value=int(config.get("games_count", 3)))
        handicap_col, percentage_col, fee_col = st.columns(3)
        hdcp_base = handicap_col.number_input("Handicap base", min_value=0, max_value=300, value=int(config.get("hdcp_base", 220)))
        hdcp_pct = percentage_col.number_input("Handicap percentage", min_value=0.0, max_value=1.0, value=float(config.get("hdcp_pct", 0.90)), step=0.05)
        entry_fee = fee_col.number_input("Standard entry fee", min_value=0.0, value=float(config.get("entry_fee", 50.0)), step=5.0)
        formula_col, fixed_col = st.columns(2)
        handicap_method = formula_col.selectbox(
            "Handicap formula",
            ["percentage", "fixed", "scratch"],
            format_func=lambda value: {
                "percentage": "Percentage of base difference",
                "fixed": "Fixed pins per game",
                "scratch": "Scratch (no handicap)",
            }[value],
            index=["percentage", "fixed", "scratch"].index(config.get("handicap_method", "percentage")),
        )
        fixed_handicap = fixed_col.number_input(
            "Fixed pins per game", min_value=0, max_value=300,
            value=int(config.get("fixed_handicap", 0)),
        )
        movement_options = [
            "Stay on Pair (No Movement)",
            "Move Right 1 Pair (+2 Lanes)",
            "Move Right 2 Pairs (+4 Lanes)",
            "Move Right 3 Pairs (+6 Lanes)",
            "Move Left 1 Pair (-2 Lanes)",
            "Move Left 2 Pairs (-4 Lanes)",
            "Move Left 3 Pairs (-6 Lanes)",
        ]
        movement_rule = st.selectbox(
            "Lane rotation rule",
            movement_options,
            index=movement_options.index(config.get("movement_rule", movement_options[1]))
            if config.get("movement_rule", movement_options[1]) in movement_options else 1,
        )
        if st.button("Apply selected preset"):
            config.update(CHUSBC_PRESET_PROFILES[selected_preset])
            config["center"] = CENTER_PROFILES[center_key]["name"]
            config["games_count"] = int(games_count)
            config["hdcp_base"] = int(hdcp_base)
            config["hdcp_pct"] = float(hdcp_pct)
            config["entry_fee"] = float(entry_fee)
            config["handicap_method"] = handicap_method
            config["fixed_handicap"] = int(fixed_handicap)
            config["movement_rule"] = movement_rule
            st.session_state.tournament_config = config
            write_active_tournament_state(config, st.session_state.roster, st.session_state.brackets)
            log_audit_event("TOURNAMENT_CONFIGURED", f"Applied {selected_preset}.")
            st.rerun()

        with st.expander("Create custom event"):
            with st.form("custom_event_form"):
                custom_name = st.text_input("Event name", "New CHUSBC Tournament")
                custom_center = st.selectbox("Center", list(CENTER_PROFILES), key="custom_event_center")
                custom_division = st.selectbox("Primary division", ["Scratch", "Handicap", "Senior", "Youth"])
                custom_games = st.number_input("Games per bowler", min_value=1, max_value=10, value=3)
                sanction_number = st.text_input("USBC sanction / certificate number")
                submitted = st.form_submit_button("Launch custom event", type="primary")
            if submitted:
                config.update({
                    "name": custom_name.strip(),
                    "center": CENTER_PROFILES[custom_center]["name"],
                    "division": custom_division,
                    "games_count": int(custom_games),
                    "sanction_number": sanction_number.strip(),
                    "lanes_range": config.get("lanes_range", "1-40"),
                    "hdcp_base": int(hdcp_base),
                    "hdcp_pct": float(hdcp_pct),
                    "handicap_method": handicap_method,
                    "fixed_handicap": int(fixed_handicap),
                    "movement_rule": movement_rule,
                    "entry_fee": float(entry_fee),
                    "status": "Active",
                })
                st.session_state.tournament_config = config
                write_active_tournament_state(config, st.session_state.roster, st.session_state.brackets)
                log_audit_event("CUSTOM_EVENT_LAUNCHED", custom_name.strip())
                st.rerun()

    with st.expander("Resume or clone a tournament"):
        active_state = fetch_active_tournament_state()
        resume_col, archive_col = st.columns(2)
        with resume_col:
            if active_state and active_state.get("config"):
                active_config = active_state["config"]
                st.markdown(f"**Active event:** {active_config.get('name', 'Tournament')}")
                st.caption(f"{len(active_state.get('roster', []))} roster entries in SQLite")
                if st.button("Resume active event", type="primary", key="resume_active_event"):
                    st.session_state.tournament_config = active_config
                    st.session_state.roster = active_state["roster"]
                    st.session_state.brackets = active_state.get("brackets", [])
                    st.session_state.td_pins = active_state.get("td_pins", {})
                    log_audit_event("ACTIVE_EVENT_RESUMED", active_config.get("name", "Tournament"))
                    st.rerun()
            else:
                st.info("No active event snapshot is available.")
        with archive_col:
            archives = fetch_archives_df()
            if archives.empty:
                st.info("No archived events are available to clone.")
            else:
                archive_names = archives["tournament_name"].astype(str).tolist()
                archived_name = st.selectbox("Archived event template", archive_names, key="archive_template_select")
                if st.button("Clone event settings", key="clone_archived_event"):
                    archived = archives[archives["tournament_name"].astype(str) == archived_name].iloc[0]
                    config.update({
                        "name": f"{archived_name} (Copy)",
                        "center": str(archived.get("center", config.get("center", ""))),
                        "division": str(archived.get("division", "Adult Open")),
                        "lanes_count": int(config.get("lanes_count", 40)),
                        "lanes_range": str(config.get("lanes_range", "1-40")),
                        "games_count": int(config.get("games_count", 3)),
                        "hdcp_base": int(config.get("hdcp_base", 220)),
                        "hdcp_pct": float(config.get("hdcp_pct", 0.90)),
                        "entry_fee": float(config.get("entry_fee", 50.0)),
                        "movement_rule": str(config.get("movement_rule", "Move Right 1 Pair (+2 Lanes)")),
                        "status": "Active",
                        "champion": "",
                    })
                    st.session_state.tournament_config = config
                    st.session_state.roster = pd.DataFrame()
                    st.session_state.brackets = []
                    write_active_tournament_state(config, st.session_state.roster, st.session_state.brackets)
                    log_audit_event("ARCHIVED_EVENT_CLONED", archived_name)
                    st.rerun()

    st.subheader("Bowler entry")
    st.link_button("Open USBC membership resources", "https://bowl.com/", icon=":material/open_in_new:")
    lookup_col, lookup_button_col = st.columns([3, 1])
    lookup_col.text_input("USBC ID lookup", key="master_lookup_id", placeholder="Enter an ID from the Association Master Book")
    lookup_button_col.button("Lookup", on_click=_apply_master_book_lookup, key="lookup_master_book")
    if "master_book_lookup_result" in st.session_state:
        lookup_result = st.session_state.master_book_lookup_result
        if lookup_result:
            st.success(f"Verified against the local Association Master Book: {lookup_result['Bowler']} · avg {lookup_result['Average']}.")
        elif st.session_state.get("master_lookup_id", "").strip():
            st.warning("No matching ID was found in the locally imported Master Book. Confirm it manually before entry.")
    with st.form("bowler_entry_form"):
        name_col, id_col, division_col = st.columns(3)
        for key, default in [
            ("entry_bowler_name", ""), ("entry_usbc_id", ""), ("entry_average", 200),
            ("entry_prior_average", 0), ("entry_current_average", 0), ("entry_current_games", 0),
            ("entry_usbc_verified", False),
        ]:
            st.session_state.setdefault(key, default)
        bowler_name = name_col.text_input("Bowler name", key="entry_bowler_name")
        usbc_id = id_col.text_input("USBC ID", key="entry_usbc_id")
        division = division_col.selectbox("Division", ["Scratch", "Handicap", "Senior", "Youth"], key="entry_division")
        avg_col, lane_col, team_col = st.columns(3)
        average = avg_col.number_input("Entering average", min_value=0, max_value=300, key="entry_average")
        starting_lane = lane_col.number_input("Starting lane", min_value=1, max_value=60, value=1)
        team_name = team_col.text_input("Team / group", "Singles")
        fee_col, status_col, verified_col = st.columns(3)
        entry_status = status_col.selectbox("Entry fee status", ["Paid", "Unpaid", "Comp"])
        bowler_fee = fee_col.number_input("Entry fee", min_value=0.0, value=float(config.get("entry_fee", 50.0)), step=5.0)
        usbc_verified = verified_col.checkbox("Staff verified ID in USBC lookup", key="entry_usbc_verified")
        prior_col, current_col, current_games_col = st.columns(3)
        prior_average_input = prior_col.number_input("Prior-season highest average (0 if none)", min_value=0, max_value=300, key="entry_prior_average")
        current_average_input = current_col.number_input("Current league average (0 if none)", min_value=0, max_value=300, key="entry_current_average")
        current_games_input = current_games_col.number_input("Games in current average", min_value=0, max_value=300, key="entry_current_games")
        tavg_col, tgames_col, rerate_col = st.columns(3)
        tournament_average_input = tavg_col.number_input("Tournament average (0 if none)", min_value=0, max_value=300, value=0)
        tournament_games_input = tgames_col.number_input("Tournament games", min_value=0, max_value=1000, value=0)
        average_adjusted = rerate_col.checkbox("Entering average has been adjusted")
        assigned_average_confirmed = st.checkbox("TD confirmed an assigned minimum average under 319b")
        prior_rerate_text = st.text_area("Prior assigned rerates (one per line: event | date | average)")
        prior_rerates_reported = st.checkbox("Bowler reported all prior rerates to tournament management")
        checked_in = st.checkbox("Checked in now")
        scholarship_side_pot = st.checkbox(
            "Youth side competition returns 100% of entries as scholarships",
            disabled=not _is_youth_division(division),
            help="Rule 400 allows youth side competitions/brackets only when all entries are returned as scholarships and awards otherwise comply.",
        )
        side_pot_games = st.multiselect(
            "Side-pot games", range(1, int(config.get("games_count", 3)) + 1),
            help="Youth participation requires the Rule 400 scholarship-only confirmation above; cash pots remain adult-only.",
        )
        add_bowler = st.form_submit_button("Add bowler", type="primary")

    if add_bowler:
        roster = st.session_state.roster.copy() if isinstance(st.session_state.roster, pd.DataFrame) else pd.DataFrame(st.session_state.roster)
        existing_ids = roster.get("USBC ID", pd.Series(dtype=str)).astype(str).tolist()
        if not bowler_name.strip() or not usbc_id.strip():
            st.error("Bowler name and USBC ID are required.")
        elif usbc_id.strip() in existing_ids:
            st.error("That USBC ID is already in the active roster.")
        elif _is_youth_division(division) and side_pot_games and not scholarship_side_pot:
            st.error("Rule 400 requires all youth side-competition entries to be returned as scholarships.")
        else:
            rerates = [line.strip() for line in prior_rerate_text.splitlines() if line.strip()]
            metadata = {
                "prior_season_average": int(prior_average_input) or None,
                "current_average": int(current_average_input) or None,
                "current_average_games": int(current_games_input),
                "tournament_average": int(tournament_average_input) or None,
                "tournament_average_games": int(tournament_games_input),
                "prior_rerates": rerates,
                "prior_rerates_reported": bool(prior_rerates_reported),
                "assigned_average_confirmed": bool(assigned_average_confirmed),
                "average_adjusted": bool(average_adjusted),
                "rule400_scholarship_side_pot": bool(scholarship_side_pot),
            }
            compliance_flags = evaluate_rule319(
                metadata, average, division, average_adjusted, prior_rerates_reported,
            )
            metadata["rule319_flags"] = compliance_flags
            status = "Comp" if entry_status == "Comp" else entry_status
            bowler = {
                "USBC ID": usbc_id.strip(),
                "Bowler": bowler_name.strip(),
                "Average": int(average),
                "Starting Lane": int(starting_lane),
                "Division": division,
                "Team_Name": team_name.strip() or "Singles",
                "Paid": status == "Paid",
                "Checked_In": bool(checked_in),
                "Entry Status": status,
                "Entry Fee": 0.0 if status == "Comp" else float(bowler_fee),
                "USBC Verified": bool(usbc_verified),
                "Member Metadata": metadata,
                "Side Pot Games": list(side_pot_games) if not _is_youth_division(division) or scholarship_side_pot else [],
            }
            roster = pd.concat([roster, pd.DataFrame([bowler])], ignore_index=True)
            _save_roster(roster, config, f"Added {bowler_name.strip()} ({usbc_id.strip()}).")
            if compliance_flags:
                for flag in compliance_flags:
                    st.warning(flag)
            st.success(f"Added {bowler_name.strip()}.")
            st.rerun()

    st.subheader("Bulk CSV import")
    upload = st.file_uploader("CSV roster", type=["csv"], key="intake_roster_csv")
    if upload is not None:
        try:
            imported = pd.read_csv(upload)
            imported.columns = [str(column).strip() for column in imported.columns]
            if "Bowler" not in imported.columns:
                st.error("CSV must include a Bowler column. USBC ID and Average are strongly recommended.")
            else:
                st.dataframe(imported.head(20), hide_index=True, alt="Roster import preview")
                if st.button("Import valid roster rows", key="import_csv_roster"):
                    roster = st.session_state.roster.copy() if isinstance(st.session_state.roster, pd.DataFrame) else pd.DataFrame(st.session_state.roster)
                    try:
                        merged, imported_count, rejected = _merge_roster_import(roster, imported, config)
                    except ValueError as error:
                        st.error(str(error))
                        merged, imported_count, rejected = roster, 0, 0
                    if imported_count:
                        _save_roster(merged, config, f"Imported {imported_count} CSV bowlers; rejected {rejected} rows.")
                        st.success(f"Imported {imported_count} bowlers; rejected {rejected} invalid or duplicate rows.")
                        st.rerun()
                    else:
                        st.warning("No valid new rows were found.")
        except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as error:
            st.error(f"Could not read roster CSV: {error}")

    st.subheader("Active roster and Rule 319 review")
    roster = st.session_state.roster.copy() if isinstance(st.session_state.roster, pd.DataFrame) else pd.DataFrame(st.session_state.roster)
    if roster.empty:
        st.info("No bowlers have been entered yet.")
        return
    roster["Handicap"] = roster["Average"].apply(
        lambda value: calculate_handicap(
            int(value), int(config.get("hdcp_base", 220)), float(config.get("hdcp_pct", 0.90)),
            str(config.get("handicap_method", "percentage")), int(config.get("fixed_handicap", 0)),
        )
    )
    roster["ID verified"] = roster.get("USBC Verified", False)
    st.dataframe(
        roster[[column for column in ["USBC ID", "Bowler", "Division", "Average", "Handicap", "Starting Lane", "Entry Status", "Checked_In", "ID verified"] if column in roster]],
        hide_index=True,
        alt="Active tournament roster and verification status",
    )
    all_flags = []
    for _, bowler in roster.iterrows():
        metadata = bowler.get("Member Metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        flags = metadata.get("rule319_flags", []) if isinstance(metadata, dict) else []
        all_flags.extend((bowler.get("Bowler", "Unknown"), flag) for flag in flags)
    if all_flags:
        st.markdown("#### Average compliance warnings")
        for name, flag in all_flags:
            st.warning(f"{name}: {flag}")
    st.caption("Rule 319 review flags are advisory; confirm averages and tournament rules with the director before ruling on eligibility or disqualification.")

    st.subheader("Roster operations")
    tab_ai, tab_photo, tab_manual, tab_master, tab_balance, tab_desk, tab_pins = st.tabs([
        "AI text intake", "Photo intake", "Master grid", "Association Master Book", "Lane balancer", "Payment and QR", "Floor PINs",
    ])

    with tab_ai:
        signup_text = st.text_area(
            "Paste signup notes",
            placeholder="USBC ID, bowler name, average, team and division",
            key="ai_signup_notes",
        )
        if st.button("Parse signup notes", key="parse_signup_notes"):
            client = get_ai_client()
            if not client:
                st.error("Configure GEMINI_API_KEY to use AI intake.")
            elif not signup_text.strip():
                st.warning("Paste signup details before parsing.")
            else:
                try:
                    csv_text = parse_roster_text_with_gemini(signup_text, client=client)
                    if not csv_text.strip():
                        st.warning("No roster rows were returned.")
                    else:
                        parsed = pd.read_csv(io.StringIO(csv_text))
                        merged, imported_count, rejected = _merge_roster_import(roster, parsed, config)
                        if imported_count:
                            _save_roster(merged, config, f"AI parsed {imported_count} bowlers; rejected {rejected}.")
                            st.success(f"Added {imported_count} bowlers; rejected {rejected} invalid or duplicate rows.")
                            st.rerun()
                        else:
                            st.warning("No new valid bowlers were found.")
                except (pd.errors.ParserError, ValueError) as error:
                    st.error(f"Could not parse roster text: {error}")

    with tab_photo:
        capture_mode = st.radio("Capture source", ["Camera", "Upload image"], horizontal=True, key="roster_photo_source")
        image_bytes = None
        image_mime = "image/jpeg"
        if capture_mode == "Camera":
            image = st.camera_input("Capture a signup sheet", key="roster_sheet_camera")
            if image:
                image_bytes = image.getvalue()
                image_mime = image.type or image_mime
        else:
            image = st.file_uploader("Upload signup sheet image", type=["jpg", "jpeg", "png", "webp"], key="roster_sheet_upload")
            if image:
                image_bytes = image.getvalue()
                image_mime = image.type or image_mime
        if image_bytes:
            st.image(image_bytes, caption="Signup sheet preview", width=360)
            if st.button("Extract roster from image", key="extract_roster_image"):
                client = get_ai_client()
                if not client:
                    st.error("Configure GEMINI_API_KEY to use photo intake.")
                else:
                    try:
                        from google.genai import types

                        prompt = (
                            "Extract all bowlers as CSV with columns USBC ID,Bowler,Average,Starting Lane,"
                            "Division,Team_Name,Paid. Use a blank USBC ID when unreadable; default missing average "
                            "to 200, lane to 1, division to Open, and team to Singles. Do not invent verified IDs."
                        )
                        response = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=[types.Part.from_bytes(data=image_bytes, mime_type=image_mime), prompt],
                        )
                        parsed = pd.read_csv(io.StringIO((response.text or "").replace("```csv", "").replace("```", "").strip()))
                        merged, imported_count, rejected = _merge_roster_import(roster, parsed, config)
                        if imported_count:
                            _save_roster(merged, config, f"Photo intake added {imported_count} bowlers; rejected {rejected}.")
                            st.success(f"Added {imported_count} bowlers; rejected {rejected} invalid or duplicate rows.")
                            st.rerun()
                        st.warning("No valid new bowlers were found in the image.")
                    except Exception as error:
                        st.error(f"Photo extraction failed: {error}")

    with tab_manual:
        editable_columns = [
            column for column in [
                "USBC ID", "Bowler", "Average", "Starting Lane", "Division", "Team_Name",
                "Paid", "Checked_In", "Entry Status", "Entry Fee", "USBC Verified",
                *[f"Game {game}" for game in range(1, 11)],
            ] if column in roster.columns
        ]
        editable = st.data_editor(
            roster[editable_columns],
            num_rows="dynamic",
            hide_index=True,
            key="intake_master_roster_grid",
            alt="Editable tournament roster",
        )
        if st.button("Save master roster changes", key="save_master_roster"):
            existing = {
                str(row.get("USBC ID", "")): row.to_dict()
                for _, row in roster.iterrows()
                if pd.notna(row.get("USBC ID"))
            }
            saved_rows = []
            for _, changed in editable.iterrows():
                values = changed.to_dict()
                identifier = "" if pd.isna(values.get("USBC ID")) else str(values.get("USBC ID", "")).strip()
                original = existing.get(identifier, {})
                original.update({key: value for key, value in values.items() if not pd.isna(value)})
                saved_rows.append(original)
            merged, imported_count, rejected = _merge_roster_import(pd.DataFrame(), pd.DataFrame(saved_rows), config)
            if rejected:
                st.warning(f"Skipped {rejected} invalid or duplicate rows.")
            _save_roster(merged, config, "Saved master roster grid.")
            st.success(f"Saved {len(merged)} roster rows.")
            st.rerun()

    with tab_master:
        st.markdown("#### Association Master Book")
        st.caption("Import association-maintained membership averages. Lookup is limited to this local SQLite copy.")
        master_upload = st.file_uploader("Master Book CSV", type=["csv"], key="association_master_book_csv")
        if master_upload is not None:
            try:
                master_frame = pd.read_csv(master_upload)
                st.dataframe(master_frame.head(20), hide_index=True, alt="Association Master Book CSV preview")
                if st.button("Import or update Master Book records", type="primary", key="import_master_book"):
                    imported_count, skipped_count = upsert_master_book_df(master_frame)
                    log_audit_event("MASTER_BOOK_IMPORTED", f"Imported or updated {imported_count}; skipped {skipped_count}.")
                    st.success(f"Imported or updated {imported_count} records; skipped {skipped_count} invalid rows.")
                    st.rerun()
            except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as error:
                st.error(f"Could not import Master Book CSV: {error}")
        master_book = fetch_master_book_df()
        st.metric("Local Master Book records", len(master_book))
        if not master_book.empty:
            st.dataframe(master_book, hide_index=True, alt="Locally stored association Master Book records")

    with tab_balance:
        st.caption("Assign complete teams to pairs while respecting lane capacity; odd/even starting lanes alternate for balance.")
        balance_cols = st.columns(4)
        lane_range = balance_cols[0].text_input("Active lane range", config.get("lanes_range", "1-40"), key="balance_lane_range")
        capacity = balance_cols[1].selectbox("Bowlers per pair", [4, 5, 6, 8, 10], index=1, key="balance_pair_capacity")
        group_teams = balance_cols[2].checkbox("Keep teams together", value=True, key="balance_group_teams")
        shuffle = balance_cols[3].checkbox("Randomize draw", value=True, key="balance_shuffle")
        pairs = parse_active_pairs(lane_range, max_lanes=60)
        field_size = len(roster)
        st.caption(f"{len(pairs)} active pairs · {field_size} bowlers · capacity {len(pairs) * capacity}")
        if not pairs:
            st.error("Enter at least one valid pair range.")
        elif field_size > len(pairs) * capacity:
            st.warning("The roster exceeds this lane layout’s capacity.")
        elif st.button("Balance and assign lanes", type="primary", key="run_lane_balancer"):
            balanced, error = auto_assign_lanes(roster, pairs, max_per_pair=capacity, shuffle=shuffle, group_by_team=group_teams)
            if error:
                st.error(error)
            else:
                config["lanes_range"] = lane_range
                config["lanes_count"] = max(lane for pair in pairs for lane in pair)
                _save_roster(balanced, config, f"Balanced {len(balanced)} bowlers across {len(pairs)} pairs.")
                st.success("Lane assignments saved.")
                st.rerun()
        if not roster.empty:
            lane_pdf = export_lane_assignments_pdf(roster, config, st.session_state.get("td_name", "Staff"))
            st.download_button("Download printable lane assignments", lane_pdf, "Lane_Assignments.pdf", "application/pdf", icon=":material/picture_as_pdf:")
            if pairs:
                matrix = st.columns(4)
                for index, pair in enumerate(pairs):
                    members = roster[pd.to_numeric(roster["Starting Lane"], errors="coerce").isin(pair)]
                    matrix[index % len(matrix)].markdown(f"**Lanes {pair[0]}-{pair[1]} · {len(members)}/{capacity}**")
                    if not members.empty:
                        matrix[index % len(matrix)].write(", ".join(members["Bowler"].astype(str)))

    with tab_desk:
        st.caption("Collect payments, issue lane QR check-in cards, and record desk overrides.")
        detected_base = str(st.secrets.get("APP_URL", "http://localhost:8501")).rstrip("/")
        qr_cols = st.columns(3)
        for column, label, mode in zip(qr_cols, ("Entrance check-in", "Bowler portal", "Customer kiosk"), ("self_checkin", "bowler_portal", "kiosk")):
            target = f"{detected_base}/?mode={mode}"
            column.image(generate_qr_image(target), width=120, alt=f"{label} QR code")
            column.link_button(f"Open {label}", target)
        render_live_checkin_counters_fragment()
        if not roster.empty:
            selected_name = st.selectbox("Desk bowler", roster["Bowler"].astype(str).tolist(), key="desk_payment_bowler")
            selected_row = roster[roster["Bowler"].astype(str) == selected_name].iloc[0]
            identifier = str(selected_row["USBC ID"])
            card = {
                "name": selected_name,
                "usbc_id": identifier,
                "avg": int(selected_row.get("Average", 200)),
                "lane": int(selected_row.get("Starting Lane", 1)),
                "pair_display": f"{min(int(selected_row.get('Starting Lane', 1)), int(selected_row.get('Starting Lane', 1)) + (1 if int(selected_row.get('Starting Lane', 1)) % 2 else -1))}-{max(int(selected_row.get('Starting Lane', 1)), int(selected_row.get('Starting Lane', 1)) + (1 if int(selected_row.get('Starting Lane', 1)) % 2 else -1))}",
            }
            paid = bool(selected_row.get("Paid", False)) or str(selected_row.get("Entry Status", "")).casefold() == "comp"
            action_cols = st.columns(3)
            if not paid and action_cols[0].button("Mark paid", key="desk_mark_paid"):
                roster.loc[roster["USBC ID"].astype(str) == identifier, "Paid"] = True
                roster.loc[roster["USBC ID"].astype(str) == identifier, "Entry Status"] = "Paid"
                _save_roster(roster, config, f"Payment collected for {selected_name}.")
                write_kiosk_card(card)
                st.rerun()
            if paid and action_cols[0].button("Push check-in card to kiosk", key="desk_push_kiosk"):
                write_kiosk_card(card)
                log_audit_event("KIOSK_CARD_PUSHED", f"Pushed check-in card for {selected_name}.")
                st.rerun()
            if not bool(selected_row.get("Checked_In", False)) and action_cols[1].button("Manual check-in", key="desk_manual_checkin"):
                roster.loc[roster["USBC ID"].astype(str) == identifier, "Checked_In"] = True
                _save_roster(roster, config, f"Manual check-in for {selected_name}.")
                st.rerun()
            if paid and action_cols[2].button("Revert payment", key="desk_revert_payment"):
                roster.loc[roster["USBC ID"].astype(str) == identifier, "Paid"] = False
                roster.loc[roster["USBC ID"].astype(str) == identifier, "Entry Status"] = "Unpaid"
                roster.loc[roster["USBC ID"].astype(str) == identifier, "Checked_In"] = False
                _save_roster(roster, config, f"Payment reverted for {selected_name}.")
                if (fetch_kiosk_card() or {}).get("usbc_id") == identifier:
                    clear_kiosk_card()
                st.rerun()
            current_card = fetch_kiosk_card()
            if current_card and str(current_card.get("usbc_id")) == identifier and paid:
                st.image(generate_qr_image(f"{detected_base}/?mode=checkin&usbc_id={identifier}"), caption=f"{selected_name} check-in", width=180, alt="Bowler check-in QR code")

    with tab_pins:
        st.caption("Floor officials use an Argon2id PIN to sign mobile game scores.")
        pins = st.session_state.get("td_pins", {})
        if pins:
            st.dataframe(pd.DataFrame([{"Official": name, "Hash": "Argon2id", "Status": "PIN registered"} for name in pins]), hide_index=True, alt="Registered floor scorers")
        with st.form("intake_td_pin_form"):
            official = st.text_input("Official name").strip()
            pin = st.text_input("Assign PIN (4–6 digits)", type="password", max_chars=6).strip()
            save_pin = st.form_submit_button("Save floor PIN", type="primary")
        if save_pin:
            if not pin.isdigit() or not 4 <= len(pin) <= 6:
                st.error("PIN must contain 4–6 digits.")
            elif register_td_pin(official, pin):
                log_audit_event("FLOOR_SCORER_PIN_REGISTERED", f"Registered {official.strip()}.")
                st.success("Floor scorer PIN saved.")
                st.rerun()
            else:
                st.error("Enter an official name and a valid PIN.")