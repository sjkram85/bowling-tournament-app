"""Floor assistant 10-key mobile scoring pad and AI Overhead OCR photo ingest."""

import streamlit as st
from components.styles import inject_styles
from modules.constants import CENTERS
from modules.db_state import get_connection, log_desk_action
from modules.events import scoring_is_open
from modules.standings import current_lane, event_lane_pattern
from modules.ocr_engine import extract_scores_from_overhead_photo
from modules.settings import ai_available, AI_OFF_MESSAGE


def _get_active_tournament_for_scoring(event: dict | None) -> dict | None:
    if not event:
        return None
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM tournaments WHERE id = ? AND status = 'active'", (event["id"],)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _load_squad(tournament_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, name, handicap, is_pacer, lane_assignment, lineup_position
               FROM bowlers WHERE tournament_id = ? ORDER BY lineup_position, name""",
            (tournament_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _lane_for(tourney: dict, bowler: dict, game: int, squad: list[dict]) -> int:
    return current_lane(bowler.get("lane_assignment") or 0, game, tourney, squad)


def _lanes_for_game(tourney: dict, squad: list[dict], game: int) -> list[int]:
    lanes = sorted({_lane_for(tourney, b, game, squad) for b in squad if b.get("lane_assignment")})
    if lanes:
        return lanes
    host_code = tourney.get("host_center", "FHL")
    max_lanes = CENTERS.get(host_code, {}).get("lanes", 40)
    return list(range(1, max_lanes + 1))


def _bowlers_on_lane(tourney: dict, squad: list[dict], lane: int, game: int) -> list[dict]:
    """Bowlers the desk shows on this lane for this game. Same-pair events do not move."""
    return [b for b in squad if _lane_for(tourney, b, game, squad) == int(lane)]


def _get_existing_lane_scores(tournament_id: int, game_num: int) -> dict[int, dict]:
    """Retrieve any existing recorded scores for this game."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT bowler_id, scratch_score, hdcp_score, total_score, recorded_by FROM scores "
            "WHERE tournament_id = ? AND game_number = ?",
            (tournament_id, game_num),
        ).fetchall()
        return {r["bowler_id"]: dict(r) for r in rows}
    finally:
        conn.close()


