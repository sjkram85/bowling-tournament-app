"""Tournament events and scores come back after the local database file is wiped.

The mailbox is not contacted. A memory store stands in for the CHUSBC Gmail
label, and a fake IMAP session checks that a large snapshot is split and that
only the latest copy is kept.
"""

import imaplib
import sqlite3
import time

import pytest

from modules import auth, db_state, staff_vault, tournament_vault
from modules.auth import authenticate, create_staff_user
from modules.td_team import heartbeat
from modules.tournament_vault import (
    MAILBOX,
    OFF_NOTICE,
    SAVED_NOTICE,
    GmailTournamentStore,
    VaultError,
    decode_snapshot,
    encode_snapshot,
    fire_deadline,
    statement_changes_tournament,
)

PASSPHRASE = "test-vault-key-" + ("k" * 32)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISM_TOURNAMENT_VAULT", "on")
    monkeypatch.setenv("STAFF_VAULT_KEY", PASSPHRASE)
    monkeypatch.delenv("CHUSBC_GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    store = tournament_vault.MemoryStore()
    tournament_vault.use_store(store)
    db_state.init_db()
    return store


def _wipe(tmp_path):
    for name in ("t.db", "t.db-wal", "t.db-shm"):
        path = tmp_path / name
        if path.exists():
            path.unlink()
    db_state.init_db()


def _names():
    conn = db_state.get_connection()
    try:
        rows = conn.execute("SELECT name FROM tournaments ORDER BY id").fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def _lane_and_score():
    conn = db_state.get_connection()
    try:
        row = conn.execute(
            "SELECT b.lane_assignment, s.scratch_score FROM bowlers b "
            "JOIN scores s ON s.bowler_id = b.id"
        ).fetchone()
    finally:
        conn.close()
    return (row[0], row[1]) if row else None


def _insert_squad(name="Saturday Sweeper", lane=12, score=214):
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO tournaments (name, host_center) VALUES (?, 'HL')",
            (name,),
        )
        tid = conn.execute("SELECT id FROM tournaments WHERE name = ?", (name,)).fetchone()[0]
        conn.execute(
            "INSERT INTO bowlers (tournament_id, name, lane_assignment) VALUES (?, 'Ann', ?)",
            (tid, lane),
        )
        bid = conn.execute(
            "SELECT id FROM bowlers WHERE tournament_id = ? AND name = 'Ann'",
            (tid,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score, total_score) "
            "VALUES (?, ?, 1, ?, ?)",
            (tid, bid, score, score),
        )
    conn.close()
    return tid


def _snapshot_names(payload):
    decoded = decode_snapshot(payload, PASSPHRASE)
    conn = sqlite3.connect(":memory:")
    try:
        # sqlite3 cannot open bytes. Replay through a backup of a temp file is heavier;
        # the deserialize API is available on this interpreter.
        conn.deserialize(decoded["sqlite"])
        rows = conn.execute("SELECT name FROM tournaments ORDER BY id").fetchall()
        return [row[0] for row in rows], decoded
    finally:
        conn.close()


def _tiny_db(name):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE tournaments (id INTEGER PRIMARY KEY, name TEXT, host_center TEXT)"
    )
    conn.execute(
        "CREATE TABLE bowlers (id INTEGER PRIMARY KEY, tournament_id INTEGER, name TEXT)"
    )
    conn.execute(
        "CREATE TABLE scores (id INTEGER PRIMARY KEY, tournament_id INTEGER, bowler_id INTEGER, "
        "game_number INTEGER, scratch_score INTEGER)"
    )
    conn.execute(
        "CREATE TABLE staff_users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)"
    )
    conn.execute("INSERT INTO tournaments (name, host_center) VALUES (?, 'HL')", (name,))
    raw = conn.serialize()
    conn.close()
    return raw


def test_fire_deadline_waits_for_a_quiet_gap_but_not_forever():
    assert fire_deadline(100, 100, 20, 60) == 120
    assert fire_deadline(150, 100, 20, 60) == 160


