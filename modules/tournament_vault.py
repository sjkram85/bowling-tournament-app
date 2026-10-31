"""Durable copy of tournament data (events, bowlers, scores, lanes, and the rest).

The live database is the on-disk SQLite file. Streamlit Cloud can wipe that
file on sleep or redeploy. When STAFF_VAULT_KEY and the CHUSBC Gmail app
password are set — the same secrets as the staff vault — this module stores
an encrypted snapshot of the database under the label PrismTournamentVault
and refills an empty file from it on startup.

The snapshot is one Fernet token, split across mailbox messages when it is
too large for a single Gmail message. Only the latest complete snapshot is
kept. Staff password hashes are removed from the copy; staff sign-in stays
in modules.staff_vault. Hosted Turso is not used.

A desk that already has events is not replaced by the snapshot. A different
lineage (db_id) is not overwritten either way. With the secrets missing,
nothing is copied and scoring still works on the local file.
"""

import imaplib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from base64 import urlsafe_b64encode
from contextlib import contextmanager
from hashlib import pbkdf2_hmac, sha256

from cryptography.fernet import Fernet, InvalidToken

from modules.db_state import get_connection
from modules.settings import get_secret

log = logging.getLogger(__name__)

MAILBOX = "PrismTournamentVault"
_SUBJECT = "prism-tournament-vault"
_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993
_IMAP_TIMEOUT_SECONDS = 30
_RETRY_AFTER_SECONDS = 60
_KDF_SALT = b"prism-tournament-vault-v1"
_KDF_ROUNDS = 200_000
_DEFAULT_DEBOUNCE = 20.0
_DEFAULT_MAX_WAIT = 60.0
_DEFAULT_CHUNK_CHARS = 6_000_000
_MAX_CHUNKS = 8
_MAX_SQLITE_BYTES = 80 * 1024 * 1024
_SCHEMA_VERSION = 1

# Heartbeats and bookkeeping must not start a mailbox copy.
_SKIP_TABLES = frozenset({
    "staff_users",
    "staff_vault_state",
    "tournament_vault_state",
    "audit_log",
    "prism_schema",
    "sqlite_sequence",
    "td_presence",
    "td_presence_events",
})
_WRITE_HEAD = re.compile(r"^\s*(?:INSERT|REPLACE|UPDATE|DELETE)\b", re.IGNORECASE)
_TABLE_NAME = re.compile(
    r"""^\s*(?:
        INSERT\s+(?:OR\s+\w+\s+)?INTO
        | REPLACE\s+(?:INTO\s+)?
        | UPDATE(?:\s+OR\s+\w+)?
        | DELETE\s+FROM
    )\s+["`']?([A-Za-z_][\w]*)""",
    re.IGNORECASE | re.VERBOSE,
)
_STRIP_TABLES = ("staff_users", "staff_vault_state", "tournament_vault_state")
_COUNT_TABLES = ("tournaments", "bowlers", "scores")

OFF_NOTICE = (
    "Auto-backup is off, so a reboot can clear events and scores. "
    "Set STAFF_VAULT_KEY and CHUSBC_GMAIL_APP_PASSWORD — the same secrets as staff accounts — "
    "to keep an encrypted copy in the CHUSBC mailbox. Scoring still works, and Backup & Restore still downloads a file."
)
SAVED_NOTICE = (
    "Events and scores are copied to an encrypted mailbox snapshot and come back after a reboot."
)
PENDING_NOTICE = "Auto-backup is on. The mailbox copy updates after scores or event changes."
REFUSE_NOTICE = (
    "This copy of the desk is not the one the tournament vault belongs to, "
    "so neither side was changed."
)

_lock_publish = threading.Lock()
_sched_lock = threading.Lock()
_stop = threading.Event()
_timing = {"debounce": _DEFAULT_DEBOUNCE, "max_wait": _DEFAULT_MAX_WAIT}
_fernet_cache: dict[str, Fernet] = {}
_test_store = None
_cached_creds: tuple[str, str, str] | None = None
_next_network_at = 0.0
_settled_empty = False
_known_empty = False
_prefer_local = False
_in_sync = False
_applying = False
_worker: threading.Thread | None = None
_fire_at: float | None = None
_dirty_since: float | None = None
_CHUNK_CHARS = _DEFAULT_CHUNK_CHARS
LAST_ERROR = ""


