"""
Tests for the Xbox 360 achievement fetch in app/platforms/xbox.py.

Xbox 360 titles are serviced by the legacy v1 achievements API, which only
ever returns earned achievements (there's no "list everything, locked or
not" call for it). The tests here cover a failure mode that used to be
completely invisible: if that one call comes back with anything other than
200, the code treated whatever partial (often empty) list it had collected
as the final, correct answer — silently. A newly-unlocked achievement that
hadn't been paged in yet would just never show up, with no error anywhere
to explain why. That's the exact shape of "it synced before, but achievements
I've since unlocked aren't showing up."
"""

import logging

import httpx

from app import db
from app.platforms.xbox import XboxPlatform
from app.xbox_auth import XboxTokens
from tests.conftest import requires_db

pytestmark = requires_db

XUID = "2533000000000000"
TITLE_ID = "1234567890"

def _title_history(total: int, current: int) -> dict:
    return {
        "titles": [
            {
                "titleId": TITLE_ID,
                "name": "Retro Adventure",
                "achievement": {
                    "totalAchievements": total,
                    "currentAchievements": current,
                    "totalGamerscore": 200,
                    "sourceVersion": 1,
                },
                "titleHistory": {"lastTimePlayed": "2024-01-01T00:00:00Z", "minutesPlayed": 60},
                "images": [],
                "pfn": None,
                "storeId": None,
            }
        ]
    }


# A fixed titleHistory summary reporting 1 total / 1 earned — modeling a
# legacy 360 title whose Xbox-reported totalAchievements is simply wrong
# (too low; the game actually has more). It never changes between syncs in
# these tests, which is what makes it exercise the bug: once locally-stored
# achievements reach this (wrong) total, the cache shortcut has no other
# signal telling it there's more to find.
_TITLE_HISTORY = _title_history(total=1, current=1)


def _json(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _handler_factory(ach_status: int, ach_body: dict | None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "titleHistory" in url:
            return _json(_TITLE_HISTORY)
        if "/users/xuid(" in url and "/achievements" in url:
            return _json(ach_body or {}, ach_status)
        raise AssertionError(f"unexpected request: {url}")

    return handler


async def test_a_failed_achievement_fetch_does_not_erase_or_fabricate_data(monkeypatch, db_conn, caplog):
    """First sync succeeds and stores one earned achievement. A second sync
    where the achievements call fails outright must leave that achievement
    exactly as it was — not wipe it, and not silently record zero."""
    from app import auth

    user = await db.create_user(db_conn, "p1", auth.hash_password("password1234"), is_admin=True)
    account = {"user_id": user["id"], "external_id": "xbox", "credentials": {}}
    platform = XboxPlatform()

    # First sync: the v1 endpoint succeeds and returns one earned achievement.
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_async_client(
            transport=httpx.MockTransport(_handler_factory(200, {
                "achievements": [{"id": "1", "name": "First Blood", "gamerscore": 100,
                                   "timeUnlocked": "2024-01-01T00:00:00Z"}],
                "pagingInfo": {},
            }))
        ),
    )

    async def fake_get_tokens(refresh_token):
        return XboxTokens(xsts_token="t", user_hash="h", xuid=XUID)

    monkeypatch.setattr("app.xbox_auth.get_tokens", fake_get_tokens)
    from app import config
    monkeypatch.setattr(config, "XBOX_REFRESH_TOKEN", "fake-refresh-token")

    await platform.sync(account, db_conn)
    await db_conn.commit()

    rows = await db._fetch(
        db_conn,
        "SELECT a.platform_ach_id, ua.unlocked FROM achievements a "
        "JOIN platform_games pg ON pg.id = a.platform_game_id "
        "JOIN user_achievements ua ON ua.achievement_id = a.id "
        "WHERE pg.platform_app_id = %s",
        TITLE_ID,
    )
    assert {r["platform_ach_id"] for r in rows} == {"1"}
    assert all(r["unlocked"] for r in rows)

    # Second sync: the v1 endpoint now fails outright.
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_async_client(transport=httpx.MockTransport(_handler_factory(500, {}))),
    )
    with caplog.at_level(logging.WARNING, logger="app.platforms.xbox"):
        await platform.sync(account, db_conn)
    await db_conn.commit()

    # This is the actual behavioural difference the fix makes: upsert() is
    # non-destructive either way, so a silently-swallowed failure and a
    # logged one leave the same rows in the database — a DB-only assertion
    # here would pass against the old, silent code too. The failure being
    # visible in the logs at all is the fix; before this, a 360 fetch
    # failure was invisible everywhere; the non-360 branch already logged
    # its equivalent failure, so this brings the two in line.
    assert any(
        "360 achievements fetch failed" in r.message and "500" in r.message
        for r in caplog.records
    ), "a failed 360 achievement fetch must be logged, not swallowed silently"

    rows_after = await db._fetch(
        db_conn,
        "SELECT a.platform_ach_id, ua.unlocked FROM achievements a "
        "JOIN platform_games pg ON pg.id = a.platform_game_id "
        "JOIN user_achievements ua ON ua.achievement_id = a.id "
        "WHERE pg.platform_app_id = %s",
        TITLE_ID,
    )
    # Still worth pinning down even though it holds either way: a failed
    # fetch must never erase what a previous successful sync recorded.
    assert {r["platform_ach_id"] for r in rows_after} == {"1"}
    assert all(r["unlocked"] for r in rows_after)


