import io
import subprocess

import pytest
from PIL import Image

from modules import db_state, event_logos, kiosk_data
from modules.reports import build_certified_pdf
from modules.tournament_templates import ROSE_MURPHY_KEY, create_tournament_from_template
from views.kiosk import build_html


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    yield


def _plain_event():
    conn = db_state.get_connection()
    with conn:
        tid = conn.execute("INSERT INTO tournaments (name, host_center, game_count) VALUES ('Plain Open','FHL',3)").lastrowid
        b = conn.execute("INSERT INTO bowlers (tournament_id, name) VALUES (?, 'Al')", (tid,)).lastrowid
        conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score) VALUES (?,?,1,200,200)", (tid, b))
    conn.close()
    return tid


def _txt(pdf, tmp_path):
    f = tmp_path / "x.pdf"; f.write_bytes(pdf)
    return " ".join(subprocess.run(["pdftotext", str(f), "-"], capture_output=True, text=True).stdout.split())


def _images(pdf, tmp_path):
    f = tmp_path / "x.pdf"; f.write_bytes(pdf)
    out = subprocess.run(["pdfimages", "-list", str(f)], capture_output=True, text=True).stdout
    return len([l for l in out.splitlines()[2:] if " image " in l])


def test_rose_murphy_preset_bundles_logos(db, tmp_path):
    tid = create_tournament_from_template(ROSE_MURPHY_KEY, "ANY")
    lg = event_logos.get_logos(tid)
    assert set(lg) == {"partner", "partner_kiosk", "event"}
    pdf = build_certified_pdf(tid, "TD")
    assert "Hosted by Forest Hill Lanes in partnership with Cecil Harford USBC • USBC Sanctioned" in _txt(pdf, tmp_path)
    assert _images(pdf, tmp_path) >= 3
    board = kiosk_data.load_board(tid)
    assert board["partner_logo"].startswith("data:image/png;base64,") and board["event_logo"]
    assert "k-plogo" in build_html(board, 0, "now")


def test_event_without_logos_unchanged(db, tmp_path):
    tid = _plain_event()
    pdf = build_certified_pdf(tid, "TD")
    assert "Hosted by" not in _txt(pdf, tmp_path)
    board = kiosk_data.load_board(tid)
    assert "partner_logo" not in board and "k-plogo" not in build_html(board, 0, "now")


def test_upload_validate_set_and_remove(db):
    tid = _plain_event()
    buf = io.BytesIO(); Image.new("RGB", (3000, 300), "navy").save(buf, "JPEG")
    png = event_logos.validate_image(buf.getvalue())
    assert Image.open(io.BytesIO(png)).size[0] == 1600
    event_logos.set_logo(tid, "partner", png)
    assert "partner" in event_logos.get_logos(tid)
    event_logos.set_logo(tid, "partner", None)
    assert event_logos.get_logos(tid) == {}
    with pytest.raises(ValueError):
        event_logos.validate_image(b"not an image")


def test_logo_cache_follows_writes_and_stays_on_its_own_database(db, tmp_path, monkeypatch):
    tid = _plain_event()
    buf = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    png = event_logos.validate_image(buf.getvalue())
    event_logos.set_logo(tid, "event", png)
    assert event_logos.get_logos(tid)["event"] == event_logos.get_logos(tid)["event"]
    event_logos.set_logo(tid, "event", None)
    assert event_logos.get_logos(tid) == {}
    # A different file can reuse tournament id 1; it must not see the other file's cache.
    other = tmp_path / "other.db"
    monkeypatch.setattr(db_state, "DB_PATH", other)
    db_state.init_db()
    tid2 = _plain_event()
    assert event_logos.get_logos(tid2) == {}


def test_partner_name_migration_column(db):
    tid = _plain_event()
    event_logos.set_partner_name(tid, " Forest Hill Lanes ")
    from modules.standings import get_tournament
    assert get_tournament(tid)["partner_name"] == "Forest Hill Lanes"
