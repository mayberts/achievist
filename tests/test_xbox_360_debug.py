"""
Tests for /api/xbox-360-debug — the admin diagnostic endpoint used to see
exactly what Xbox Live's API is telling the server about a specific game.

It used to always query the *signed-in backend account's own* xuid. Xbox's
own model — "one backend Xbox sign-in authorizes all lookups; individual
accounts get added by gamertag" — means a game's actual owner can easily be
a different xuid than the signed-in one. Querying the wrong xuid returns a
perfectly well-formed 200 with an empty achievement list: indistinguishable
from "this account genuinely has nothing here" unless you already know to
doubt it. That's a bad shape for a diagnostic tool whose entire job is to
be trusted.
"""

import httpx

from app import auth, db
from app.main import app
from app.xbox_auth import XboxTokens
from tests.conftest import requires_db

pytestmark = requires_db

SIGNED_IN_XUID = "1111111111111111"  # the backend's own account
OWNER_XUID = "2222222222222222"      # a different gamertag added to the family
TITLE_ID = "1096157159"


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "titleHistory" in url:
        return httpx.Response(200, json={"titles": []})
    if f"/titles/{TITLE_ID}/achievements" in url:
        return httpx.Response(404, text="not found")
    if f"/users/xuid({SIGNED_IN_XUID})/achievements" in url:
        # The wrong account: well-formed, empty, and indistinguishable from
        # a real "nothing earned" response unless you know it's the wrong xuid.
        return httpx.Response(200, json={"achievements": [], "pagingInfo": {"totalRecords": 0}})
    if f"/users/xuid({OWNER_XUID})/achievements" in url:
        return httpx.Response(200, json={
            "achievements": [{"id": "1", "name": "First Blood"}],
            "pagingInfo": {"totalRecords": 1},
        })
    raise AssertionError(f"unexpected request: {url}")


async def test_debug_checks_the_games_actual_owner_not_the_signed_in_account(
    monkeypatch, db_conn,
):
    admin = await db.create_user(db_conn, "parent", auth.hash_password("password1234"), is_admin=True)
    linked_id = await db.upsert_linked_account(db_conn, admin["id"], "xbox", OWNER_XUID)
    pg_id = await db.upsert_platform_game(db_conn, "xbox", TITLE_ID, "Retro Adventure", None, 1)
    await db.upsert_user_game(db_conn, linked_id, pg_id, 0, 1, 1)
    await db_conn.commit()

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_async_client(transport=httpx.MockTransport(_handler)),
    )

    async def fake_get_tokens(refresh_token):
        return XboxTokens(xsts_token="t", user_hash="h", xuid=SIGNED_IN_XUID)

    monkeypatch.setattr("app.xbox_auth.get_tokens", fake_get_tokens)
    from app import config
    monkeypatch.setattr(config, "XBOX_REFRESH_TOKEN", "fake-refresh-token")

    transport = httpx.ASGITransport(app=app)
    async with real_async_client(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "parent", "password": "password1234"})
        resp = await c.get(f"/api/xbox-360-debug?game_id={pg_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["signed_in_xuid"] == SIGNED_IN_XUID

    accounts = body["accounts_checked"]
    assert len(accounts) == 1
    checked = accounts[0]
    # The whole point: it queried the owner's xuid, not the signed-in one,
    # and so sees the real achievement rather than a plausible-looking blank.
    assert checked["xuid"] == OWNER_XUID
    assert checked["user_v1_sample"]["achievements"] == [{"id": "1", "name": "First Blood"}]


async def test_explicit_xuid_overrides_owner_lookup(monkeypatch, db_conn):
    """An admin checking an account that doesn't own the game yet (e.g. it
    hasn't synced once) needs to be able to name the xuid directly."""
    admin = await db.create_user(db_conn, "parent2", auth.hash_password("password1234"), is_admin=True)
    pg_id = await db.upsert_platform_game(db_conn, "xbox", TITLE_ID, "Retro Adventure", None, 1)
    await db_conn.commit()

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_async_client(transport=httpx.MockTransport(_handler)),
    )

    async def fake_get_tokens(refresh_token):
        return XboxTokens(xsts_token="t", user_hash="h", xuid=SIGNED_IN_XUID)

    monkeypatch.setattr("app.xbox_auth.get_tokens", fake_get_tokens)
    from app import config
    monkeypatch.setattr(config, "XBOX_REFRESH_TOKEN", "fake-refresh-token")

    transport = httpx.ASGITransport(app=app)
    async with real_async_client(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "parent2", "password": "password1234"})
        resp = await c.get(f"/api/xbox-360-debug?game_id={pg_id}&xuid={OWNER_XUID}")

    assert resp.status_code == 200
    accounts = resp.json()["accounts_checked"]
    assert accounts[0]["xuid"] == OWNER_XUID