class VaultError(Exception):
    """A tournament-vault read or write failed. The message is safe to show."""


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
            raise VaultError("Tournament vault could not be read.")
        return self.payload

    def save(self, payload: bytes) -> None:
        self.saves += 1
        if self.fail_save:
            raise VaultError("Tournament vault could not be saved.")
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            raise VaultError("Tournament vault could not be saved.")
        self.payload = bytes(payload)


def statement_changes_tournament(sql: str) -> bool:
    """True for a data change the mailbox copy should keep.

    Presence heartbeats, staff rows, audit lines, and vault bookkeeping are
    not tournament data. Streamlit reruns those constantly.
    """
    if not sql or not _WRITE_HEAD.match(sql):
        return False
    match = _TABLE_NAME.match(sql)
    if not match:
        return False
    return match.group(1).lower() not in _SKIP_TABLES


def fire_deadline(now: float, dirty_since: float, debounce: float, max_wait: float) -> float:
    """When a burst of writes should publish. Never later than max_wait after the first one."""
    return min(now + debounce, dirty_since + max_wait)


def use_store(store) -> None:
    """Install a test double, or None to use the mailbox again."""
    global _test_store, _cached_creds, _next_network_at, _settled_empty, _known_empty, LAST_ERROR
    global _prefer_local, _in_sync, _applying, _CHUNK_CHARS
    _shutdown_worker()
    _test_store = store
    _cached_creds = None
    _next_network_at = 0.0
    _settled_empty = False
    _known_empty = False
    LAST_ERROR = ""
    _prefer_local = False
    _in_sync = False
    _applying = False
    _CHUNK_CHARS = _DEFAULT_CHUNK_CHARS
    if store is not None:
        _timing["debounce"] = 0
        _timing["max_wait"] = 0
    else:
        _timing["debounce"] = _DEFAULT_DEBOUNCE
        _timing["max_wait"] = _DEFAULT_MAX_WAIT


def _shutdown_worker() -> None:
    global _worker, _fire_at, _dirty_since
    _stop.set()
    worker = _worker
    if worker is not None and worker is not threading.current_thread():
        worker.join(timeout=5)
    with _sched_lock:
        _worker = None
        _fire_at = None
        _dirty_since = None
    _stop.clear()


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


def vault_configured() -> bool:
    """True when this process should read and write the tournament vault."""
    if os.environ.get("PRISM_TOURNAMENT_VAULT") == "off":
        return False
    if not _passphrase():
        return False
    if _test_store is not None:
        return True
    return bool(_gmail_password())


def _remember_creds() -> bool:
    """Capture secrets on the script thread. The saver thread does not touch Streamlit."""
    global _cached_creds
    if not vault_configured():
        _cached_creds = None
        return False
    passphrase = _passphrase()
    if not passphrase:
        _cached_creds = None
        return False
    if _test_store is not None:
        _cached_creds = (passphrase, "", "")
        return True
    password = _gmail_password()
    if not password:
        _cached_creds = None
        return False
    _cached_creds = (passphrase, _gmail_user(), password)
    return True


def _set_status(message: str) -> None:
    global LAST_ERROR
    LAST_ERROR = message


def _failure_text(detail: str) -> str:
    text = " ".join((detail or "").split()) or "unknown error"
    return (
        "The tournament copy could not be saved ("
        + text
        + "). Events and scores can disappear on the next reboot until this succeeds."
    )


def _public_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    # Cached on the script thread. Do not read Streamlit secrets from the saver thread.
    if _cached_creds is not None:
        for secret in _cached_creds:
            if secret:
                text = text.replace(secret, "…")
    return text[:180] or "unknown error"


def _fernet(passphrase: str) -> Fernet:
    cached = _fernet_cache.get(passphrase)
    if cached is not None:
        return cached
    derived = pbkdf2_hmac("sha256", passphrase.encode("utf-8"), _KDF_SALT, _KDF_ROUNDS, dklen=32)
    cached = Fernet(urlsafe_b64encode(derived))
    _fernet_cache[passphrase] = cached
    return cached