def test_heartbeat_and_staff_writes_are_not_tournament_changes():
    assert statement_changes_tournament(
        "INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score) VALUES (1, 1, 1, 200)"
    )
    assert statement_changes_tournament("UPDATE bowlers SET lane_assignment = 4 WHERE id = 1")
    assert statement_changes_tournament("delete from tournaments where id = 1")
    assert not statement_changes_tournament(
        "INSERT INTO td_presence_events (username, display_name, tournament_id) VALUES ('a', 'A', 1)"
    )
    assert not statement_changes_tournament("UPDATE staff_users SET role = 'td' WHERE id = 1")
    assert not statement_changes_tournament(
        "INSERT INTO audit_log (user_name, role, action_description) VALUES ('A', 'td', 'x')"
    )
    assert not statement_changes_tournament("CREATE TABLE tournaments (id INTEGER)")


def test_an_empty_desk_does_not_read_the_vault_on_every_rerun(vault):
    loads = vault.loads
    db_state.init_db()
    db_state.init_db()
    assert vault.loads == loads
    assert vault.saves == 0


def test_scores_and_lanes_survive_a_wiped_database(vault, tmp_path):
    assert vault.saves == 0
    _insert_squad()
    assert vault.saves == 1
    names, decoded = _snapshot_names(vault.payload)
    assert names == ["Saturday Sweeper"]
    assert b"SENTINEL" not in decoded["sqlite"]
    assert tournament_vault.notice() == SAVED_NOTICE
    loads = vault.loads
    saves = vault.saves
    db_state.init_db()
    db_state.init_db()
    assert vault.loads == loads
    assert vault.saves == saves

    _wipe(tmp_path)
    assert _names() == ["Saturday Sweeper"]
    assert _lane_and_score() == (12, 214)
    assert db_state.using_turso() is False
    assert db_state.turso_config() is None


def test_a_rolled_back_score_is_not_saved(vault):
    conn = db_state.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO tournaments (name, host_center) VALUES ('Nope', 'HL')"
            )
            raise RuntimeError("nope")
    except RuntimeError:
        pass
    conn.close()
    assert vault.saves == 0
    assert _names() == []


def test_presence_heartbeat_does_not_save(vault):
    tid = _insert_squad()
    saves = vault.saves
    heartbeat("scott", "Scott Kramer", tid)
    heartbeat("scott", "Scott Kramer", tid)
    assert vault.saves == saves


def test_staff_hash_is_not_in_the_tournament_snapshot(vault):
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO staff_users (username, password_hash, display_name, role) "
            "VALUES ('friend', 'SENTINEL-HASH-not-a-password', 'Scott Friend', 'td')"
        )
    conn.close()
    assert vault.saves == 0
    _insert_squad()
    _names_in_snap, decoded = _snapshot_names(vault.payload)
    assert b"SENTINEL-HASH-not-a-password" not in decoded["sqlite"]
    assert "friend" not in decoded["sqlite"].decode("utf-8", errors="ignore")


def test_deleting_the_last_event_stays_gone_after_a_wipe(vault, tmp_path):
    _insert_squad()
    conn = db_state.get_connection()
    with conn:
        conn.execute("DELETE FROM tournaments")
    conn.close()
    names, _decoded = _snapshot_names(vault.payload)
    assert names == []
    loads = vault.loads
    db_state.init_db()
    db_state.init_db()
    assert vault.loads == loads
    _wipe(tmp_path)
    assert _names() == []


def test_a_failed_read_does_not_overwrite_or_retry_every_startup(vault):
    _insert_squad("Saturday Sweeper")
    original = bytes(vault.payload)
    vault.fail_load = True
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO tournaments (name, host_center) VALUES ('Sunday', 'HL')"
        )
    conn.close()
    assert vault.payload == original
    assert _names() == ["Saturday Sweeper", "Sunday"]
    assert "could not be read" in tournament_vault.notice()
    loads = vault.loads
    db_state.init_db()
    assert vault.loads == loads

    vault.fail_load = False
    conn = db_state.get_connection()
    with conn:
        conn.execute("UPDATE tournaments SET host_center = 'FHL' WHERE name = 'Sunday'")
    conn.close()
    names, _decoded = _snapshot_names(vault.payload)
    assert names == ["Saturday Sweeper", "Sunday"]
    assert tournament_vault.LAST_ERROR == ""


def test_a_damaged_snapshot_does_not_wipe_local_events(vault):
    _insert_squad()
    vault.payload = b"this is not a tournament vault"
    conn = db_state.get_connection()
    with conn:
        conn.execute("UPDATE tournaments SET host_center = 'FHL' WHERE name = 'Saturday Sweeper'")
    conn.close()
    assert vault.payload == b"this is not a tournament vault"
    assert _names() == ["Saturday Sweeper"]
    assert "could not be read" in tournament_vault.LAST_ERROR


