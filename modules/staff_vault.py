"""Durable copy of staff sign-in accounts.

Tournament data stays in the local SQLite file. That file is wiped when
Streamlit Cloud sleeps or redeploys. Staff rows are the exception: when
STAFF_VAULT_KEY and the CHUSBC Gmail app password are set, this module stores
an encrypted snapshot (Argon2 hashes, names, roles — never a plaintext
password) as one message in that mailbox, and refills an empty staff_users
table from it on startup.

Hosted Turso is not used. With the secrets missing, nothing is copied and the
desk keeps working on the local file alone.
"""

import imaplib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from base64 import urlsafe_b64encode
from hashlib import pbkdf2_hmac

from cryptography.fernet import Fernet, InvalidToken

from modules.db_state import get_connection
from modules.settings import get_secret

log = logging.getLogger(__name__)

MAILBOX = "PrismStaffVault"
_SUBJECT = "prism-staff-vault"
_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993
_IMAP_TIMEOUT_SECONDS = 12
_RETRY_AFTER_SECONDS = 600
_KDF_SALT = b"prism-staff-vault-v1"
_KDF_ROUNDS = 200_000
_ROLES = ("td", "admin")
_ACCOUNT_FIELDS = (
    "id",
    "username",
    "password_hash",
    "display_name",
    "email",
    "center_affiliation",
    "role",
    "is_approved",
    "is_active",
    "created_at",
)

OFF_NOTICE = (
    "Staff accounts live on this app's disk only, so a reboot removes them. "
    "To keep them, set STAFF_VAULT_KEY and CHUSBC_GMAIL_APP_PASSWORD in Streamlit secrets "
    "and turn on IMAP for the CHUSBC Gmail account. The README lists the exact steps."
)
SAVED_NOTICE = (
    "Staff accounts are copied to an encrypted vault and come back after a reboot. "
    "Events and scores are not in that vault."
)
PENDING_NOTICE = "The staff vault is set up. Accounts are copied when they are added or changed."

_lock = threading.Lock()
_fernet_cache: dict[str, Fernet] = {}
_test_store = None
_next_network_at = 0.0
_settled_empty = False
LAST_ERROR = ""


class VaultError(Exception):
    """A staff-vault read or write failed. The message is safe to show."""


class MemoryStore:
    """In-process stand-in for the mailbox. Tests use this; the desk does not."""

    def __init__(self):
        self.payload: bytes | None = None
        self.loads = 0
        self.saves = 0
        self.fail_load = False
        self.fail_save = False

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def load(self) -> bytes | None:
        self.loads += 1
        if self.fail_load:
            raise VaultError("Staff vault could not be read.")
        return self.payload

    def save(self, payload: bytes) -> None:
        self.saves += 1
        if self.fail_save:
            raise VaultError("Staff vault could not be saved.")
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            raise VaultError("Staff vault could not be saved.")
        self.payload = bytes(payload)


def use_store(store) -> None:
    """Install a test double, or None to use the mailbox again."""
    global _test_store, _next_network_at, _settled_empty, LAST_ERROR
    _test_store = store
    _next_network_at = 0.0
    _settled_empty = False
    LAST_ERROR = ""


def _secret_text(key: str) -> str:
    value = get_secret(key) or ""
    if not isinstance(value, str):
        return ""
    return value.strip()


def _passphrase() -> str:
    return _secret_text("STAFF_VAULT_KEY")


def _gmail_user() -> str:
    user = _secret_text("CHUSBC_GMAIL_USER")
    return user or "chusbc.tournaments@gmail.com"


def _gmail_password() -> str:
    value = get_secret("CHUSBC_GMAIL_APP_PASSWORD") or ""
    if not isinstance(value, str):
        return ""
    return value.replace(" ", "").strip()


def _gmail_ready() -> bool:
    if _test_store is not None:
        return True
    return bool(_gmail_password())


def vault_configured() -> bool:
    """True when this process should read and write the staff vault."""
    if os.environ.get("PRISM_STAFF_VAULT") == "off":
        return False
    return bool(_passphrase()) and _gmail_ready()


