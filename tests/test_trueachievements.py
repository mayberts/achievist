"""
Tests for app/platforms/trueachievements.py (the TSA/TA achievement-link
scraper) and the guide-link caching plumbing in app/db.py.
"""

import httpx
import pytest

from app import config, db
from app.platforms import trueachievements as ta
from tests.conftest import requires_db

pytestmark = requires_db

_FRAGMENT = """
<table>
  <tr><td><a href="/a2453/and-theyll-tell-two-friends-achievement">And They'll Tell Two Friends</a></td></tr>
  <tr><td><a href="/a2454/tf2-unboxed-achievement">TF2 Unboxed</a></td></tr>
</table>
"""


def test_slugify_matches_the_real_url_scheme():
    assert ta.slugify("Borderlands") == "Borderlands"
    assert ta.slugify("Halo Infinite") == "Halo-Infinite"
    assert ta.slugify("Tom Clancy's The Division™") == "Tom-Clancys-The-Division"


def test_normalize_name_ignores_case_and_punctuation():
    assert ta.normalize_name("And They'll Tell Two Friends") == ta.normalize_name("and theyll tell two friends")


def test_game_url_only_supports_steam_and_xbox():
    assert ta.game_url("steam", "Borderlands") == "https://truesteamachievements.com/game/Borderlands/achievements"
    assert ta.game_url("xbox", "Halo Infinite") == "https://www.trueachievements.com/game/Halo-Infinite/achievements"
    assert ta.game_url("psn", "Some Game") is None


def test_slugify_expands_common_edition_abbreviations():
    assert ta.slugify("Borderlands GOTY Enhanced") == "Borderlands-Game-of-the-Year-Enhanced"


def test_game_url_applies_manual_slug_overrides():
    # Confirmed real slug for this one (reported broken — TSA spells out
    # "Game of the Year" even beyond what the abbreviation expansion alone
    # produces from Steam's own "GOTY" app name).
    assert (
        ta.game_url("steam", "Borderlands GOTY Enhanced")
        == "https://truesteamachievements.com/game/Borderlands-Game-of-the-Year-Enhanced/achievements"
    )
    # Xbox's own name for this is just "Guitar Hero III" — missing the
    # "Legends of Rock" subtitle TA's real slug includes, which slugify()
    # alone could never recover.
    assert (
        ta.game_url("xbox", "Guitar Hero III")
        == "https://www.trueachievements.com/game/Guitar-Hero-3-Legends-of-Rock/achievements"
    )
    # TA uses Arabic numerals for this series, not Xbox's roman numerals.
    assert (
        ta.game_url("xbox", "Guitar Hero II")
        == "https://www.trueachievements.com/game/Guitar-Hero-2/achievements"
    )


async def test_fetch_achievement_links_parses_permalinks(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_FRAGMENT)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler), **kw)
    )
    links = await ta.fetch_achievement_links("steam", "Team Fortress 2")
    key = ta.normalize_name("And They'll Tell Two Friends")
    assert links[key] == "https://truesteamachievements.com/a2453/and-theyll-tell-two-friends-achievement"


async def test_fetch_achievement_links_returns_empty_on_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler), **kw)
    )
    links = await ta.fetch_achievement_links("steam", "Some Game")
    assert links == {}


async def test_search_achievement_url_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SEARCH_API_KEY", "")
    monkeypatch.setattr(config, "GOOGLE_SEARCH_ENGINE_ID", "")
    assert ta.search_api_configured() is False
    assert await ta.search_achievement_url("steam", "Team Fortress 2", "First Blood") is None


async def test_search_achievement_url_only_trusts_real_permalinks(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SEARCH_API_KEY", "fake-key")
    monkeypatch.setattr(config, "GOOGLE_SEARCH_ENGINE_ID", "fake-cx")
    assert ta.search_api_configured() is True

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [
                {"link": "https://truesteamachievements.com/game/Team-Fortress-2/achievements"},
                {"link": "https://truesteamachievements.com/a2453/and-theyll-tell-two-friends-achievement"},
            ]
        })

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler), **kw)
    )
    url = await ta.search_achievement_url("steam", "Team Fortress 2", "And They'll Tell Two Friends")
    assert url == "https://truesteamachievements.com/a2453/and-theyll-tell-two-friends-achievement"


async def test_search_achievement_url_returns_none_if_no_result_is_a_permalink(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SEARCH_API_KEY", "fake-key")
    monkeypatch.setattr(config, "GOOGLE_SEARCH_ENGINE_ID", "fake-cx")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [{"link": "https://truesteamachievements.com/game/Team-Fortress-2/achievements"}]
        })

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler), **kw)
    )
    url = await ta.search_achievement_url("steam", "Team Fortress 2", "First Blood")
    assert url is None