def test_a_different_desk_does_not_replace_either_copy(vault):
    _insert_squad("Local Cup")
    remote = encode_snapshot("other-lineage", _tiny_db("Remote Cup"), PASSPHRASE)
    vault.payload = remote
    loads = vault.loads
    conn = db_state.get_connection()
    with conn:
        conn.execute("UPDATE tournaments SET name = 'Local Cup 2' WHERE name = 'Local Cup'")
    conn.close()
    assert vault.payload == remote
    assert _names() == ["Local Cup 2"]
    assert "neither side was changed" in tournament_vault.LAST_ERROR
    db_state.init_db()
    assert vault.loads == loads + 1


def test_local_events_without_a_lineage_do_not_clobber_the_vault(vault):
    remote = encode_snapshot("other-lineage", _tiny_db("Remote Cup"), PASSPHRASE)
    vault.payload = remote
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO tournaments (name, host_center) VALUES ('Local Cup', 'HL')"
        )
    conn.close()
    assert vault.payload == remote
    assert _names() == ["Local Cup"]
    assert "neither side was changed" in tournament_vault.notice()


def test_debounce_collapses_a_burst_of_scores(vault):
    tournament_vault._timing["debounce"] = 0.6
    tournament_vault._timing["max_wait"] = 5
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO tournaments (name, host_center) VALUES ('Burst', 'HL')"
        )
    conn.close()
    assert vault.saves == 0
    time.sleep(0.2)
    conn = db_state.get_connection()
    with conn:
        conn.execute("UPDATE tournaments SET host_center = 'FHL' WHERE name = 'Burst'")
    conn.close()
    time.sleep(0.2)
    assert vault.saves == 0
    tournament_vault.wait_for_quiet(3)
    assert vault.saves == 1
    names, _decoded = _snapshot_names(vault.payload)
    assert names == ["Burst"]


def test_manual_restore_becomes_the_saved_copy(vault, tmp_path):
    _insert_squad("Event A")
    data = db_state.backup_bytes()
    conn = db_state.get_connection()
    with conn:
        conn.execute("UPDATE tournaments SET name = 'Event B' WHERE name = 'Event A'")
    conn.close()
    assert _snapshot_names(vault.payload)[0] == ["Event B"]
    db_state.restore_from_bytes(data)
    assert _names() == ["Event A"]
    assert _snapshot_names(vault.payload)[0] == ["Event A"]
    _wipe(tmp_path)
    assert _names() == ["Event A"]


