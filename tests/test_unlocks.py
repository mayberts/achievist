"""
Tests for the achievement-unlock notification feed: the pure ring-buffer
helper and the /api/unlocks/recent endpoint, both of which are in-memory and
don't need a live database.
"""

from datetime import datetime, timezone

import httpx
import pytest

from app import main as main_module
from app.main import _UNLOCK_EVENTS_MAX, _record_unlock_events, _unlock_events, app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


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
    _record_unlock_events(rows)
    assert len(main_module._unlock_events) == _UNLOCK_EVENTS_MAX
    # the oldest entries should have been dropped, newest kept
    assert main_module._unlock_events[-1]["achievement_name"] == f"ach-{_UNLOCK_EVENTS_MAX + 19}"


async def test_recent_unlocks_empty_by_default(client):
    resp = await client.get("/api/unlocks/recent")
    assert resp.status_code == 200
    assert resp.json() == {"events": []}


async def test_recent_unlocks_filters_by_since(client):
    _record_unlock_events([
        _row("first", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _row("second", datetime(2026, 1, 2, tzinfo=timezone.utc)),
    ])
    cutoff = datetime(2026, 1, 1, 12, tzinfo=timezone.utc).isoformat()

    resp = await client.get("/api/unlocks/recent", params={"since": cutoff})
    assert resp.status_code == 200
    names = [e["achievement_name"] for e in resp.json()["events"]]
    assert names == ["second"]


async def test_recent_unlocks_without_since_returns_everything_buffered(client):
    _record_unlock_events([_row("only", datetime(2026, 1, 1, tzinfo=timezone.utc))])
    resp = await client.get("/api/unlocks/recent")
    names = [e["achievement_name"] for e in resp.json()["events"]]
    assert names == ["only"]
