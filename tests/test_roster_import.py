import io
import pandas as pd
from modules import roster_import as ri
from modules.ai_roster import _fast_structured_text_parser


def test_template_xlsx_roundtrip():
    df = ri.read_table(ri.template_xlsx(), "t.xlsx")
    assert ri.matches_template(df.columns)
    rows = ri.validate_rows(ri.apply_mapping(df, ri.guess_mapping(df.columns)))
    assert rows[0]["name"] == "Jane Doe" and rows[0]["entering_avg"] == 210 and rows[0]["errors"] == ""


def test_template_header_variations_csv():
    csv = "Name ,USBC ID,Email,Entering Avg,HANDICAP,Lane Assignment,Is Youth,Smart Account ID,Paid Status\n" \
          "Bob Smith,8412-1,bob@x.com,190,27,3,no,,Paid\n"
    df = ri.read_table(csv.encode(), "r.csv")
    assert ri.matches_template(df.columns)
    r = ri.validate_rows(ri.apply_mapping(df, ri.guess_mapping(df.columns)))[0]
    assert (r["entering_avg"], r["lane_assignment"], r["paid_status"], r["errors"]) == (190, 3, "paid", "")


def test_messy_sheet_needs_mapping():
    buf = io.BytesIO()
    pd.DataFrame({"Player": ["Al", "Bea"], "Avg.": ["201", "185"], "Notes": ["x", "y"], "Shift": ["Mon", "Tue"]}).to_excel(buf, index=False)
    df = ri.read_table(buf.getvalue(), "messy.xlsx")
    assert not ri.matches_template(df.columns)
    m = ri.guess_mapping(df.columns)
    assert m["entering_avg"] == "Avg." and m["name"] == "Player" and m["lane_assignment"] is None
    rows = ri.validate_rows(ri.apply_mapping(df, m))
    # no lane / paid columns -> flagged, not defaulted
    assert rows[0]["lane_assignment"] is None and rows[0]["paid_status"] is None
    assert "missing lane" in rows[0]["errors"] and "missing paid status" in rows[0]["errors"]


def test_bad_rows_flagged():
    rows = ri.validate_rows([
        {"name": "", "entering_avg": "abc", "lane_assignment": "2", "paid_status": "paid"},
        {"name": "Cy", "entering_avg": "350", "lane_assignment": "", "paid_status": "maybe", "email": "nope"},
        {"name": "Di", "entering_avg": "180.0", "lane_assignment": "4", "paid_status": "UNPAID", "is_youth": "yes"},
    ])
    assert "missing name" in rows[0]["errors"] and "not a whole number" in rows[0]["errors"]
    assert all(e in rows[1]["errors"] for e in ("out of range", "missing lane", "paid or unpaid", "email"))
    assert rows[2]["errors"] == "" and rows[2]["paid_status"] == "unpaid" and rows[2]["is_youth"] is True


def test_paste_parser_no_silent_defaults():
    r = _fast_structured_text_parser("Marcus Vance (USBC 8412-10921)")[0]
    assert r["entering_avg"] is None and r["lane_assignment"] is None and r["paid_status"] is None
    assert "missing average" in ri.validate_rows([r])[0]["errors"]