def _entered_scratch(value):
    """Blank / empty is not a score. 0 is a real score. NaN and junk are blank."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return int(number)


def scores_to_save(values: dict) -> dict[int, int]:
    """Scores a floor phone or photo review should write.

    A blank box is not a score (that bowler has not bowled). A typed 0 is a
    real score and is saved. Bowlers with no value are left out — nothing is invented.
    """
    saved = {}
    for bowler_id, raw in values.items():
        score = _entered_scratch(raw)
        if score is None:
            continue
        saved[int(bowler_id)] = score
    return saved


def _score_box(label: str, key: str, saved, max_value: int):
    """Scratch box. Starts empty so blank stays blank. Prefills a saved score, including 0.

    value=None keeps the box clearable. Passing 0 as the default would make
    'not bowled' and 'scored 0' the same number, which is how a zero was lost.
    """
    if key not in st.session_state and saved is not None:
        st.session_state[key] = int(saved)
    return st.number_input(
        label,
        min_value=0,
        max_value=max_value,
        value=None,
        step=1,
        placeholder="Not bowled",
        key=key,
    )


def _record_score(tournament_id: int, bowler_id: int, game_num: int, scratch: int, hdcp: int, verifier_name: str,
                  source: str = "floor", device: str | None = None) -> int | None:
    if not scoring_is_open(tournament_id):
        return None
    from modules import score_history
    before = score_history.current(tournament_id, bowler_id, game_num)
    conn = get_connection()
    total = scratch + hdcp
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, hdcp_score, total_score, recorded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tournament_id, bowler_id, game_number) DO UPDATE SET
                    scratch_score = excluded.scratch_score,
                    hdcp_score = excluded.hdcp_score,
                    total_score = excluded.total_score,
                    recorded_by = excluded.recorded_by,
                    verified = 0, verified_by = NULL, verified_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (tournament_id, bowler_id, game_num, scratch, hdcp, total, verifier_name),
            )
    finally:
        conn.close()
    log_desk_action(verifier_name, "floor_verifier", f"Entered Game {game_num} score {scratch} (Total {total}) for Bowler #{bowler_id}")
    return score_history.log_change(tournament_id, bowler_id, game_num, before, scratch, source, verifier_name, device)


def render_mobile_scoring() -> None:
    inject_styles()
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #1E3A8A 0%, #0F172A 100%); border: 1px solid #3B82F6; border-radius: 12px; padding: 16px; text-align: center; margin-bottom: 16px;">
            <h3 style="color: #F8FAFC; margin: 0 0 4px 0;">📱 Floor Scoring Pad</h3>
            <p style="color: #93C5FD; font-size: 12px; margin: 0;">Verified 10-Key Score Entry & Overhead Camera Snap</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    from components.event_picker import public_event
    tourney = _get_active_tournament_for_scoring(public_event(st.query_params.get("t") or st.query_params.get("tournament")))
    if tourney and st.session_state.get("scorer_event") != tourney["id"]:
        # Unlocking one event's pad never unlocks another event.
        st.session_state["scorer_event"] = tourney["id"]
        st.session_state.pop("scorer_authenticated", None)
    if not tourney:
        st.warning("No active tournament available for scoring.")
        return

    # Authentication Gate
    if not st.session_state.get("scorer_authenticated"):
        with st.container(border=True):
            st.subheader("Floor Assistant Access")
            verifier = st.text_input("Your Name / Identifier", placeholder="e.g. Mike R.")
            entered_pin = st.text_input("4-Digit Scoring PIN", type="password", max_chars=4)
            if st.button("Unlock Scoring Pad", type="primary", use_container_width=True):
                if entered_pin == tourney["pin_verifier"] and verifier.strip():
                    st.session_state["scorer_authenticated"] = True
                    st.session_state["verifier_name"] = verifier.strip()
                    st.rerun()
                else:
                    st.error("Invalid PIN or missing Verifier Name.")
        return

    verifier_name = st.session_state.get("verifier_name", "Floor Verifier")
    if "floor_device" not in st.session_state:
        import uuid
        st.session_state["floor_device"] = uuid.uuid4().hex
    device = st.session_state["floor_device"]

    # Header status badge
    st.markdown(
        f"""
        <div style="background:#0F172A; border:1px solid #334155; border-radius:8px; padding:10px 14px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="color:#F8FAFC; font-weight:700; font-size:13px;">👤 {verifier_name}</span>
                <span style="color:#94A3B8; font-size:12px; margin-left:8px;">&bull; {tourney['name']}</span>
            </div>
            <span style="background:#1E3A8A; color:#93C5FD; font-size:10px; font-weight:800; padding:2px 8px; border-radius:4px;">
                PIN VERIFIED
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_manual, tab_camera = st.tabs(["🔢 10-Key Manual Input", "📸 AI Overhead Camera OCR"])

    squad = _load_squad(tourney["id"])
    if event_lane_pattern(tourney) == "same_pair":
        st.caption("Same pair: the lane does not change between games. It matches the desk.")
    else:
        st.caption("Lane shown is the lane for the game you pick — the same lane as the desk.")

    # --- TAB 1: 10-KEY MANUAL PAD ---
    with tab_manual:
        col_game, col_lane = st.columns([1, 1], gap="small")
        with col_game:
            game_options = list(range(1, tourney["game_count"] + 1))
            game = st.radio(
                "Select Game",
                options=game_options,
                format_func=lambda g: f"Game {g}",
                horizontal=True,
                index=0,
                key="mobile_game_radio",
            )
        active_lanes = _lanes_for_game(tourney, squad, int(game))
        with col_lane:
            if len(active_lanes) <= 12:
                lane = st.radio(
                    "Select Lane",
                    options=active_lanes,
                    format_func=lambda l: f"Lane {l}",
                    horizontal=True,
                    index=0,
                    key=f"mobile_lane_g{game}",
                )
            else:
                lane = st.selectbox("Select Lane", options=active_lanes, key=f"mobile_lane_g{game}")

        bowlers = _bowlers_on_lane(tourney, squad, int(lane), int(game))
        existing_scores = _get_existing_lane_scores(tourney["id"], game)

        if not bowlers:
            st.info(f"No bowlers assigned to Lane {lane}.")
        else:
            st.caption("Leave a box blank if that bowler has not bowled. Type 0 to save a real zero.")
            with st.form(f"score_form_lane_{lane}_gm_{game}"):
                all_recorded = True
                entered = {}
                for b in bowlers:
                    pacer_tag = " (PACER)" if b["is_pacer"] else ""
                    b_id = b["id"]
                    prev_score = existing_scores.get(b_id)
                    if prev_score is None:
                        all_recorded = False
                        current = None
                    else:
                        current = int(prev_score["scratch_score"])

                    st.markdown(f"**{b['name']}**{pacer_tag} — HDCP: `+{b['handicap']}`")
                    if prev_score is not None:
                        st.caption(
                            f"✅ Current Score: **{current}** (HDCP Total: **{prev_score.get('total_score')}**) "
                            f"· By: {prev_score.get('recorded_by', 'Desk')}"
                        )

                    entered[b_id] = _score_box(
                        f"Scratch Score for {b['name']}",
                        f"scratch_{b_id}_g{game}",
                        current,
                        300,
                    )

                btn_label = f"Update Lane {lane} Game {game} Scores" if all_recorded else f"Submit Lane {lane} Game {game} Scores"
                submitted = st.form_submit_button(btn_label, type="primary", use_container_width=True)
                if submitted:
                    if not scoring_is_open(tourney["id"]):
                        st.error("This event is frozen. Scores were not changed.")
                        st.stop()
                    to_save = scores_to_save(entered)
                    if not to_save:
                        st.info("No scores were entered, so nothing was written. Leave a box blank to skip a bowler, or type 0 for a real zero.")
                    else:
                        changed = []
                        for b in bowlers:
                            if b["id"] not in to_save:
                                continue
                            hid = _record_score(
                                tourney["id"], b["id"], game, to_save[b["id"]], b["handicap"], verifier_name,
                                device=device,
                            )
                            if hid:
                                changed.append(hid)
                        st.session_state["floor_undo"] = changed
                        st.success(
                            f"Saved {len(to_save)} score{'s' if len(to_save) != 1 else ''} for Lane {lane} Game {game}. "
                            "Blank boxes were skipped."
                        )
                        st.rerun()

        from components.undo_box import saved_undo_button
        saved_undo_button("floor_undo", verifier_name, device=device)

    # --- TAB 2: AI OVERHEAD OCR CAMERA SNAP ---
    with tab_camera:
        _render_photo_tab(tourney, squad, verifier_name)


