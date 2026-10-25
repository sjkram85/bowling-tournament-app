"""The desk uses the on-disk SQLite file.

TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are not read. PRISM_TEST_TURSO_URL does
not switch the suite onto a libSQL server. PRISM_DB_ENGINE=libsql-file still
runs the libSQL adapter against the local file inside the tests that set it.
"""
