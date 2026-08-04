"""
Tests for app/platforms/ubisoft.py — reworked to sync via Exophase's public
per-player API instead of Ubisoft's own club-actions API (whose "actions"
are mostly generic XP grinding, not curated achievements). Mirrors
tests/test_ea.py's approach exactly since both now share
app.platforms.exophase.sync_environment.
"""

import pytest

from app import config, db
from app.platforms import exophase as exophase_module
from app.platforms.ubisoft import UbisoftPlatform
from tests.conftest import requires_db

pytestmark = requires_db


async def test_missing_exophase_config_raises(monkeypatch):
    monkeypatch.setattr(config, "EXOPHASE_PLAYER_ID", "")
    monkeypatch.setattr(config, "EXOPHASE_ACCESS_TOKEN", "")
    with pytest.raises(RuntimeError, match="EXOPHASE_PLAYER_ID"):
        await UbisoftPlatform().sync({"external_id": "ubisoft"}, conn=None)


async def test_sync_upserts_games_and_achievements(monkeypatch, db_conn):
    monkeypatch.setattr(config, "EXOPHASE_PLAYER_ID", "123")
    monkeypatch.setattr(config, "EXOPHASE_ACCESS_TOKEN", "tok")

    async def fake_games(client, player_id, access_token, environment):
        assert environment == "uplay"
        return [{
            "master_id": 1, "master_playerid": 999, "title": "Far Cry 6",
            "total_awards": 3, "earned_awards": 2, "cover": "https://cdn/cover.png",
            "exo_slug": "far-cry-6-uplay", "page_type": "challenges",
        }]

    async def fake_icons(exo_slug, page_type="achievements"):
        assert exo_slug == "far-cry-6-uplay"
        assert page_type == "challenges"  # Ubisoft's page path differs from EA's
        return {"first-blood": "https://cdn/a.png", "well-armed": "https://cdn/b.png"}

    async def fake_earned(master_playerid, game_id):
        assert (master_playerid, game_id) == (999, 1)
        return {
            "first-blood": {"timestamp": 1704067200, "icon": "https://cdn/a-earned.png"},
            "well-armed": {"timestamp": 1704067300, "icon": "https://cdn/b-earned.png"},
        }

    monkeypatch.setattr(exophase_module, "fetch_environment_games", fake_games)
    monkeypatch.setattr(exophase_module, "fetch_game_page_icons", fake_icons)
    monkeypatch.setattr(exophase_module, "fetch_earned", fake_earned)

    await UbisoftPlatform().sync({"external_id": "ubisoft"}, db_conn)
    await db_conn.commit()

    linked_id = await db.upsert_linked_account(db_conn, "ubisoft", "ubisoft")
    row = await db._fetchrow(
        db_conn,
        "SELECT ug.earned_achievements, ug.total_achievements FROM user_games ug "
        "JOIN platform_games pg ON pg.id = ug.platform_game_id "
        "WHERE ug.linked_account_id = %s AND pg.platform_app_id = %s",
        linked_id, "far-cry-6-uplay",
    )
    assert row["earned_achievements"] == 2
    assert row["total_achievements"] == 3
