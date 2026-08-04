"""
Integration tests against a real Postgres connection — for behavior that
DB-free tests structurally can't cover: account dedup, achievement-unlock
detection, and the one-time schema migration that cleaned up existing
duplicate account rows.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app import db
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def user_id(db_conn):
    user = await db.create_user(db_conn, "parent", "x")
    return user["id"]


async def test_upsert_account_creates_and_updates(db_conn, user_id):
    id1 = await db.upsert_account(db_conn, user_id, "steam", "111", {"api_key": "a"})
    id2 = await db.upsert_account(db_conn, user_id, "steam", "111", {"api_key": "b"})
    assert id1 == id2  # same (user, platform, external_id) -> same row, credentials updated

    row = await db.get_account(db_conn, id1, user_id)
    assert row["credentials"] == {"api_key": "b"}


async def test_reconnect_under_a_different_external_id_leaves_an_orphan_without_cleanup(db_conn, user_id):
    # This is the exact bug: reconnecting a platform under a different
    # external_id (e.g. Ubisoft/PSN re-resolving a username to a different
    # profile id) creates a second row instead of replacing the first,
    # because the upsert's conflict target is (user_id, platform, external_id).
    await db.upsert_account(db_conn, user_id, "ubisoft", "profile-1", {"ticket": "a"})
    await db.upsert_account(db_conn, user_id, "ubisoft", "profile-2", {"ticket": "b"})

    rows = await db.list_accounts(db_conn, user_id)
    assert len(rows) == 2


async def test_delete_other_accounts_for_platform_cleans_up_the_orphan(db_conn, user_id):
    await db.upsert_account(db_conn, user_id, "ubisoft", "profile-1", {"ticket": "a"})
    await db.upsert_account(db_conn, user_id, "ubisoft", "profile-2", {"ticket": "b"})

    await db.delete_other_accounts_for_platform(db_conn, user_id, "ubisoft", "profile-2")

    rows = await db.list_accounts(db_conn, user_id)
    assert len(rows) == 1
    assert rows[0]["external_id"] == "profile-2"


async def test_delete_other_accounts_for_platform_is_scoped_to_one_platform(db_conn, user_id):
    await db.upsert_account(db_conn, user_id, "steam", "111", {})
    await db.upsert_account(db_conn, user_id, "ubisoft", "profile-1", {})
    await db.upsert_account(db_conn, user_id, "ubisoft", "profile-2", {})

    await db.delete_other_accounts_for_platform(db_conn, user_id, "ubisoft", "profile-2")

    rows = await db.list_accounts(db_conn, user_id)
    platforms = sorted((r["platform"], r["external_id"]) for r in rows)
    assert platforms == [("steam", "111"), ("ubisoft", "profile-2")]


async def test_delete_other_accounts_for_platform_is_scoped_to_one_user(db_conn, user_id):
    other_id = (await db.create_user(db_conn, "kid", "x"))["id"]
    await db.upsert_account(db_conn, user_id, "ubisoft", "profile-1", {})
    await db.upsert_account(db_conn, other_id, "ubisoft", "profile-2", {})

    # Deduping user_id's ubisoft accounts must never touch the other user's row.
    await db.delete_other_accounts_for_platform(db_conn, user_id, "ubisoft", "profile-1")

    rows = await db.list_accounts(db_conn, other_id)
    assert len(rows) == 1
    assert rows[0]["external_id"] == "profile-2"


async def test_schema_migration_dedupes_pre_existing_orphan_rows(db_conn):
    # Simulate rows left behind by the bug on an already-deployed database
    # (bypassing upsert_account's ON CONFLICT since these have different
    # external_ids), then confirm re-applying schema.sql's migration prunes
    # everything but the most-recently-created row per platform. These rows
    # deliberately have no user_id, matching a pre-multi-user deployment.
    await db_conn.execute(
        "INSERT INTO linked_accounts (platform, external_id) VALUES (%s, %s)",
        ("ubisoft", "profile-1"),
    )
    await db_conn.execute(
        "INSERT INTO linked_accounts (platform, external_id) VALUES (%s, %s)",
        ("ubisoft", "profile-2"),
    )
    rows_before = await db._fetch(db_conn, "SELECT id FROM linked_accounts WHERE platform = 'ubisoft'")
    assert len(rows_before) == 2
    newest_id = max(r["id"] for r in rows_before)

    # apply_schema runs its migration on a separate pooled connection; commit
    # here first so it isn't blocked waiting on this connection's open transaction
    # (pool.connection() only commits automatically when its own `async with` exits).
    await db_conn.commit()

    pool = await db.get_pool()
    await db.apply_schema(pool)

    rows_after = await db._fetch(db_conn, "SELECT id FROM linked_accounts WHERE platform = 'ubisoft'")
    assert len(rows_after) == 1
    assert rows_after[0]["id"] == newest_id


async def _seed_achievement(conn, platform_game_id: int, ach_id: str) -> int:
    return await db.upsert_achievement(conn, platform_game_id, ach_id, ach_id, None, None, 10, None)


async def test_unlocks_since_only_returns_unlocks_after_the_cutoff(db_conn, user_id):
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    game_id = await db.upsert_platform_game(db_conn, "steam", "42", "Some Game", None, 2)
    old_ach = await _seed_achievement(db_conn, game_id, "old")
    new_ach = await _seed_achievement(db_conn, game_id, "new")

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=2)
    new_time = now - timedelta(minutes=5)
    cutoff = now - timedelta(hours=1)

    await db.upsert_user_achievement(db_conn, account_id, old_ach, True, old_time)
    await db.upsert_user_achievement(db_conn, account_id, new_ach, True, new_time)

    events = await db.unlocks_since(db_conn, account_id, cutoff)

    names = [e["achievement_name"] for e in events]
    assert names == ["new"]


async def test_unlocks_since_ignores_locked_achievements(db_conn, user_id):
    account_id = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    game_id = await db.upsert_platform_game(db_conn, "steam", "42", "Some Game", None, 1)
    ach_id = await _seed_achievement(db_conn, game_id, "still-locked")

    await db.upsert_user_achievement(db_conn, account_id, ach_id, False, None)

    events = await db.unlocks_since(db_conn, account_id, datetime.now(timezone.utc) - timedelta(days=1))
    assert events == []


async def test_unlocks_since_is_scoped_to_the_account(db_conn, user_id):
    account_a = await db.upsert_account(db_conn, user_id, "steam", "111", {})
    account_b = await db.upsert_account(db_conn, user_id, "steam", "222", {})
    game_id = await db.upsert_platform_game(db_conn, "steam", "42", "Some Game", None, 1)
    ach_id = await _seed_achievement(db_conn, game_id, "shared-ach")

    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.upsert_user_achievement(db_conn, account_a, ach_id, True, recent)

    events_a = await db.unlocks_since(db_conn, account_a, datetime.now(timezone.utc) - timedelta(hours=1))
    events_b = await db.unlocks_since(db_conn, account_b, datetime.now(timezone.utc) - timedelta(hours=1))

    assert len(events_a) == 1
    assert events_b == []


async def test_get_profile_defaults_to_null_fields(db_conn):
    profile = await db.get_profile(db_conn)
    assert profile == {"display_name": None, "avatar_url": None}


async def test_update_profile_sets_both_fields(db_conn):
    updated = await db.update_profile(db_conn, "Nick", "https://example.com/avatar.png")
    assert updated == {"display_name": "Nick", "avatar_url": "https://example.com/avatar.png"}

    fetched = await db.get_profile(db_conn)
    assert fetched == updated


async def test_update_profile_can_clear_a_field_back_to_null(db_conn):
    await db.update_profile(db_conn, "Nick", "https://example.com/avatar.png")
    cleared = await db.update_profile(db_conn, "Nick", None)
    assert cleared == {"display_name": "Nick", "avatar_url": None}
