"""
Tests for POST /api/games/{id}/import-exophase-catalog — backfills the full
locked+unlocked achievement catalog for a legacy Xbox 360 title from
Exophase's public game page. Xbox's own v1 achievements API has no "list
everything, locked or not" call, so native sync can only ever create a row
for an achievement it's confirmed earned; this is how the rest of a
title's real catalog gets in, with icons, without needing them pasted in
by hand (unlike the older /api/exophase-import-icons).
"""
import httpx

from app import auth, db
from app.main import app
from app.platforms import exophase
from tests.conftest import requires_db

pytestmark = requires_db


async def _setup_game(db_conn, title_id="900", name="Some 360 Game"):
    admin = await db.create_user(db_conn, "admin_" + title_id, auth.hash_password("password1234"), is_admin=True)
    linked_id = await db.upsert_linked_account(db_conn, admin["id"], "xbox", "xuid" + title_id)
    pg_id = await db.upsert_platform_game(db_conn, "xbox", title_id, name, None, 50)
    await db.upsert_user_game(db_conn, linked_id, pg_id, 0, 1, 50)
    return admin, linked_id, pg_id


async def _client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_imports_full_catalog_and_skips_already_synced(monkeypatch, db_conn):
    admin, linked_id, pg_id = await _setup_game(db_conn, title_id="901", name="Guitar Hero Hits")
    ach_id = await db.upsert_achievement(db_conn, pg_id, "1", "Golden Fingers", None, None, 10, None)
    await db.upsert_user_achievement(db_conn, linked_id, ach_id, True, None)
    await db_conn.commit()

    async def fake_awards(exo_slug, page_type="achievements"):
        assert exo_slug == "guitar-hero-hits-xbox-360"
        return [
            {"name": "Golden Fingers", "description": "You performed as the Guitarist.",
             "icon": "https://example.com/golden.png", "points": "10", "rarity_pct": "42.5"},
            {"name": "I Wanna Rock", "description": "You completed a song.",
             "icon": "https://example.com/rock.png", "points": "15", "rarity_pct": "30.1"},
        ]

    monkeypatch.setattr(exophase, "fetch_game_page_awards", fake_awards)

    async with await _client() as c:
        await c.post("/api/auth/login", json={"username": admin["username"], "password": "password1234"})
        resp = await c.post(f"/api/games/{pg_id}/import-exophase-catalog")

    assert resp.status_code == 200
    body = resp.json()
    assert body["exo_slug"] == "guitar-hero-hits-xbox-360"
    assert body["achievements_created"] == 1  # "Golden Fingers" already existed, skipped

    rows = await db._fetch(
        db_conn,
        "SELECT a.platform_ach_id, a.icon_url, ua.unlocked, ua.linked_account_id "
        "FROM achievements a JOIN user_achievements ua ON ua.achievement_id = a.id "
        "WHERE a.platform_game_id = %s AND a.platform_ach_id = 'exo-i-wanna-rock'",
        pg_id,
    )
    assert len(rows) == 1
    assert rows[0]["icon_url"] == "https://example.com/rock.png"
    assert rows[0]["unlocked"] is False
    assert rows[0]["linked_account_id"] == linked_id


async def test_falls_back_to_alt_title_when_own_name_has_no_match(monkeypatch, db_conn):
    admin, linked_id, pg_id = await _setup_game(db_conn, title_id="902", name="Guitar Hero Hits")
    await db_conn.commit()

    async def fake_awards(exo_slug, page_type="achievements"):
        if exo_slug == "guitar-hero-smash-hits-xbox-360":
            return [{"name": "Only Award", "description": None, "icon": None, "points": None, "rarity_pct": None}]
        return []

    monkeypatch.setattr(exophase, "fetch_game_page_awards", fake_awards)

    async with await _client() as c:
        await c.post("/api/auth/login", json={"username": admin["username"], "password": "password1234"})
        resp = await c.post(
            f"/api/games/{pg_id}/import-exophase-catalog",
            json={"alt_title": "Guitar Hero Smash Hits"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["exo_slug"] == "guitar-hero-smash-hits-xbox-360"
    assert body["achievements_created"] == 1


async def test_reports_an_error_when_no_slug_matches(monkeypatch, db_conn):
    admin, linked_id, pg_id = await _setup_game(db_conn, title_id="903", name="Untitled Rhythm Game")
    await db_conn.commit()

    async def fake_awards(exo_slug, page_type="achievements"):
        return []

    monkeypatch.setattr(exophase, "fetch_game_page_awards", fake_awards)

    async with await _client() as c:
        await c.post("/api/auth/login", json={"username": admin["username"], "password": "password1234"})
        resp = await c.post(f"/api/games/{pg_id}/import-exophase-catalog")

    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body


async def test_no_owner_reports_an_error_instead_of_attaching_to_an_arbitrary_account(monkeypatch, db_conn):
    """Regression guard for the exact bug fixed in #291: never fall back to
    an arbitrary xbox account when nobody actually owns the game."""
    admin = await db.create_user(db_conn, "admin_904", auth.hash_password("password1234"), is_admin=True)
    # A different xbox account exists but never played this game.
    await db.upsert_linked_account(db_conn, admin["id"], "xbox", "unrelated_904")
    pg_id = await db.upsert_platform_game(db_conn, "xbox", "904", "Orphan Game", None, 10)
    await db_conn.commit()

    async def fake_awards(exo_slug, page_type="achievements"):
        return [{"name": "Should Not Import", "description": None, "icon": None, "points": None, "rarity_pct": None}]

    monkeypatch.setattr(exophase, "fetch_game_page_awards", fake_awards)

    async with await _client() as c:
        await c.post("/api/auth/login", json={"username": admin["username"], "password": "password1234"})
        resp = await c.post(f"/api/games/{pg_id}/import-exophase-catalog")

    assert resp.status_code == 200
    assert "error" in resp.json()

    count = await db._fetchrow(
        db_conn, "SELECT count(*) AS n FROM achievements WHERE platform_game_id = %s", pg_id,
    )
    assert count["n"] == 0
