"""
Tests for app.platforms.exophase._dedupe_stored_achievements — cleans up
duplicate achievement rows left in the database from before the
_dedupe_awards() fix existed (EA sometimes lists the same achievement twice
under different numeric ids; games already synced before that fix keep
their stale duplicates forever otherwise, since incremental sync skips
re-scraping once counts already match).
"""

from app import db
from app.platforms.exophase import _dedupe_stored_achievements
from tests.conftest import requires_db

pytestmark = requires_db


async def test_dedupe_stored_achievements_keeps_unlocked_copy(db_conn):
    account_id = await db.upsert_account(db_conn, "ea", "ea", {})
    linked_id = await db.upsert_linked_account(db_conn, "ea", "ea")
    pg_id = await db.upsert_platform_game(db_conn, "ea", "a-way-out-origin", "A Way Out", None, 14)

    # Two duplicate rows for the same real achievement (different platform_ach_id),
    # only one of which is marked unlocked.
    locked_dup = await db.upsert_achievement(
        db_conn, pg_id, "108-backseat-mechanic", "Backseat Mechanic", "You helped fix the bike.", None, 10, 83.42,
    )
    unlocked_dup = await db.upsert_achievement(
        db_conn, pg_id, "230-backseat-mechanic", "Backseat Mechanic", "You helped fix the bike.", None, 10, 83.42,
    )
    await db.upsert_user_achievement(db_conn, linked_id, unlocked_dup, True, None)

    # An unrelated, genuinely distinct achievement — must survive untouched.
    other = await db.upsert_achievement(
        db_conn, pg_id, "109-in-sync", "In Sync", "Music was played in harmony.", None, 20, 28.21,
    )

    await _dedupe_stored_achievements(db_conn, pg_id)

    rows = await db._fetch(
        db_conn, "SELECT id, platform_ach_id FROM achievements WHERE platform_game_id = %s ORDER BY id", pg_id,
    )
    ids = {r["id"] for r in rows}
    assert locked_dup not in ids
    assert unlocked_dup in ids
    assert other in ids
    assert len(rows) == 2


async def test_dedupe_stored_achievements_matches_despite_case_differences(db_conn):
    """Ubisoft's duplicate copies differ in case/punctuation, e.g. "DIY" vs "Diy"."""
    pg_id = await db.upsert_platform_game(db_conn, "ubisoft", "far-cry-6-uplay", "Far Cry 6", None, 92)

    upper = await db.upsert_achievement(
        db_conn, pg_id, "1-diy", "DIY", "Acquire 5 of Juan's Resolver Weapons.", None, None, 41.0,
    )
    lower = await db.upsert_achievement(db_conn, pg_id, "2-diy", "Diy", None, None, None, None)

    await _dedupe_stored_achievements(db_conn, pg_id)

    rows = await db._fetch(
        db_conn, "SELECT id FROM achievements WHERE platform_game_id = %s", pg_id,
    )
    ids = {r["id"] for r in rows}
    assert len(rows) == 1
    # Neither copy is unlocked, so the one with a description wins (its
    # capitalization/punctuation happens to reflect the real name better).
    assert upper in ids
    assert lower not in ids
