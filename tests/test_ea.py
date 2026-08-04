"""
Tests for app/platforms/ea.py — EA App achievement sync via Exophase's public
per-player API (Exophase has already reverse-engineered EA/Origin achievement
data; EA's own unofficial GraphQL API was a dead end — see the module
docstring in app/platforms/ea.py for why). Mocks the Exophase helper
functions directly rather than hitting real network.
"""

import pytest

from app import config, db
from app.platforms import ea as ea_module
from app.platforms.ea import EAPlatform
from tests.conftest import requires_db

pytestmark = requires_db


async def test_missing_exophase_config_raises(monkeypatch):
    monkeypatch.setattr(config, "EXOPHASE_PLAYER_ID", "")
    monkeypatch.setattr(config, "EXOPHASE_ACCESS_TOKEN", "")
    with pytest.raises(RuntimeError, match="EXOPHASE_PLAYER_ID"):
        await EAPlatform().sync({"external_id": "ea"}, conn=None)


async def test_sync_upserts_games_and_achievements(monkeypatch, db_conn):
    monkeypatch.setattr(config, "EXOPHASE_PLAYER_ID", "123")
    monkeypatch.setattr(config, "EXOPHASE_ACCESS_TOKEN", "tok")

    async def fake_games(client, player_id, access_token, environment):
        assert environment == "origin"
        return [{
            "master_id": 1, "master_playerid": 999, "title": "Battlefield X",
            "total_awards": 2, "earned_awards": 1, "cover": "https://cdn/cover.png",
            "exo_slug": "battlefield-x-origin",
        }]

    async def fake_icons(exo_slug):
        assert exo_slug == "battlefield-x-origin"
        return {"first-blood": "https://cdn/first-blood.png", "ace": "https://cdn/ace.png"}

    async def fake_earned(master_playerid, game_id):
        assert (master_playerid, game_id) == (999, 1)
        return {"first-blood": {"timestamp": 1704067200, "icon": "https://cdn/first-blood-earned.png"}}

    monkeypatch.setattr(ea_module, "fetch_environment_games", fake_games)
    monkeypatch.setattr(ea_module, "fetch_game_page_icons", fake_icons)
    monkeypatch.setattr(ea_module, "fetch_earned", fake_earned)

    await EAPlatform().sync({"external_id": "ea"}, db_conn)
    await db_conn.commit()

    linked_id = await db.upsert_linked_account(db_conn, "ea", "ea")
    row = await db._fetchrow(
        db_conn,
        "SELECT ug.earned_achievements, ug.total_achievements FROM user_games ug "
        "JOIN platform_games pg ON pg.id = ug.platform_game_id "
        "WHERE ug.linked_account_id = %s AND pg.platform_app_id = %s",
        linked_id, "battlefield-x-origin",
    )
    assert row["earned_achievements"] == 1
    assert row["total_achievements"] == 2
