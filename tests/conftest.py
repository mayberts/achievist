"""
Shared fixtures for DB-backed integration tests.

Most of Pantheon's actual behavior (account dedup, achievement-unlock
detection, schema migrations) lives behind Postgres queries that the
DB-free unit/smoke tests can't exercise. These fixtures point the app at a
real (throwaway) test database when one is reachable, and skip the tests
that need it otherwise — so `pytest` still runs cleanly with no DB present
(e.g. a bare checkout), while CI and local dev-with-docker get full coverage.
"""

import os

import psycopg
import pytest
import pytest_asyncio

from app import config, db

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://pantheon:pantheon@localhost:5432/pantheon_test",
)

# Truncate order: children before parents, to satisfy FK constraints.
_APP_TABLES = [
    "sync_runs",
    "user_achievements",
    "achievements",
    "user_games",
    "platform_games",
    "igdb_games",
    "linked_accounts",
]


def _db_reachable() -> bool:
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=2):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_reachable(),
    reason=(
        "no reachable Postgres at TEST_DATABASE_URL "
        f"({TEST_DATABASE_URL}) — DB-backed tests are skipped"
    ),
)


@pytest_asyncio.fixture
async def db_conn():
    """A connection to a real, schema-applied, empty-between-tests test database."""
    config.DATABASE_URL = TEST_DATABASE_URL
    db._pool = None  # force a fresh pool bound to the test DB
    pool = await db.get_pool()
    await db.apply_schema(pool)
    async with pool.connection() as conn:
        yield conn
        for table in _APP_TABLES:
            await conn.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
