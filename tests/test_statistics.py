"""
Tests for GET /api/statistics and /api/statistics/platform/{platform}.

This endpoint is the largest block of hand-written SQL in the app — eleven
separate queries whose results are stitched together in Python — and none of
it was covered. The tests below concentrate on the parts that can be silently
wrong rather than on echoing every field back: CASE boundaries (a rarity of
exactly 5%, a completion of exactly 25%), the gap-and-islands streak query,
running totals, date arithmetic in "on this day", and per-user scoping.
"""

from datetime import date, datetime, timedelta

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


async def _login(db_conn, client, username="parent") -> int:
    user = await db.create_user(db_conn, username, auth.hash_password("parentpassword1"), is_admin=True)
    await db_conn.commit()
    await client.post("/api/auth/login", json={"username": username, "password": "parentpassword1"})
    return user["id"]


async def _seed_game(
    db_conn, account_id: int, app_id: str, *, earned: int, total: int,
    platform: str = "steam", name: str | None = None,
) -> int:
    """A game with only its user_games counters set — enough for the counts,
    completion buckets and per-platform totals, which never look at rows in
    the achievements table."""
    game = await db.upsert_platform_game(
        db_conn, platform, app_id, name or f"Game {app_id}", None, total,
    )
    await db.upsert_user_game(db_conn, account_id, game, 0, earned, total)
    return game


async def _seed_unlock(
    db_conn, account_id: int, game: int, key: str, *,
    rarity: float | None = None, points: int | None = None,
    unlocked_at: datetime | None = None, unlocked: bool = True,
) -> None:
    """One achievement row plus its unlock state — needed by the rarity,
    progression, streak and on-this-day queries, which count real rows."""
    ach = await db.upsert_achievement(db_conn, game, key, f"Ach {key}", "", None, points, rarity)
    await db.upsert_user_achievement(db_conn, account_id, ach, unlocked, unlocked_at)


def _same_day_previous_year(years_back: int = 1) -> datetime:
    """Today's month/day in an earlier year, stepping back further if that
    date doesn't exist (29 February in a non-leap year)."""
    today = date.today()
    for extra in range(0, 9):
        try:
            return datetime(today.year - years_back - extra, today.month, today.day, 12, 0)
        except ValueError:
            continue
    raise AssertionError("could not build a same-day date in an earlier year")


