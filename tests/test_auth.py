"""
Tests for app/auth.py (password hashing) and the auth/user-management
endpoints in app/main.py — Phase 1 of multi-user support: login/setup/session
handling works, though most other endpoints don't scope by user yet (that's
a separate follow-up).
"""

import httpx
import pytest

from app import auth, db
from app.main import app
from tests.conftest import requires_db

pytestmark = requires_db


def test_hash_and_verify_password_roundtrip():
    h = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", h)
    assert not auth.verify_password("wrong password", h)


def test_hash_is_salted_differently_each_time():
    a = auth.hash_password("same password")
    b = auth.hash_password("same password")
    assert a != b
    assert auth.verify_password("same password", a)
    assert auth.verify_password("same password", b)


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_setup_creates_admin_and_blocks_second_call(db_conn, client):
    resp = await client.post("/api/auth/setup", json={"username": "parent", "password": "hunter22222"})
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is True
    assert "achievist_session" in resp.cookies

    resp2 = await client.post("/api/auth/setup", json={"username": "someone_else", "password": "hunter22222"})
    assert resp2.status_code == 400


async def test_login_wrong_password_rejected(db_conn):
    async with db_conn:
        await db.create_user(db_conn, "parent", auth.hash_password("correctpassword"), is_admin=True)
        await db_conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/login", json={"username": "parent", "password": "wrongpassword"})
        assert resp.status_code == 401


async def test_login_logout_flow(db_conn):
    await db.create_user(db_conn, "parent", auth.hash_password("correctpassword"), is_admin=True)
    await db_conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        login = await c.post("/api/auth/login", json={"username": "parent", "password": "correctpassword"})
        assert login.status_code == 200
        assert "achievist_session" in c.cookies

        status = await c.get("/api/auth/status")
        assert status.json()["logged_in"] is True
        assert status.json()["user"]["username"] == "parent"

        await c.post("/api/auth/logout")
        status2 = await c.get("/api/auth/status")
        assert status2.json()["logged_in"] is False


async def test_non_admin_cannot_create_users(db_conn):
    await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await db_conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "kid", "password": "kidpassword1"})
        resp = await c.post("/api/users", json={"username": "sibling", "password": "siblingpassword1"})
        assert resp.status_code == 403


async def test_admin_can_create_and_delete_child_account(db_conn):
    admin = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    await db_conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})

        created = await c.post("/api/users", json={"username": "kid1", "password": "kidpassword1"})
        assert created.status_code == 200
        kid_id = created.json()["id"]

        listed = await c.get("/api/users")
        assert {u["username"] for u in listed.json()} == {"parent", "kid1"}

        deleted = await c.delete(f"/api/users/{kid_id}")
        assert deleted.status_code == 200

        listed2 = await c.get("/api/users")
        assert {u["username"] for u in listed2.json()} == {"parent"}


async def test_migrate_single_user_to_admin_attaches_existing_data(db_conn):
    pool = await db.get_pool()
    # Simulates a pre-multi-user row (no user_id yet) — can't use
    # db.upsert_account() here since it now always requires a real user_id.
    row = await db._fetchrow(
        db_conn,
        "INSERT INTO linked_accounts (platform, external_id, display_name) "
        "VALUES ('steam', '111', 'Old Profile Name') RETURNING id",
    )
    account_id = row["id"]
    await db_conn.commit()

    password = await db.migrate_single_user_to_admin(pool)
    assert password is not None

    admin = await db.get_user_by_username(db_conn, "admin")
    assert admin is not None
    assert admin["is_admin"] is True

    row = await db._fetchrow(db_conn, "SELECT user_id FROM linked_accounts WHERE id = %s", account_id)
    assert row["user_id"] == admin["id"]

    # Second call is a no-op — a user already exists.
    assert await db.migrate_single_user_to_admin(pool) is None


async def test_migrate_single_user_to_admin_noop_on_fresh_install(db_conn):
    pool = await db.get_pool()
    assert await db.migrate_single_user_to_admin(pool) is None
