import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st


DATABASE_PATH = Path(os.environ.get("PRISM_DB_PATH", Path(__file__).with_name("prism_operational.db")))
USER_COLUMNS = [
    "username", "name", "email", "password_hash", "role", "status",
    "center_id", "preferred_mode", "must_change_password", "created_at",
]
ARCHIVE_COLUMNS = [
    "tournament_name", "center", "division", "date", "entries",
    "champion", "pdf_data", "archived_by",
]


def get_sqlite_conn():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_sqlite_tables():
    game_columns = ",\n".join(
        f"game_{game} INTEGER NOT NULL DEFAULT 0, g{game}_verified_by TEXT, g{game}_verified_at TEXT"
        for game in range(1, 11)
    )
    conn = get_sqlite_conn()
    try:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS live_roster (
                usbc_id TEXT PRIMARY KEY,
                bowler TEXT NOT NULL DEFAULT '',
                average INTEGER NOT NULL DEFAULT 200,
                starting_lane INTEGER NOT NULL DEFAULT 1,
                division TEXT NOT NULL DEFAULT 'Open',
                team_name TEXT NOT NULL DEFAULT 'Singles',
                {game_columns},
                paid INTEGER NOT NULL DEFAULT 0,
                checked_in INTEGER NOT NULL DEFAULT 0,
                is_sub INTEGER NOT NULL DEFAULT 0,
                subbing_for TEXT,
                last_updated_by TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(live_roster)").fetchall()
        }
        required_columns = {
            "bowler": "TEXT NOT NULL DEFAULT ''",
            "average": "INTEGER NOT NULL DEFAULT 200",
            "starting_lane": "INTEGER NOT NULL DEFAULT 1",
            "division": "TEXT NOT NULL DEFAULT 'Open'",
            "team_name": "TEXT NOT NULL DEFAULT 'Singles'",
            "paid": "INTEGER NOT NULL DEFAULT 0",
            "checked_in": "INTEGER NOT NULL DEFAULT 0",
            "is_sub": "INTEGER NOT NULL DEFAULT 0",
            "subbing_for": "TEXT",
            "last_updated_by": "TEXT",
            "updated_at": "TEXT",
        }
        for game in range(1, 11):
            required_columns[f"game_{game}"] = "INTEGER NOT NULL DEFAULT 0"
            required_columns[f"g{game}_verified_by"] = "TEXT"
            required_columns[f"g{game}_verified_at"] = "TEXT"
        for column, definition in required_columns.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE live_roster ADD COLUMN {column} {definition}")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tournament_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                config_json TEXT NOT NULL,
                brackets_json TEXT NOT NULL DEFAULT '[]',
                td_pins_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                td TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS staff_users (
                username TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'td',
                status TEXT NOT NULL DEFAULT 'active',
                center_id TEXT NOT NULL DEFAULT 'association',
                preferred_mode TEXT NOT NULL DEFAULT 'Advanced',
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tournament_archives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_name TEXT NOT NULL,
                center TEXT NOT NULL DEFAULT '',
                division TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL DEFAULT '',
                entries INTEGER NOT NULL DEFAULT 0,
                champion TEXT NOT NULL DEFAULT '',
                pdf_data TEXT NOT NULL DEFAULT '',
                archived_by TEXT NOT NULL DEFAULT ''
            );
        """)
        conn.commit()
    finally:
        conn.close()


def log_audit_event(action: str, details: str = ""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    actor = (
        st.session_state.get("mobile_scorer_td")
        or st.session_state.get("td_name")
        or st.session_state.get("username", "Staff")
    )
    action_text = str(action)
    details_text = str(details or "")
    conn = get_sqlite_conn()
    try:
        conn.execute(
            "INSERT INTO audit_log (timestamp, td, action, details) VALUES (?, ?, ?, ?)",
            (timestamp, actor, action_text, details_text),
        )
        conn.commit()
    finally:
        conn.close()
    st.session_state.setdefault("audit_trail", []).append({
        "timestamp": timestamp,
        "td": actor,
        "action": action_text,
        "details": details_text,
    })


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _as_int(value, default=0):
    try:
        return default if value is None or pd.isna(value) else int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value):
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    return bool(value)


def write_active_tournament_state(config, roster_df, brackets, sync_to_cloud=False):
    del sync_to_cloud
    init_sqlite_tables()
    roster = roster_df.to_dict(orient="records") if isinstance(roster_df, pd.DataFrame) else list(roster_df or [])
    conn = get_sqlite_conn()
    try:
        with conn:
            conn.execute("DELETE FROM live_roster")
            for index, row in enumerate(roster):
                bowler = str(row.get("Bowler", row.get("bowler", "")) or "")
                raw_id = row.get("USBC ID", row.get("usbc_id", ""))
                if raw_id is None or pd.isna(raw_id) or not str(raw_id).strip():
                    raw_id = f"LOCAL-{index + 1}-{bowler.strip().lower().replace(' ', '-')}"
                usbc_id = str(raw_id)
                values = {
                    "usbc_id": usbc_id,
                    "bowler": bowler,
                    "average": _as_int(row.get("Average", row.get("average", 200)), 200),
                    "starting_lane": _as_int(row.get("Starting Lane", row.get("starting_lane", 1)), 1),
                    "division": str(row.get("Division", row.get("division", "Open")) or "Open"),
                    "team_name": str(row.get("Team_Name", row.get("team_name", "Singles")) or "Singles"),
                    "paid": int(_as_bool(row.get("Paid", row.get("paid", False)))),
                    "checked_in": int(_as_bool(row.get("Checked_In", row.get("checked_in", False)))),
                    "is_sub": int(_as_bool(row.get("is_sub", False))),
                    "subbing_for": None if pd.isna(row.get("subbing_for")) else row.get("subbing_for"),
                    "last_updated_by": st.session_state.get("username", "Staff"),
                }
                for game in range(1, 11):
                    values[f"game_{game}"] = _as_int(row.get(f"Game {game}", row.get(f"game_{game}", 0)))
                columns = list(values)
                columns.extend(f"g{game}_{suffix}" for game in range(1, 11) for suffix in ("verified_by", "verified_at"))
                values.update({
                    f"g{game}_{suffix}": row.get(f"g{game}_{suffix}")
                    for game in range(1, 11)
                    for suffix in ("verified_by", "verified_at")
                })
                conn.execute(
                    f"INSERT INTO live_roster ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [values[column] for column in columns],
                )
            conn.execute(
                """INSERT INTO tournament_state (id, config_json, brackets_json, td_pins_json, updated_at)
                   VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json,
                       brackets_json=excluded.brackets_json, td_pins_json=excluded.td_pins_json,
                       updated_at=CURRENT_TIMESTAMP""",
                (
                    json.dumps(config or {}, default=_json_default),
                    json.dumps(brackets or [], default=_json_default),
                    json.dumps(st.session_state.get("td_pins", {}), default=_json_default),
                ),
            )
    finally:
        conn.close()
    return True


def fetch_active_tournament_state():
    init_sqlite_tables()
    conn = get_sqlite_conn()
    try:
        state = conn.execute("SELECT * FROM tournament_state WHERE id = 1").fetchone()
        if state is None:
            return None
        roster_rows = conn.execute(
            "SELECT * FROM live_roster ORDER BY starting_lane, bowler"
        ).fetchall()
        roster = []
        for row in roster_rows:
            item = dict(row)
            item.update({
                "USBC ID": item.get("usbc_id", ""),
                "Bowler": item.get("bowler", ""),
                "Average": item.get("average", 200),
                "Starting Lane": item.get("starting_lane", 1),
                "Division": item.get("division", "Open"),
                "Team_Name": item.get("team_name", "Singles"),
                "Paid": bool(item.get("paid", 0)),
                "Checked_In": bool(item.get("checked_in", 0)),
                "is_sub": bool(item.get("is_sub", 0)),
            })
            for game in range(1, 11):
                item[f"Game {game}"] = item.get(f"game_{game}", 0)
            roster.append(item)
        return {
            "config": json.loads(state["config_json"]),
            "roster": pd.DataFrame(roster),
            "brackets": json.loads(state["brackets_json"]),
            "td_pins": json.loads(state["td_pins_json"]),
        }
    finally:
        conn.close()


def fetch_archives_df():
    init_sqlite_tables()
    conn = get_sqlite_conn()
    try:
        return pd.read_sql_query(
            "SELECT tournament_name, center, division, date, entries, champion, pdf_data, archived_by "
            "FROM tournament_archives ORDER BY id DESC",
            conn,
        )
    finally:
        conn.close()


def write_archives_df(archives_df):
    init_sqlite_tables()
    frame = archives_df if isinstance(archives_df, pd.DataFrame) else pd.DataFrame(archives_df)
    conn = get_sqlite_conn()
    try:
        with conn:
            conn.execute("DELETE FROM tournament_archives")
            for column in ARCHIVE_COLUMNS:
                if column not in frame:
                    frame[column] = 0 if column == "entries" else ""
            conn.executemany(
                """INSERT INTO tournament_archives
                   (tournament_name, center, division, date, entries, champion, pdf_data, archived_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    tuple(row[column] if pd.notna(row[column]) else "" for column in ARCHIVE_COLUMNS)
                    for _, row in frame.iterrows()
                ],
            )
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def fetch_users_df():
    init_sqlite_tables()
    conn = get_sqlite_conn()
    try:
        return pd.read_sql_query(
            f"SELECT {', '.join(USER_COLUMNS)} FROM staff_users ORDER BY username", conn
        )
    finally:
        conn.close()


def write_users_df(users_df):
    init_sqlite_tables()
    frame = users_df if isinstance(users_df, pd.DataFrame) else pd.DataFrame(users_df)
    for column in USER_COLUMNS:
        if column not in frame:
            frame[column] = False if column == "must_change_password" else ""
    conn = get_sqlite_conn()
    try:
        with conn:
            conn.execute("DELETE FROM staff_users")
            conn.executemany(
                f"INSERT INTO staff_users ({', '.join(USER_COLUMNS)}) VALUES ({', '.join('?' for _ in USER_COLUMNS)})",
                [
                    tuple(
                        int(bool(row[column])) if column == "must_change_password" else str(row[column] or "")
                        for column in USER_COLUMNS
                    )
                    for _, row in frame.iterrows()
                ],
            )
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()