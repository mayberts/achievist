"""
Tests for GET /api/games?sort=fastest — the "Fastest to 100%" ordering, which
ranks games by the How Long To Beat completionist time still owed
(hltb_complete scaled by the unearned fraction) rather than raw playtime.

The ordering is pure SQL interpolated into both the ORDER BY and the SELECT,
so nothing but a DB-backed request exercises it; these cover the three cases
that expression has to get right — a real estimate, an absent HLTB figure,
and an already-mastered game.
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


async def _seed_game(
    db_conn, account_id: int, app_id: str, name: str,
    earned: int, total: int, hltb_complete: float | None,
) -> int:
    game = await db.upsert_platform_game(db_conn, "steam", app_id, name, None, total)
    await db.upsert_user_game(db_conn, account_id, game, 0, earned, total)
    if hltb_complete is not None:
        await db.update_hltb(db_conn, game, 10, None, hltb_complete)
    return game


async def _login_with_games(db_conn, client) -> None:
    user = await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    account_id = await db.upsert_account(db_conn, user["id"], "steam", "111", {})

    # 100h completionist, 90% still unearned -> ~90h owed
    await _seed_game(db_conn, account_id, "1", "Long Grind", 10, 100, 100)
    # 100h completionist, only 5% left -> ~5h owed, so a nearly-done long game
    # should outrank a short game started from scratch
    await _seed_game(db_conn, account_id, "2", "Nearly There", 95, 100, 100)
    # 10h completionist, untouched -> ~10h owed
    await _seed_game(db_conn, account_id, "3", "Short Game", 0, 10, 10)
    # no completionist figure at all -> unknown, must not sort as "instant"
    await _seed_game(db_conn, account_id, "4", "No HLTB", 1, 10, None)
    # already at 100% -> nothing left to spend, regardless of its 2h figure
    await _seed_game(db_conn, account_id, "5", "Mastered", 10, 10, 2)
    await db_conn.commit()

    await client.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})


async def test_fastest_orders_by_remaining_time_not_total_length(db_conn, client):
    await _login_with_games(db_conn, client)

    resp = await client.get("/api/games", params={"sort": "fastest"})
    assert resp.status_code == 200
    names = [g["name"] for g in resp.json()["games"]]

    # Nearly There (~5h) beats Short Game (~10h) even though it's a 100h game,
    # and Long Grind (~90h) trails both.
    assert names[:3] == ["Nearly There", "Short Game", "Long Grind"]
    # Unknown-HLTB and already-mastered games bring up the rear.
    assert set(names[3:]) == {"No HLTB", "Mastered"}


async def test_fastest_reports_the_remaining_estimate_it_sorted_by(db_conn, client):
    await _login_with_games(db_conn, client)

    resp = await client.get("/api/games", params={"sort": "fastest"})
    remaining = {g["name"]: g["hltb_remaining"] for g in resp.json()["games"]}

    assert float(remaining["Nearly There"]) == 5.0
    assert float(remaining["Short Game"]) == 10.0
    assert float(remaining["Long Grind"]) == 90.0
    # No completionist figure means no estimate — not a zero.
    assert remaining["No HLTB"] is None


async def test_other_sorts_still_report_the_estimate(db_conn, client):
    """The estimate rides along on every sort, so the UI can show it anywhere."""
    await _login_with_games(db_conn, client)

    resp = await client.get("/api/games", params={"sort": "name"})
    assert resp.status_code == 200
    by_name = {g["name"]: g["hltb_remaining"] for g in resp.json()["games"]}
    assert float(by_name["Short Game"]) == 10.0
