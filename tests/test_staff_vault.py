"""Staff accounts come back after the local database file is wiped.

The mailbox is not contacted. A memory store stands in for the CHUSBC Gmail
label, and a fake IMAP session checks that the real store keeps one message.
"""

import imaplib

import pytest

from modules import auth, db_state, staff_vault
from modules.auth import (
    approve_user,
    authenticate,
    change_own_password,
    create_staff_user,
    delete_user,
    hash_password,
    register_staff_user,
    reset_password,
    set_role,
    update_staff_profile,
)
from modules.staff_vault import (
    MAILBOX,
    OFF_NOTICE,
    SAVED_NOTICE,
    GmailStaffStore,
    VaultError,
    decode_snapshot,
    encode_snapshot,
)

PASSPHRASE = "test-vault-key-" + ("k" * 32)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISM_STAFF_VAULT", "on")
    monkeypatch.setenv("STAFF_VAULT_KEY", PASSPHRASE)
    monkeypatch.delenv("CHUSBC_GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    store = staff_vault.MemoryStore()
    staff_vault.use_store(store)
    db_state.init_db()
    return store


def _wipe(tmp_path):
    for name in ("t.db", "t.db-wal", "t.db-shm"):
        path = tmp_path / name
        if path.exists():
            path.unlink()
    db_state.init_db()


def _rows(username=None):
    conn = db_state.get_connection()
    try:
        if username is None:
            found = conn.execute(
                "SELECT id, username, password_hash, display_name, email, center_affiliation, "
                "role, is_approved FROM staff_users ORDER BY username"
            ).fetchall()
        else:
            found = conn.execute(
                "SELECT id, username, password_hash, display_name, email, center_affiliation, "
                "role, is_approved FROM staff_users WHERE username = ?",
                (username,),
            ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in found]


def _names(payload):
    decoded = decode_snapshot(payload, PASSPHRASE)
    return {account["username"] for account in decoded["accounts"]}


def _assert_no_plaintext_password(decoded):
    assert "password" not in decoded
    for account in decoded["accounts"]:
        assert "password" not in account
        assert "plaintext_password" not in account
        assert "password_hash" in account


def test_staff_survive_an_empty_database_and_the_password_is_not_stored(vault, tmp_path):
    ok, message = create_staff_user(
        "friend",
        "lane-pair-42",
        "Scott Friend",
        email="friend@example.com",
        center_affiliation="HL",
        role="td",
    )
    assert ok, message
    ok, message = create_staff_user(
        "casey",
        "temporary1",
        "Casey",
        email="casey@example.com",
        center_affiliation="CHUSBC",
        role="td",
    )
    assert ok, message
    casey_id = _rows("casey")[0]["id"]
    friend_id = _rows("friend")[0]["id"]
    assert update_staff_profile(
        casey_id,
        display_name="Casey D.",
        email="casey@example.com",
        center_affiliation="HL",
        role="admin",
        admin_name="Ada",
    ) is None
    assert set_role(casey_id, "td", "Ada") is None
    assert reset_password(friend_id, "new-lane-99", "Ada") is None
    assert change_own_password(casey_id, "temporary1", "casey-own-99") is None

    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO tournaments (name, host_center) VALUES ('Saturday Sweeper', 'HL')"
        )
    conn.close()

    raw = vault.payload
    assert b"lane-pair-42" not in raw
    assert b"new-lane-99" not in raw
    assert b"casey-own-99" not in raw
    assert b"Saturday Sweeper" not in raw
    decoded = decode_snapshot(raw, PASSPHRASE)
    _assert_no_plaintext_password(decoded)
    friend = next(account for account in decoded["accounts"] if account["username"] == "friend")
    casey = next(account for account in decoded["accounts"] if account["username"] == "casey")
    assert friend["role"] == "td"
    assert friend["email"] == "friend@example.com"
    assert casey["role"] == "td"
    assert casey["display_name"] == "Casey D."
    assert casey["center_affiliation"] == "HL"
    assert staff_vault.notice() == SAVED_NOTICE

    _wipe(tmp_path)

    assert _rows("friend")[0]["email"] == "friend@example.com"
    assert authenticate("friend", "new-lane-99")["display_name"] == "Scott Friend"
    assert authenticate("friend", "lane-pair-42") is None
    signed_in = authenticate("casey", "casey-own-99")
    assert signed_in["role"] == "td"
    assert signed_in["display_name"] == "Casey D."
    assert authenticate("casey", "temporary1") is None
    conn = db_state.get_connection()
    try:
        events = conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0]
    finally:
        conn.close()
    assert events == 0

    # The next account must not reuse a restored id.
    ok, message = create_staff_user(
        "pat",
        "password1",
        "Pat",
        email="pat@example.com",
        center_affiliation="FHL",
        role="td",
    )
    assert ok, message
    ids = [row["id"] for row in _rows()]
    assert len(ids) == len(set(ids))

    assert delete_user(friend_id, casey_id, "Casey D.") is None
    assert "friend" not in _names(vault.payload)
    _wipe(tmp_path)
    assert _rows("friend") == []
    assert authenticate("casey", "casey-own-99") is not None


