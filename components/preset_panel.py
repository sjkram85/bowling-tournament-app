"""Locked preset rules + 'confirm with tournament flyer' box, shown on Intake Gateway."""

from __future__ import annotations

import json
import re

import streamlit as st

from modules import auth
from modules.db_state import get_connection, log_desk_action
from modules.divisions import GROUPINGS, division_label, get_divisions, past_deadline, unconfirmed_items


def _update(t_id: int, **cols) -> None:
    conn = get_connection()
    try:
        with conn:
            sets = ", ".join(f"{k} = ?" for k in cols)
            conn.execute(f"UPDATE tournaments SET {sets} WHERE id = ?", (*cols.values(), t_id))
    finally:
        conn.close()


def render_preset_panel(t: dict, td_name: str) -> None:
    divs = get_divisions(t)
    if not (t.get("preset_key") or divs):
        return
    t_id = t["id"]
    locked = bool(t.get("rules_locked"))
    with st.container(border=True):
        st.markdown(f"### {'🔒 Tournament rules (locked by preset)' if locked else '📋 Tournament rules'}")
        lines = []
        if t.get("event_start"):
            lines.append(f"**When:** {t['event_start']}")
        if t.get("entry_deadline"):
            lines.append(
                f"**Entry deadline:** {t['entry_deadline']} (end of day, Eastern Time)"
                + (" — **NO walk-ins**" if t.get("no_walkins") else "")
            )
        if t.get("youth_only"):
            lines.append("**Youth bowlers only** (Maryland USBC sanctioned)")
        if t.get("require_smart"):
            lines.append("**SMART account number required.** Prizes are guaranteed SMART scholarships, never cash (USBC Rule 400).")
        if t.get("fees_at_front_desk"):
            lines.append("**Entry fees are collected by the Forest Hill Lanes front desk**, not in Prism.")
        lines.append(f"**Ranked by:** {GROUPINGS.get(t.get('grouping') or 'division')}")
        for d in divs:
            lines.append("• " + division_label(d["name"], divs))
        try:
            lines += ["• " + r for r in json.loads(t.get("rules_text") or "[]")]
        except ValueError:
            pass
        st.markdown("<div style='font-size:18px; line-height:1.7'>" + "<br>".join(re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", ln) for ln in lines) + "</div>", unsafe_allow_html=True)
        if t.get("no_walkins") and past_deadline(t):
            st.error("The entry deadline has passed. New bowlers can't be added (no walk-ins).")

        if locked and auth.is_admin():
            with st.expander("Admin only: unlock these rules"):
                st.caption("Only do this if the tournament flyer changed. The change is written to the audit log.")
                if st.button("Unlock preset rules", key="unlock_preset"):
                    _update(t_id, rules_locked=0)
                    log_desk_action(td_name, "admin", f"Unlocked preset rules for tournament #{t_id}")
                    st.rerun()
        elif not locked and t.get("preset_key") and auth.is_admin():
            keys = list(GROUPINGS)
            new_g = st.selectbox("Rank bowlers by", keys, index=keys.index(t.get("grouping") or "division"),
                                 format_func=GROUPINGS.get, key="grouping_pick")
            if new_g != (t.get("grouping") or "division"):
                _update(t_id, grouping=new_g)
                from modules.divisions import assign_all
                assign_all(t_id)
                log_desk_action(td_name, "admin", f"Changed ranking groups to '{new_g}' for tournament #{t_id}")
                st.rerun()
            if st.button("🔒 Re-lock preset rules", key="relock_preset"):
                _update(t_id, rules_locked=1)
                log_desk_action(td_name, "admin", f"Re-locked preset rules for tournament #{t_id}")
                st.rerun()

    todo = unconfirmed_items(t)
    if todo:
        with st.container(border=True):
            st.markdown("### ⚠️ Confirm with the tournament flyer")
            st.markdown("<p style='font-size:17px'>The website didn't say these things. Check the official entry form, then fill them in:</p>"
                        + "".join(f"<div style='font-size:17px'>• {x}</div>" for x in todo), unsafe_allow_html=True)
            with st.form(f"flyer_{t_id}"):
                from modules.smart_export import confirm_flyer_amounts, lower_amounts_text
                amounts = {}
                lowers = {}
                for d in divs:
                    amounts[d["name"]] = st.number_input(f"{d['name']} 1st place scholarship ($)", 0, 10000,
                                                         int(d.get("first_place") or 0), step=25)
                    lowers[d["name"]] = st.text_input(
                        f"{d['name']} — 2nd place and below (optional, dollars, comma-separated)",
                        value=lower_amounts_text(d),
                        placeholder="Leave blank if the committee has not set these",
                        help="Example: 250, 100. Blank does not store $0 and does not clear the reminder.",
                    )
                notes = st.text_area("Other notes from the flyer (optional)", value=t.get("flyer_notes") or "")
                st.caption("2nd place and below stay on the reminder until every division has an amount typed above. "
                           "Prism does not fill those in.")
                if st.form_submit_button("✅ I checked the flyer. Save these.", type="primary", use_container_width=True):
                    try:
                        new_divs, remaining = confirm_flyer_amounts(divs, todo, amounts, lowers)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        _update(t_id, divisions_json=json.dumps(new_divs), flyer_notes=notes.strip(),
                                unconfirmed_json=json.dumps(remaining))
                        log_desk_action(td_name, "td", f"Confirmed flyer details for tournament #{t_id}")
                        st.rerun()
