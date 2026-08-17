"""
Shared fixtures for DB-backed integration tests.

Most of Achievist's actual behavior (account dedup, achievement-unlock
detection, schema migrations, and every hand-written query behind the
statistics/leaderboard/chase-list endpoints) lives behind Postgres and can't
be exercised by the DB-free unit tests. These fixtures point the app at a
real (throwaway) test database when one is reachable, and skip the tests
that need it otherwise — so `pytest` still runs on a bare checkout.

Skipping quietly turned out to be its own hazard: well over half the suite
would sit out, and the run still ended in a green "N passed" that looks
exactly like a full pass. Two things guard against that now:

* Whenever the database is missing, the run ends with an unmissable summary
  saying how many tests did not run and how to run them.
* Setting REQUIRE_DB_TESTS=1 turns an unreachable database into an error
  instead of a skip. CI sets it, so a broken Postgres service container
  fails the build rather than quietly reducing it to the unit tests.
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
    "sessions",
    "linked_accounts",
    "users",
    "profile",
]


def _db_reachable() -> bool:
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=2):
            return True
    except Exception:
        return False


DB_REACHABLE = _db_reachable()

# Distinctive enough to pick these skips back out of the report later, and to
# tell them apart from any other reason a test might be skipped.
_SKIP_REASON = (
    "no reachable Postgres at TEST_DATABASE_URL "
    f"({TEST_DATABASE_URL}) — DB-backed tests are skipped"
)

requires_db = pytest.mark.skipif(not DB_REACHABLE, reason=_SKIP_REASON)


def _require_db_requested() -> bool:
    return os.getenv("REQUIRE_DB_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}


def pytest_configure(config):
    """Refuse to run at all when the caller said the database is mandatory.

    Without this, a CI job whose Postgres service failed to come up would
    skip every integration test and still report success.
    """
    if _require_db_requested() and not DB_REACHABLE:
        raise pytest.UsageError(
            f"REQUIRE_DB_TESTS is set but no Postgres is reachable at {TEST_DATABASE_URL}. "
            "Start one (see README → Backend tests) or unset REQUIRE_DB_TESTS to skip "
            "the DB-backed tests instead."
        )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Say loudly when a green run only covered part of the suite."""
    if DB_REACHABLE:
        return
    skipped = [
        report for report in terminalreporter.stats.get("skipped", [])
        if _SKIP_REASON in str(getattr(report, "longrepr", ""))
    ]
    if not skipped:
        return

    ran = len(terminalreporter.stats.get("passed", []))
    terminalreporter.write_sep("=", "INCOMPLETE RUN — NO DATABASE", red=True, bold=True)
    terminalreporter.write_line(
        f"{len(skipped)} DB-backed tests did not run; {ran} tests did. "
        "This run did NOT verify anything that touches Postgres."
    )
    terminalreporter.write_line(f"  No server answered at {TEST_DATABASE_URL}")
    terminalreporter.write_line(
        "  To run them:  docker run --rm -d -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16-alpine"
    )
    terminalreporter.write_line(
        "                TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest"
    )
    terminalreporter.write_line(
        "  To make a missing database an error instead of a skip:  REQUIRE_DB_TESTS=1 pytest"
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
