"""USBC SMART scholarship export: who gets what, per group, from the event's real payout setup.

Never invents money. Amounts come from the divisions setup:
  first_place (from the flyer) and optional place_amounts = [1st, 2nd, 3rd, ...] typed by the TD.
A place with no amount is left blank and listed as a warning.
Groups with an unresolved roll-off or an unfinished stepladder get no awards yet (warning instead).
"""

from __future__ import annotations

import csv
import io
import json
import re

from modules.db_state import get_connection
from modules.divisions import get_divisions, grouped_results
from modules.standings import get_tournament

COLUMNS = ["USBC ID", "Last Name", "First Name", "Scholarship Amount", "Division/Group", "Place"]
UPLOAD_COLUMNS = COLUMNS[:4]  # Division/Group and Place are for the TD's review only
HEADER_COLUMNS = ["Event Name", "Total Amount", "Date Event Ended", "Center Name", "Tournament Cert #"]
USBC_ID_RE = re.compile(r"^\d{3,5}-\d{3,7}$")


def split_name(name: str) -> tuple[str, str]:
    name = (name or "").strip()
    if "," in name:
        last, _, first = name.partition(",")
        return last.strip(), first.strip()
    parts = name.split()
    if len(parts) < 2:
        return name, ""
    return parts[-1], " ".join(parts[:-1])


def place_amounts(division: dict) -> dict[int, float]:
    out: dict[int, float] = {}
    for i, v in enumerate(division.get("place_amounts") or [], start=1):
        try:
            if v not in (None, ""):
                out[i] = float(v)
        except (TypeError, ValueError):
            pass
    if division.get("first_place") and 1 not in out:
        out[1] = float(division["first_place"])
    return out


def save_place_amounts(tournament_id: int, division_name: str, amounts: list) -> None:
    t = get_tournament(tournament_id) or {}
    divs = get_divisions(t)
    for d in divs:
        if d["name"] == division_name:
            d["place_amounts"] = amounts
            if amounts and amounts[0] not in (None, ""):
                d["first_place"] = amounts[0]
    _update(tournament_id, divisions_json=json.dumps(divs))


def save_header_fields(tournament_id: int, end_date: str, cert_number: str) -> None:
    _update(tournament_id, event_end_date=end_date.strip(), cert_number=cert_number.strip())


def _update(tournament_id: int, **fields) -> None:
    conn = get_connection()
    try:
        with conn:
            for k, v in fields.items():
                conn.execute(f"UPDATE tournaments SET {k} = ? WHERE id = ?", (v, tournament_id))
    finally:
        conn.close()


def build_smart_export(tournament_id: int) -> dict:
    """{'header': {...}, 'rows': [...], 'warnings': [...]}."""
    t = get_tournament(tournament_id) or {}
    from modules.constants import CENTERS, HOST_CENTERS
    center = (CENTERS.get(t.get("host_center")) or HOST_CENTERS.get(t.get("host_center"), {})).get("name", t.get("host_center") or "")
    end_date = t.get("event_end_date") or (t.get("event_start") or "")[:10]
    rows, warnings = [], []
    divs = {d["name"]: d for d in get_divisions(t)}
    groups = grouped_results(tournament_id)
    if not groups:
        warnings.append("This event has no divisions set up, so Prism can't tell who gets a scholarship. Enter awards in the SMART portal by hand.")
    for g in groups:
        name = g["group"]
        bowled = [r for r in g["rows"] if r.get("games")]
        if not bowled:
            continue
        if g.get("rolloff"):
            warnings.append(f"{name}: roll-off for the last finals spot isn't recorded yet, so no awards are listed for this group.")
            continue
        from modules.placement import STATUS_LADDER_PENDING, group_placement
        plc = group_placement(tournament_id, g)
        if plc["status"] == STATUS_LADDER_PENDING:
            warnings.append(f"{name}: stepladder finals not finished yet, so no awards are listed for this group.")
            continue
        ranked = plc["finalists"]
        amounts = place_amounts(divs.get(name.partition(" – ")[0], {}))
        for place, r in enumerate(ranked, start=1):
            amt = amounts.get(place)
            last, first = split_name(r["name"])
            rows.append({"USBC ID": (r.get("usbc_id") or "").strip(), "Last Name": last, "First Name": first,
                         "Scholarship Amount": "" if amt is None else f"{amt:.2f}",
                         "Division/Group": name, "Place": place, "_smart": (r.get("smart_account_id") or "").strip()})
            who = f"{name}, place {place} ({r['name']})"
            if amt is None:
                warnings.append(f"{who}: no scholarship amount set. Left blank — fill it in before uploading.")
            uid = rows[-1]["USBC ID"]
            if not uid:
                warnings.append(f"{who}: missing USBC ID.")
            elif not USBC_ID_RE.match(uid):
                warnings.append(f"{who}: USBC ID '{uid}' doesn't look right (expected like 1234-56789).")
            if not rows[-1]["_smart"]:
                warnings.append(f"{who}: no SMART account number on file.")
    total = sum(float(r["Scholarship Amount"]) for r in rows if r["Scholarship Amount"])
    if not end_date:
        warnings.append("Date the event ended is not set.")
    if not t.get("cert_number"):
        warnings.append("Tournament cert # is blank — type it in before uploading.")
    header = {"Event Name": t.get("name", ""), "Total Amount": f"{total:.2f}", "Date Event Ended": end_date,
              "Center Name": center, "Tournament Cert #": t.get("cert_number") or ""}
    return {"header": header, "rows": rows, "warnings": warnings}