PHOTO_FAIL_MESSAGE = "Prism A.I. couldn't read this photo. Please type the scores in the 10-Key Manual Input tab."


def read_photo(image: bytes, lane_bowlers: list[dict]) -> dict | None:
    """A.I. read -> review dict, or None if the A.I. failed or read nothing. Never raises, never saves."""
    from modules.photo_review import build_review
    try:
        result = extract_scores_from_overhead_photo(image)
    except Exception:
        return None
    if result.get("status") != "success" or not result.get("extracted_data"):
        return None
    return build_review(lane_bowlers, result["extracted_data"])


def _render_photo_tab(tourney: dict, squad: list[dict], verifier_name: str) -> None:
    """Photo -> A.I. read -> 'Does this look right?' review -> 'Save these scores'. Never saves directly."""

    st.subheader("Overhead Monitor Photo")
    st.caption("Take a photo of the lane monitor. Prism A.I. reads it, you check the numbers, then save.")
    c1, c2 = st.columns(2)
    game = c1.selectbox("Game", list(range(1, tourney["game_count"] + 1)), format_func=lambda g: f"Game {g}",
                        key="photo_game")
    photo_lanes = _lanes_for_game(tourney, squad, int(game))
    lane = c2.selectbox("Lane", photo_lanes, format_func=lambda l: f"Lane {l}", key=f"photo_lane_g{game}")
    if not ai_available():
        st.info(AI_OFF_MESSAGE + " Please use the 10-Key Manual Input tab.")
        return
    img = st.camera_input("Snap Monitor Screen", key="photo_cam")
    if img is None:
        return
    key = (tourney["id"], int(lane), int(game), hash(img.getvalue()))
    if st.session_state.get("photo_key") != key:
        st.session_state.pop("photo_review", None)
    if "photo_review" not in st.session_state:
        if not st.button("Read scores from photo", type="primary", use_container_width=True):
            return
        with st.spinner("Prism A.I. is reading the photo..."):
            review = read_photo(img.getvalue(), _bowlers_on_lane(tourney, squad, int(lane), int(game)))
        if review is None:
            st.error(PHOTO_FAIL_MESSAGE)
            return
        st.session_state["photo_review"] = review
        st.session_state["photo_key"] = key
    _render_photo_review(tourney, int(lane), int(game), img.getvalue(), st.session_state["photo_review"],
                         verifier_name)