OTHER_TITLE_ID = "1096157999"  # a second Xbox titleId for the "same" game


def _handler_with_split_titles(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "titleHistory" in url:
        return httpx.Response(200, json={
            "titles": [
                {"titleId": int(TITLE_ID), "name": "Rock Band Legacy",
                 "achievement": {"currentAchievements": 4, "totalAchievements": 11}},
                {"titleId": int(OTHER_TITLE_ID), "name": "Rock Band Legacy",
                 "achievement": {"currentAchievements": 7, "totalAchievements": 11}},
                {"titleId": 999, "name": "A Completely Different Game",
                 "achievement": {"currentAchievements": 2, "totalAchievements": 2}},
            ]
        })
    if f"/titles/{TITLE_ID}/achievements" in url:
        return httpx.Response(404, text="not found")
    if f"/users/xuid({OWNER_XUID})/achievements" in url:
        return httpx.Response(200, json={
            "achievements": [{"id": "1", "name": "First Blood"}] * 4,
            "pagingInfo": {"totalRecords": 4},
        })
    raise AssertionError(f"unexpected request: {url}")


async def test_debug_surfaces_a_second_titleid_holding_the_missing_achievements(
    monkeypatch, db_conn,
):
    """The real bug this was built to catch: sync only ever fetches
    achievements for the one titleId its per-name dedup picks as "best" —
    it never merges two titleIds' achievements together. If a game's real
    unlocks are split across two Xbox-assigned titleIds for what is visibly
    one game, the loser is invisible to the app forever, not just this sync,
    and nothing before this endpoint change could have shown that."""
    admin = await db.create_user(db_conn, "parent3", auth.hash_password("password1234"), is_admin=True)
    linked_id = await db.upsert_linked_account(db_conn, admin["id"], "xbox", OWNER_XUID)
    pg_id = await db.upsert_platform_game(db_conn, "xbox", TITLE_ID, "Rock Band Legacy", None, 11)
    await db.upsert_user_game(db_conn, linked_id, pg_id, 0, 4, 11)
    await db_conn.commit()

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_async_client(transport=httpx.MockTransport(_handler_with_split_titles)),
    )

    async def fake_get_tokens(refresh_token):
        return XboxTokens(xsts_token="t", user_hash="h", xuid=SIGNED_IN_XUID)

    monkeypatch.setattr("app.xbox_auth.get_tokens", fake_get_tokens)
    from app import config
    monkeypatch.setattr(config, "XBOX_REFRESH_TOKEN", "fake-refresh-token")

    transport = httpx.ASGITransport(app=app)
    async with real_async_client(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "parent3", "password": "password1234"})
        resp = await c.get(f"/api/xbox-360-debug?game_id={pg_id}")

    assert resp.status_code == 200
    checked = resp.json()["accounts_checked"][0]
    others = checked["other_titleids_same_name"]

    # Finds the second titleId sharing this game's name...
    assert [o["titleId"] for o in others] == [int(OTHER_TITLE_ID)]
    # ...and reports enough about it to show it's the one holding the gap:
    # 7 more current achievements than the titleId Achievist actually synced.
    assert others[0]["currentAchievements"] == 7
    assert others[0]["totalAchievements"] == 11
    # A same-named-by-coincidence different game must never show up here.
    assert all(o["titleId"] != 999 for o in others)
