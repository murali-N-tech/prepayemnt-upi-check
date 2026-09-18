"""Point the store at a throwaway database for the whole test session.

Without this the suite runs against data/behavior_profiles.db - the real one.
It passed for a long time because every table it needed already existed, so
the writes it did were invisible, and CREATE TABLE IF NOT EXISTS never had to
do anything. Adding a table made it visible: the DDL failed outright, and the
reason it failed is incidental (a network-mounted file), while the reason it
was reachable at all is not. A test run should not be able to touch a user's
data whether or not the filesystem happens to stop it.

Session-scoped and autouse, so no test has to remember. Individual tests that
want their own isolated database still override DB_PATH themselves.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_store():
    import backend.app.services.profile_store as store

    original = store.DB_PATH
    scratch = Path(tempfile.mkdtemp(prefix="upi-tests-")) / "test_store.db"
    store.DB_PATH = scratch
    store._SCHEMA_DONE.clear()
    try:
        yield scratch
    finally:
        store.DB_PATH = original
        store._SCHEMA_DONE.clear()
