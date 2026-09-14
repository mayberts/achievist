"""
Tests for the Xbox 360 achievement data-corruption cleanup.

Covers three historically-introduced, unrelated bugs found while chasing a
"strange date, no icons" report:

1. Some now-removed version of the 360 sync stamped achievements it hadn't
   actually confirmed as earned with SQL Server's DATETIME-minimum sentinel
   (1753-01-01T00:00:00+00:00) and marked them unlocked anyway. Today's sync
   never revisits those rows, so they'd sit there forever uncorrected.
2. /api/exophase-import-icons used to attach every synthetic achievement row
   it created to an arbitrary ("LIMIT 1") Xbox linked_account rather than the
   one that actually owns the game.
3. Because of (1)/(2), a game could carry the same real-world achievement
   twice: once under Xbox's own numeric id (kept correct by live syncs, but
   with no icon) and once under a synthetic "exo-<slug>" id (has an icon,
   but never gets real unlock status). These must merge into a single row
   that's both correctly synced and has an icon.
"""

from datetime import datetime, timezone

import httpx

from app import auth, db
from app.main import app
from tests.conftest import requires_db

pytestmark = requires_db

SENTINEL = datetime(1753, 1, 1, tzinfo=timezone.utc)


async def _setup_game(db_conn, platform="xbox", title_id="555"):
    user = await db.create_user(db_conn, "u_" + title_id, auth.hash_password("password1234"), is_admin=True)
    linked_id = await db.upsert_linked_account(db_conn, user["id"], platform, "xuid" + title_id)
    pg_id = await db.upsert_platform_game(db_conn, platform, title_id, "Some Game", None, 10)
    await db.upsert_user_game(db_conn, linked_id, pg_id, 0, 1, 10)
    return user, linked_id, pg_id


async def test_fake_1753_unlocks_are_cleared(db_conn):
    _, linked_id, pg_id = await _setup_game(db_conn, title_id="601")
    ach_id = await db.upsert_achievement(db_conn, pg_id, "10", "Fake Unlock", None, None, None, None)
    await db.upsert_user_achievement(db_conn, linked_id, ach_id, True, SENTINEL)
    await db_conn.commit()

    counts = await db.cleanup_legacy_xbox_achievement_data(db_conn)
    await db_conn.commit()

    assert counts["fake_unlocks_cleared"] == 1

    row = await db._fetchrow(
        db_conn,
        "SELECT unlocked, unlocked_at FROM user_achievements WHERE achievement_id = %s AND linked_account_id = %s",
        ach_id, linked_id,
    )
    assert row["unlocked"] is False
    assert row["unlocked_at"] is None


async def test_real_unlocks_with_other_dates_are_untouched(db_conn):
    _, linked_id, pg_id = await _setup_game(db_conn, title_id="602")
    real_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ach_id = await db.upsert_achievement(db_conn, pg_id, "10", "Real Unlock", None, None, None, None)
    await db.upsert_user_achievement(db_conn, linked_id, ach_id, True, real_time)
    await db_conn.commit()

    counts = await db.cleanup_legacy_xbox_achievement_data(db_conn)
    await db_conn.commit()

    assert counts["fake_unlocks_cleared"] == 0
    row = await db._fetchrow(
        db_conn,
        "SELECT unlocked, unlocked_at FROM user_achievements WHERE achievement_id = %s AND linked_account_id = %s",
        ach_id, linked_id,
    )
    assert row["unlocked"] is True
    assert row["unlocked_at"] == real_time


async def test_duplicate_numeric_and_exo_achievements_are_merged(db_conn):
    _, linked_id, pg_id = await _setup_game(db_conn, title_id="603")

    numeric_id = await db.upsert_achievement(
        db_conn, pg_id, "10", "First Blood", "Kill an enemy", None, 10, None,
    )
    await db.upsert_user_achievement(db_conn, linked_id, numeric_id, True, datetime(2024, 1, 1, tzinfo=timezone.utc))

    exo_id = await db.upsert_achievement(
        db_conn, pg_id, "exo-first-blood", "First Blood", None, "https://example.com/icon.png", None, None,
    )
    await db.upsert_user_achievement(db_conn, linked_id, exo_id, False, None)
    await db_conn.commit()

    counts = await db.cleanup_legacy_xbox_achievement_data(db_conn)
    await db_conn.commit()

    assert counts["duplicate_achievements_merged"] == 1

    remaining = await db._fetch(
        db_conn,
        "SELECT platform_ach_id, icon_url FROM achievements WHERE platform_game_id = %s",
        pg_id,
    )
    assert len(remaining) == 1
    assert remaining[0]["platform_ach_id"] == "10"
    assert remaining[0]["icon_url"] == "https://example.com/icon.png"

    ua = await db._fetchrow(
        db_conn,
        "SELECT unlocked FROM user_achievements ua "
        "JOIN achievements a ON a.id = ua.achievement_id "
        "WHERE a.platform_ach_id = '10' AND ua.linked_account_id = %s",
        linked_id,
    )
    assert ua["unlocked"] is True