async def test_guide_links_need_refresh_true_until_marked_fetched(db_conn):
    game = await db.upsert_platform_game(db_conn, "steam", "440", "Team Fortress 2", None, 1)
    await db_conn.commit()

    assert await db.guide_links_need_refresh(db_conn, game) is True
    await db.mark_guide_links_fetched(db_conn, game)
    assert await db.guide_links_need_refresh(db_conn, game) is False


async def test_guide_links_need_refresh_false_for_unsupported_platform(db_conn):
    game = await db.upsert_platform_game(db_conn, "psn", "999", "Some Game", None, 1)
    await db_conn.commit()

    assert await db.guide_links_need_refresh(db_conn, game) is False


async def test_set_achievement_guide_urls_updates_the_right_rows(db_conn):
    game = await db.upsert_platform_game(db_conn, "steam", "440", "Team Fortress 2", None, 1)
    a1 = await db.upsert_achievement(db_conn, game, "a1", "First Blood", "", None, 10, None)
    a2 = await db.upsert_achievement(db_conn, game, "a2", "Domination", "", None, 10, None)
    await db_conn.commit()

    await db.set_achievement_guide_urls(db_conn, {a1: "https://truesteamachievements.com/a1/first-blood"})
    await db_conn.commit()

    names = await db.list_achievement_names(db_conn, game)
    rows = await db._fetch(db_conn, "SELECT id, guide_url FROM achievements WHERE platform_game_id = %s", game)
    by_id = {r["id"]: r["guide_url"] for r in rows}
    assert by_id[a1] == "https://truesteamachievements.com/a1/first-blood"
    assert by_id[a2] is None
    assert {n["id"] for n in names} == {a1, a2}


async def test_clear_guide_links_resets_the_30_day_cache(db_conn):
    game = await db.upsert_platform_game(db_conn, "steam", "440", "Team Fortress 2", None, 1)
    a1 = await db.upsert_achievement(db_conn, game, "a1", "First Blood", "", None, 10, None)
    await db.set_achievement_guide_urls(db_conn, {a1: "https://truesteamachievements.com/a1/first-blood"})
    await db.set_platform_game_guide_url(db_conn, game, "https://truesteamachievements.com/game/Wrong-Slug/achievements")
    await db.mark_guide_links_fetched(db_conn, game)
    await db_conn.commit()

    assert await db.guide_links_need_refresh(db_conn, game) is False

    await db.clear_guide_links(db_conn, game)
    await db_conn.commit()

    assert await db.guide_links_need_refresh(db_conn, game) is True
    row = await db._fetchrow(db_conn, "SELECT guide_url FROM platform_games WHERE id = %s", game)
    assert row["guide_url"] is None
    ach_row = await db._fetchrow(db_conn, "SELECT guide_url FROM achievements WHERE id = %s", a1)
    assert ach_row["guide_url"] is None


async def test_has_unmatched_achievements_and_list_unmatched(db_conn):
    game = await db.upsert_platform_game(db_conn, "steam", "440", "Team Fortress 2", None, 2)
    a1 = await db.upsert_achievement(db_conn, game, "a1", "First Blood", "", None, 10, None)
    a2 = await db.upsert_achievement(db_conn, game, "a2", "Domination", "", None, 10, None)
    await db_conn.commit()

    assert await db.has_unmatched_achievements(db_conn, game) is True
    unmatched = await db.list_unmatched_achievement_names(db_conn, game, limit=10)
    assert {u["id"] for u in unmatched} == {a1, a2}

    await db.set_achievement_guide_urls(db_conn, {
        a1: "https://truesteamachievements.com/a1/first-blood",
        a2: "https://truesteamachievements.com/a2/domination",
    })
    await db_conn.commit()

    assert await db.has_unmatched_achievements(db_conn, game) is False
    assert await db.list_unmatched_achievement_names(db_conn, game, limit=10) == []


async def test_list_unmatched_achievement_names_respects_limit(db_conn):
    game = await db.upsert_platform_game(db_conn, "steam", "440", "Team Fortress 2", None, 3)
    for i in range(3):
        await db.upsert_achievement(db_conn, game, f"a{i}", f"Achievement {i}", "", None, 10, None)
    await db_conn.commit()

    unmatched = await db.list_unmatched_achievement_names(db_conn, game, limit=2)
    assert len(unmatched) == 2
