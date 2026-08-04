"""
Tests for the achievement-unlock notification feed: the pure ring-buffer
helper (no DB needed) and the /api/unlocks/recent endpoint, which now
requires login and filters events to the logged-in user.
"""

from datetime import datetime, timezone

import httpx
import pytest

from app import auth, db, main as main_module
from app.main import _UNLOCK_EVENTS_MAX, _record_unlock_events, _unlock_events, app
from tests.conftest import requires_db


@pytest.fixture(autouse=True)
def clear_unlock_events():
    _unlock_events.clear()
    yield
    _unlock_events.clear()


def _row(name: str, ts: datetime) -> dict:
    return {
        "achievement_name": name,
        "icon_url": None,
        "points": 10,
        "game_name": "Some Game",
        "platform": "steam",
        "platform_game_id": 1,
        "unlocked_at": ts,
    }


def test_record_unlock_events_caps_buffer():
    rows = [_row(f"ach-{i}", datetime(2026, 1, 1, tzinfo=timezone.utc)) for i in range(_UNLOCK_EVENTS_MAX + 20)]
    _record_unlock_events(rows, user_id=1)
    assert len(main_module._unlock_events) == _UNLOCK_EVENTS_MAX
    # the oldest entries should have been dropped, newest kept
    assert main_module._unlock_events[-1]["achievement_name"] == f"ach-{_UNLOCK_EVENTS_MAX + 19}"


pytestmark = requires_db


@pytest.fixture
async def client(db_conn):
    await db.create_user(db_conn, "parent", auth.hash_password("parentpassword1"), is_admin=True)
    await db_conn.commit()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "parent", "password": "parentpassword1"})
        yield c


async def test_recent_unlocks_empty_by_default(client):
    resp = await client.get("/api/unlocks/recent")
    assert resp.status_code == 200
    assert resp.json() == {"events": []}


async def test_recent_unlocks_filters_by_since(client, db_conn):
    me = await db.get_user_by_username(db_conn, "parent")
    _record_unlock_events([
        _row("first", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _row("second", datetime(2026, 1, 2, tzinfo=timezone.utc)),
    ], user_id=me["id"])
    cutoff = datetime(2026, 1, 1, 12, tzinfo=timezone.utc).isoformat()

    resp = await client.get("/api/unlocks/recent", params={"since": cutoff})
    assert resp.status_code == 200
    names = [e["achievement_name"] for e in resp.json()["events"]]
    assert names == ["second"]


async def test_recent_unlocks_without_since_returns_everything_buffered(client, db_conn):
    me = await db.get_user_by_username(db_conn, "parent")
    _record_unlock_events([_row("only", datetime(2026, 1, 1, tzinfo=timezone.utc))], user_id=me["id"])
    resp = await client.get("/api/unlocks/recent")
    names = [e["achievement_name"] for e in resp.json()["events"]]
    assert names == ["only"]


async def test_recent_unlocks_excludes_other_users_events(client, db_conn):
    other = await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"))
    await db_conn.commit()
    _record_unlock_events([_row("not-mine", datetime(2026, 1, 1, tzinfo=timezone.utc))], user_id=other["id"])
    resp = await client.get("/api/unlocks/recent")
    assert resp.json() == {"events": []}
