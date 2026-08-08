"""
Tests for GET /api/leaderboard and the users.share_stats opt-in flag —
family members only appear on each other's leaderboard once they've opted
in via PUT /api/profile, except the requesting user always sees themself.
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


async def _seed_achievements(db_conn, user_id: int, platform: str, external_id: str, unlocked: int):
    account_id = await db.upsert_account(db_conn, user_id, platform, external_id, {})
    game = await db.upsert_platform_game(db_conn, platform, "1", "Some Game", None, unlocked)
    await db.upsert_user_game(db_conn, account_id, game, 0, unlocked, unlocked)
    for i in range(unlocked):
        a = await db.upsert_achievement(db_conn, game, f"a{i}", f"Achievement {i}", "", None, 10, None)
        await db.upsert_user_achievement(db_conn, account_id, a, True, None)


async def test_leaderboard_only_shows_self_when_no_one_opted_in(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await _seed_achievements(db_conn, parent["id"], "steam", "111", 2)
    await _seed_achievements(db_conn, kid["id"], "steam", "222", 5)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/leaderboard")
    assert resp.status_code == 200
    usernames = [e["username"] for e in resp.json()["entries"]]
    assert usernames == ["parent"]


async def test_leaderboard_includes_opted_in_users(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await db.update_user_profile(db_conn, kid["id"], None, None, True)
    await _seed_achievements(db_conn, parent["id"], "steam", "111", 2)
    await _seed_achievements(db_conn, kid["id"], "steam", "222", 5)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/leaderboard")
    assert resp.status_code == 200
    entries = {e["username"]: e for e in resp.json()["entries"]}
    assert set(entries) == {"parent", "kid"}
    # 15 pts/achievement for unrated rarity: kid has 5 unlocked, parent has 2
    assert entries["kid"]["achievist_points"] == 75
    assert entries["parent"]["achievist_points"] == 30
    assert entries["kid"]["achievements_unlocked"] == 5


async def test_shared_games_only_include_games_two_visible_users_both_own(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    stranger = await db.create_user(db_conn, "stranger", auth.hash_password("strangerpassword1"), is_admin=False)
    await db.update_user_profile(db_conn, kid["id"], None, None, True)
    # parent and kid both own the same "steam"/"1" game (shared); stranger
    # hasn't opted in, so their copy of it shouldn't pull them into the row.
    await _seed_achievements(db_conn, parent["id"], "steam", "111", 2)
    await _seed_achievements(db_conn, kid["id"], "steam", "222", 5)
    await _seed_achievements(db_conn, stranger["id"], "steam", "333", 1)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/leaderboard/games")
    assert resp.status_code == 200
    games = resp.json()["games"]
    assert len(games) == 1
    players = {p["username"]: p for p in games[0]["players"]}
    assert set(players) == {"parent", "kid"}
    assert players["kid"]["earned"] == 5
    assert players["parent"]["earned"] == 2


async def test_shared_games_empty_when_no_overlap(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await db.update_user_profile(db_conn, kid["id"], None, None, True)
    await _seed_achievements(db_conn, parent["id"], "steam", "111", 2)
    await _seed_achievements(db_conn, kid["id"], "xbox", "222", 5)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/leaderboard/games")
    assert resp.status_code == 200
    assert resp.json()["games"] == []


async def test_compare_shows_per_user_unlock_status(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await db.update_user_profile(db_conn, kid["id"], None, None, True)
    parent_account = await db.upsert_account(db_conn, parent["id"], "steam", "111", {})
    kid_account = await db.upsert_account(db_conn, kid["id"], "steam", "222", {})
    game = await db.upsert_platform_game(db_conn, "steam", "1", "Some Game", None, 2)
    await db.upsert_user_game(db_conn, parent_account, game, 0, 1, 2)
    await db.upsert_user_game(db_conn, kid_account, game, 0, 2, 2)
    a1 = await db.upsert_achievement(db_conn, game, "a1", "First", "", None, 10, None)
    a2 = await db.upsert_achievement(db_conn, game, "a2", "Second", "", None, 10, None)
    await db.upsert_user_achievement(db_conn, parent_account, a1, True, None)
    await db.upsert_user_achievement(db_conn, kid_account, a1, True, None)
    await db.upsert_user_achievement(db_conn, kid_account, a2, True, None)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get(f"/api/leaderboard/games/{game}/compare")
    assert resp.status_code == 200
    data = resp.json()
    assert data["game"]["name"] == "Some Game"
    assert {o["username"] for o in data["owners"]} == {"parent", "kid"}
    assert len(data["achievements"]) == 2

    by_name = {a["name"]: a for a in data["achievements"]}
    second = by_name["Second"]
    per_user = {p["user_id"]: p["unlocked"] for p in second["per_user"]}
    assert per_user[parent["id"]] is False
    assert per_user[kid["id"]] is True


async def test_compare_404s_for_a_game_you_dont_own(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    kid_account = await db.upsert_account(db_conn, kid["id"], "steam", "222", {})
    game = await db.upsert_platform_game(db_conn, "steam", "1", "Some Game", None, 1)
    await db.upsert_user_game(db_conn, kid_account, game, 0, 0, 1)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get(f"/api/leaderboard/games/{game}/compare")
    assert resp.status_code == 404


async def test_share_stats_toggle_via_profile_endpoint(db_conn, client):
    await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.put("/api/profile", json={"share_stats": True})
    assert resp.status_code == 200
    assert resp.json()["share_stats"] is True

    prof = await client.get("/api/profile")
    assert prof.json()["share_stats"] is True


async def test_leaderboard_platform_filter_scopes_all_stats(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    account = await db.upsert_account(db_conn, parent["id"], "steam", "111", {})
    steam_game = await db.upsert_platform_game(db_conn, "steam", "1", "Steam Game", None, 2)
    for i in range(2):
        a = await db.upsert_achievement(db_conn, steam_game, f"s{i}", f"Steam Ach {i}", "", None, 10, None)
        await db.upsert_user_achievement(db_conn, account, a, True, None)
    await db.upsert_user_game(db_conn, account, steam_game, 0, 2, 2)

    xbox_account = await db.upsert_account(db_conn, parent["id"], "xbox", "222", {})
    xbox_game = await db.upsert_platform_game(db_conn, "xbox", "1", "Xbox Game", None, 1)
    a = await db.upsert_achievement(db_conn, xbox_game, "x0", "Xbox Ach", "", None, 10, None)
    await db.upsert_user_achievement(db_conn, xbox_account, a, True, None)
    await db.upsert_user_game(db_conn, xbox_account, xbox_game, 0, 1, 1)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})

    resp = await client.get("/api/leaderboard", params={"platform": "steam"})
    entry = resp.json()["entries"][0]
    assert entry["achievements_unlocked"] == 2
    assert entry["games_played"] == 1

    resp_all = await client.get("/api/leaderboard")
    assert resp_all.json()["entries"][0]["achievements_unlocked"] == 3


async def test_leaderboard_window_filter_scopes_unlocked_count_only(db_conn, client):
    from datetime import date

    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    account = await db.upsert_account(db_conn, parent["id"], "steam", "111", {})
    game = await db.upsert_platform_game(db_conn, "steam", "1", "Some Game", None, 2)
    old = await db.upsert_achievement(db_conn, game, "a1", "Old", "", None, 10, None)
    recent = await db.upsert_achievement(db_conn, game, "a2", "Recent", "", None, 10, None)
    await db.upsert_user_achievement(db_conn, account, old, True, date(2020, 1, 1))
    await db.upsert_user_achievement(db_conn, account, recent, True, date.today())
    await db.upsert_user_game(db_conn, account, game, 0, 2, 2)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})

    resp = await client.get("/api/leaderboard", params={"window": "week"})
    entry = resp.json()["entries"][0]
    assert entry["achievements_unlocked"] == 1
    # games_played/completed stay all-time regardless of the window filter
    assert entry["games_played"] == 1


async def test_shared_games_platform_filter(db_conn, client):
    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await db.update_user_profile(db_conn, kid["id"], None, None, True)
    await _seed_achievements(db_conn, parent["id"], "steam", "111", 2)
    await _seed_achievements(db_conn, kid["id"], "steam", "222", 5)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})

    resp = await client.get("/api/leaderboard/games", params={"platform": "steam"})
    assert len(resp.json()["games"]) == 1

    resp_xbox = await client.get("/api/leaderboard/games", params={"platform": "xbox"})
    assert resp_xbox.json()["games"] == []


async def test_shared_games_include_last_activity_and_last_played_at(db_conn, client):
    from datetime import datetime, timezone

    parent = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    kid = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await db.update_user_profile(db_conn, kid["id"], None, None, True)
    parent_account = await db.upsert_account(db_conn, parent["id"], "steam", "111", {})
    kid_account = await db.upsert_account(db_conn, kid["id"], "steam", "222", {})
    game = await db.upsert_platform_game(db_conn, "steam", "1", "Some Game", None, 1)
    when = datetime(2025, 6, 1, tzinfo=timezone.utc)
    await db.upsert_user_game(db_conn, parent_account, game, 0, 1, 1, last_played_at=when)
    await db.upsert_user_game(db_conn, kid_account, game, 0, 0, 1)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
    resp = await client.get("/api/leaderboard/games")
    g = resp.json()["games"][0]
    assert g["last_activity"] is not None
    players = {p["username"]: p for p in g["players"]}
    assert players["parent"]["last_played_at"] is not None
    assert players["kid"]["last_played_at"] is None
