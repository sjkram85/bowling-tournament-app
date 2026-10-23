"""CHUSBC Master Tournament Schedule & Template Library."""

from modules.db_state import get_connection

CHUSBC_TEMPLATES = {
    "CHUSBC Open Championship (Team, Doubles, Singles)": {
        "name": "CHUSBC Annual Open Championship",
        "squad_format": "Team / Doubles / Singles",
        "game_count": 3,
        "default_fee": 30.0,
        "description": "Standard association handicap tournament across Team, Doubles, and Singles divisions."
    },
    "Youth Scholarship Series (USBC Rule 400)": {
        "name": "CHUSBC Youth Scholarship Series",
        "squad_format": "Singles",
        "game_count": 4,
        "default_fee": 25.0,
        "description": "Youth-exclusive scratch/handicap singles event with automatic USBC SMART scholarship escrow routing."
    },
    "Senior Singles Handicap Tournament": {
        "name": "CHUSBC Senior Singles Classic",
        "squad_format": "Singles",
        "game_count": 3,
        "default_fee": 35.0,
        "description": "Open to bowlers age 50 and over with age-bracketed handicap tiers."
    },
    "Holiday No-Tap Fun Tournament": {
        "name": "CHUSBC Holiday No-Tap Mixer",
        "squad_format": "No-Tap",
        "game_count": 3,
        "default_fee": 20.0,
        "description": "Casual fundraising no-tap tournament where knocking down 9 pins counts as a strike."
    }
}

def create_tournament_from_template(template_key: str, host_center: str, pin: str = "6199") -> int:
    """Instantiate a new tournament squad using a pre-configured CHUSBC template."""
    tmpl = CHUSBC_TEMPLATES.get(template_key)
    if not tmpl:
        raise ValueError("Invalid tournament template selected.")

    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO tournaments (name, host_center, squad_format, game_count, pin_verifier, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                """,
                (tmpl["name"], host_center, tmpl["squad_format"], tmpl["game_count"], pin),
            )
            return cur.lastrowid
    finally:
        conn.close()

def save_tournament_as_template(tournament_id: int, custom_template_name: str) -> None:
    """Capture an existing active tournament's configuration and store it as a reusable template."""
    conn = get_connection()
    try:
        tourney = conn.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,)).fetchone()
        if tourney:
            CHUSBC_TEMPLATES[custom_template_name] = {
                "name": tourney["name"],
                "squad_format": tourney["squad_format"],
                "game_count": tourney["game_count"],
                "default_fee": 25.0,
                "description": f"Custom saved template from Tournament #{tournament_id} ({tourney['host_center']})."
            }
    finally:
        conn.close()