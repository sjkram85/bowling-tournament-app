"""The Rose Murphy weekend dry run reprints the same 40-bowler report and names a champion in every group."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rose_murphy_dry_run.py"
REPORT = ROOT / "artifacts" / "rose_murphy_dry_run_standings.md"
QUALIFYING = ROOT / "artifacts" / "rose_murphy_dry_run_qualifying.csv"


def _load():
    spec = importlib.util.spec_from_file_location("rose_murphy_dry_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_roster_covers_divisions_and_both_genders():
    dry = _load()
    roster = dry.build_roster()
    assert len(roster) == 40
    assert len({row["name"] for row in roster}) == 40
    assert {row["gender"] for row in roster} == {"Boys", "Girls"}
    counts = {}
    for row in roster:
        counts[(row["division_name"], row["gender"])] = counts.get((row["division_name"], row["gender"]), 0) + 1
        assert row["paid_status"] == "paid"
        assert row["usbc_id"] and row["smart_account_id"] and row["birth_date"]
        assert 1 <= row["lane_assignment"] <= 20
    assert counts[("Division 2", "Boys")] == 26
    assert counts[("Division 1", "Boys")] == 3
    assert counts[("Division 3", "Girls")] == 2


def test_dry_run_matches_committed_report_and_names_champions(tmp_path):
    dry = _load()
    result = dry.run(tmp_path / "t.db", tmp_path / "out")
    report = (tmp_path / "out" / dry.REPORT_NAME).read_text(encoding="utf-8")
    assert report == REPORT.read_text(encoding="utf-8")
    assert result["bowler_count"] == 40
    assert result["is_practice"] == 0
    assert len(result["champions"]) == 6
    top5 = [c for c in result["champions"] if c["rule"] == "Top 5"]
    top3 = [c for c in result["champions"] if c["rule"] == "Top 3"]
    assert len(top5) == 1 and top5[0]["field"] == 26 and top5[0]["cut"] == 5
    assert len(top3) == 5
    assert all(c["champion"] for c in result["champions"])
    for name in result["names"]:
        assert name in report
    for champ in result["champions"]:
        assert f"**Champion: {champ['champion']}**" in report
    csv_text = (tmp_path / "out" / dry.QUALIFYING_CSV).read_text(encoding="utf-8")
    assert csv_text == QUALIFYING.read_text(encoding="utf-8")
    assert "Leo Park,Boys,151,62," in csv_text
    ladder = (tmp_path / "out" / dry.STEPLADDER_CSV).read_text(encoding="utf-8")
    assert ladder.count(",completed") == ladder.count("\n") - 1
    assert "Ryan Foster" in report and "Division 2" in report
