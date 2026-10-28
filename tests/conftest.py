"""The desk uses the on-disk SQLite file.

TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are not read. PRISM_TEST_TURSO_URL does
not switch the suite onto a libSQL server. PRISM_DB_ENGINE=libsql-file still
runs the libSQL adapter against the local file inside the tests that set it.

PRISM_STAFF_VAULT=off keeps the suite off the CHUSBC mailbox. A test that
exercises the staff vault turns it on and installs an in-memory store.
"""

import pytest


@pytest.fixture(autouse=True)
def _staff_vault_off(monkeypatch):
    monkeypatch.setenv("PRISM_STAFF_VAULT", "off")
    from modules import staff_vault

    staff_vault.use_store(None)
    yield
    staff_vault.use_store(None)