def _set_status(message: str) -> None:
    global LAST_ERROR
    LAST_ERROR = message


def _public_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    for secret in (_passphrase(), _gmail_password(), _gmail_user()):
        if secret:
            text = text.replace(secret, "…")
    return (text[:180] or "unknown error")


def _fernet(passphrase: str) -> Fernet:
    cached = _fernet_cache.get(passphrase)
    if cached is not None:
        return cached
    derived = pbkdf2_hmac("sha256", passphrase.encode("utf-8"), _KDF_SALT, _KDF_ROUNDS, dklen=32)
    cached = Fernet(urlsafe_b64encode(derived))
    _fernet_cache[passphrase] = cached
    return cached


def _flag(value, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return 1 if int(value) else 0
    except (TypeError, ValueError):
        return default


def _clean_account(raw) -> dict | None:
    """One staff row safe to store or restore. Plaintext password keys are dropped."""
    if not isinstance(raw, dict):
        return None
    data = dict(raw)
    data.pop("password", None)
    data.pop("plaintext_password", None)
    username = str(data.get("username") or "").strip()
    password_hash = str(data.get("password_hash") or "").strip()
    role = str(data.get("role") or "").strip()
    display_name = str(data.get("display_name") or "").strip() or username
    if not username or not password_hash or role not in _ROLES:
        return None
    account = {
        "username": username,
        "password_hash": password_hash,
        "display_name": display_name,
        "email": str(data.get("email") or "").strip(),
        "center_affiliation": str(data.get("center_affiliation") or "").strip() or "CHUSBC",
        "role": role,
        "is_approved": _flag(data.get("is_approved"), 1),
        "is_active": _flag(data.get("is_active"), 1),
    }
    try:
        row_id = int(data["id"]) if data.get("id") is not None else 0
    except (TypeError, ValueError):
        row_id = 0
    if row_id > 0:
        account["id"] = row_id
    created = data.get("created_at")
    if created is not None and not isinstance(created, str):
        created = str(created)
    if isinstance(created, str) and created.strip():
        account["created_at"] = created.strip()
    return account


def encode_snapshot(db_id: str, accounts: list[dict], passphrase: str) -> bytes:
    """Encrypt staff rows. The token does not contain plaintext passwords."""
    body = {
        "v": 1,
        "db_id": db_id,
        "accounts": [_clean_account(account) for account in accounts],
    }
    body["accounts"] = [account for account in body["accounts"] if account]
    token = _fernet(passphrase).encrypt(
        json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    return token


def decode_snapshot(payload: bytes, passphrase: str) -> dict:
    """Return {'db_id', 'accounts'} or raise VaultError. Extra password fields are ignored."""
    try:
        raw = _fernet(passphrase).decrypt(payload)
        data = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError, TypeError) as exc:
        raise VaultError("Staff vault could not be read.") from exc
    if not isinstance(data, dict) or data.get("v") != 1:
        raise VaultError("Staff vault could not be read.")
    db_id = data.get("db_id")
    accounts_raw = data.get("accounts")
    if not isinstance(db_id, str) or not db_id.strip() or not isinstance(accounts_raw, list):
        raise VaultError("Staff vault could not be read.")
    accounts = []
    for item in accounts_raw:
        cleaned = _clean_account(item)
        if cleaned is not None:
            accounts.append(cleaned)
    return {"db_id": db_id.strip(), "accounts": accounts}


def _ensure_state(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS staff_vault_state ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "db_id TEXT NOT NULL DEFAULT '', "
        "dirty INTEGER NOT NULL DEFAULT 0)"
    )


def _state_from_row(row) -> dict:
    if not row:
        return {"db_id": "", "dirty": False}
    return {"db_id": (row["db_id"] or ""), "dirty": bool(row["dirty"])}


def _read_state() -> dict:
    """Vault bookkeeping, or a blank record when that table has not been created yet."""
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                "SELECT db_id, dirty FROM staff_vault_state WHERE id = 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return {"db_id": "", "dirty": False}
    finally:
        conn.close()
    return _state_from_row(row)


def _local_status() -> tuple[dict, int]:
    """Bookkeeping plus how many staff rows exist. One connection, no write."""
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                "SELECT db_id, dirty FROM staff_vault_state WHERE id = 1"
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        try:
            count = int(conn.execute("SELECT COUNT(*) FROM staff_users").fetchone()[0])
        except sqlite3.OperationalError:
            count = 0
    finally:
        conn.close()
    return _state_from_row(row), count


def _write_state(db_id: str, dirty: bool) -> None:
    conn = get_connection()
    try:
        with conn:
            _ensure_state(conn)
            conn.execute("DELETE FROM staff_vault_state")
            conn.execute(
                "INSERT INTO staff_vault_state (id, db_id, dirty) VALUES (1, ?, ?)",
                (db_id or "", 1 if dirty else 0),
            )
    finally:
        conn.close()


def _read_accounts() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, password_hash, display_name, email, center_affiliation, "
            "role, is_approved, is_active, created_at FROM staff_users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    accounts = []
    for row in rows:
        cleaned = _clean_account(dict(row))
        if cleaned is not None:
            accounts.append(cleaned)
    return accounts


def _bump_sequence(conn, max_id: int) -> None:
    if max_id <= 0:
        return
    try:
        found = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'staff_users'"
        ).fetchone()
    except sqlite3.OperationalError:
        return
    if found is None:
        try:
            conn.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES ('staff_users', ?)",
                (max_id,),
            )
        except sqlite3.OperationalError:
            return
        return
    try:
        current = int(found[0] or 0)
    except (TypeError, ValueError):
        current = 0
    if current < max_id:
        conn.execute(
            "UPDATE sqlite_sequence SET seq = ? WHERE name = 'staff_users'",
            (max_id,),
        )