def test_deleting_the_last_account_stays_deleted_after_a_wipe(vault, tmp_path):
    ok, message = create_staff_user(
        "friend",
        "lane-pair-42",
        "Scott Friend",
        email="friend@example.com",
        center_affiliation="HL",
        role="td",
    )
    assert ok, message
    friend_id = _rows("friend")[0]["id"]
    assert delete_user(friend_id, friend_id + 1, "Ada") is None
    assert decode_snapshot(vault.payload, PASSPHRASE)["accounts"] == []
    loads = vault.loads
    db_state.init_db()
    db_state.init_db()
    assert vault.loads == loads
    _wipe(tmp_path)
    assert _rows() == []


def test_pending_registration_survives_until_it_is_approved(vault, tmp_path):
    ok, message = register_staff_user(
        "newbie", "pending-pass-1", "New Bie", "new@example.com", "HL"
    )
    assert ok, message
    pending = next(
        account for account in decode_snapshot(vault.payload, PASSPHRASE)["accounts"]
        if account["username"] == "newbie"
    )
    assert pending["is_approved"] == 0
    newbie_id = _rows("newbie")[0]["id"]

    _wipe(tmp_path)
    assert authenticate("newbie", "pending-pass-1") is None
    assert _rows("newbie")[0]["is_approved"] == 0

    assert approve_user(newbie_id, "Ada") is None
    _wipe(tmp_path)
    assert authenticate("newbie", "pending-pass-1")["email"] == "new@example.com"


def test_startup_does_not_read_the_vault_again_once_it_is_saved(vault):
    ok, message = create_staff_user(
        "friend",
        "lane-pair-42",
        "Scott Friend",
        email="friend@example.com",
        center_affiliation="HL",
        role="td",
    )
    assert ok, message
    loads = vault.loads
    saves = vault.saves
    db_state.init_db()
    db_state.init_db()
    assert vault.loads == loads
    assert vault.saves == saves


def test_a_failed_read_does_not_overwrite_the_vault_or_retry_every_startup(vault):
    ok, message = create_staff_user(
        "friend",
        "lane-pair-42",
        "Scott Friend",
        email="friend@example.com",
        center_affiliation="HL",
        role="td",
    )
    assert ok, message
    original = bytes(vault.payload)
    vault.fail_load = True
    ok, message = create_staff_user(
        "casey",
        "temporary1",
        "Casey",
        email="casey@example.com",
        center_affiliation="CHUSBC",
        role="admin",
    )
    assert ok, message
    assert vault.payload == original
    assert _rows("casey")
    assert "could not be read" in staff_vault.notice()
    loads = vault.loads
    db_state.init_db()
    assert vault.loads == loads

    vault.fail_load = False
    staff_vault.save_staff_vault()
    assert _names(vault.payload) == {"friend", "casey"}
    assert staff_vault.LAST_ERROR == ""


def test_a_damaged_snapshot_does_not_wipe_local_accounts(vault):
    ok, message = create_staff_user(
        "friend",
        "lane-pair-42",
        "Scott Friend",
        email="friend@example.com",
        center_affiliation="HL",
        role="td",
    )
    assert ok, message
    vault.payload = b"this is not a staff vault"
    staff_vault.save_staff_vault()
    assert vault.payload == b"this is not a staff vault"
    assert authenticate("friend", "lane-pair-42") is not None
    assert "could not be read" in staff_vault.LAST_ERROR


def test_a_different_desk_does_not_replace_the_vault(vault):
    ok, message = create_staff_user(
        "admin",
        "password1",
        "Ada Admin",
        email="ada@example.com",
        center_affiliation="CHUSBC",
        role="admin",
    )
    assert ok, message
    friend = {
        "id": 9,
        "username": "friend",
        "password_hash": hash_password("friend-secret"),
        "display_name": "Scott Friend",
        "email": "friend@example.com",
        "center_affiliation": "HL",
        "role": "td",
        "is_approved": 1,
    }
    vault.payload = encode_snapshot("other-lineage", [friend], PASSPHRASE)
    loads = vault.loads
    ok, message = create_staff_user(
        "casey",
        "temporary1",
        "Casey",
        email="casey@example.com",
        center_affiliation="HL",
        role="td",
    )
    assert ok, message
    assert _names(vault.payload) == {"friend"}
    assert {row["username"] for row in _rows()} == {"admin", "casey"}
    assert "left unchanged" in staff_vault.LAST_ERROR
    db_state.init_db()
    assert vault.loads == loads + 1