async def test_a_later_successful_sync_picks_up_the_new_unlock(monkeypatch, db_conn):
    """The scenario reported: synced fine once, then a newly-unlocked
    achievement doesn't show up.

    Modeled here as a 360 title whose Xbox-reported totalAchievements is
    wrong (too low) and never corrects itself — a real category of data
    quality issue for legacy titles. Once locally-stored achievements reach
    that (wrong) total, the ordinary "nothing changed, skip re-fetching"
    shortcut has no other signal telling it there's more to find, and would
    stay skipping forever even as real new unlocks come in. 360 titles must
    not go through that shortcut at all — the one authoritative source for
    what's actually unlocked is the achievements endpoint itself, which is
    cheap enough (one bounded, paginated call) to just always ask."""
    from app import auth

    user = await db.create_user(db_conn, "p2", auth.hash_password("password1234"), is_admin=True)
    account = {"user_id": user["id"], "external_id": "xbox", "credentials": {}}
    platform = XboxPlatform()

    real_async_client = httpx.AsyncClient

    async def fake_get_tokens(refresh_token):
        return XboxTokens(xsts_token="t", user_hash="h", xuid=XUID)

    monkeypatch.setattr("app.xbox_auth.get_tokens", fake_get_tokens)
    from app import config
    monkeypatch.setattr(config, "XBOX_REFRESH_TOKEN", "fake-refresh-token")

    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_async_client(
            transport=httpx.MockTransport(_handler_factory(200, {
                "achievements": [{"id": "1", "name": "First Blood", "gamerscore": 100,
                                   "timeUnlocked": "2024-01-01T00:00:00Z"}],
                "pagingInfo": {},
            }))
        ),
    )
    await platform.sync(account, db_conn)
    await db_conn.commit()

    # A second unlock has since happened, but Xbox's titleHistory summary
    # (currentAchievements) is unreliable for legacy titles and still
    # reports 1 — exactly as modeled by _TITLE_HISTORY above, which never
    # changes between syncs in this test.
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_async_client(
            transport=httpx.MockTransport(_handler_factory(200, {
                "achievements": [
                    {"id": "1", "name": "First Blood", "gamerscore": 100,
                     "timeUnlocked": "2024-01-01T00:00:00Z"},
                    {"id": "2", "name": "Second Blood", "gamerscore": 100,
                     "timeUnlocked": "2024-02-01T00:00:00Z"},
                ],
                "pagingInfo": {},
            }))
        ),
    )
    await platform.sync(account, db_conn)
    await db_conn.commit()

    rows = await db._fetch(
        db_conn,
        "SELECT a.platform_ach_id, ua.unlocked FROM achievements a "
        "JOIN platform_games pg ON pg.id = a.platform_game_id "
        "JOIN user_achievements ua ON ua.achievement_id = a.id "
        "WHERE pg.platform_app_id = %s",
        TITLE_ID,
    )
    assert {r["platform_ach_id"] for r in rows} == {"1", "2"}
    assert all(r["unlocked"] for r in rows)