async def test_numeric_achievement_keeps_its_own_icon_if_it_already_has_one(db_conn):
    _, linked_id, pg_id = await _setup_game(db_conn, title_id="604")

    numeric_id = await db.upsert_achievement(
        db_conn, pg_id, "10", "First Blood", "Kill an enemy", "https://example.com/native-icon.png", 10, None,
    )
    await db.upsert_user_achievement(db_conn, linked_id, numeric_id, True, None)

    exo_id = await db.upsert_achievement(
        db_conn, pg_id, "exo-first-blood", "First Blood", None, "https://example.com/exo-icon.png", None, None,
    )
    await db.upsert_user_achievement(db_conn, linked_id, exo_id, False, None)
    await db_conn.commit()

    await db.cleanup_legacy_xbox_achievement_data(db_conn)
    await db_conn.commit()

    remaining = await db._fetch(
        db_conn,
        "SELECT icon_url FROM achievements WHERE platform_game_id = %s",
        pg_id,
    )
    assert len(remaining) == 1
    assert remaining[0]["icon_url"] == "https://example.com/native-icon.png"


async def test_misattributed_exo_rows_for_non_owning_accounts_are_removed(db_conn):
    """An exo- row attached to an account that never actually owns the game
    (bug 2, before the account-targeting fix) carries nothing real — dropping
    it lets a re-run of the icon import attach a fresh, correctly-owned one."""
    owner, linked_id, pg_id = await _setup_game(db_conn, title_id="605")

    other_user = await db.create_user(db_conn, "u_other_605", auth.hash_password("password1234"), is_admin=True)
    other_linked_id = await db.upsert_linked_account(db_conn, other_user["id"], "xbox", "xuid_other_605")
    # other_linked_id never gets a user_games row for pg_id — it doesn't own the game.

    exo_id = await db.upsert_achievement(
        db_conn, pg_id, "exo-orphan", "Orphan Achievement", None, "https://example.com/icon.png", None, None,
    )
    await db.upsert_user_achievement(db_conn, other_linked_id, exo_id, False, None)
    await db_conn.commit()

    counts = await db.cleanup_legacy_xbox_achievement_data(db_conn)
    await db_conn.commit()

    assert counts["misattributed_rows_removed"] == 1

    row = await db._fetchrow(
        db_conn,
        "SELECT 1 AS present FROM user_achievements ua "
        "JOIN achievements a ON a.id = ua.achievement_id "
        "WHERE a.platform_ach_id = 'exo-orphan' AND ua.linked_account_id = %s",
        other_linked_id,
    )
    assert row is None


async def test_cleanup_is_idempotent(db_conn):
    """Runs automatically on every boot, so a second run over already-clean
    data must be a no-op rather than erroring or corrupting anything further."""
    _, linked_id, pg_id = await _setup_game(db_conn, title_id="606")
    ach_id = await db.upsert_achievement(db_conn, pg_id, "10", "Fake Unlock", None, None, None, None)
    await db.upsert_user_achievement(db_conn, linked_id, ach_id, True, SENTINEL)
    await db_conn.commit()

    await db.cleanup_legacy_xbox_achievement_data(db_conn)
    await db_conn.commit()
    counts = await db.cleanup_legacy_xbox_achievement_data(db_conn)
    await db_conn.commit()

    assert counts == {
        "fake_unlocks_cleared": 0,
        "duplicate_achievements_merged": 0,
        "misattributed_rows_removed": 0,
    }


async def test_exophase_import_creates_rows_for_every_real_owner_not_an_arbitrary_account(db_conn):
    """Regression test for the "LIMIT 1" account bug: in a household with
    more than one Xbox account, a synthetic achievement row created by the
    icon importer used to attach to whichever xbox linked_account Postgres
    happened to return first — regardless of whether that account had ever
    played the game. Every real owner must get its own row."""
    admin = await db.create_user(db_conn, "admin_multi", auth.hash_password("password1234"), is_admin=True)
    owner1 = await db.upsert_linked_account(db_conn, admin["id"], "xbox", "xuid_owner1")
    owner2 = await db.upsert_linked_account(db_conn, admin["id"], "xbox", "xuid_owner2")
    # A third xbox linked_account that exists but never played this game —
    # under the old LIMIT 1 behaviour this could easily be the one picked.
    await db.upsert_linked_account(db_conn, admin["id"], "xbox", "xuid_unrelated")

    pg_id = await db.upsert_platform_game(db_conn, "xbox", "700", "Guitar Hero III", None, 5)
    await db.upsert_user_game(db_conn, owner1, pg_id, 0, 1, 5)
    await db.upsert_user_game(db_conn, owner2, pg_id, 0, 2, 5)
    await db_conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "admin_multi", "password": "password1234"})
        resp = await c.post("/api/exophase-import-icons", json={
            "game_name": "Guitar Hero III",
            "icons": {"New Achievement": "https://example.com/icon.png"},
        })

    assert resp.status_code == 200
    assert resp.json()["achievements_created"] == 1

    rows = await db._fetch(
        db_conn,
        "SELECT ua.linked_account_id FROM user_achievements ua "
        "JOIN achievements a ON a.id = ua.achievement_id "
        "WHERE a.platform_ach_id = 'exo-new-achievement' AND a.platform_game_id = %s",
        pg_id,
    )
    assert {r["linked_account_id"] for r in rows} == {owner1, owner2}
