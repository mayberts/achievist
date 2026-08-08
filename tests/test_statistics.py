"""
Tests for GET /api/statistics — specifically the additions on top of the
existing general/rarity/completion_dist/platforms/progression payload:
active_games/untouched_games backlog counts, points_progression,
progression_years, and the on_this_day anniversary callout.
"""

from datetime import date, timedelta

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


async def test_statistics_reports_active_and_untouched_games(db_conn, client):
    user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    account = await db.upsert_account(db_conn, user["id"], "steam", "111", {})

    played = await db.upsert_platform_game(db_conn, "steam", "1", "Played Game", None, 2)
    a1 = await db.upsert_achievement(db_conn, played, "a1", "First", "", None, 10, None)
    await db.upsert_user_achievement(db_conn, account, a1, True, None)
    await db.upsert_user_game(db_conn, account, played, 0, 1, 2)

    untouched = await db.upsert_platform_game(db_conn, "steam", "2", "Untouched Game", None, 3)
    await db.upsert_achievement(db_conn, untouched, "b1", "Locked", "", None, 10, None)
    await db.upsert_user_game(db_conn, account, untouched, 0, 0, 3)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/statistics")
    assert resp.status_code == 200
    general = resp.json()["general"]
    assert general["active_games"] == 1
    assert general["untouched_games"] == 1
    assert general["games_total"] == 2


async def test_statistics_points_progression_matches_unlocked_points(db_conn, client):
    user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    account = await db.upsert_account(db_conn, user["id"], "steam", "111", {})
    game = await db.upsert_platform_game(db_conn, "steam", "1", "Some Game", None, 2)
    a1 = await db.upsert_achievement(db_conn, game, "a1", "First", "", None, 10, None)
    a2 = await db.upsert_achievement(db_conn, game, "a2", "Second", "", None, 25, None)
    unlock_time = date(2024, 3, 15)
    await db.upsert_user_achievement(db_conn, account, a1, True, unlock_time)
    await db.upsert_user_achievement(db_conn, account, a2, True, unlock_time)
    await db.upsert_user_game(db_conn, account, game, 0, 2, 2)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/statistics")
    assert resp.status_code == 200
    body = resp.json()
    pts = body["points_progression"]
    assert len(pts) == 1
    assert pts[0]["cnt"] == 35
    assert pts[0]["total"] == 35
    assert body["progression_years"] == [2024]


async def test_statistics_on_this_day_finds_past_anniversaries(db_conn, client):
    user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    account = await db.upsert_account(db_conn, user["id"], "steam", "111", {})
    game = await db.upsert_platform_game(db_conn, "steam", "1", "Some Game", None, 2)
    a1 = await db.upsert_achievement(db_conn, game, "a1", "Anniversary Achievement", "", None, 10, None)
    a2 = await db.upsert_achievement(db_conn, game, "a2", "Unrelated Achievement", "", None, 10, None)

    today = date.today()
    two_years_ago = today.replace(year=today.year - 2)
    await db.upsert_user_achievement(db_conn, account, a1, True, two_years_ago)
    # Unlocked today itself — should NOT show up as an "anniversary".
    await db.upsert_user_achievement(db_conn, account, a2, True, today)
    await db.upsert_user_game(db_conn, account, game, 0, 2, 2)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/statistics")
    assert resp.status_code == 200
    on_this_day = resp.json()["on_this_day"]
    assert len(on_this_day) == 1
    assert on_this_day[0]["achievement_name"] == "Anniversary Achievement"
    assert on_this_day[0]["years_ago"] == 2
