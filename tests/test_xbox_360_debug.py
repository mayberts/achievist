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