def _insert_accounts(accounts: list[dict]) -> None:
    if not accounts:
        return
    conn = get_connection()
    try:
        with conn:
            taken = {int(row[0]) for row in conn.execute("SELECT id FROM staff_users")}
            for account in accounts:
                row = dict(account)
                if row.get("id") in taken:
                    row.pop("id", None)
                cols = [name for name in _ACCOUNT_FIELDS if name in row and row[name] is not None]
                placeholders = ", ".join("?" for _ in cols)
                names = ", ".join(cols)
                conn.execute(
                    f"INSERT INTO staff_users ({names}) VALUES ({placeholders})",
                    [row[name] for name in cols],
                )
                if "id" in cols:
                    taken.add(int(row["id"]))
            seq = conn.execute("SELECT MAX(id) FROM staff_users").fetchone()
            _bump_sequence(conn, int(seq[0] or 0))
    finally:
        conn.close()


def _plan(state: dict, local: list[dict], remote: dict | None) -> dict:
    """What to insert and whether the local rows should replace the vault.

    An empty table with no vault id is a wiped disk and is refilled from the
    snapshot. An empty table that this desk just wrote (id set, dirty) is a
    real "delete every account" and must not be filled back in.
    """
    if not local and state["dirty"] and state["db_id"]:
        if remote is not None and remote["db_id"] != state["db_id"]:
            return {
                "insert": [],
                "publish": False,
                "db_id": state["db_id"],
                "restored": False,
                "refused": True,
            }
        return {
            "insert": [],
            "publish": bool(remote and remote["accounts"]),
            "db_id": state["db_id"],
            "restored": False,
        }

    if remote is None:
        if not local:
            return {"insert": [], "publish": False, "db_id": "", "restored": False}
        return {
            "insert": [],
            "publish": True,
            "db_id": state["db_id"] or uuid.uuid4().hex,
            "restored": False,
        }

    if not local:
        return {
            "insert": list(remote["accounts"]),
            "publish": False,
            "db_id": remote["db_id"],
            "restored": bool(remote["accounts"]),
        }

    local_id = state["db_id"]
    remote_id = remote["db_id"]
    if local_id and local_id != remote_id:
        return {"insert": [], "publish": False, "db_id": local_id, "restored": False, "refused": True}

    if not local_id:
        existing = {account["username"].casefold() for account in local}
        missing = [
            account for account in remote["accounts"] if account["username"].casefold() not in existing
        ]
        local_names = existing
        remote_names = {account["username"].casefold() for account in remote["accounts"]}
        publish = bool(local_names - remote_names) or state["dirty"]
        return {
            "insert": missing,
            "publish": publish,
            "db_id": remote_id,
            "restored": bool(missing),
        }

    if state["dirty"]:
        return {"insert": [], "publish": True, "db_id": local_id, "restored": False}
    return {"insert": [], "publish": False, "db_id": local_id, "restored": False}


