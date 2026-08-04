"""
Tests for app/platforms/ea.py — EA App achievement sync via the unofficial
Juno GraphQL API. Uses httpx.MockTransport to stub responses (no real
network access, since accounts.ea.com/service-aggregation-layer.juno.ea.com
are unreachable from this environment and were never verified live).
"""

import httpx
import pytest

from app import db
from app.platforms.ea import EAPlatform
from tests.conftest import requires_db

pytestmark = requires_db


def _json(data: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _patch_client(monkeypatch, handler):
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler))
    )


async def test_missing_token_raises():
    with pytest.raises(RuntimeError, match="Missing EA access token"):
        await EAPlatform().sync({"credentials": {}}, conn=None)


async def test_expired_token_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    _patch_client(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="expired or invalid"):
        await EAPlatform().sync({"credentials": {"access_token": "stale"}}, conn=None)


async def test_sync_upserts_games_and_achievements(monkeypatch, db_conn):
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "GetIdentity" in body:
            return _json({"data": {"me": {"player": {"pd": "1", "psd": "psd-1", "displayName": "Nick"}}}})
        if "GetOwnedGameProducts" in body:
            return _json({
                "data": {
                    "me": {
                        "ownedGameProducts": {
                            "items": [
                                {"originOfferId": "offer-1", "product": {"id": "p1", "name": "Battlefield X"}},
                            ]
                        }
                    }
                }
            })
        if "GetAchievements" in body:
            return _json({
                "data": {
                    "achievements": {
                        "id": "offer-1",
                        "achievements": [
                            {"id": "a1", "name": "First Blood", "description": "Get a kill",
                             "awardCount": 1, "date": "2024-01-01T00:00:00.000Z"},
                            {"id": "a2", "name": "Ace", "description": "Win a round",
                             "awardCount": 0, "date": None},
                        ],
                    }
                }
            })
        raise AssertionError(f"unexpected request body: {body}")

    _patch_client(monkeypatch, handler)

    await EAPlatform().sync({"credentials": {"access_token": "tok"}}, db_conn)
    await db_conn.commit()

    linked_id = await db.upsert_linked_account(db_conn, "ea", "1")
    row = await db._fetchrow(
        db_conn,
        "SELECT ug.earned_achievements, ug.total_achievements FROM user_games ug "
        "JOIN platform_games pg ON pg.id = ug.platform_game_id "
        "WHERE ug.linked_account_id = %s AND pg.platform_app_id = %s",
        linked_id, "offer-1",
    )
    assert row["earned_achievements"] == 1
    assert row["total_achievements"] == 2
