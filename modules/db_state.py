def log_desk_action(user_name: str, role: str, action_description: str) -> None:
    """Record an operational action to the immutable audit log."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action_description TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO audit_log (user_name, role, action_description) VALUES (?, ?, ?)",
                (user_name, role, action_description),
            )
    finally:
        conn.close()