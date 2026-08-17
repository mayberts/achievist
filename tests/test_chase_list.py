"""
Tests for GET /api/chase-list — the rarest still-locked achievements in games
you've been playing.

The ranking used to happen in the browser, which meant downloading every
achievement of every recent game to show eight rows. It's now one SQL query
that returns only the displayed rows, so the selection rules it enforces —
recent games only, still-unfinished only, a per-game cap, rarest first — need
covering here rather than being visible in the client.
"""

from datetime import datetime, timedelta

import httpx
import pytest

from app import auth, db
from app.main import app
from tests.conftest import requires_db

pytestmark = requires_db

_NOW = datetime.now()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _login(db_conn, client, username="parent") -> int:
    user = await db.create_user(db_conn, username, auth.hash_password("parentpassword1"), is_admin=True)
    await db_conn.commit()
    await client.post("/api/auth/login", json={"username": username, "password": "parentpassword1"})
    return user["id"]


async def _seed_game(
    db_conn, account_id: int, app_id: str, name: str, *,
    rarities: list[float | None], earned: int, days_ago: int | None = 1,
    platform: str = "steam",
) -> int:
    """A game whose achievements carry the given rarities; the first `earned`
    of them are unlocked, the rest locked."""
    total = len(rarities)
    game = await db.upsert_platform_game(db_conn, platform, app_id, name, None, total)
    last_played = None if days_ago is None else _NOW - timedelta(days=days_ago)
    await db.upsert_user_game(db_conn, account_id, game, 0, earned, total, last_played)
    for i, rarity in enumerate(rarities):
        a = await db.upsert_achievement(
            db_conn, game, f"{app_id}-{i}", f"{name} {i}", "", None, 10, rarity,
        )
        await db.upsert_user_achievement(db_conn, account_id, a, i < earned, None)
    return game


async def test_returns_rarest_locked_first(db_conn, client):
    user_id = await _login(db_conn, client)
    acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await _seed_game(db_conn, acct, "a", "Game", rarities=[40.0, 2.0, 15.0], earned=0)
    await db_conn.commit()

    rows = (await client.get("/api/chase-list")).json()
    # capped at two per game, and those two are the rarest
    assert [r["rarity_pct"] for r in rows] == [2.0, 15.0]
    assert rows[0]["name"] == "Game 1"
    assert rows[0]["game_name"] == "Game"
    assert rows[0]["platform"] == "steam"


async def test_a_single_game_cannot_fill_the_whole_list(db_conn, client):
    """An achievement-farm title with thousands of near-zero-rarity entries
    would otherwise crowd out every other game on rarity alone."""
    user_id = await _login(db_conn, client)
    acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await _seed_game(db_conn, acct, "farm", "Farm", rarities=[0.0] * 40, earned=0, days_ago=1)
    await _seed_game(db_conn, acct, "other", "Other", rarities=[5.0, 6.0], earned=0, days_ago=2)
    await db_conn.commit()

    rows = (await client.get("/api/chase-list")).json()
    by_game = [r["game_name"] for r in rows]
    assert by_game.count("Farm") == 2
    assert by_game.count("Other") == 2


async def test_unlocked_achievements_are_excluded(db_conn, client):
    user_id = await _login(db_conn, client)
    acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    # the two rarest are already unlocked
    await _seed_game(db_conn, acct, "a", "Game", rarities=[1.0, 2.0, 30.0, 40.0], earned=2)
    await db_conn.commit()

    rows = (await client.get("/api/chase-list")).json()
    assert [r["rarity_pct"] for r in rows] == [30.0, 40.0]


async def test_achievements_without_a_rarity_are_excluded(db_conn, client):
    """The list is ranked by rarity, so an achievement with no figure has no
    place in it."""
    user_id = await _login(db_conn, client)
    acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await _seed_game(db_conn, acct, "a", "Game", rarities=[None, 12.0], earned=0)
    await db_conn.commit()

    rows = (await client.get("/api/chase-list")).json()
    assert [r["rarity_pct"] for r in rows] == [12.0]


async def test_an_achievement_with_no_user_row_counts_as_locked(db_conn, client):
    """A platform can list an achievement the user has no row for at all —
    never synced, never touched — which is as locked as it gets. That's why
    the query LEFT JOINs user_achievements instead of requiring a row."""
    user_id = await _login(db_conn, client)
    acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    game = await db.upsert_platform_game(db_conn, "steam", "a", "Game", None, 2)
    await db.upsert_user_game(db_conn, acct, game, 0, 0, 2, _NOW - timedelta(days=1))
    # only one of the two achievements gets a user_achievements row
    tracked = await db.upsert_achievement(db_conn, game, "a-0", "Tracked", "", None, 10, 30.0)
    await db.upsert_user_achievement(db_conn, acct, tracked, False, None)
    await db.upsert_achievement(db_conn, game, "a-1", "Untracked", "", None, 10, 8.0)
    await db_conn.commit()

    rows = (await client.get("/api/chase-list")).json()
    assert [r["name"] for r in rows] == ["Untracked", "Tracked"]


async def test_finished_and_never_played_games_are_skipped(db_conn, client):
    user_id = await _login(db_conn, client)
    acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await _seed_game(db_conn, acct, "done", "Finished", rarities=[1.0, 2.0], earned=2)
    await _seed_game(db_conn, acct, "never", "Never Played", rarities=[3.0], earned=0, days_ago=None)
    await _seed_game(db_conn, acct, "wip", "In Progress", rarities=[50.0, 60.0], earned=1)
    await db_conn.commit()

    rows = (await client.get("/api/chase-list")).json()
    assert {r["game_name"] for r in rows} == {"In Progress"}


async def test_only_the_most_recently_played_games_are_drawn_from(db_conn, client):
    user_id = await _login(db_conn, client)
    acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    # six candidates; only the five most recent may contribute, so the stalest
    # one is left out even though it holds the rarest achievement of all
    for i in range(5):
        await _seed_game(db_conn, acct, f"r{i}", f"Recent {i}", rarities=[20.0], earned=0, days_ago=i + 1)
    await _seed_game(db_conn, acct, "stale", "Stale", rarities=[0.1], earned=0, days_ago=400)
    await db_conn.commit()

    rows = (await client.get("/api/chase-list")).json()
    assert "Stale" not in {r["game_name"] for r in rows}


async def test_caps_the_number_of_rows_returned(db_conn, client):
    user_id = await _login(db_conn, client)
    acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    # five games x two rows each would be ten without the overall limit
    for i in range(5):
        await _seed_game(db_conn, acct, f"g{i}", f"Game {i}", rarities=[1.0, 2.0, 3.0], earned=0, days_ago=i + 1)
    await db_conn.commit()

    rows = (await client.get("/api/chase-list")).json()
    assert len(rows) == 8


async def test_scoped_to_the_logged_in_user(db_conn, client):
    user_id = await _login(db_conn, client)
    other = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"))
    other_acct = await db.upsert_account(db_conn, other["id"], "steam", "999", {})
    await _seed_game(db_conn, other_acct, "theirs", "Theirs", rarities=[0.1], earned=0)
    mine = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await _seed_game(db_conn, mine, "mine", "Mine", rarities=[50.0], earned=0)
    await db_conn.commit()

    rows = (await client.get("/api/chase-list")).json()
    assert {r["game_name"] for r in rows} == {"Mine"}


async def test_empty_when_there_is_nothing_to_chase(db_conn, client):
    await _login(db_conn, client)
    resp = await client.get("/api/chase-list")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_requires_login(db_conn, client):
    assert (await client.get("/api/chase-list")).status_code == 401
