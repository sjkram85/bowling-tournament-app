"""Optional per-event logos: a partner/host logo and an event logo (PDF header + kiosk).

Logos live in their own small table so normal tournament lookups stay light.
Kinds: 'partner' (dark lettering, for white paper), 'partner_kiosk' (light lettering, dark kiosk), 'event'.
Events without logos are unchanged.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from modules.db_state import get_connection

KINDS = ("partner", "partner_kiosk", "event")
LOGO_DIR = Path(__file__).resolve().parent.parent / "assets" / "logos"
MAX_BYTES = 2_000_000

# Logos bundled with presets: {preset_key: {"partner_name":..., kind: filename}}
PRESET_LOGOS = {
    "rose_murphy": {
        "partner_name": "Forest Hill Lanes",
        "partner": "forest_hill_lanes_dark.png",
        "partner_kiosk": "forest_hill_lanes_white.png",
        "event": "rose_murphy_2nd_annual.png",
    }
}


def _ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS event_logos (
        tournament_id INTEGER NOT NULL, kind TEXT NOT NULL, data BLOB NOT NULL,
        PRIMARY KEY (tournament_id, kind))""")


def validate_image(data: bytes) -> bytes:
    """Return PNG bytes for an uploaded image, or raise ValueError with a plain message."""
    if not data:
        raise ValueError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise ValueError("That image is too big (2 MB max).")
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise ValueError("That file isn't a picture Prism can read (use PNG or JPG).")
    if max(im.size) > 1600:
        im.thumbnail((1600, 1600))
    out = io.BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue()


def set_logo(tournament_id: int, kind: str, data: bytes | None) -> None:
    if kind not in KINDS:
        raise ValueError(kind)
    conn = get_connection()
    try:
        _ensure(conn)
        with conn:
            conn.execute("DELETE FROM event_logos WHERE tournament_id = ? AND kind = ?", (tournament_id, kind))
            if data:
                conn.execute("INSERT INTO event_logos (tournament_id, kind, data) VALUES (?,?,?)",
                             (tournament_id, kind, data))
    finally:
        conn.close()


def get_logos(tournament_id: int) -> dict[str, bytes]:
    conn = get_connection()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT kind, data FROM event_logos WHERE tournament_id = ?", (tournament_id,)).fetchall()
        return {r["kind"]: bytes(r["data"]) for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def set_partner_name(tournament_id: int, name: str) -> None:
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE tournaments SET partner_name = ? WHERE id = ?", ((name or "").strip(), tournament_id))
    finally:
        conn.close()


def apply_preset_logos(tournament_id: int, logo_key: str | None) -> None:
    spec = PRESET_LOGOS.get(logo_key or "")
    if not spec:
        return
    for kind in KINDS:
        f = LOGO_DIR / spec.get(kind, "")
        if spec.get(kind) and f.is_file():
            set_logo(tournament_id, kind, f.read_bytes())
    set_partner_name(tournament_id, spec.get("partner_name", ""))


def partner_heading(partner_name: str | None) -> str:
    return f"Hosted by {partner_name} in partnership with Cecil Harford USBC • USBC Sanctioned" if partner_name else ""


def data_uri(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()
