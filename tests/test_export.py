"""
Tests for GET /api/export — a self-service, per-user JSON export of a
user's own accounts (no credentials), games, and unlocked achievements.
"""

import httpx
import pytest

from app import auth, db
from app.main import app
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_export_contains_own_data_and_excludes_credentials(db_conn, client):
    user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    account_id = await db.upsert_account(db_conn, user["id"], "steam", "111", {"api_key": "super-secret"})
    game = await db.upsert_platform_game(db_conn, "steam", "1", "Borderlands", None, 3)
    await db.upsert_user_game(db_conn, account_id, game, 120, 2, 3)
    a = await db.upsert_achievement(db_conn, game, "a1", "First Blood", "desc", None, 10, 5.0)
    await db.upsert_user_achievement(db_conn, account_id, a, True, None)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]

    data = resp.json()
    assert data["username"] == "parent"
    assert len(data["accounts"]) == 1
    assert "credentials" not in data["accounts"][0]
    assert "api_key" not in str(data["accounts"][0])
    assert data["games"][0]["name"] == "Borderlands"
    assert data["achievements"][0]["achievement_name"] == "First Blood"


async def test_export_only_includes_own_data(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    kid_account = await db.upsert_account(db_conn, kid["id"], "steam", "222", {})
    game = await db.upsert_platform_game(db_conn, "steam", "2", "Halo", None, 1)
    await db.upsert_user_game(db_conn, kid_account, game, 0, 1, 1)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/export")
    assert resp.status_code == 200
    data = resp.json()
    assert data["accounts"] == []
    assert data["games"] == []
