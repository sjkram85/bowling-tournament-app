"""Optional per-event logos: a partner/host logo and an event logo (PDF header + kiosk).

Logos live in their own small table so normal tournament lookups stay light.
Kinds: 'partner' (dark lettering, for white paper), 'partner_kiosk' (light lettering, dark kiosk), 'event'.
Events without logos are unchanged.
"""

from __future__ import annotations

import base64
import io
import threading
import time
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


# Logo blobs are a few hundred KB. Re-downloading them on every hub click (the setup
# expander runs even while collapsed) dominated a Turso rerun. Kept for a minute, and
# dropped the moment this process writes or restores logos.
_LOGO_TTL = 60.0
_logo_lock = threading.Lock()
_logo_cache: dict[tuple, tuple[float, dict]] = {}
_logo_ensured: set[str] = set()


def _db_token() -> str:
    from modules.db_state import DB_PATH, turso_config
    cfg = turso_config()
    return "turso:" + cfg[0] if cfg else "file:" + str(DB_PATH)


def clear_logo_cache(tournament_id: int | None = None) -> None:
    """Forget cached logo bytes. No id drops every event (restore / replace)."""
    with _logo_lock:
        if tournament_id is None:
            _logo_cache.clear()
            return
        _logo_cache.pop((_db_token(), int(tournament_id)), None)


def _ensure(conn) -> None:
    token = _db_token()
    with _logo_lock:
        if token in _logo_ensured:
            return
    conn.execute("""CREATE TABLE IF NOT EXISTS event_logos (
        tournament_id INTEGER NOT NULL, kind TEXT NOT NULL, data BLOB NOT NULL,
        PRIMARY KEY (tournament_id, kind))""")
    with _logo_lock:
        _logo_ensured.add(token)


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
        clear_logo_cache(tournament_id)
    finally:
        conn.close()


def get_logos(tournament_id: int) -> dict[str, bytes]:
    key = (_db_token(), int(tournament_id))
    now = time.monotonic()
    with _logo_lock:
        hit = _logo_cache.get(key)
        if hit is not None and now - hit[0] < _LOGO_TTL:
            return dict(hit[1])
    conn = get_connection()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT kind, data FROM event_logos WHERE tournament_id = ?", (tournament_id,)).fetchall()
        data = {r["kind"]: bytes(r["data"]) for r in rows}
    except Exception:
        with _logo_lock:
            _logo_ensured.discard(key[0])
        return {}
    finally:
        conn.close()
    with _logo_lock:
        _logo_cache[key] = (now, data)
    return dict(data)


def set_partner_name(tournament_id: int, name: str) -> None:
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE tournaments SET partner_name = ? WHERE id = ?", ((name or "").strip(), tournament_id))
        from modules.run_memo import forget
        forget(("tournament", str(tournament_id)))
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
