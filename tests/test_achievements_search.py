"""
Integration tests for GET /api/achievements/search — searches/filters
achievements across the whole library, not just within one game. Requires
login and only returns achievements for games in the logged-in user's own
library (joined through user_games/linked_accounts).
"""

from datetime import datetime, timezone

import httpx
import pytest

from app import auth, db
from app.main import app
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def client(db_conn):
    await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    await db_conn.commit()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
        yield c


async def _seed(db_conn):
    """One steam account, two games, achievements spanning every rarity tier."""
    user = await db.get_user_by_username(db_conn, "parent")
    account_id = await db.upsert_account(db_conn, user["id"], "steam", "111", {})
    game1 = await db.upsert_platform_game(db_conn, "steam", "1", "Borderlands", None, 3)
    game2 = await db.upsert_platform_game(db_conn, "xbox", "2", "Halo", None, 1)
    await db.upsert_user_game(db_conn, account_id, game1, 0, 2, 3)
    await db.upsert_user_game(db_conn, account_id, game2, 0, 0, 1)

    achs = [
        (game1, "a1", "Legendary Feat", "so rare", 1.0, True),
        (game1, "a2", "Epic Deed", "pretty rare", 3.0, False),
        (game1, "a3", "Common Thing", "everyone has it", 80.0, True),
        (game2, "a4", "Halo Win", "won a match", 40.0, False),
    ]
    now = datetime.now(timezone.utc)
    for game_id, ach_id, name, desc, rarity, unlocked in achs:
        a = await db.upsert_achievement(db_conn, game_id, ach_id, name, desc, None, 10, rarity)
        await db.upsert_user_achievement(db_conn, account_id, a, unlocked, now if unlocked else None)

    # The API endpoint queries through a *different* pooled connection, which
    # (READ COMMITTED) can't see this connection's writes until committed.
    await db_conn.commit()
    return account_id


async def test_search_with_no_filters_returns_everything(db_conn, client):
    await _seed(db_conn)
    resp = await client.get("/api/achievements/search")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    assert len(data["achievements"]) == 4


async def test_search_filters_by_rarity_tier(db_conn, client):
    await _seed(db_conn)
    resp = await client.get("/api/achievements/search", params={"rarity": "Legendary"})
    data = resp.json()
    assert data["total"] == 1
    assert data["achievements"][0]["name"] == "Legendary Feat"


async def test_search_filters_by_text(db_conn, client):
    await _seed(db_conn)
    resp = await client.get("/api/achievements/search", params={"q": "Halo"})
    data = resp.json()
    names = {a["name"] for a in data["achievements"]}
    assert names == {"Halo Win"}


async def test_search_filters_by_unlocked(db_conn, client):
    await _seed(db_conn)
    resp = await client.get("/api/achievements/search", params={"unlocked": "true"})
    data = resp.json()
    assert data["total"] == 2
    assert all(a["unlocked"] for a in data["achievements"])


async def test_search_filters_by_platform(db_conn, client):
    await _seed(db_conn)
    resp = await client.get("/api/achievements/search", params={"platform": "xbox"})
    data = resp.json()
    assert data["total"] == 1
    assert data["achievements"][0]["platform"] == "xbox"


async def test_search_sort_by_rarity_is_rarest_first(db_conn, client):
    await _seed(db_conn)
    resp = await client.get("/api/achievements/search", params={"sort": "rarity"})
    data = resp.json()
    rarities = [a["rarity_pct"] for a in data["achievements"]]
    assert rarities == sorted(rarities)


async def test_search_pagination(db_conn, client):
    await _seed(db_conn)
    resp = await client.get("/api/achievements/search", params={"page": 1, "page_size": 2})
    data = resp.json()
    assert data["total"] == 4
    assert len(data["achievements"]) == 2


async def test_search_excludes_other_users_games(db_conn, client):
    await _seed(db_conn)
    other = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"))
    other_account = await db.upsert_account(db_conn, other["id"], "steam", "222", {})
    other_game = await db.upsert_platform_game(db_conn, "steam", "99", "Kid's Game", None, 1)
    await db.upsert_user_game(db_conn, other_account, other_game, 0, 0, 1)
    a = await db.upsert_achievement(db_conn, other_game, "b1", "Not Mine", "d", None, 10, 50.0)
    await db.upsert_user_achievement(db_conn, other_account, a, False, None)
    await db_conn.commit()

    resp = await client.get("/api/achievements/search")
    names = {a["name"] for a in resp.json()["achievements"]}
    assert "Not Mine" not in names
