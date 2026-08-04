"""
Tests for GET /api/leaderboard and the users.share_stats opt-in flag —
family members only appear on each other's leaderboard once they've opted
in via PUT /api/profile, except the requesting user always sees themself.
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


async def _seed_achievements(db_conn, user_id: int, platform: str, external_id: str, unlocked: int):
    account_id = await db.upsert_account(db_conn, user_id, platform, external_id, {})
    game = await db.upsert_platform_game(db_conn, platform, "1", "Some Game", None, unlocked)
    await db.upsert_user_game(db_conn, account_id, game, 0, unlocked, unlocked)
    for i in range(unlocked):
        a = await db.upsert_achievement(db_conn, game, f"a{i}", f"Achievement {i}", "", None, 10, None)
        await db.upsert_user_achievement(db_conn, account_id, a, True, None)


async def test_leaderboard_only_shows_self_when_no_one_opted_in(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await _seed_achievements(db_conn, parent["id"], "steam", "111", 2)
    await _seed_achievements(db_conn, kid["id"], "steam", "222", 5)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/leaderboard")
    assert resp.status_code == 200
    usernames = [e["username"] for e in resp.json()["entries"]]
    assert usernames == ["parent"]


async def test_leaderboard_includes_opted_in_users(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await db.update_user_profile(db_conn, kid["id"], None, None, True)
    await _seed_achievements(db_conn, parent["id"], "steam", "111", 2)
    await _seed_achievements(db_conn, kid["id"], "steam", "222", 5)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/leaderboard")
    assert resp.status_code == 200
    entries = {e["username"]: e for e in resp.json()["entries"]}
    assert set(entries) == {"parent", "kid"}
    # 15 pts/achievement for unrated rarity: kid has 5 unlocked, parent has 2
    assert entries["kid"]["achievist_points"] == 75
    assert entries["parent"]["achievist_points"] == 30
    assert entries["kid"]["achievements_unlocked"] == 5


async def test_share_stats_toggle_via_profile_endpoint(db_conn, client):
    await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.put("/api/profile", json={"share_stats": True})
    assert resp.status_code == 200
    assert resp.json()["share_stats"] is True

    prof = await client.get("/api/profile")
    assert prof.json()["share_stats"] is True