def _render_photo_review(tourney: dict, lane: int, game: int, image: bytes, review: dict, verifier_name: str) -> None:
    from html import escape
    from modules.photo_review import check_value, save_errors

    st.markdown("### Does this look right?")
    st.caption(
        "Fix any number that is wrong. Yellow = please check. "
        "Leave a box blank to skip a bowler. Type 0 to save a real zero."
    )
    left, right = st.columns([1, 1])
    left.image(image, caption=f"Lane {lane} · Game {game}", use_container_width=True)
    values = {}
    with right:
        for r in review["rows"]:
            k = f"photo_val_{r['bowler_id']}_{game}"
            v = _score_box(r["name"], k, r["value"], 999)
            values[r["bowler_id"]] = v
            flags = check_value(v) + [f for f in r["flags"] if f == "low confidence"]
            if flags:
                read = f" (photo said: {escape(str(r['read_name']))})" if r["read_name"] else ""
                st.markdown(f"<div style='background:#713F12;color:#FEF08A;padding:4px 8px;border-radius:6px;"
                            f"font-size:13px'>⚠️ Please check: {', '.join(flags)}{read}</div>",
                            unsafe_allow_html=True)
        if review["unmatched"]:
            st.caption("Names on the photo not on this lane: " + ", ".join(escape(n) for n in review["unmatched"]))
    errors = save_errors(values)
    for e in errors:
        st.error(e)
    b1, b2 = st.columns(2)
    if b1.button("Save these scores", type="primary", use_container_width=True, disabled=bool(errors),
                 key="photo_save"):
        if not scoring_is_open(tourney["id"]):
            st.error("This event is frozen. Scores were not changed.")
            return
        handicaps = {r["bowler_id"]: r["handicap"] for r in review["rows"]}
        to_save = scores_to_save(values)
        if not to_save:
            st.info("No scores were entered, so nothing was written. Leave a box blank to skip a bowler, or type 0 for a real zero.")
        else:
            n, changed = 0, []
            for bid, v in to_save.items():
                hid = _record_score(tourney["id"], bid, game, v, handicaps.get(bid, 0), f"{verifier_name} (photo)",
                                    source="photo", device=st.session_state.get("floor_device"))
                if hid:
                    changed.append(hid)
                n += 1
            st.session_state.pop("photo_review", None)
            st.session_state["photo_undo"] = changed
            st.success(f"Saved {n} score{'s' if n != 1 else ''}. They are waiting in the TD Verify list.")
            from components.undo_box import saved_undo_button
            saved_undo_button("photo_undo", verifier_name, device=st.session_state.get("floor_device"))
    if b2.button("Cancel", use_container_width=True, key="photo_cancel"):
        st.session_state.pop("photo_review", None)
        st.rerun()