async def test_a_1753_placeholder_from_xbox_itself_is_stored_as_unlocked_with_no_date(monkeypatch, db_conn):
    """Xbox's own legacy achievements API has been observed returning
    1753-01-01 (SQL Server's DATETIME minimum) as a "no real timestamp on
    file" placeholder for old 360 unlocks — the same kind of placeholder as
    the documented 0001-01-01 one, just from an older part of Microsoft's
    backend. This isn't Achievist-side data corruption to clean up after
    the fact: it comes from Xbox's API on every sync, so if sync doesn't
    filter it at the source, a one-time repair migration gets silently
    undone by the very next sync. The achievement is still genuinely
    earned (it's in the earned list at all only because Xbox confirmed it),
    so it must be stored unlocked, just with no fabricated date."""
    from app import auth

    user = await db.create_user(db_conn, "p3", auth.hash_password("password1234"), is_admin=True)
    account = {"user_id": user["id"], "external_id": "xbox", "credentials": {}}
    platform = XboxPlatform()

    real_async_client = httpx.AsyncClient

    async def fake_get_tokens(refresh_token):
        return XboxTokens(xsts_token="t", user_hash="h", xuid=XUID)

    monkeypatch.setattr("app.xbox_auth.get_tokens", fake_get_tokens)
    from app import config
    monkeypatch.setattr(config, "XBOX_REFRESH_TOKEN", "fake-refresh-token")

    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_async_client(
            transport=httpx.MockTransport(_handler_factory(200, {
                "achievements": [{"id": "1", "name": "Old Unlock", "gamerscore": 100,
                                   "timeUnlocked": "1753-01-01T00:00:00.0000000Z"}],
                "pagingInfo": {},
            }))
        ),
    )
    await platform.sync(account, db_conn)
    await db_conn.commit()

    row = await db._fetchrow(
        db_conn,
        "SELECT ua.unlocked, ua.unlocked_at FROM achievements a "
        "JOIN platform_games pg ON pg.id = a.platform_game_id "
        "JOIN user_achievements ua ON ua.achievement_id = a.id "
        "WHERE pg.platform_app_id = %s AND a.platform_ach_id = '1'",
        TITLE_ID,
    )
    assert row["unlocked"] is True
    assert row["unlocked_at"] is None


async def test_360_achievement_icon_is_built_from_title_and_image_ids(monkeypatch, db_conn):
    """Legacy 360 achievements only ever carry a numeric imageId, not a
    usable URL — verified directly against a real deployment: two
    different imageIds for the same title each resolved to a distinct,
    correct icon at http://image.xboxlive.com/global/t.<title hex>/ach/0/<image hex>."""
    from app import auth

    user = await db.create_user(db_conn, "p4", auth.hash_password("password1234"), is_admin=True)
    account = {"user_id": user["id"], "external_id": "xbox", "credentials": {}}
    platform = XboxPlatform()

    real_async_client = httpx.AsyncClient

    async def fake_get_tokens(refresh_token):
        return XboxTokens(xsts_token="t", user_hash="h", xuid=XUID)

    monkeypatch.setattr("app.xbox_auth.get_tokens", fake_get_tokens)
    from app import config
    monkeypatch.setattr(config, "XBOX_REFRESH_TOKEN", "fake-refresh-token")

    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_async_client(
            transport=httpx.MockTransport(_handler_factory(200, {
                "achievements": [{"id": "1", "name": "Easy Tour Champ", "gamerscore": 10,
                                   "imageId": 36, "timeUnlocked": "2024-01-01T00:00:00Z"}],
                "pagingInfo": {},
            }))
        ),
    )
    await platform.sync(account, db_conn)
    await db_conn.commit()

    row = await db._fetchrow(
        db_conn,
        "SELECT a.icon_url FROM achievements a "
        "JOIN platform_games pg ON pg.id = a.platform_game_id "
        "WHERE pg.platform_app_id = %s AND a.platform_ach_id = '1'",
        TITLE_ID,
    )
    assert row["icon_url"] == f"http://image.xboxlive.com/global/t.{int(TITLE_ID):x}/ach/0/24"