def _open_store():
    if _test_store is not None:
        return _test_store
    return GmailStaffStore(_gmail_user(), _gmail_password())


def _backoff() -> None:
    global _next_network_at
    _next_network_at = time.monotonic() + _RETRY_AFTER_SECONDS


def _clear_backoff() -> None:
    global _next_network_at
    _next_network_at = 0.0


def _sync_body(force: bool) -> None:
    """Restore an empty staff table, or publish local staff rows. Never raises."""
    global _settled_empty
    if not vault_configured():
        return
    try:
        state, count = _local_status()
    except Exception as exc:
        _set_status(_public_error(exc))
        log.warning("Staff vault could not read the local accounts")
        return

    # A saved lineage does not touch the network. Desk reruns stay on the local
    # file. An empty table still syncs once, so a wiped file (no id yet) is
    # refilled. Leave LAST_ERROR alone so a refusal stays visible.
    if state["db_id"] and not state["dirty"] and (count or _settled_empty):
        return
    if not force and time.monotonic() < _next_network_at:
        return
    try:
        local = _read_accounts()
    except Exception as exc:
        _set_status(_public_error(exc))
        log.warning("Staff vault could not read the local accounts")
        return

    try:
        store = _open_store()
    except Exception as exc:
        _set_status(_public_error(exc))
        _backoff()
        log.warning("Staff vault sync failed")
        return
    try:
        store.open()
        try:
            remote_blob = store.load()
        except VaultError as exc:
            _set_status(str(exc))
            _backoff()
            return
        if remote_blob:
            try:
                remote = decode_snapshot(remote_blob, _passphrase())
            except VaultError as exc:
                _set_status(str(exc))
                _backoff()
                return
        else:
            remote = None
        plan = _plan(state, local, remote)
        if plan.get("refused"):
            _set_status(
                "This copy of the desk is not the one the staff vault belongs to, "
                "so the vault was left unchanged."
            )
            # Do not retry on every rerun. The next account change tries again.
            _write_state(state["db_id"], dirty=False)
            _clear_backoff()
            return
        if plan["insert"]:
            _insert_accounts(plan["insert"])
            local = _read_accounts()
        if plan["publish"]:
            _write_state(plan["db_id"], dirty=True)
            store.save(encode_snapshot(plan["db_id"], local, _passphrase()))
        if plan["db_id"] and (plan["publish"] or plan["insert"] or plan["restored"] or state["dirty"]):
            _write_state(plan["db_id"], dirty=False)
        _set_status("")
        _clear_backoff()
        _settled_empty = bool(plan["db_id"]) and not local
        if plan["restored"]:
            log.info("Restored %s staff account(s) from the vault", len(local))
    except VaultError as exc:
        _set_status(str(exc))
        _backoff()
    except Exception as exc:
        _set_status(_public_error(exc))
        _backoff()
        log.warning("Staff vault sync failed")
    finally:
        store.close()


def sync_staff_accounts() -> None:
    """Startup copy: refill an empty staff table, or finish a save that did not land."""
    with _lock:
        try:
            _sync_body(force=False)
        except Exception:
            log.warning("Staff vault sync failed")


def save_staff_vault() -> None:
    """Publish the current staff rows. Failures are logged and do not raise."""
    with _lock:
        if not vault_configured():
            return
        try:
            state = _read_state()
            _write_state(state["db_id"], dirty=True)
        except Exception:
            log.warning("Could not mark staff accounts for the vault")
            return
        try:
            _sync_body(force=True)
        except Exception:
            log.warning("Staff vault save failed")


