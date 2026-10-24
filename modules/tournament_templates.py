"""CHUSBC Master Tournament Schedule & Template Library."""

import json

from modules.db_state import get_connection

ROSE_MURPHY_KEY = "Rose Murphy Memorial Youth Scholarship (Forest Hill Lanes, Dec 6 2026)"
# Facts below come from https://foresthillbowl.com/?page_id=326 (checked Oct 23, 2026).
# Anything the page doesn't say is left editable and listed in "unconfirmed" for the TD to check on the flyer.
ROSE_MURPHY_PRESET = {
    "name": "2nd Annual Rose Murphy Memorial Youth Scholarship",
    "squad_format": "Singles",
    "game_count": 3,
    "default_fee": 0.0,
    "description": ("Youth-only (Maryland USBC), handicap 90% of 220, 3 games on the same pair. Average divisions 1/2/3, "
                    "boys and girls ranked separately. Guaranteed SMART scholarships (no cash, Rule 400). "
                    "Sun Dec 6, 2026 at 10:00 AM. Entry deadline 11/29/2026, NO walk-ins. $30 fee paid at the front desk."),
    "locked": {
        "host_center": "FHL",
        "event_start": "2026-12-06 10:00",
        "entry_deadline": "2026-11-29",
        "no_walkins": 1,
        "youth_only": 1,
        "require_smart": 1,
        "require_usbc": 1,
        "require_gender": 1,
        "require_birthdate": 1,
        "fees_at_front_desk": 1,  # $30 ($15 bowling + $15 scholarships) collected by Forest Hill front desk, not Prism
        "handicap_pct": 90,
        "handicap_base": 220,
        "grouping": "division_gender",  # confirmed by Scott: average division x boys/girls
        "divisions": [
            {"name": "Division 1", "min_avg": 160, "max_avg": None, "first_place": 500},
            {"name": "Division 2", "min_avg": 126, "max_avg": 159, "first_place": 300},
            {"name": "Division 3", "min_avg": None, "max_avg": 125, "first_place": 150},
        ],
        # Informational only (not used for ranking): age as of July 31, 2026.
        "age_cutoff": "2026-07-31",
        "age_groups": [
            {"name": "Preps", "min_age": None, "max_age": 11},
            {"name": "Juniors", "min_age": 12, "max_age": 14},
            {"name": "Majors", "min_age": 15, "max_age": 18},
        ],
        "rules_text": [
            "Handicap: 90% of 220. Bowlers without a qualifying average bowl scratch.",
            "3 games on the same pair of lanes.",
            "Boys and girls ranked separately within each average division.",
            "Top qualifiers in each division (boys and girls) bowl a 1-game stepladder final for the handicap championship: "
            "top 5 if more than 25 in the division, otherwise top 3.",
            "Ties for a finalist spot: one-game roll-off; if still tied, a 9th and 10th frame roll-off.",
            "Scholarships: at least a 1 in 5 ratio, all deposited to USBC SMART accounts (no cash). "
            "The tournament committee decides the final amounts.",
            "Eligibility: certified in a 2026-27 Maryland USBC youth league with 12 games by Nov 15, 2026.",
            "Average: highest 2025-26 Maryland youth average (21+ games); if none, current 2026-27 average "
            "(12+ games, USBC Rule 319a-1) with a league standing sheet; otherwise bowl scratch.",
            "Birth date and USBC ID required on the entry.",
        ],
    },
    "unconfirmed": [
        "Lane pairs and check-in time",
        "Scholarship amounts for 2nd place and below (committee decides; at least 1 in 5 ratio)",
        "Exactly 25 bowlers in a division: top 3 or top 5? (form says 'more than 25' / 'less than 25')",
        "Which division a 'bowls scratch' bowler goes in",
    ],
}

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
    ROSE_MURPHY_KEY: ROSE_MURPHY_PRESET,
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
            locked = tmpl.get("locked")
            if locked:
                host_center = locked["host_center"]
            cur = conn.execute(
                """
                INSERT INTO tournaments (name, host_center, squad_format, game_count, pin_verifier, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                """,
                (tmpl["name"], host_center, tmpl["squad_format"], tmpl["game_count"], pin),
            )
            t_id = cur.lastrowid
            if locked:
                conn.execute(
                    """UPDATE tournaments SET preset_key = ?, rules_locked = 1, youth_only = ?, require_smart = ?,
                       no_walkins = ?, entry_deadline = ?, event_start = ?, divisions_json = ?, unconfirmed_json = ?,
                       fees_at_front_desk = ?, entry_fee = CASE WHEN ? THEN 0 ELSE entry_fee END,
                       require_usbc = ?, require_gender = ?, require_birthdate = ?, handicap_pct = ?, handicap_base = ?,
                       grouping = ?, age_cutoff = ?, age_groups_json = ?, rules_text = ?
                       WHERE id = ?""",
                    (template_key, locked["youth_only"], locked["require_smart"], locked["no_walkins"],
                     locked["entry_deadline"], locked["event_start"], json.dumps(locked["divisions"]),
                     json.dumps(tmpl.get("unconfirmed", [])),
                     locked.get("fees_at_front_desk", 0), locked.get("fees_at_front_desk", 0),
                     locked.get("require_usbc", 0), locked.get("require_gender", 0), locked.get("require_birthdate", 0),
                     locked.get("handicap_pct", 90), locked.get("handicap_base", 220), locked.get("grouping", "division"),
                     locked.get("age_cutoff"), json.dumps(locked.get("age_groups", [])),
                     json.dumps(locked.get("rules_text", [])), t_id),
                )
            return t_id
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