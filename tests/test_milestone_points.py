"""
Tests for milestone points: what each milestone is worth, and the
leaderboard's milestone_points column.

The leaderboard sums the point values in SQL (a VALUES list rendered from
app.milestones) while /api/milestones sums them in Python. These tests pin
both to the same shared table so the two can't drift apart.
"""

from datetime import datetime

import httpx
import pytest

from app import auth, db, milestones
from app.main import app
from tests.conftest import requires_db


def test_a_milestone_is_worth_its_own_threshold():
    assert milestones.achievement_milestone_points(2_500) == 2_500


def test_mastering_games_is_scaled_up_against_single_unlocks():
    assert milestones.mastered_milestone_points(5) == 5 * milestones.MASTERED_POINTS_PER_GAME


def test_total_points_only_counts_passed_thresholds():
    # 600 achievements clears 100/250/500; 6 mastered games clears 1 and 5
    expected = (100 + 250 + 500) + (100 + 500)
    assert milestones.total_points_for(600, 6) == expected


def test_nothing_earned_yet_is_worth_nothing():
    assert milestones.total_points_for(0, 0) == 0


def test_every_milestone_has_a_known_badge_tier():
    tiers = {milestones.BRONZE, milestones.SILVER, milestones.GOLD, milestones.PLATINUM, milestones.DIAMOND}
    for table in (milestones.ACHIEVEMENT_MILESTONES, milestones.MASTERED_MILESTONES):
        assert [t for t, _ in table] == sorted(t for t, _ in table), "thresholds must ascend"
        for threshold, tier in table:
            assert tier in tiers, f"{threshold} has unknown tier {tier!r}"


class TestLeaderboardMilestonePoints:
    pytestmark = requires_db

    @pytest.fixture
    async def client(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @staticmethod
    async def _seed(db_conn, user_id: int, *, earned: int, total: int, app_id: str) -> None:
        account_id = await db.upsert_account(db_conn, user_id, "steam", f"ext-{app_id}", {})
        game = await db.upsert_platform_game(db_conn, "steam", app_id, f"Game {app_id}", None, total)
        await db.upsert_user_game(db_conn, account_id, game, 0, earned, total)

    async def test_matches_the_shared_table(self, db_conn, client):
        user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
        # 600 unlocked achievements, none of these games mastered
        await self._seed(db_conn, user["id"], earned=600, total=1000, app_id="a")
        await db_conn.commit()

        await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
        entry = (await client.get("/api/leaderboard")).json()["entries"][0]

        assert entry["milestone_points"] == milestones.total_points_for(600, 0)
        assert entry["milestone_points"] == 100 + 250 + 500

    async def test_mastered_games_contribute_their_own_points(self, db_conn, client):
        user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
        # five fully-completed games: clears mastered milestones 1 and 5.
        # 5 x 30 = 150 achievements, which clears the 100 achievement milestone.
        for i in range(5):
            await self._seed(db_conn, user["id"], earned=30, total=30, app_id=str(i))
        await db_conn.commit()

        await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
        entry = (await client.get("/api/leaderboard")).json()["entries"][0]

        assert entry["games_completed"] == 5
        assert entry["milestone_points"] == milestones.total_points_for(150, 5)
        assert entry["milestone_points"] == 100 + (100 + 500)

    @staticmethod
    async def _one_unlock_one_mastered_game(db_conn, username="parent") -> None:
        user = await db.create_user(db_conn, username, auth.hash_password("parentpassword1"), is_admin=True)
        account_id = await db.upsert_account(db_conn, user["id"], "steam", "111", {})
        game = await db.upsert_platform_game(db_conn, "steam", "g", "Game", None, 1)
        await db.upsert_user_game(db_conn, account_id, game, 0, 1, 1)
        a = await db.upsert_achievement(db_conn, game, "a0", "Only One", "", None, 10, None)
        # dated so it falls inside a "this week" window
        await db.upsert_user_achievement(db_conn, account_id, a, True, datetime.now())
        await db_conn.commit()

    async def test_folded_into_achievist_points(self, db_conn, client):
        """The headline score counts landmarks as well as grinding, while the
        breakdown stays visible in its own column."""
        await self._one_unlock_one_mastered_game(db_conn)

        await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
        entry = (await client.get("/api/leaderboard")).json()["entries"][0]

        # one unrated unlock is worth 15, and mastering a game clears the
        # first mastered milestone
        milestone = milestones.mastered_milestone_points(1)
        assert entry["milestone_points"] == milestone
        assert entry["achievist_points"] == 15 + milestone

    async def test_left_out_of_a_windowed_score(self, db_conn, client):
        """Milestones can't be attributed to a week, so a windowed score counts
        only the unlocks earned in it — otherwise an all-time figure would
        swamp the window and make it meaningless."""
        await self._one_unlock_one_mastered_game(db_conn)

        await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
        entry = (await client.get("/api/leaderboard", params={"window": "week"})).json()["entries"][0]

        assert entry["achievist_points"] == 15
        # still reported, just not added in
        assert entry["milestone_points"] == milestones.mastered_milestone_points(1)

    async def test_endpoint_and_leaderboard_agree(self, db_conn, client):
        user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
        for i in range(5):
            await self._seed(db_conn, user["id"], earned=30, total=30, app_id=str(i))
        await db_conn.commit()

        await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
        board = (await client.get("/api/leaderboard")).json()["entries"][0]
        panel = (await client.get("/api/milestones")).json()

        panel_total = panel["achievements"]["points_earned"] + panel["mastered"]["points_earned"]
        assert panel_total == board["milestone_points"]

    async def test_scoped_to_the_selected_platform(self, db_conn, client):
        """Milestone points are derived from platform-scoped totals, like every
        other leaderboard stat — so filtering to one platform must not credit
        milestones that another platform's unlocks paid for."""
        user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
        steam_acct = await db.upsert_account(db_conn, user["id"], "steam", "111", {})
        steam_game = await db.upsert_platform_game(db_conn, "steam", "s1", "Steam Game", None, 1000)
        await db.upsert_user_game(db_conn, steam_acct, steam_game, 0, 600, 1000)
        # a second platform holding far too few unlocks to clear any milestone
        xbox_acct = await db.upsert_account(db_conn, user["id"], "xbox", "222", {})
        xbox_game = await db.upsert_platform_game(db_conn, "xbox", "x1", "Xbox Game", None, 1000)
        await db.upsert_user_game(db_conn, xbox_acct, xbox_game, 0, 10, 1000)
        await db_conn.commit()

        await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})

        all_platforms = (await client.get("/api/leaderboard")).json()["entries"][0]
        assert all_platforms["milestone_points"] == milestones.total_points_for(610, 0)

        only_xbox = (await client.get("/api/leaderboard", params={"platform": "xbox"})).json()["entries"][0]
        assert only_xbox["milestone_points"] == 0

    async def test_reached_milestones_carry_tier_and_points(self, db_conn, client):
        user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
        await self._seed(db_conn, user["id"], earned=600, total=1000, app_id="a")
        await db_conn.commit()

        await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
        ach = (await client.get("/api/milestones")).json()["achievements"]

        highest = ach["reached"][0]
        assert highest["threshold"] == 500
        assert highest["points"] == 500
        assert highest["tier"] == milestones.SILVER
        # the upcoming one advertises its badge and reward too
        assert ach["next"]["threshold"] == 1_000
        assert ach["next"]["tier"] == milestones.SILVER
        assert ach["next"]["points"] == 1_000
