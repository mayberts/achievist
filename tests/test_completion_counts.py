"""
Tests for how a fully-completed game is counted, including the case where a
platform reports more earned achievements than the game's stated total.

That used to land such a game outside every bucket at once: the "perfect
games" / "mastered" counts tested `completion_pct = 100`, and the 80-99%
"finished" band excludes anything at 100 or above, so a game that was *more*
than finished counted as neither. completion_pct is now clamped on write, and
the counts use `>=` so rows stored before the clamp are still counted.
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


async def _login(db_conn, client) -> int:
    user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    await db_conn.commit()
    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    return user["id"]


async def _pct(db_conn, platform_app_id: str) -> float:
    row = await db._fetchrow(
        db_conn,
        "SELECT ug.completion_pct FROM user_games ug "
        "JOIN platform_games pg ON pg.id = ug.platform_game_id "
        "WHERE pg.platform_app_id = %s",
        platform_app_id,
    )
    return float(row["completion_pct"])


async def test_completion_pct_is_clamped_when_earned_exceeds_total(db_conn, client):
    user_id = await _login(db_conn, client)
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    game = await db.upsert_platform_game(db_conn, "steam", "over", "Overcounted", None, 50)
    # platform claims 51 of 50 earned
    await db.upsert_user_game(db_conn, account_id, game, 0, 51, 50)
    await db_conn.commit()

    assert await _pct(db_conn, "over") == 100.0


async def test_normal_completion_is_unaffected_by_the_clamp(db_conn, client):
    user_id = await _login(db_conn, client)
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    game = await db.upsert_platform_game(db_conn, "steam", "half", "Halfway", None, 50)
    await db.upsert_user_game(db_conn, account_id, game, 0, 20, 50)
    await db_conn.commit()

    assert await _pct(db_conn, "half") == 40.0


async def test_overcounted_game_counts_as_perfect_and_mastered(db_conn, client):
    user_id = await _login(db_conn, client)
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    game = await db.upsert_platform_game(db_conn, "steam", "over", "Overcounted", None, 50)
    await db.upsert_user_game(db_conn, account_id, game, 0, 51, 50)
    await db_conn.commit()

    summary = (await client.get("/api/summary")).json()
    assert summary["perfect_games"] == 1

    general = (await client.get("/api/statistics")).json()["general"]
    assert int(general["mastered"]) == 1
    # and it must not also be claimed by the 80-99% band
    assert int(general["finished"]) == 0


async def test_rows_stored_before_the_clamp_are_still_counted(db_conn, client):
    """A pre-existing row can hold a >100 percentage until its next sync, so
    the counts must not depend on the clamp having run."""
    user_id = await _login(db_conn, client)
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    game = await db.upsert_platform_game(db_conn, "steam", "legacy", "Legacy Row", None, 50)
    await db.upsert_user_game(db_conn, account_id, game, 0, 51, 50)
    # simulate what the old, unclamped write would have left behind
    await db_conn.execute(
        "UPDATE user_games SET completion_pct = 102 WHERE platform_game_id = %s", (game,)
    )
    await db_conn.commit()

    assert (await client.get("/api/summary")).json()["perfect_games"] == 1
    assert int((await client.get("/api/statistics")).json()["general"]["mastered"]) == 1
