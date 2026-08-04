"""
Tests for app/platforms/googleplay.py — syncs via Exophase's public
per-player API rather than registering a Google Cloud OAuth client for
Play Games Services' official (but heavier-to-integrate) API. Mirrors
tests/test_ea.py and tests/test_ubisoft.py exactly since all three share
app.platforms.exophase.sync_environment.
"""

import pytest

from app import config, db
from app.platforms import exophase as exophase_module
from app.platforms.googleplay import GooglePlayPlatform
from tests.conftest import requires_db

pytestmark = requires_db


async def test_missing_exophase_config_raises(monkeypatch):
    monkeypatch.setattr(config, "EXOPHASE_PLAYER_ID", "")
    monkeypatch.setattr(config, "EXOPHASE_ACCESS_TOKEN", "")
    with pytest.raises(RuntimeError, match="EXOPHASE_PLAYER_ID"):
        await GooglePlayPlatform().sync({"external_id": "googleplay"}, conn=None)


async def test_sync_upserts_games_and_achievements(monkeypatch, db_conn):
    monkeypatch.setattr(config, "EXOPHASE_PLAYER_ID", "123")
    monkeypatch.setattr(config, "EXOPHASE_ACCESS_TOKEN", "tok")
    user = await db.create_user(db_conn, "parent", "x")

    async def fake_games(client, player_id, access_token, environment):
        assert environment == "android"
        return [{
            "master_id": 1, "master_playerid": 999, "title": "Mini Metro",
            "total_awards": 3, "earned_awards": 1, "cover": "https://cdn/cover.png",
            "exo_slug": "mini-metro-android", "page_type": "achievements",
        }]

    async def fake_awards(exo_slug, page_type="achievements"):
        assert exo_slug == "mini-metro-android"
        assert page_type == "achievements"
        return [
            {"slug": "1-first-line", "name": "First Line", "description": "d1",
             "icon": "https://cdn/a.png", "points": "10", "rarity_pct": "70.0", "locked": False},
            {"slug": "2-network", "name": "Network", "description": "d2",
             "icon": "https://cdn/b.png", "points": "20", "rarity_pct": "30.0", "locked": True},
            {"slug": "3-planner", "name": "Planner", "description": "d3",
             "icon": "https://cdn/c.png", "points": "30", "rarity_pct": "5.0", "locked": True},
        ]

    async def fake_earned(master_playerid, game_id):
        assert (master_playerid, game_id) == (999, 1)
        return {"1-first-line": {"timestamp": 1704067200, "icon": "https://cdn/a-earned.png"}}

    monkeypatch.setattr(exophase_module, "fetch_environment_games", fake_games)
    monkeypatch.setattr(exophase_module, "fetch_game_page_awards", fake_awards)
    monkeypatch.setattr(exophase_module, "fetch_earned", fake_earned)

    await GooglePlayPlatform().sync({"external_id": "googleplay", "user_id": user["id"]}, db_conn)
    await db_conn.commit()

    linked_id = await db.upsert_linked_account(db_conn, user["id"], "googleplay", "googleplay")
    row = await db._fetchrow(
        db_conn,
        "SELECT ug.earned_achievements, ug.total_achievements FROM user_games ug "
        "JOIN platform_games pg ON pg.id = ug.platform_game_id "
        "WHERE ug.linked_account_id = %s AND pg.platform_app_id = %s",
        linked_id, "mini-metro-android",
    )
    assert row["earned_achievements"] == 1
    assert row["total_achievements"] == 3
