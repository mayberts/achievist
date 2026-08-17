"""
Fixtures for the browser smoke tests.

These live outside `tests/` on purpose. pytest.ini points testpaths at
`tests`, so a plain `pytest` never collects these and never claims to have
run them — they need a built frontend, a browser and a live server, and a
suite that quietly skipped them would be the same trap as the DB-backed
tests silently sitting out (see tests/conftest.py). Run them deliberately:

    pytest e2e

What they are for: jsdom, which the Vitest component tests run against, has
no layout engine. It cannot tell you that a button's label wrapped onto two
lines or that the page scrolls sideways at some width. Those need a real
browser, and they are exactly the regressions that have slipped through.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBDIST = REPO_ROOT / "app" / "webdist"

E2E_DATABASE_URL = os.getenv(
    "E2E_DATABASE_URL",
    os.getenv("TEST_DATABASE_URL", "postgresql://pantheon:pantheon@localhost:5432/pantheon_e2e"),
)

USERNAME = "smoke"
PASSWORD = "smokepassword1"

# Playwright normally finds its own browser. This override exists for
# environments that already have a Chromium on disk under a different
# revision than the installed Playwright expects.
CHROMIUM_PATH = os.getenv("E2E_CHROMIUM_PATH")

# Seeding runs in its own interpreter rather than in-process: pytest.ini sets
# asyncio_mode=auto, so there is already a loop running here and the app's db
# helpers are async. A subprocess gets a clean one and lets us reuse those
# helpers verbatim instead of reimplementing the schema and inserts.
_SEED_SCRIPT = """
import asyncio, os, sys
sys.path.insert(0, {repo!r})
os.environ["DATABASE_URL"] = {url!r}
from datetime import datetime, timedelta
from app import auth, config, db

config.DATABASE_URL = {url!r}

TABLES = ["sync_runs", "user_achievements", "achievements", "user_games",
          "platform_games", "igdb_games", "sessions", "linked_accounts", "users"]

async def main():
    pool = await db.get_pool()
    try:
        await db.apply_schema(pool)
        async with pool.connection() as conn:
            for table in TABLES:
                await conn.execute("TRUNCATE TABLE " + table + " RESTART IDENTITY CASCADE")

            user = await db.create_user(conn, {username!r}, auth.hash_password({password!r}), is_admin=True)
            account = await db.upsert_account(conn, user["id"], "steam", "111", {{}})
            now = datetime.now()

            # One finished game and one in progress, so Quick Wins, the chase
            # list and both milestone cards all have something to render.
            done = await db.upsert_platform_game(conn, "steam", "1", "A Finished Game", None, 4)
            await db.upsert_user_game(conn, account, done, 600, 4, 4, now - timedelta(days=3))
            for i in range(4):
                a = await db.upsert_achievement(conn, done, "d%d" % i, "Cleared %d" % i, "", None, 10, 20.0)
                await db.upsert_user_achievement(conn, account, a, True, now - timedelta(days=3, hours=i))

            wip = await db.upsert_platform_game(conn, "steam", "2", "A Game In Progress", None, 6)
            await db.upsert_user_game(conn, account, wip, 120, 2, 6, now - timedelta(days=1))
            for i in range(6):
                a = await db.upsert_achievement(conn, wip, "w%d" % i, "Objective %d" % i, "", None, 10, 3.5 + i)
                await db.upsert_user_achievement(
                    conn, account, a, i < 2, now - timedelta(days=1) if i < 2 else None)
            await conn.commit()
    finally:
        await pool.close()

asyncio.run(main())
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url() -> str:
    """A real server, serving the built SPA against a seeded database."""
    if not (WEBDIST / "index.html").exists():
        pytest.fail(
            f"No built frontend at {WEBDIST}. These tests drive the real app, so build it first:\n"
            "    cd frontend && npm ci && npm run build"
        )
    try:
        with psycopg.connect(E2E_DATABASE_URL, connect_timeout=3):
            pass
    except Exception as exc:
        pytest.fail(f"No Postgres reachable at {E2E_DATABASE_URL} for the smoke tests: {exc}")

    seed = subprocess.run(
        [sys.executable, "-c", _SEED_SCRIPT.format(
            repo=str(REPO_ROOT), url=E2E_DATABASE_URL, username=USERNAME, password=PASSWORD,
        )],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if seed.returncode != 0:
        pytest.fail(f"seeding failed:\n{seed.stdout}\n{seed.stderr}")

    port = _free_port()
    # Server output goes to a file, not a pipe: nothing here drains a pipe, so
    # once the access log filled its buffer the server would block and the
    # whole run would hang.
    log = tempfile.NamedTemporaryFile(prefix="e2e-server-", suffix=".log", delete=False)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": E2E_DATABASE_URL},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"Server exited before it was ready:\n{Path(log.name).read_text()}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            pytest.fail(f"Server at {url} never became ready")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        Path(log.name).unlink(missing_ok=True)


@pytest_asyncio.fixture
async def page(base_url):
    """A logged-in page. Signing in through the API keeps these tests about
    layout rather than about the login form."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        kwargs = {"executable_path": CHROMIUM_PATH} if CHROMIUM_PATH else {}
        browser = await p.chromium.launch(**kwargs)
        try:
            context = await browser.new_context(viewport={"width": 1280, "height": 900})
            await context.request.post(
                f"{base_url}/api/auth/login",
                data={"username": USERNAME, "password": PASSWORD},
            )
            page = await context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(base_url, wait_until="networkidle")
            await page.wait_for_timeout(500)
            yield page
            assert not errors, f"the page raised: {errors}"
        finally:
            await browser.close()
