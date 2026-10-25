"""Turn an A.I. photo read into a 'Does this look right?' review. Nothing here saves scores."""

import difflib

LOW_CONFIDENCE = 0.7


def _match(name: str, bowlers: list[dict]) -> dict | None:
    if not name:
        return None
    n = name.strip().lower()
    for b in bowlers:
        if b["name"].strip().lower() == n:
            return b
    names = [b["name"].lower() for b in bowlers]
    best = difflib.get_close_matches(n, names, n=1, cutoff=0.6)
    if not best:  # monitors often show first names / short names
        best = [x for x in names if x.split()[0] == n.split()[0]][:1]
    return next((b for b in bowlers if b["name"].lower() == best[0]), None) if best else None


def _to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def build_review(lane_bowlers: list[dict], extracted: list[dict]) -> dict:
    """{'rows': [{bowler_id, name, read_name, value, flags}], 'unmatched': [read names]}."""
    rows = {b["id"]: {"bowler_id": b["id"], "name": b["name"], "handicap": b.get("handicap") or 0,
                      "read_name": None, "value": None, "flags": []} for b in lane_bowlers}
    unmatched = []
    for item in extracted or []:
        if not isinstance(item, dict):
            continue
        b = _match(str(item.get("name") or ""), lane_bowlers)
        if not b or rows[b["id"]]["read_name"]:
            unmatched.append(str(item.get("name") or "?"))
            continue
        r = rows[b["id"]]
        r["read_name"] = item.get("name")
        r["value"] = _to_int(item.get("game_score"))
        conf = item.get("confidence")
        if isinstance(conf, (int, float)) and conf < LOW_CONFIDENCE:
            r["flags"].append("low confidence")
    for r in rows.values():
        r["flags"] = check_value(r["value"]) + r["flags"]
    return {"rows": list(rows.values()), "unmatched": unmatched}


def check_value(v) -> list[str]:
    """Blank is missing. 0 is a real score, same as the desk."""
    if v is None:
        return ["missing"]
    if v > 300 or v < 0:
        return ["out of range (0–300)"]
    return []


def save_errors(values: dict) -> list[str]:
    """Messages that block saving. Blank is allowed (that bowler is skipped). 0 is a real score."""
    return [
        f"Score {v} is over 300."
        for v in values.values()
        if v is not None and (v > 300 or v < 0)
    ]