def encode_snapshot(db_id: str, sqlite_bytes: bytes, passphrase: str) -> bytes:
    """Encrypt a SQLite file. The token does not include the passphrase."""
    if not isinstance(db_id, str) or not db_id.strip():
        raise VaultError("Tournament vault could not be saved.")
    if not sqlite_bytes.startswith(b"SQLite format 3\x00"):
        raise VaultError("Tournament vault could not be saved.")
    if len(sqlite_bytes) > _MAX_SQLITE_BYTES:
        raise VaultError(
            "Tournament vault copy is too large for the mailbox. "
            "Download a backup from Backup & Restore."
        )
    meta = {
        "v": _SCHEMA_VERSION,
        "db_id": db_id.strip(),
        "saved_at": int(time.time()),
        "sha256": sha256(sqlite_bytes).hexdigest(),
    }
    blob = json.dumps(meta, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    framed = len(blob).to_bytes(4, "big") + blob + sqlite_bytes
    return _fernet(passphrase).encrypt(framed)


def decode_snapshot(payload: bytes, passphrase: str) -> dict:
    """Return {'db_id', 'sqlite', 'saved_at'} or raise VaultError."""
    try:
        framed = _fernet(passphrase).decrypt(payload)
        if len(framed) < 5:
            raise ValueError("short")
        size = int.from_bytes(framed[:4], "big")
        if size < 2 or 4 + size > len(framed):
            raise ValueError("size")
        meta = json.loads(framed[4:4 + size].decode("utf-8"))
        sqlite_bytes = framed[4 + size:]
    except (InvalidToken, ValueError, json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
        raise VaultError("Tournament vault could not be read.") from exc
    if not isinstance(meta, dict) or meta.get("v") != _SCHEMA_VERSION:
        raise VaultError("Tournament vault could not be read.")
    db_id = meta.get("db_id")
    digest = meta.get("sha256")
    if not isinstance(db_id, str) or not db_id.strip():
        raise VaultError("Tournament vault could not be read.")
    if not isinstance(digest, str) or sha256(sqlite_bytes).hexdigest() != digest:
        raise VaultError("Tournament vault could not be read.")
    if not sqlite_bytes.startswith(b"SQLite format 3\x00") or len(sqlite_bytes) > _MAX_SQLITE_BYTES:
        raise VaultError("Tournament vault could not be read.")
    return {"db_id": db_id.strip(), "sqlite": sqlite_bytes, "saved_at": meta.get("saved_at")}


def _ensure_state(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tournament_vault_state ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "db_id TEXT NOT NULL DEFAULT '', "
        "dirty INTEGER NOT NULL DEFAULT 0, "
        "epoch INTEGER NOT NULL DEFAULT 0)"
    )


def _state_from_row(row) -> dict:
    if not row:
        return {"db_id": "", "dirty": False, "epoch": 0}
    try:
        epoch = int(row["epoch"] or 0)
    except (TypeError, ValueError, KeyError, IndexError):
        epoch = 0
    return {"db_id": (row["db_id"] or ""), "dirty": bool(row["dirty"]), "epoch": epoch}


def _counts_have_rows(conn) -> bool:
    total = 0
    for table in _COUNT_TABLES:
        try:
            total += int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        except sqlite3.OperationalError:
            continue
    return total > 0


def _read_state() -> dict:
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                "SELECT db_id, dirty, epoch FROM tournament_vault_state WHERE id = 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return {"db_id": "", "dirty": False, "epoch": 0}
    finally:
        conn.close()
    return _state_from_row(row)


def _local_status() -> tuple[dict, bool]:
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                "SELECT db_id, dirty, epoch FROM tournament_vault_state WHERE id = 1"
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        try:
            has_rows = _counts_have_rows(conn)
        except sqlite3.OperationalError:
            has_rows = False
    finally:
        conn.close()
    return _state_from_row(row), has_rows


def _begin_immediate(conn) -> None:
    conn.execute("BEGIN IMMEDIATE")


def _mark_dirty() -> bool:
    """Bump the epoch and remember that the mailbox copy is behind. Returns whether rows exist."""
    conn = get_connection()
    try:
        _begin_immediate(conn)
        try:
            _ensure_state(conn)
            row = conn.execute(
                "SELECT db_id, epoch FROM tournament_vault_state WHERE id = 1"
            ).fetchone()
            db_id = (row["db_id"] or "") if row else ""
            try:
                epoch = int(row["epoch"] or 0) if row else 0
            except (TypeError, ValueError):
                epoch = 0
            conn.execute("DELETE FROM tournament_vault_state")
            conn.execute(
                "INSERT INTO tournament_vault_state (id, db_id, dirty, epoch) VALUES (1, ?, 1, ?)",
                (db_id, epoch + 1),
            )
            has_rows = _counts_have_rows(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return has_rows
    finally:
        conn.close()


def _set_lineage(db_id: str, dirty: bool) -> None:
    """Update lineage and the dirty flag without moving the epoch backwards."""
    conn = get_connection()
    try:
        _begin_immediate(conn)
        try:
            _ensure_state(conn)
            row = conn.execute(
                "SELECT epoch FROM tournament_vault_state WHERE id = 1"
            ).fetchone()
            try:
                epoch = int(row["epoch"] or 0) if row else 0
            except (TypeError, ValueError):
                epoch = 0
            conn.execute("DELETE FROM tournament_vault_state")
            conn.execute(
                "INSERT INTO tournament_vault_state (id, db_id, dirty, epoch) VALUES (1, ?, ?, ?)",
                (db_id or "", 1 if dirty else 0, epoch),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def _clear_dirty_if_epoch(db_id: str, epoch: int) -> bool:
    """Clear dirty only if no write landed after this copy started."""
    conn = get_connection()
    try:
        _begin_immediate(conn)
        try:
            _ensure_state(conn)
            row = conn.execute(
                "SELECT epoch FROM tournament_vault_state WHERE id = 1"
            ).fetchone()
            try:
                current = int(row["epoch"] or 0) if row else 0
            except (TypeError, ValueError):
                current = 0
            if current != epoch:
                conn.rollback()
                return False
            conn.execute("DELETE FROM tournament_vault_state")
            conn.execute(
                "INSERT INTO tournament_vault_state (id, db_id, dirty, epoch) VALUES (1, ?, 0, ?)",
                (db_id or "", epoch),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return True
    finally:
        conn.close()


def _plan(state: dict, has_rows: bool, remote: dict | None, *, prefer_local: bool) -> dict:
    """Decide whether to restore, publish, or leave both sides alone.

    An empty file with no lineage is a wiped disk and is refilled from the
    snapshot. An empty file this desk just cleared (lineage set, dirty) is a
    real delete and is published so a later reboot stays empty.

    prefer_local is the manual restore button: that file is the one to keep.
    """
    if prefer_local:
        db_id = state["db_id"] or (remote["db_id"] if remote else "") or uuid.uuid4().hex
        return {"action": "publish", "db_id": db_id}

    if not has_rows and state["dirty"] and state["db_id"]:
        if remote is not None and remote["db_id"] != state["db_id"]:
            return {"action": "refuse", "db_id": state["db_id"]}
        if remote is not None and remote["has_rows"]:
            return {"action": "publish", "db_id": state["db_id"]}
        return {"action": "remember", "db_id": state["db_id"]}

    if remote is None:
        if not has_rows:
            return {"action": "none", "db_id": ""}
        return {"action": "publish", "db_id": state["db_id"] or uuid.uuid4().hex}

    if not has_rows:
        if remote["has_rows"]:
            return {"action": "restore", "db_id": remote["db_id"]}
        return {"action": "remember", "db_id": state["db_id"] or remote["db_id"]}

    local_id = state["db_id"]
    if local_id and local_id != remote["db_id"]:
        return {"action": "refuse", "db_id": local_id}
    if not local_id:
        # Local events exist and so does a snapshot, but this file was never
        # part of that snapshot. Do not destroy either copy.
        return {"action": "refuse", "db_id": ""}
    if state["dirty"]:
        return {"action": "publish", "db_id": local_id}
    return {"action": "none", "db_id": local_id}


def _sqlite_has_rows(data: bytes) -> bool:
    if not data.startswith(b"SQLite format 3\x00"):
        raise VaultError("Tournament vault could not be read.")
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "remote.db"
        path.write_bytes(data)
        conn = sqlite3.connect(str(path))
        try:
            try:
                return _counts_have_rows(conn)
            except sqlite3.DatabaseError as exc:
                raise VaultError("Tournament vault could not be read.") from exc
        finally:
            conn.close()


def _export_sqlite() -> bytes:
    """Consistent database bytes with staff hashes and vault bookkeeping removed."""
    import tempfile
    from pathlib import Path
    from modules.db_state import backup_bytes
    raw = backup_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "export.db"
        path.write_bytes(raw)
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA secure_delete = ON")
            for table in _STRIP_TABLES:
                try:
                    conn.execute(f'DELETE FROM "{table}"')
                except sqlite3.OperationalError:
                    pass
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()
        data = path.read_bytes()
    if not data.startswith(b"SQLite format 3\x00"):
        raise VaultError("Tournament vault could not be saved.")
    return data


def _replace_live(data: bytes) -> None:
    import tempfile
    from pathlib import Path
    if not data.startswith(b"SQLite format 3\x00"):
        raise VaultError("Tournament vault could not be read.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "vault.db"
        path.write_bytes(data)
        src = sqlite3.connect(str(path))
        try:
            try:
                checked = src.execute("PRAGMA integrity_check").fetchone()
            except sqlite3.DatabaseError as exc:
                raise VaultError("Tournament vault could not be read.") from exc
            if not checked or checked[0] != "ok":
                raise VaultError("Tournament vault could not be read.")
            from modules.db_state import copy_database
            dst = get_connection()
            try:
                if isinstance(dst, sqlite3.Connection):
                    src.backup(dst)
                else:
                    copy_database(src, dst)
            finally:
                dst.close()
        finally:
            src.close()


def _clear_staff_rows() -> None:
    """Drop staff rows that rode in on a database file. The staff vault refills them."""
    conn = get_connection()
    try:
        with conn:
            for table in ("staff_users", "staff_vault_state"):
                try:
                    conn.execute(f'DELETE FROM "{table}"')
                except sqlite3.OperationalError:
                    pass
    finally:
        conn.close()


def _install_snapshot(data: bytes, db_id: str) -> None:
    global _applying
    _applying = True
    try:
        _replace_live(data)
        _clear_staff_rows()
        from modules.db_state import migrate_if_needed
        migrate_if_needed()
        _set_lineage(db_id, dirty=False)
        try:
            from modules.event_logos import clear_logo_cache
            clear_logo_cache()
        except Exception:
            pass
    finally:
        _applying = False


def _open_store(user: str, password: str):
    if _test_store is not None:
        return _test_store
    return GmailTournamentStore(user, password)


def _backoff() -> None:
    global _next_network_at
    _next_network_at = time.monotonic() + _RETRY_AFTER_SECONDS


def _clear_backoff() -> None:
    global _next_network_at
    _next_network_at = 0.0


def _sync_once() -> str:
    """One read of the mailbox and at most one write. 'again' means a newer local write landed."""
    global _settled_empty, _known_empty
    creds = _cached_creds
    if creds is None:
        return "ok"
    passphrase, user, password = creds
    state, has_rows = _local_status()
    epoch_seen = state["epoch"]
    store = _open_store(user, password)
    restore_bytes = None
    restore_id = ""
    try:
        store.open()
        try:
            blob = store.load()
        except VaultError:
            raise
        remote = None
        if blob:
            remote = decode_snapshot(blob, passphrase)
            remote["has_rows"] = _sqlite_has_rows(remote["sqlite"])
        plan = _plan(state, has_rows, remote, prefer_local=_prefer_local)
        action = plan["action"]
        if action == "refuse":
            _set_status(REFUSE_NOTICE)
            kept = plan["db_id"] or state["db_id"] or uuid.uuid4().hex
            _set_lineage(kept, dirty=False)
            _clear_backoff()
            _settled_empty = False
            return "ok"
        if action == "remember":
            if plan["db_id"]:
                _set_lineage(plan["db_id"], dirty=False)
            _set_status("")
            _clear_backoff()
            _settled_empty = True
            return "ok"
        if action == "none":
            _set_status("")
            _clear_backoff()
            _settled_empty = bool(state["db_id"]) and not has_rows
            if not has_rows and not state["db_id"] and remote is None:
                # Nothing on disk and nothing in the mailbox. Further reruns
                # must not open IMAP until a tournament write lands.
                _known_empty = True
            return "ok"
        if action == "publish":
            _set_lineage(plan["db_id"], dirty=True)
            epoch_seen = _read_state()["epoch"]
            payload = encode_snapshot(plan["db_id"], _export_sqlite(), passphrase)
            store.save(payload)
            if not _clear_dirty_if_epoch(plan["db_id"], epoch_seen):
                return "again"
            latest = _read_state()
            if latest["dirty"] or latest["epoch"] != epoch_seen:
                return "again"
            _set_status("")
            _clear_backoff()
            _settled_empty = not _counts_open()
            log.info("Saved a tournament snapshot to the vault")
            return "ok"
        if action == "restore" and remote is not None:
            restore_bytes = remote["sqlite"]
            restore_id = plan["db_id"]
        else:
            return "ok"
    finally:
        store.close()
    if restore_bytes is None:
        return "ok"
    _install_snapshot(restore_bytes, restore_id)
    _set_status("")
    _clear_backoff()
    has_after = _counts_open()
    _settled_empty = not has_after
    if has_after:
        log.info("Restored tournament data from the vault")
    return "ok"


def _counts_open() -> bool:
    _state, has_rows = _local_status()
    return has_rows


def _run_sync() -> None:
    global _in_sync
    _in_sync = True
    try:
        rounds = 0
        while True:
            result = _sync_once()
            if result != "again":
                return
            rounds += 1
            if rounds >= 3:
                if _timing["debounce"] > 0:
                    _arm_timer()
                return
    except VaultError as exc:
        _set_status(_failure_text(str(exc)))
        _backoff()
    except Exception as exc:
        _set_status(_failure_text(_public_error(exc)))
        _backoff()
        log.warning("Tournament vault sync failed")
    finally:
        _in_sync = False


def _publish_blocking() -> None:
    with _lock_publish:
        if _in_sync:
            return
        if _cached_creds is None:
            return
        _run_sync()


def _timer_pending() -> bool:
    with _sched_lock:
        return _fire_at is not None


def _arm_timer(delay: float | None = None) -> None:
    global _worker, _fire_at, _dirty_since
    with _sched_lock:
        if _stop.is_set():
            return
        now = time.monotonic()
        if _dirty_since is None:
            _dirty_since = now
        if delay is None:
            _fire_at = fire_deadline(now, _dirty_since, _timing["debounce"], _timing["max_wait"])
        else:
            _fire_at = now + delay
        worker = _worker
        if worker is not None and worker.is_alive():
            return
        _worker = threading.Thread(target=_worker_main, name="tournament-vault", daemon=True)
        _worker.start()


def _worker_main() -> None:
    global _fire_at, _dirty_since
    while not _stop.is_set():
        with _sched_lock:
            fire = _fire_at
        if fire is None:
            return
        delay = fire - time.monotonic()
        if delay > 0:
            if _stop.wait(min(delay, 0.5)):
                return
            continue
        with _sched_lock:
            if _fire_at is None or time.monotonic() + 0.02 < _fire_at:
                continue
            _fire_at = None
            _dirty_since = None
        try:
            _publish_blocking()
        except Exception:
            log.warning("Tournament vault sync failed", exc_info=True)
        if _stop.is_set():
            return
        try:
            state = _read_state()
        except Exception:
            return
        if state["dirty"]:
            wait = _timing["debounce"] if _timing["debounce"] > 0 else 0.5
            remain = _next_network_at - time.monotonic()
            if remain > wait:
                wait = remain
            _arm_timer(delay=wait)
            continue
        with _sched_lock:
            if _fire_at is None:
                return


def note_tournament_change() -> None:
    """A tournament row changed. Publish now, or after a short quiet period. Never raises."""
    global _known_empty
    if _applying:
        return
    _known_empty = False
    try:
        if not _remember_creds():
            return
        has_rows = _mark_dirty()
    except Exception:
        log.warning("Tournament vault was not notified", exc_info=True)
        return
    if _in_sync:
        return
    try:
        if _timing["debounce"] <= 0 or not has_rows:
            _publish_blocking()
            return
        _arm_timer()
    except Exception:
        log.warning("Tournament vault was not notified", exc_info=True)


def sync_tournament_data() -> None:
    """Startup copy: refill a wiped file, or finish a save that did not land. Never raises."""
    try:
        if not vault_configured():
            return
        if not _remember_creds():
            return
        state, has_rows = _local_status()
        if (
            not _prefer_local
            and _known_empty
            and not state["dirty"]
            and not state["db_id"]
            and not has_rows
        ):
            return
        if (
            not _prefer_local
            and state["db_id"]
            and not state["dirty"]
            and (has_rows or _settled_empty)
        ):
            return
        if not _prefer_local and _timer_pending():
            return
        if not _prefer_local and time.monotonic() < _next_network_at:
            return
        needs_restore = (not has_rows) and not (state["dirty"] and state["db_id"])
        blocking = _prefer_local or needs_restore or not has_rows or _timing["debounce"] <= 0
        if blocking:
            _publish_blocking()
            return
        _arm_timer(delay=0)
    except Exception:
        log.warning("Tournament vault sync failed", exc_info=True)


@contextmanager
def prefer_local_database():
    """The file on disk was just chosen by hand (manual restore). Publish that copy."""
    global _prefer_local
    previous = _prefer_local
    _prefer_local = True
    try:
        yield
    finally:
        _prefer_local = previous


def wait_for_quiet(timeout: float = 3.0) -> None:
    """Block until a debounced copy finishes. Tests use this."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        worker = _worker
        alive = worker is not None and worker.is_alive()
        try:
            state = _read_state()
        except Exception:
            state = {"dirty": True}
        if not alive and not state["dirty"] and not _timer_pending():
            return
        time.sleep(0.02)
    raise TimeoutError("Tournament vault did not finish saving.")


def needs_attention() -> bool:
    """True when the sidebar should say the mailbox copy is off or failed."""
    if not vault_configured():
        return True
    return bool(LAST_ERROR)


def notice() -> str:
    """One line for the desk. Does not contact the mailbox."""
    try:
        if not vault_configured():
            return OFF_NOTICE
        if LAST_ERROR:
            return LAST_ERROR
        state = _read_state()
    except Exception:
        return PENDING_NOTICE
    if state["db_id"] and not state["dirty"]:
        return SAVED_NOTICE
    return PENDING_NOTICE


def _chunk_payload(payload: bytes) -> list[bytes]:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise VaultError("Tournament vault could not be saved.") from exc
    size = max(1, int(_CHUNK_CHARS))
    parts = [text[i:i + size] for i in range(0, len(text), size)] or [""]
    if len(parts) > _MAX_CHUNKS:
        raise VaultError(
            "Tournament vault copy is too large for the mailbox. "
            "Download a backup from Backup & Restore."
        )
    return [part.encode("ascii") for part in parts]


def _wrap_message(payload: bytes, snapshot_id: str, part: int, total: int) -> bytes:
    token = payload.decode("ascii")
    folded = "\r\n".join(token[i:i + 76] for i in range(0, len(token), 76))
    text = (
        f"Subject: {_SUBJECT}\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=us-ascii\r\n"
        "Content-Transfer-Encoding: 7bit\r\n"
        f"X-Prism-Snapshot: {snapshot_id}\r\n"
        f"X-Prism-Part: {part}/{total}\r\n"
        "\r\n"
        f"{folded}\r\n"
    )
    return text.encode("ascii")


def _header_value(header: str, name: str) -> str:
    prefix = name.lower() + ":"
    for line in header.splitlines():
        if line.lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _unwrap_message(raw: bytes) -> dict:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise VaultError("Tournament vault could not be read.") from exc
    parts = text.split("\r\n\r\n", 1)
    if len(parts) != 2:
        parts = text.split("\n\n", 1)
    if len(parts) != 2 or _SUBJECT not in parts[0]:
        raise VaultError("Tournament vault could not be read.")
    snapshot = _header_value(parts[0], "X-Prism-Snapshot")
    part_text = _header_value(parts[0], "X-Prism-Part")
    if not snapshot or "/" not in part_text:
        raise VaultError("Tournament vault could not be read.")
    try:
        part_s, total_s = part_text.split("/", 1)
        part = int(part_s)
        total = int(total_s)
    except ValueError as exc:
        raise VaultError("Tournament vault could not be read.") from exc
    if part < 1 or total < 1 or part > total:
        raise VaultError("Tournament vault could not be read.")
    compact = "".join(parts[1].split())
    if not compact:
        raise VaultError("Tournament vault could not be read.")
    return {"snapshot": snapshot, "part": part, "total": total, "payload": compact.encode("ascii")}


def _assemble(messages: list[tuple[int, bytes]]) -> bytes | None:
    if not messages:
        return None
    groups: dict[str, dict] = {}
    for uid, raw in messages:
        try:
            parsed = _unwrap_message(raw)
        except VaultError:
            continue
        group = groups.setdefault(
            parsed["snapshot"],
            {"total": parsed["total"], "parts": {}, "max_uid": uid, "bad": False},
        )
        if group["total"] != parsed["total"]:
            group["bad"] = True
        group["parts"][parsed["part"]] = parsed["payload"]
        if uid > group["max_uid"]:
            group["max_uid"] = uid
    complete = []
    for group in groups.values():
        if group["bad"]:
            continue
        total = group["total"]
        if total < 1 or set(group["parts"]) != set(range(1, total + 1)):
            continue
        payload = b"".join(group["parts"][index] for index in range(1, total + 1))
        complete.append((group["max_uid"], payload))
    if not complete:
        raise VaultError("Tournament vault could not be read.")
    complete.sort(key=lambda item: item[0])
    return complete[-1][1]


def _rfc822(fetched) -> bytes:
    for item in fetched or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    raise VaultError("Tournament vault could not be read.")


def _imap_connect():
    return imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, timeout=_IMAP_TIMEOUT_SECONDS)


class GmailTournamentStore:
    """Encrypted snapshot messages under the PrismTournamentVault label.

    A snapshot that fits in one message is one message. A larger snapshot is
    several numbered parts. After a complete save, older messages are removed.
    """

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
            log.warning("Tournament vault sign-in failed (%s)", type(exc).__name__)
            raise VaultError("Tournament vault sign-in failed.") from None
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
            raise VaultError("Tournament vault mailbox could not be opened.")
        status, _data = imap.select(MAILBOX)
        if status != "OK":
            raise VaultError("Tournament vault mailbox could not be opened.")

    def _ids(self, imap) -> list[bytes]:
        status, data = imap.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        return data[0].split()

    def _messages(self) -> list[tuple[int, bytes]]:
        imap = self._imap
        if imap is None:
            raise VaultError("Tournament vault could not be read.")
        self._select(imap)
        found = []
        for mid in self._ids(imap):
            status, fetched = imap.fetch(mid, "(RFC822)")
            if status != "OK":
                raise VaultError("Tournament vault could not be read.")
            found.append((int(bytes(mid).decode("ascii")), _rfc822(fetched)))
        return found

    def load(self) -> bytes | None:
        return _assemble(self._messages())

    def save(self, payload: bytes) -> None:
        if not payload:
            raise VaultError("Tournament vault could not be saved.")
        parts = _chunk_payload(payload)
        snapshot_id = uuid.uuid4().hex
        imap = self._imap
        if imap is None:
            raise VaultError("Tournament vault could not be saved.")
        self._select(imap)
        before = set(self._ids(imap))
        for index, part in enumerate(parts, start=1):
            status, _data = imap.append(
                MAILBOX,
                "(\\Seen)",
                imaplib.Time2Internaldate(time.time()),
                _wrap_message(part, snapshot_id, index, len(parts)),
            )
            if status != "OK":
                raise VaultError("Tournament vault could not be saved.")
        ids = self._ids(imap)
        new_ids = [mid for mid in ids if mid not in before]
        if len(new_ids) != len(parts):
            raise VaultError("Tournament vault could not be saved.")
        for mid in new_ids:
            status, fetched = imap.fetch(mid, "(RFC822)")
            if status != "OK":
                raise VaultError("Tournament vault could not be saved.")
            parsed = _unwrap_message(_rfc822(fetched))
            if parsed["snapshot"] != snapshot_id:
                raise VaultError("Tournament vault could not be saved.")
        stale = [mid for mid in ids if mid not in set(new_ids)]
        if not stale:
            return
        try:
            for old in stale:
                imap.store(old, "+FLAGS", "\\Deleted")
            imap.expunge()
        except Exception:
            log.warning("Tournament vault left an older copy in the mailbox")