def _csv(columns, rows) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


def _is_lower_place_reminder(item: str) -> bool:
    text = (item or "").lower()
    return "scholarship" in text and "2nd place" in text


def _has_lower_amount(division: dict) -> bool:
    for value in (division.get("place_amounts") or [])[1:]:
        if value not in (None, ""):
            return True
    return False


def lower_amounts_text(division: dict) -> str:
    """Comma list of 2nd place and below already stored. Blank when none are set."""
    parts = []
    for value in (division.get("place_amounts") or [])[1:]:
        if value in (None, ""):
            parts.append("")
            continue
        number = float(value)
        parts.append(str(int(number)) if number == int(number) else str(number))
    return ", ".join(parts)


def parse_optional_amounts(text: str) -> list | None:
    """Blank means 'not set' (None). A typed list never invents a number for an empty slot.

    Raises ValueError when a slot is not a number.
    """
    if not str(text or "").strip():
        return None
    parsed = []
    for part in str(text).split(","):
        part = part.strip().lstrip("$")
        if not part:
            parsed.append(None)
            continue
        try:
            number = float(part)
        except ValueError:
            raise ValueError("Scholarship amounts must be numbers, like 250, 100. Nothing was saved.") from None
        if number < 0:
            raise ValueError("Scholarship amounts can't be negative. Nothing was saved.")
        parsed.append(int(number) if number == int(number) else number)
    return parsed


def confirm_flyer_amounts(divs: list[dict], unconfirmed: list[str], first_places: dict,
                          lower_text: dict) -> tuple[list[dict], list[str]]:
    """Save flyer scholarship fields.

    1st place is the number the TD typed (the preset already has one). 2nd place and
    below are stored only when that box has amounts. A blank box does not invent
    dollars and does not clear the 2nd-place reminder. The reminder stays until
    every division has at least one lower-place amount.
    """
    new_divs = []
    for division in divs:
        updated = dict(division)
        name = division["name"]
        if name in first_places and first_places[name] is not None:
            updated["first_place"] = first_places[name]
        parsed = parse_optional_amounts(lower_text.get(name, ""))
        if parsed is None:
            updated.pop("place_amounts", None)
        else:
            sequence = [updated.get("first_place") if updated.get("first_place") is not None else 0]
            sequence.extend(parsed)
            while sequence and sequence[-1] is None:
                sequence.pop()
            if any(value is not None for value in sequence[1:]):
                updated["place_amounts"] = sequence
            else:
                updated.pop("place_amounts", None)
        new_divs.append(updated)
    all_set = bool(new_divs) and all(_has_lower_amount(division) for division in new_divs)
    kept = [item for item in unconfirmed if _is_lower_place_reminder(item) and not all_set]
    return new_divs, kept


def recipients_csv(data: dict, upload_only: bool = False) -> str:
    return _csv(UPLOAD_COLUMNS if upload_only else COLUMNS, data["rows"])


def header_csv(data: dict) -> str:
    return _csv(HEADER_COLUMNS, [data["header"]])