class TestGeneralCounts:
    async def test_counts_and_percentages(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        await _seed_game(db_conn, acct, "a", earned=30, total=100)
        await _seed_game(db_conn, acct, "b", earned=50, total=100)
        await _seed_game(db_conn, acct, "c", earned=0, total=10)    # untouched
        await _seed_game(db_conn, acct, "d", earned=90, total=100)  # "finished" band
        await _seed_game(db_conn, acct, "e", earned=20, total=20)   # mastered
        await db_conn.commit()

        g = (await client.get("/api/statistics")).json()["general"]

        assert g["unlocked"] == 190
        assert g["locked"] == 140
        assert g["games_total"] == 5
        assert g["mastered"] == 1
        assert g["finished"] == 1
        assert g["active_games"] == 4
        assert g["untouched_games"] == 1
        # mean of the per-game percentages: (30+50+0+90+100)/5
        assert g["avg_completion"] == 54.0
        # and the pooled figure, which is a different number: 190/330
        assert g["absolute_completion"] == 57.58

    async def test_finished_band_excludes_its_endpoints(self, db_conn, client):
        """"Finished" is 80% up to but not including 100%, so a game sitting
        exactly on either edge must not be double-counted."""
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        await _seed_game(db_conn, acct, "at80", earned=80, total=100)
        await _seed_game(db_conn, acct, "at79", earned=79, total=100)
        await _seed_game(db_conn, acct, "at100", earned=100, total=100)
        await db_conn.commit()

        g = (await client.get("/api/statistics")).json()["general"]
        assert g["finished"] == 1  # only the 80% one
        assert g["mastered"] == 1  # only the 100% one

    async def test_games_without_achievements_are_left_out(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        await _seed_game(db_conn, acct, "real", earned=5, total=10)
        await _seed_game(db_conn, acct, "none", earned=0, total=0)
        await db_conn.commit()

        g = (await client.get("/api/statistics")).json()["general"]
        assert g["games_total"] == 1


class TestRarityTiers:
    async def test_tier_boundaries_are_inclusive_upper_bounds(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=5, total=5)
        # each value sits exactly on a tier's upper edge, plus one past the last
        for i, rarity in enumerate([1.0, 5.0, 20.0, 50.0, 50.1]):
            await _seed_unlock(db_conn, acct, game, f"r{i}", rarity=rarity)
        await db_conn.commit()

        rarity = (await client.get("/api/statistics")).json()["rarity"]
        assert [r["tier"] for r in rarity] == ["Legendary", "Epic", "Rare", "Uncommon", "Common"]
        assert all(r["cnt"] == 1 for r in rarity)

    async def test_unrated_and_locked_achievements_are_excluded(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=1, total=3)
        await _seed_unlock(db_conn, acct, game, "rated", rarity=2.0)
        await _seed_unlock(db_conn, acct, game, "unrated", rarity=None)
        await _seed_unlock(db_conn, acct, game, "locked", rarity=2.0, unlocked=False)
        await db_conn.commit()

        rarity = (await client.get("/api/statistics")).json()["rarity"]
        assert rarity == [{"tier": "Epic", "cnt": 1}]


class TestCompletionDistribution:
    async def test_every_bracket_is_reported_in_order_even_when_empty(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        await _seed_game(db_conn, acct, "a", earned=0, total=10)
        await db_conn.commit()

        dist = (await client.get("/api/statistics")).json()["completion_dist"]
        assert [d["bracket"] for d in dist] == ["0%", "1-25%", "26-50%", "51-75%", "76-99%", "100%"]
        assert {d["bracket"]: d["cnt"] for d in dist}["0%"] == 1
        assert sum(d["cnt"] for d in dist) == 1

    async def test_bucket_edges(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        # one game landing exactly on each bucket's upper edge
        for app_id, earned in [("z", 0), ("q", 25), ("h", 50), ("t", 75), ("n", 99), ("f", 100)]:
            await _seed_game(db_conn, acct, app_id, earned=earned, total=100)
        await db_conn.commit()

        dist = {d["bracket"]: d["cnt"] for d in (await client.get("/api/statistics")).json()["completion_dist"]}
        assert dist == {"0%": 1, "1-25%": 1, "26-50%": 1, "51-75%": 1, "76-99%": 1, "100%": 1}

    async def test_labels_are_true_of_fractional_percentages(self, db_conn, client):
        """The bands are cut on the rounded percentage, so a game can never sit
        under a label that excludes its own number."""
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        # 25.4% and 25.6% straddle the 1-25 / 26-50 label boundary
        await _seed_game(db_conn, acct, "low", earned=127, total=500)
        await _seed_game(db_conn, acct, "high", earned=128, total=500)
        await db_conn.commit()

        dist = {d["bracket"]: d["cnt"] for d in (await client.get("/api/statistics")).json()["completion_dist"]}
        assert dist["1-25%"] == 1
        assert dist["26-50%"] == 1

    async def test_outer_bands_stay_exact_rather_than_rounded(self, db_conn, client):
        """0% must mean nothing earned and 100% must mean actually finished, so
        neither may absorb a value that merely rounds to it."""
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        await _seed_game(db_conn, acct, "barely", earned=2, total=500)    # 0.4% -> rounds to 0
        await _seed_game(db_conn, acct, "almost", earned=498, total=500)  # 99.6% -> rounds to 100
        await db_conn.commit()

        dist = {d["bracket"]: d["cnt"] for d in (await client.get("/api/statistics")).json()["completion_dist"]}
        assert dist["0%"] == 0, "0.4% is progress, not an untouched game"
        assert dist["1-25%"] == 1
        assert dist["100%"] == 0, "99.6% is not a finished game"
        assert dist["76-99%"] == 1


class TestPlatformTotals:
    async def test_earned_is_summed_per_platform(self, db_conn, client):
        user_id = await _login(db_conn, client)
        steam = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        xbox = await db.upsert_account(db_conn, user_id, "xbox", "222", {})
        await _seed_game(db_conn, steam, "s1", earned=10, total=20, platform="steam")
        await _seed_game(db_conn, steam, "s2", earned=5, total=20, platform="steam")
        await _seed_game(db_conn, xbox, "x1", earned=7, total=20, platform="xbox")
        await db_conn.commit()

        platforms = (await client.get("/api/statistics")).json()["platforms"]
        assert {p["platform"]: p["earned"] for p in platforms} == {"steam": 15, "xbox": 7}


class TestProgression:
    async def test_monthly_counts_carry_a_running_total(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=5, total=5)
        # 2 unlocks in Jan 2024, 3 in Mar 2024
        for i in range(2):
            await _seed_unlock(db_conn, acct, game, f"j{i}", points=10, unlocked_at=datetime(2024, 1, 5 + i, 12))
        for i in range(3):
            await _seed_unlock(db_conn, acct, game, f"m{i}", points=20, unlocked_at=datetime(2024, 3, 2 + i, 12))
        await db_conn.commit()

        stats = (await client.get("/api/statistics")).json()
        assert [(p["month"], p["cnt"], p["total"]) for p in stats["progression"]] == [
            ("2024-01-01", 2, 2),
            ("2024-03-01", 3, 5),
        ]
        # points accumulate independently: 2x10 then 3x20
        assert [(p["month"], p["cnt"], p["total"]) for p in stats["points_progression"]] == [
            ("2024-01-01", 20, 20),
            ("2024-03-01", 60, 80),
        ]

    async def test_years_are_listed_newest_first_without_duplicates(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=3, total=3)
        for i, when in enumerate([datetime(2023, 2, 1, 12), datetime(2023, 8, 1, 12), datetime(2025, 1, 1, 12)]):
            await _seed_unlock(db_conn, acct, game, f"y{i}", unlocked_at=when)
        await db_conn.commit()

        assert (await client.get("/api/statistics")).json()["progression_years"] == [2025, 2023]

    async def test_untimestamped_unlocks_stay_out_of_the_timeline(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=2, total=2)
        await _seed_unlock(db_conn, acct, game, "dated", unlocked_at=datetime(2024, 1, 5, 12))
        await _seed_unlock(db_conn, acct, game, "undated", unlocked_at=None)
        await db_conn.commit()

        stats = (await client.get("/api/statistics")).json()
        assert [p["cnt"] for p in stats["progression"]] == [1]


class TestRecords:
    async def test_best_day_and_month(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=6, total=6)
        # 1 unlock in Jan, 3 on one Feb day, 2 spread over other Feb days
        await _seed_unlock(db_conn, acct, game, "a0", unlocked_at=datetime(2024, 1, 9, 12))
        for i in range(3):
            await _seed_unlock(db_conn, acct, game, f"b{i}", unlocked_at=datetime(2024, 2, 10, 9 + i))
        await _seed_unlock(db_conn, acct, game, "c0", unlocked_at=datetime(2024, 2, 20, 12))
        await _seed_unlock(db_conn, acct, game, "c1", unlocked_at=datetime(2024, 2, 21, 12))
        await db_conn.commit()

        g = (await client.get("/api/statistics")).json()["general"]
        assert g["daily_max"] == 3
        assert g["best_day"] == "2024-02-10"
        assert g["best_month"] == "2024-02-01"
        assert g["best_month_cnt"] == 5
        assert g["monthly_max"] == 5

    async def test_longest_streak_picks_the_longest_run_of_consecutive_days(self, db_conn, client):
        """The streak query is gap-and-islands over distinct unlock days: two
        unlocks on one day are still one day, and a missing day ends the run."""
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=8, total=8)
        # 1-3 March (three days, one of them twice), gap, then 10-11 March
        days = [1, 2, 3, 10, 11]
        for i, d in enumerate(days):
            await _seed_unlock(db_conn, acct, game, f"s{i}", unlocked_at=datetime(2024, 3, d, 12))
        await _seed_unlock(db_conn, acct, game, "dup", unlocked_at=datetime(2024, 3, 2, 20))
        await db_conn.commit()

        g = (await client.get("/api/statistics")).json()["general"]
        assert g["best_streak_days"] == 3
        assert g["best_streak_start"] == "2024-03-01"
        assert g["best_streak_end"] == "2024-03-03"

    async def test_a_single_active_day_is_a_streak_of_one(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=1, total=1)
        await _seed_unlock(db_conn, acct, game, "only", unlocked_at=datetime(2024, 5, 5, 12))
        await db_conn.commit()

        g = (await client.get("/api/statistics")).json()["general"]
        assert g["best_streak_days"] == 1
        assert g["best_streak_start"] == g["best_streak_end"] == "2024-05-05"


class TestOnThisDay:
    async def test_reports_earlier_years_with_how_long_ago(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=2, total=2, name="Anniversary")
        last_year = _same_day_previous_year(1)
        two_back = _same_day_previous_year(2)
        await _seed_unlock(db_conn, acct, game, "older", unlocked_at=two_back)
        await _seed_unlock(db_conn, acct, game, "newer", unlocked_at=last_year)
        await db_conn.commit()

        entries = (await client.get("/api/statistics")).json()["on_this_day"]
        assert len(entries) == 2
        # most recent anniversary first
        assert [e["achievement_name"] for e in entries] == ["Ach newer", "Ach older"]
        assert entries[0]["game_name"] == "Anniversary"
        today_year = date.today().year
        assert entries[0]["years_ago"] == today_year - last_year.year
        assert entries[1]["years_ago"] == today_year - two_back.year
        # and the arithmetic really is a year count, not a fixed label
        assert entries[1]["years_ago"] - entries[0]["years_ago"] == 1

    async def test_todays_own_unlocks_are_not_an_anniversary(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=1, total=1)
        await _seed_unlock(db_conn, acct, game, "today", unlocked_at=datetime.now())
        await db_conn.commit()

        assert (await client.get("/api/statistics")).json()["on_this_day"] == []

    async def test_other_dates_are_ignored(self, db_conn, client):
        user_id = await _login(db_conn, client)
        acct = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        game = await _seed_game(db_conn, acct, "a", earned=1, total=1)
        # same year offset, but a day away from today's month/day
        await _seed_unlock(db_conn, acct, game, "near", unlocked_at=_same_day_previous_year() + timedelta(days=1))
        await db_conn.commit()

        assert (await client.get("/api/statistics")).json()["on_this_day"] == []


class TestScopingAndEmptyState:
    async def test_another_users_data_never_leaks_in(self, db_conn, client):
        user_id = await _login(db_conn, client)
        other = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"))
        other_acct = await db.upsert_account(db_conn, other["id"], "xbox", "999", {})
        other_game = await _seed_game(db_conn, other_acct, "theirs", earned=40, total=40, platform="xbox")
        await _seed_unlock(
            db_conn, other_acct, other_game, "theirs0", rarity=0.5, points=99,
            unlocked_at=datetime(2024, 6, 1, 12),
        )

        mine = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        my_game = await _seed_game(db_conn, mine, "mine", earned=1, total=4)
        await _seed_unlock(
            db_conn, mine, my_game, "mine0", rarity=30.0, points=5,
            unlocked_at=datetime(2024, 7, 1, 12),
        )
        await db_conn.commit()

        stats = (await client.get("/api/statistics")).json()
        assert stats["general"]["unlocked"] == 1
        assert stats["general"]["games_total"] == 1
        assert [p["platform"] for p in stats["platforms"]] == ["steam"]
        assert [r["tier"] for r in stats["rarity"]] == ["Uncommon"]
        assert [p["month"] for p in stats["progression"]] == ["2024-07-01"]
        assert stats["progression_years"] == [2024]

    async def test_a_brand_new_account_gets_zeros_rather_than_an_error(self, db_conn, client):
        await _login(db_conn, client)

        resp = await client.get("/api/statistics")
        assert resp.status_code == 200
        stats = resp.json()

        assert stats["general"]["unlocked"] == 0
        assert stats["general"]["games_total"] == 0
        assert stats["general"]["avg_completion"] == 0
        assert stats["general"]["absolute_completion"] == 0
        assert stats["general"]["best_streak_days"] == 0
        assert stats["general"]["best_day"] is None
        assert stats["general"]["best_month"] is None
        assert stats["rarity"] == []
        assert stats["platforms"] == []
        assert stats["progression"] == []
        assert stats["progression_years"] == []
        assert stats["on_this_day"] == []
        # the buckets are always present, just all zero
        assert [d["cnt"] for d in stats["completion_dist"]] == [0, 0, 0, 0, 0, 0]

    async def test_requires_login(self, db_conn, client):
        resp = await client.get("/api/statistics")
        assert resp.status_code == 401


class TestPlatformDrilldown:
    async def test_returns_only_that_platforms_games_best_first(self, db_conn, client):
        user_id = await _login(db_conn, client)
        steam = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        xbox = await db.upsert_account(db_conn, user_id, "xbox", "222", {})
        await _seed_game(db_conn, steam, "s1", earned=5, total=20, platform="steam", name="Fewer")
        await _seed_game(db_conn, steam, "s2", earned=15, total=20, platform="steam", name="More")
        await _seed_game(db_conn, xbox, "x1", earned=99, total=100, platform="xbox", name="Elsewhere")
        await db_conn.commit()

        rows = (await client.get("/api/statistics/platform/steam")).json()
        assert [r["name"] for r in rows] == ["More", "Fewer"]

    async def test_skips_games_with_no_achievements(self, db_conn, client):
        user_id = await _login(db_conn, client)
        steam = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        await _seed_game(db_conn, steam, "s1", earned=3, total=5, platform="steam", name="Tracked")
        await _seed_game(db_conn, steam, "s2", earned=0, total=0, platform="steam", name="Untracked")
        await db_conn.commit()

        rows = (await client.get("/api/statistics/platform/steam")).json()
        assert [r["name"] for r in rows] == ["Tracked"]

    async def test_scoped_to_the_logged_in_user(self, db_conn, client):
        user_id = await _login(db_conn, client)
        other = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"))
        other_acct = await db.upsert_account(db_conn, other["id"], "steam", "999", {})
        await _seed_game(db_conn, other_acct, "theirs", earned=50, total=50, platform="steam", name="Theirs")
        mine = await db.upsert_account(db_conn, user_id, "steam", "111", {})
        await _seed_game(db_conn, mine, "mine", earned=1, total=5, platform="steam", name="Mine")
        await db_conn.commit()

        rows = (await client.get("/api/statistics/platform/steam")).json()
        assert [r["name"] for r in rows] == ["Mine"]