def test_a_local_admin_does_not_erase_accounts_already_in_the_vault(vault):
    friend = {
        "id": 4,
        "username": "friend",
        "password_hash": hash_password("friend-secret"),
        "display_name": "Scott Friend",
        "email": "friend@example.com",
        "center_affiliation": "HL",
        "role": "td",
        "is_approved": 1,
        "password": "friend-secret",
    }
    vault.payload = encode_snapshot("lineage-a", [friend], PASSPHRASE)
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO staff_users "
            "(username, password_hash, display_name, email, center_affiliation, role, is_approved) "
            "VALUES ('skramer', 'hash-skramer', 'Scott Kramer', 'scottjk85@gmail.com', 'CHUSBC', 'admin', 1)"
        )
    conn.close()
    staff_vault.sync_staff_accounts()
    assert {row["username"] for row in _rows()} == {"friend", "skramer"}
    decoded = decode_snapshot(vault.payload, PASSPHRASE)
    assert {account["username"] for account in decoded["accounts"]} == {"friend", "skramer"}
    _assert_no_plaintext_password(decoded)
    assert authenticate("friend", "friend-secret")["role"] == "td"
    conn = db_state.get_connection()
    try:
        stored = conn.execute(
            "SELECT password_hash FROM staff_users WHERE username = 'friend'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert stored != "friend-secret"
    assert "friend-secret" not in stored


def test_repaired_scott_row_is_what_the_vault_keeps(vault, tmp_path):
    conn = db_state.get_connection()
    with conn:
        conn.execute(
            "INSERT INTO staff_users "
            "(username, password_hash, display_name, email, center_affiliation, role, is_approved) "
            "VALUES ('scott', 'keep-me', 'Scott', 'CHUSBC', 'admin', 'td', 1)"
        )
    conn.close()
    db_state.init_db()
    decoded = decode_snapshot(vault.payload, PASSPHRASE)
    scott = next(account for account in decoded["accounts"] if account["username"] == "scott")
    assert scott["role"] == "admin"
    assert scott["email"] == ""
    assert scott["center_affiliation"] == "CHUSBC"
    assert scott["password_hash"] == "keep-me"
    _wipe(tmp_path)
    restored = _rows("scott")[0]
    assert restored["role"] == "admin"
    assert restored["email"] == ""
    assert restored["password_hash"] == "keep-me"


def test_missing_secrets_leave_a_wiped_database_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    assert staff_vault.notice() == OFF_NOTICE
    ok, message = create_staff_user(
        "friend",
        "lane-pair-42",
        "Scott Friend",
        email="friend@example.com",
        center_affiliation="HL",
        role="td",
    )
    assert ok, message
    _wipe(tmp_path)
    assert _rows() == []
    assert staff_vault.vault_configured() is False


def test_wrong_key_is_rejected():
    payload = encode_snapshot(
        "lineage",
        [{
            "username": "friend",
            "password_hash": "hash",
            "display_name": "Scott Friend",
            "role": "td",
        }],
        PASSPHRASE,
    )
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


def test_gmail_store_keeps_only_the_latest_snapshot():
    fake = _FakeImap()
    store = GmailStaffStore("chusbc.tournaments@gmail.com", "abcd efgh ijkl mnop", connect=lambda: fake)
    account = {
        "username": "friend",
        "password_hash": "stored-hash",
        "password": "lane-pair-42",
        "display_name": "Scott Friend",
        "email": "friend@example.com",
        "role": "td",
        "is_approved": 1,
    }
    first = encode_snapshot("lineage", [], PASSPHRASE)
    second = encode_snapshot("lineage", [account], PASSPHRASE)
    store.open()
    try:
        assert store.load() is None
        store.save(first)
        store.save(second)
        loaded = store.load()
    finally:
        store.close()
    assert fake.logout_called
    assert fake.password == "abcdefghijklmnop"
    assert len(fake.boxes[MAILBOX]) == 1
    assert loaded == second
    restored = decode_snapshot(loaded, PASSPHRASE)
    assert restored["accounts"][0]["username"] == "friend"
    raw = fake.boxes[MAILBOX][0]["raw"]
    assert b"lane-pair-42" not in raw
    assert b"\r\n" in raw


def test_gmail_sign_in_failure_does_not_repeat_the_password():
    class _BadImap:
        def login(self, user, password):
            raise imaplib.IMAP4.error(b"AUTHENTICATIONFAILED")

        def logout(self):
            self.logged_out = True

    bad = _BadImap()
    store = GmailStaffStore("desk@example.com", "super-secret-pass", connect=lambda: bad)
    with pytest.raises(VaultError, match="sign-in failed") as caught:
        store.open()
    assert "super-secret-pass" not in str(caught.value)
    assert bad.logged_out