def notice() -> str:
    """One line for the Staff Accounts page. Does not contact the mailbox."""
    if not vault_configured():
        return OFF_NOTICE
    if LAST_ERROR:
        return (
            "Staff accounts could not be copied to the vault ("
            + LAST_ERROR
            + "). They can disappear on the next reboot until this succeeds."
        )
    try:
        state = _read_state()
    except Exception:
        return PENDING_NOTICE
    if state["db_id"] and not state["dirty"]:
        return SAVED_NOTICE
    return PENDING_NOTICE


def _imap_connect():
    return imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, timeout=_IMAP_TIMEOUT_SECONDS)


def _wrap_message(payload: bytes) -> bytes:
    token = payload.decode("ascii")
    folded = "\r\n".join(token[i:i + 76] for i in range(0, len(token), 76))
    text = (
        f"Subject: {_SUBJECT}\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=us-ascii\r\n"
        "Content-Transfer-Encoding: 7bit\r\n"
        "\r\n"
        f"{folded}\r\n"
    )
    return text.encode("ascii")


def _unwrap_message(raw: bytes) -> bytes:
    text = raw.decode("ascii")
    parts = text.split("\r\n\r\n", 1)
    if len(parts) != 2:
        parts = text.split("\n\n", 1)
    if len(parts) != 2 or _SUBJECT not in parts[0]:
        raise VaultError("Staff vault could not be read.")
    compact = "".join(parts[1].split())
    if not compact:
        raise VaultError("Staff vault could not be read.")
    return compact.encode("ascii")


def _rfc822(fetched) -> bytes:
    for item in fetched or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    raise VaultError("Staff vault could not be read.")


class GmailStaffStore:
    """One encrypted message under the PrismStaffVault label in the CHUSBC mailbox."""

    def __init__(self, user: str, password: str, connect=None):
        self.user = user
        self.password = (password or "").replace(" ", "").strip()
        self._connect = connect or _imap_connect
        self._imap = None

    def open(self) -> None:
        imap = None
        try:
            imap = self._connect()
            imap.login(self.user, self.password)
        except Exception as exc:
            if imap is not None:
                try:
                    imap.logout()
                except Exception:
                    pass
            log.warning("Staff vault sign-in failed (%s)", type(exc).__name__)
            raise VaultError("Staff vault sign-in failed.") from None
        self._imap = imap

    def close(self) -> None:
        imap = self._imap
        self._imap = None
        if imap is None:
            return
        try:
            imap.logout()
        except Exception:
            pass

    def _select(self, imap) -> None:
        status, _data = imap.select(MAILBOX)
        if status == "OK":
            return
        status, _data = imap.create(MAILBOX)
        if status != "OK":
            raise VaultError("Staff vault mailbox could not be opened.")
        status, _data = imap.select(MAILBOX)
        if status != "OK":
            raise VaultError("Staff vault mailbox could not be opened.")

    def _ids(self, imap) -> list[bytes]:
        status, data = imap.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        return data[0].split()

    def load(self) -> bytes | None:
        imap = self._imap
        if imap is None:
            raise VaultError("Staff vault could not be read.")
        self._select(imap)
        ids = self._ids(imap)
        if not ids:
            return None
        status, fetched = imap.fetch(ids[-1], "(RFC822)")
        if status != "OK":
            raise VaultError("Staff vault could not be read.")
        return _unwrap_message(_rfc822(fetched))

    def save(self, payload: bytes) -> None:
        if not payload:
            raise VaultError("Staff vault could not be saved.")
        imap = self._imap
        if imap is None:
            raise VaultError("Staff vault could not be saved.")
        self._select(imap)
        status, _data = imap.append(
            MAILBOX,
            "(\\Seen)",
            imaplib.Time2Internaldate(time.time()),
            _wrap_message(payload),
        )
        if status != "OK":
            raise VaultError("Staff vault could not be saved.")
        ids = self._ids(imap)
        if len(ids) <= 1:
            return
        try:
            for old in ids[:-1]:
                imap.store(old, "+FLAGS", "\\Deleted")
            imap.expunge()
        except Exception:
            log.warning("Staff vault left an older copy in the mailbox")
