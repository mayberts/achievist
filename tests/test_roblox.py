"""
Tests for app/platforms/roblox.py — syncs via Roblox's public badges API
(no login/API key needed). Uses httpx.MockTransport to stub responses so
these run without real network access.
"""

import httpx

from app import db
from app.platforms.roblox import RobloxPlatform
from tests.conftest import requires_db

pytestmark = requires_db


def _json(data: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/usernames/users" in url:
        return _json({"data": [{"id": 42, "name": "mayberts"}]})
    if "/users/42/badges/awarded-dates" in url:
        return _json({"data": [{"badgeId": 1, "awardedDate": "2024-01-01T00:00:00.000Z"}]})
    if "/users/42/badges" in url:
        return _json({
            "data": [{
                "id": 1, "name": "First Steps", "description": "Do the thing",
                "awardingUniverse": {"id": 100, "name": "Cool Game", "rootPlaceId": 200},
            }],
            "nextPageCursor": None,
        })
    if "/universes/100/badges" in url:
        return _json({
            "data": [
                {"id": 1, "name": "First Steps", "description": "Do the thing"},
                {"id": 2, "name": "Secret Badge", "description": "Locked"},
            ],
            "nextPageCursor": None,
        })
    if "/badges/icons" in url:
        return _json({"data": [{"targetId": 1, "imageUrl": "https://cdn/1.png"}]})
    raise AssertionError(f"unexpected request: {url}")


async def test_sync_upserts_games_and_achievements(monkeypatch, db_conn):
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(_handler))
    )
    user = await db.create_user(db_conn, "parent", "x")

    await RobloxPlatform().sync({"external_id": "mayberts", "user_id": user["id"]}, db_conn)
    await db_conn.commit()

    linked_id = await db.upsert_linked_account(db_conn, user["id"], "roblox", "mayberts")
    row = await db._fetchrow(
        db_conn,
        "SELECT ug.earned_achievements, ug.total_achievements, pg.store_id FROM user_games ug "
        "JOIN platform_games pg ON pg.id = ug.platform_game_id "
        "WHERE ug.linked_account_id = %s AND pg.platform_app_id = %s",
        linked_id, "100",
    )
    assert row["earned_achievements"] == 1
    assert row["total_achievements"] == 2
    assert row["store_id"] == "200"
