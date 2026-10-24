"""Direct (no-AI) roster file import: template matching, column mapping, and row validation."""

from __future__ import annotations

import io
import re

import pandas as pd

# Prism roster fields, in template order. (field, label, required)
FIELDS = [
    ("name", "Bowler Name", True),
    ("usbc_id", "USBC ID", False),
    ("email", "Email", False),
    ("entering_avg", "Entering Average", True),
    ("handicap", "Handicap", False),
    ("lane_assignment", "Starting Lane", True),
    ("is_youth", "Youth (yes/no)", False),
    ("smart_account_id", "SMART Account ID", False),
    ("paid_status", "Paid Status (paid/unpaid)", True),
    ("gender", "Boys/Girls", False),
    ("birth_date", "Birth Date", False),
    ("bowls_scratch", "Bowls Scratch (yes/no)", False),
]
FIELD_KEYS = [f[0] for f in FIELDS]
REQUIRED = {f[0] for f in FIELDS if f[2]}

# Extra header spellings accepted for auto-matching.
ALIASES = {
    "name": ["name", "bowler", "bowlername", "fullname", "bowlerfullname", "competitor", "player", "bowlersname"],
    "usbc_id": ["usbcid", "usbc", "usbcnumber", "memberid", "usbcmemberid"],
    "email": ["email", "emailaddress", "e-mail"],
    "entering_avg": ["enteringavg", "average", "avg", "enteringaverage"],
    "handicap": ["handicap", "hdcp", "hcp"],
    "lane_assignment": ["laneassignment", "lane", "startinglane", "startlane"],
    "is_youth": ["isyouth", "youth"],
    "smart_account_id": ["smartaccountid", "smartid", "smart", "smartaccount"],
    "paid_status": ["paidstatus", "paid", "payment", "paymentstatus"],
    "gender": ["gender", "sex", "boysgirls", "boygirl"],
    "birth_date": ["birthdate", "dob", "dateofbirth", "birthday"],
    "bowls_scratch": ["bowlsscratch", "scratch"],
}

SAMPLE_ROW = {
    "name": "Jane Doe", "usbc_id": "8412-12345", "email": "jane@example.com",
    "entering_avg": 210, "handicap": 9, "lane_assignment": 1, "is_youth": "no",
    "smart_account_id": "", "paid_status": "paid",
}


def _norm(header) -> str:
    return re.sub(r"[^a-z0-9]", "", str(header).lower())


def template_csv() -> bytes:
    return pd.DataFrame([SAMPLE_ROW], columns=FIELD_KEYS).to_csv(index=False).encode()


def template_xlsx() -> bytes:
    buf = io.BytesIO()
    pd.DataFrame([SAMPLE_ROW], columns=FIELD_KEYS).to_excel(buf, index=False, sheet_name="Roster")
    return buf.getvalue()


def read_table(file_bytes: bytes, file_name: str) -> pd.DataFrame | None:
    """Read a CSV/XLSX into a DataFrame of strings. Returns None for other file types."""
    fn = file_name.lower()
    try:
        if fn.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False, encoding="utf-8-sig")
        elif fn.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
        else:
            return None
    except Exception:
        return None
    df = df.dropna(how="all")
    df = df[~(df.astype(str).apply(lambda r: "".join(r).strip(), axis=1) == "")]
    df.columns = [str(c).strip() for c in df.columns]
    return df.reset_index(drop=True)


def guess_mapping(columns) -> dict[str, str | None]:
    """Map each Prism field to a file column by header name (case/spacing-insensitive)."""
    normed = {_norm(c): c for c in columns}
    mapping = {}
    for key in FIELD_KEYS:
        mapping[key] = next((normed[a] for a in [_norm(key)] + ALIASES[key] if a in normed), None)
    return mapping


def matches_template(columns) -> bool:
    """True when every template column is present (ignoring case, spaces, underscores)."""
    normed = {_norm(c) for c in columns}
    # The newer optional youth columns (gender, birth date, scratch) are not required here.
    return all(_norm(k) in normed for k in FIELD_KEYS if k not in ("gender", "birth_date", "bowls_scratch"))


def apply_mapping(df: pd.DataFrame, mapping: dict[str, str | None]) -> list[dict]:
    rows = []
    for _, r in df.iterrows():
        rows.append({k: (str(r[c]).strip() if c else "") for k, c in mapping.items()})
    return rows


def _to_int(v):
    s = str(v if v is not None else "").strip()
    if s == "" or s.lower() in ("nan", "none"):
        return None, "blank"
    try:
        f = float(s)
    except ValueError:
        return None, "bad"
    if f != int(f):
        return None, "bad"
    return int(f), None


def validate_rows(rows: list[dict]) -> list[dict]:
    """Return cleaned rows, each with an 'errors' string (empty when the row is OK). No defaults are invented."""
    out = []
    for raw in rows:
        errs = []
        row = {k: raw.get(k) for k in FIELD_KEYS}
        name = str(row["name"] or "").strip()
        if not name or name.lower() == "nan":
            errs.append("missing name")
        row["name"] = name

        for key, label, lo, hi in (("entering_avg", "average", 0, 300), ("lane_assignment", "lane", 1, 200)):
            val, problem = _to_int(row[key])
            if problem == "blank":
                errs.append(f"missing {label}")
            elif problem == "bad":
                errs.append(f"{label} '{row[key]}' is not a whole number")
            elif not lo <= val <= hi:
                errs.append(f"{label} {val} out of range")
            row[key] = val

        val, problem = _to_int(row["handicap"])
        if problem == "bad":
            errs.append(f"handicap '{row['handicap']}' is not a whole number")
        row["handicap"] = val  # blank handicap stays blank (shown in preview)

        paid = str(row["paid_status"] or "").strip().lower()
        if paid in ("paid", "yes", "y"):
            row["paid_status"] = "paid"
        elif paid in ("unpaid", "no", "n", "owing", "due"):
            row["paid_status"] = "unpaid"
        else:
            errs.append("paid status must be paid or unpaid" if paid else "missing paid status")
            row["paid_status"] = paid or None

        youth = row["is_youth"]
        ys = str(youth if youth is not None else "").strip().lower()
        if isinstance(youth, bool):
            row["is_youth"] = youth
        elif ys in ("", "0", "no", "n", "false", "nan", "none"):
            row["is_youth"] = False
        elif ys in ("1", "yes", "y", "true", "youth"):
            row["is_youth"] = True
        else:
            errs.append(f"youth '{youth}' should be yes or no")
            row["is_youth"] = False

        for k in ("usbc_id", "email", "smart_account_id"):
            s = str(row[k] or "").strip()
            row[k] = "" if s.lower() in ("nan", "none") else s
        if row["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", row["email"]):
            errs.append("email looks invalid")

        g = str(row.get("gender") or "").strip().lower()
        row["gender"] = {"b": "Boys", "boy": "Boys", "boys": "Boys", "m": "Boys", "male": "Boys",
                         "g": "Girls", "girl": "Girls", "girls": "Girls", "f": "Girls", "female": "Girls"}.get(g, "")
        if g and g not in ("nan", "none") and not row["gender"]:
            errs.append(f"boys/girls '{row.get('gender')}' not understood")
        bd = str(row.get("birth_date") or "").strip()
        row["birth_date"] = "" if bd.lower() in ("nan", "none", "nat") else bd
        row["bowls_scratch"] = str(row.get("bowls_scratch") or "").strip().lower() in ("1", "yes", "y", "true")

        row["errors"] = "; ".join(errs)
        out.append(row)
    return out
