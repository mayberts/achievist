"""
Tests for GET /api/milestones — round-number landmarks (Nth achievement, Nth
mastered game) plus distance to the next one.

Both milestone kinds are window-function queries over unlock history, and the
"which achievement crossed it" lookup deliberately disagrees with the reached/
not-reached decision (see the endpoint's docstring: reached-ness comes from the
per-game counters, details come from timestamped unlocks). These cover that
split, since it's the part most likely to break.
"""

from datetime import datetime, timedelta

import httpx
import pytest

from app import auth, db, milestones as milestones_def
from app.main import app
from tests.conftest import requires_db

pytestmark = requires_db

_BASE = datetime(2026, 1, 1)


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


async def _seed_unlocks(
    db_conn, account_id: int, app_id: str, game_name: str, count: int,
    *, start_index: int, with_timestamps: bool = True, total: int | None = None,
) -> None:
    """Give the account `count` unlocked achievements in one game.

    `start_index` offsets the unlock timestamps so callers can lay several
    games end to end on a single global timeline, which is what the Nth-unlock
    ordering keys off.
    """
    total = count if total is None else total
    game = await db.upsert_platform_game(db_conn, "steam", app_id, game_name, None, total)
    await db.upsert_user_game(db_conn, account_id, game, 0, count, total)
    for i in range(count):
        a = await db.upsert_achievement(db_conn, game, f"{app_id}-a{i}", f"{game_name} {i}", "", None, 10, None)
        unlocked_at = _BASE + timedelta(hours=start_index + i) if with_timestamps else None
        await db.upsert_user_achievement(db_conn, account_id, a, True, unlocked_at)


async def test_reports_reached_milestones_newest_first_with_the_crossing_achievement(db_conn, client):
    user_id = await _login(db_conn, client)
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    # 120 unlocks total -> crosses the 100 milestone, not 250
    await _seed_unlocks(db_conn, account_id, "1", "Grinder", 120, start_index=0)
    await db_conn.commit()

    resp = await client.get("/api/milestones")
    assert resp.status_code == 200
    ach = resp.json()["achievements"]

    assert [m["threshold"] for m in ach["reached"]] == [100]
    hundredth = ach["reached"][0]
    # 100th unlock is the one seeded at index 99
    assert hundredth["achievement_name"] == "Grinder 99"
    assert hundredth["game_name"] == "Grinder"
    assert hundredth["reached_at"].startswith((_BASE + timedelta(hours=99)).strftime("%Y-%m-%dT%H"))


async def test_reports_distance_to_the_next_milestone(db_conn, client):
    user_id = await _login(db_conn, client)
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await _seed_unlocks(db_conn, account_id, "1", "Grinder", 120, start_index=0)
    await db_conn.commit()

    nxt = (await client.get("/api/milestones")).json()["achievements"]["next"]
    assert nxt == {
        "threshold": 250, "current": 120, "remaining": 130,
        "tier": milestones_def.BRONZE,
        "points": milestones_def.achievement_milestone_points(250),
    }


async def test_no_milestones_reached_yet(db_conn, client):
    user_id = await _login(db_conn, client)
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await _seed_unlocks(db_conn, account_id, "1", "Starter", 3, start_index=0, total=50)
    await db_conn.commit()

    ach = (await client.get("/api/milestones")).json()["achievements"]
    assert ach["reached"] == []
    assert ach["next"] == {
        "threshold": 100, "current": 3, "remaining": 97,
        "tier": milestones_def.BRONZE,
        "points": milestones_def.achievement_milestone_points(100),
    }


async def test_milestone_still_counts_when_unlocks_have_no_timestamps(db_conn, client):
    """Reached-ness comes from the per-game counters, so a platform that gives
    no unlock times still gets credit — just with no nameable crossing point."""
    user_id = await _login(db_conn, client)
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await _seed_unlocks(db_conn, account_id, "1", "Timeless", 110, start_index=0, with_timestamps=False)
    await db_conn.commit()

    ach = (await client.get("/api/milestones")).json()["achievements"]
    assert [m["threshold"] for m in ach["reached"]] == [100]
    assert ach["reached"][0]["achievement_name"] is None
    assert ach["reached"][0]["reached_at"] is None


async def test_mastered_milestones_order_by_when_each_game_was_finished(db_conn, client):
    user_id = await _login(db_conn, client)
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    # Five fully-completed games, finished in a known order, crossing both the
    # 1st- and 5th-mastered-game milestones.
    for i in range(5):
        await _seed_unlocks(db_conn, account_id, str(i + 1), f"Done {i}", 2, start_index=i * 10)
    # An in-progress game must not count toward mastered
    await _seed_unlocks(db_conn, account_id, "99", "Unfinished", 1, start_index=500, total=10)
    await db_conn.commit()

    mastered = (await client.get("/api/milestones")).json()["mastered"]
    assert [m["threshold"] for m in mastered["reached"]] == [5, 1]
    by_threshold = {m["threshold"]: m for m in mastered["reached"]}
    assert by_threshold[1]["game_name"] == "Done 0"
    assert by_threshold[5]["game_name"] == "Done 4"
    assert mastered["next"] == {
        "threshold": 10, "current": 5, "remaining": 5,
        "tier": milestones_def.SILVER,
        "points": milestones_def.mastered_milestone_points(10),
    }


async def test_milestones_are_scoped_to_the_logged_in_user(db_conn, client):
    user_id = await _login(db_conn, client)
    other = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"))
    other_account = await db.upsert_account(db_conn, other["id"], "steam", "222", {})
    await _seed_unlocks(db_conn, other_account, "1", "Not Mine", 150, start_index=0)
    mine = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await _seed_unlocks(db_conn, mine, "2", "Mine", 5, start_index=0, total=50)
    await db_conn.commit()

    ach = (await client.get("/api/milestones")).json()["achievements"]
    assert ach["reached"] == []
    assert ach["next"]["current"] == 5
