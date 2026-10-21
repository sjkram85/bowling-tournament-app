import json
from datetime import datetime

import db_state


BOWLERS = [
    ("TEST-001", "Avery Morgan", 180, 1, 198, 205),
    ("TEST-002", "Jordan Lee", 185, 1, 214, 190),
    ("TEST-003", "Casey Brooks", 190, 2, 202, 217),
    ("TEST-004", "Riley Parker", 195, 2, 188, 211),
    ("TEST-005", "Taylor Quinn", 200, 3, 224, 208),
    ("TEST-006", "Morgan Ellis", 205, 3, 197, 219),
    ("TEST-007", "Cameron Reed", 210, 4, 216, 203),
    ("TEST-008", "Drew Bennett", 220, 4, 209, 226),
]

TOURNAMENT_CONFIG = {
    "name": "CHUSBC Open Championship Test",
    "games_count": 3,
    "hdcp_base": 220,
    "hdcp_pct": 0.90,
}


def main():
    db_state.init_sqlite_tables()
    conn = db_state.get_sqlite_conn()
    try:
        with conn:
            conn.executemany(
                """INSERT INTO live_roster (
                       usbc_id, bowler, average, starting_lane, division, team_name,
                       game_1, game_2, paid, checked_in, last_updated_by
                   ) VALUES (?, ?, ?, ?, 'Open', 'Singles', ?, ?, 1, 1, 'Test Data Seeder')
                   ON CONFLICT(usbc_id) DO UPDATE SET
                       bowler=excluded.bowler,
                       average=excluded.average,
                       starting_lane=excluded.starting_lane,
                       division=excluded.division,
                       team_name=excluded.team_name,
                       game_1=excluded.game_1,
                       game_2=excluded.game_2,
                       paid=excluded.paid,
                       checked_in=excluded.checked_in,
                       last_updated_by=excluded.last_updated_by,
                       updated_at=CURRENT_TIMESTAMP""",
                BOWLERS,
            )
            conn.execute(
                """INSERT INTO tournament_state (id, config_json, brackets_json, td_pins_json)
                   VALUES (1, ?, '[]', '{}')
                   ON CONFLICT(id) DO UPDATE SET
                       config_json=excluded.config_json,
                       updated_at=CURRENT_TIMESTAMP""",
                (json.dumps(TOURNAMENT_CONFIG),),
            )
            conn.execute(
                "INSERT INTO audit_log (timestamp, td, action, details) VALUES (?, ?, ?, ?)",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Test Data Seeder",
                    "TEST_DATA_SEEDED",
                    "Inserted or updated 8 test bowlers on lanes 1-4.",
                ),
            )
    finally:
        conn.close()

    print("Seeded 8 test bowlers and tournament metadata.")


if __name__ == "__main__":
    main()