def test_restore_uses_the_staff_vault_for_sign_in(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISM_TOURNAMENT_VAULT", "on")
    monkeypatch.setenv("PRISM_STAFF_VAULT", "on")
    monkeypatch.setenv("STAFF_VAULT_KEY", PASSPHRASE)
    monkeypatch.delenv("CHUSBC_GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    staff_store = staff_vault.MemoryStore()
    staff_vault.use_store(staff_store)
    store = tournament_vault.MemoryStore()
    tournament_vault.use_store(store)
    db_state.init_db()
    ok, message = create_staff_user(
        "friend",
        "lane-pair-42",
        "Scott Friend",
        email="friend@example.com",
        center_affiliation="HL",
        role="td",
    )
    assert ok, message
    _insert_squad()
    assert b"lane-pair-42" not in store.payload
    _wipe(tmp_path)
    assert _lane_and_score() == (12, 214)
    assert authenticate("friend", "lane-pair-42")["display_name"] == "Scott Friend"


def test_missing_secrets_leave_a_wiped_database_empty_and_sign_in_works(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISM_TOURNAMENT_VAULT", "on")
    monkeypatch.delenv("STAFF_VAULT_KEY", raising=False)
    monkeypatch.delenv("CHUSBC_GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    assert tournament_vault.vault_configured() is False
    assert tournament_vault.notice() == OFF_NOTICE
    _insert_squad()
    _wipe(tmp_path)
    assert _names() == []
    assert db_state.using_turso() is False
    assert db_state.turso_config() is None
    auth._bootstrap_admin()
    assert authenticate("skramer", "Gussierocks1")["role"] == "admin"


def test_wrong_key_is_rejected():
    payload = encode_snapshot("lineage", _tiny_db("Cup"), PASSPHRASE)
    with pytest.raises(VaultError, match="could not be read"):
        decode_snapshot(payload, "x" * 40)


class _FakeImap:
    def __init__(self):
        self.boxes = {}
        self.selected = None
        self.logout_called = False

    def login(self, user, password):
        self.user = user
        self.password = password
        return "OK", [b"logged in"]

    def select(self, mailbox):
        name = mailbox.strip('"')
        if name not in self.boxes:
            return "NO", [b"no such mailbox"]
        self.selected = name
        return "OK", [str(len(self.boxes[name])).encode()]

    def create(self, mailbox):
        self.boxes.setdefault(mailbox.strip('"'), [])
        return "OK", [b"created"]

    def search(self, charset, criterion):
        rows = self.boxes[self.selected]
        ids = [str(index + 1).encode() for index, row in enumerate(rows) if not row["deleted"]]
        return "OK", [b" ".join(ids)]

    def fetch(self, num, what):
        row = self.boxes[self.selected][int(num) - 1]
        return "OK", [(b"RFC822", row["raw"])]

    def append(self, mailbox, flags, date_time, message):
        self.boxes.setdefault(mailbox.strip('"'), []).append({"raw": message, "deleted": False})
        return "OK", [b"appended"]

    def store(self, num, op, flag):
        self.boxes[self.selected][int(num) - 1]["deleted"] = True
        return "OK", [b"stored"]

    def expunge(self):
        self.boxes[self.selected] = [row for row in self.boxes[self.selected] if not row["deleted"]]
        return "OK", [b"expunged"]

    def logout(self):
        self.logout_called = True
        return "BYE", [b"bye"]


def test_gmail_store_keeps_only_the_latest_snapshot_and_chunks():
    fake = _FakeImap()
    store = GmailTournamentStore(
        "chusbc.tournaments@gmail.com", "abcd efgh ijkl mnop", connect=lambda: fake
    )
    previous = tournament_vault._CHUNK_CHARS
    tournament_vault._CHUNK_CHARS = 4000
    first = encode_snapshot("lineage", _tiny_db("One"), PASSPHRASE)
    second = encode_snapshot("lineage", _tiny_db("Two"), PASSPHRASE)
    try:
        store.open()
        try:
            assert store.load() is None
            store.save(first)
            store.save(second)
            loaded = store.load()
        finally:
            store.close()
    finally:
        tournament_vault._CHUNK_CHARS = previous
    assert fake.logout_called
    assert fake.password == "abcdefghijklmnop"
    assert len(fake.boxes[MAILBOX]) == max(1, (len(second) + 3999) // 4000)
    assert len(fake.boxes[MAILBOX]) > 1
    assert loaded == second
    assert _snapshot_names(loaded)[0] == ["Two"]
    raw = b"".join(row["raw"] for row in fake.boxes[MAILBOX])
    assert b"\r\n" in raw
    assert MAILBOX == "PrismTournamentVault"


def test_an_incomplete_newer_snapshot_is_ignored():
    fake = _FakeImap()
    store = GmailTournamentStore("desk@example.com", "secret", connect=lambda: fake)
    previous = tournament_vault._CHUNK_CHARS
    tournament_vault._CHUNK_CHARS = 4000
    full = encode_snapshot("lineage", _tiny_db("Kept"), PASSPHRASE)
    try:
        store.open()
        try:
            store.save(full)
            part = tournament_vault._wrap_message(b"abcdef", "newer-but-short", 1, 2)
            fake.append(MAILBOX, "(\\Seen)", None, part)
            loaded = store.load()
        finally:
            store.close()
    finally:
        tournament_vault._CHUNK_CHARS = previous
    assert loaded == full
    assert _snapshot_names(loaded)[0] == ["Kept"]


def test_gmail_sign_in_failure_does_not_repeat_the_password():
    class _BadImap:
        def login(self, user, password):
            raise imaplib.IMAP4.error(b"AUTHENTICATIONFAILED")

        def logout(self):
            self.logged_out = True

    bad = _BadImap()
    store = GmailTournamentStore("desk@example.com", "super-secret-pass", connect=lambda: bad)
    with pytest.raises(VaultError, match="sign-in failed") as caught:
        store.open()
    assert "super-secret-pass" not in str(caught.value)
    assert bad.logged_out
