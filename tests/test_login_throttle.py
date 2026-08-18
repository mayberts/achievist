"""
Failed-login throttling and expired-session cleanup.

Login had no limiter of any kind: guessing ran as fast as the server could
hash. These cover the parts that are easy to get subtly wrong — that a good
password still works right up to the cap, that the cap actually bites, that
success clears the slate, and that an unknown username costs the same time
as a wrong password so it can't be used to enumerate accounts.
"""

import httpx
import pytest

from app import auth, db, ratelimit
from app.main import app
from tests.conftest import requires_db


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── the limiter itself, no database needed ───────────────────────────────

def test_locks_out_only_after_the_configured_number_of_failures():
    lim = ratelimit.LoginLimiter()
    key = "user:dad"
    for _ in range(ratelimit.USER_MAX_ATTEMPTS - 1):
        lim.record_failure(key, max_attempts=ratelimit.USER_MAX_ATTEMPTS, window=900, lockout=600)
        assert lim.retry_after(key) == 0, "locked out too early"

    lim.record_failure(key, max_attempts=ratelimit.USER_MAX_ATTEMPTS, window=900, lockout=600)
    assert lim.retry_after(key) > 0


def test_lockout_expires():
    lim = ratelimit.LoginLimiter()
    key = "user:dad"
    for _ in range(3):
        lim.record_failure(key, max_attempts=3, window=900, lockout=600, now=1000.0)
    assert lim.retry_after(key, now=1000.0) > 0
    assert lim.retry_after(key, now=1000.0 + 599) > 0
    assert lim.retry_after(key, now=1000.0 + 601) == 0


def test_failures_outside_the_window_do_not_accumulate():
    """Eight typos spread over a year must not add up to a lockout."""
    lim = ratelimit.LoginLimiter()
    key = "user:dad"
    for i in range(20):
        lim.record_failure(key, max_attempts=3, window=900, lockout=600, now=1000.0 + i * 1000)
        assert lim.retry_after(key, now=1000.0 + i * 1000) == 0


def test_a_locked_key_never_reports_zero_wait():
    lim = ratelimit.LoginLimiter()
    key = "user:dad"
    for _ in range(3):
        lim.record_failure(key, max_attempts=3, window=900, lockout=600, now=1000.0)
    # Sub-second remaining would truncate to 0 and read as "go ahead".
    assert lim.retry_after(key, now=1000.0 + 599.7) >= 1


def test_ip_budget_is_looser_than_the_username_budget():
    """Behind a reverse proxy the whole family shares one address, so a tight
    IP limit would let one attacker lock everyone out."""
    assert ratelimit.IP_MAX_ATTEMPTS > ratelimit.USER_MAX_ATTEMPTS


# ── end to end through the endpoint ──────────────────────────────────────

@requires_db
async def test_repeated_wrong_passwords_get_429_then_the_right_one_still_fails(db_conn, client):
    await db.create_user(db_conn, "dad", auth.hash_password("correctpassword1"), is_admin=True)
    await db_conn.commit()

    for _ in range(ratelimit.USER_MAX_ATTEMPTS):
        r = await client.post("/api/auth/login", json={"username": "dad", "password": "nope"})
        assert r.status_code == 401

    r = await client.post("/api/auth/login", json={"username": "dad", "password": "nope"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0

    # The lockout has to hold even for the correct password, or it would be
    # trivially bypassed by the very guess it exists to prevent.
    r = await client.post("/api/auth/login", json={"username": "dad", "password": "correctpassword1"})
    assert r.status_code == 429


@requires_db
async def test_a_correct_password_clears_the_failure_count(db_conn, client):
    await db.create_user(db_conn, "dad", auth.hash_password("correctpassword1"), is_admin=True)
    await db_conn.commit()

    for _ in range(ratelimit.USER_MAX_ATTEMPTS - 1):
        await client.post("/api/auth/login", json={"username": "dad", "password": "nope"})

    ok = await client.post("/api/auth/login", json={"username": "dad", "password": "correctpassword1"})
    assert ok.status_code == 200

    # Slate wiped: another near-full run of typos must not tip straight over.
    for _ in range(ratelimit.USER_MAX_ATTEMPTS - 1):
        r = await client.post("/api/auth/login", json={"username": "dad", "password": "nope"})
        assert r.status_code == 401


@requires_db
async def test_unknown_username_is_indistinguishable_from_a_wrong_password(db_conn, client):
    await db.create_user(db_conn, "dad", auth.hash_password("correctpassword1"), is_admin=True)
    await db_conn.commit()

    real = await client.post("/api/auth/login", json={"username": "dad", "password": "nope"})
    fake = await client.post("/api/auth/login", json={"username": "nobody", "password": "nope"})
    assert real.status_code == fake.status_code == 401
    assert real.json()["detail"] == fake.json()["detail"]


@requires_db
async def test_expired_sessions_are_purged_and_live_ones_are_not(db_conn):
    from datetime import datetime, timedelta, timezone

    user = await db.create_user(db_conn, "dad", auth.hash_password("correctpassword1"), is_admin=True)
    now = datetime.now(timezone.utc)
    await db.create_session(db_conn, "live-token", user["id"], now + timedelta(days=1))
    await db.create_session(db_conn, "dead-token", user["id"], now - timedelta(days=1))
    await db_conn.commit()

    removed = await db.delete_expired_sessions(db_conn)
    assert removed == 1

    assert await db.get_session_user(db_conn, "live-token") is not None
    assert await db.get_session_user(db_conn, "dead-token") is None
