"""Mobile scoring view, reached with ?mode=score."""

import hmac

import streamlit as st

from modules.db_state import get_connection, init_db
from modules.prism_ai import extract_scores_from_photo
from modules.standings import commit_scores, get_tournament, lane_count, lane_for_game, pair_of_lane

MAX_PIN_ATTEMPTS = 5

# Streamlit text inputs can't set inputmode directly, so patch them in the parent page.
_DIALPAD_JS = """
<script>
const apply = () => window.parent.document
  .querySelectorAll('input[aria-label^="Score"]')
  .forEach(el => { el.setAttribute('inputmode', 'numeric'); el.setAttribute('pattern', '[0-9]*'); });
apply();
new MutationObserver(apply).observe(window.parent.document.body, {childList: true, subtree: true});
</script>
"""


def _query(sql: str, params: tuple = ()) -> list[dict]:
    connection = get_connection()
    try:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def _expected_pin(tournament_id: int) -> str:
    row = _query("SELECT pin_verifier FROM tournaments WHERE id = ?", (tournament_id,))
    return str((row[0]["pin_verifier"] if row else None) or st.secrets.get("SCORING_PIN", ""))


def _pin_gate(tournament_id: int) -> str | None:
    """Return the verifier name once this tournament's PIN and a name are accepted."""
    unlocked = st.session_state.setdefault("score_unlocked", {})
    if tournament_id in unlocked:
        return unlocked[tournament_id]

    expected = _expected_pin(tournament_id)
    if not expected:
        st.error("No scoring PIN is set for this tournament.")
        return None

    with st.form("score_login"):
        verifier = st.text_input("Verifier name")
        pin = st.text_input("4-digit PIN", type="password", max_chars=4)
        submitted = st.form_submit_button("Unlock", width="stretch")
    if submitted:
        attempts = st.session_state.get("score_pin_attempts", 0)
        if attempts >= MAX_PIN_ATTEMPTS:
            st.error("Too many attempts. Reload the page to try again.")
        elif not verifier.strip():
            st.error("Enter your verifier name.")
        elif len(pin) == 4 and pin.isdigit() and hmac.compare_digest(pin, expected):
            unlocked[tournament_id] = verifier.strip()
            st.rerun()
        else:
            st.session_state["score_pin_attempts"] = attempts + 1
            st.error("Invalid PIN.")
    return None


def _pair_label(pair: int) -> str:
    return f"Pair {pair} (lanes {2 * pair - 1}-{2 * pair})"


def render_mobile_scoring() -> None:
    init_db()
    st.title("Score Entry")

    tournaments = _query("SELECT id, name, game_count FROM tournaments WHERE status = 'active' ORDER BY id DESC")
    if not tournaments:
        st.info("No active tournaments.")
        return
    tournament = st.selectbox("Tournament", tournaments, format_func=lambda t: t["name"])

    verifier = _pin_gate(tournament["id"])
    if not verifier:
        return
    st.caption(f"Verifier: {verifier}")

    game_number = (
        st.slider("Game", 1, tournament["game_count"], 1) if tournament["game_count"] > 1 else 1
    )

    bowlers = _query(
        "SELECT id, name, lane_assignment FROM bowlers WHERE tournament_id = ? ORDER BY lane_assignment, name",
        (tournament["id"],),
    )
    if not bowlers:
        st.info("No bowlers in this tournament.")
        return

    # Lane rotation: each bowler's pair for the selected game.
    lanes = lane_count(get_tournament(tournament["id"]) or {}, bowlers)
    by_pair: dict[int, list[dict]] = {}
    for bowler in bowlers:
        if bowler["lane_assignment"]:
            pair = pair_of_lane(lane_for_game(bowler["lane_assignment"], game_number, lanes))
            by_pair.setdefault(pair, []).append(bowler)
    if not by_pair:
        st.info("No bowlers have lane assignments.")
        return
    pair = st.selectbox("Lane pair", sorted(by_pair), format_func=_pair_label)
    pair_bowlers = by_pair[pair]

    existing = {
        r["bowler_id"]: r["scratch_score"]
        for r in _query(
            "SELECT bowler_id, scratch_score FROM bowler_scores WHERE tournament_id = ? AND game_number = ?",
            (tournament["id"], game_number),
        )
    }
    key = lambda b: f"score_{tournament['id']}_{game_number}_{b['id']}"
    for b in pair_bowlers:
        st.session_state.setdefault(key(b), str(existing[b["id"]]) if b["id"] in existing else "")

    photo = st.camera_input("Snap a photo of the overhead scoring monitor (optional)")
    if photo is not None and st.button("Read scores from photo", width="stretch"):
        with st.spinner("Reading photo..."):
            found = extract_scores_from_photo(photo.getvalue(), [b["name"] for b in pair_bowlers])
        for b in pair_bowlers:
            if b["name"] in found:
                st.session_state[key(b)] = str(found[b["name"]])
        st.info(f"Filled {len(found)} scores. Review before submitting.")

    entries = {}
    for b in pair_bowlers:
        entries[b["id"]] = st.text_input(
            f"Score – {b['name']}", key=key(b), max_chars=3, placeholder="0-300"
        )
    st.iframe(_DIALPAD_JS, height=1)

    if st.button("Verify & Submit Scores", type="primary", width="stretch"):
        scores, errors = {}, []
        for b in pair_bowlers:
            raw = entries[b["id"]].strip()
            if not raw:
                continue
            if not raw.isdigit() or int(raw) > 300:
                errors.append(f"{b['name']}: '{raw}' is not a valid score (0-300).")
            else:
                scores[b["id"]] = int(raw)
        if errors:
            st.error("\n\n".join(errors))
        elif not scores:
            st.warning("Enter at least one score.")
        else:
            commit_scores(tournament["id"], game_number, scores, verifier, "verifier")
            st.success(f"Submitted {len(scores)} scores for game {game_number}, verified by {verifier}.")
