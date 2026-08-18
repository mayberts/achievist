"""
Smoke tests for routes that don't require a live database connection.

Most of main.py's endpoints touch Postgres, so a full integration suite needs
a running DB (out of scope here). These cover what's safe to exercise without
one: static/schema-only routes, and that the app object wires up cleanly.
"""

import pytest
import httpx

from app.main import app, PLATFORMS

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_every_registered_platform_exposes_a_connect_schema():
    # Checked against the classes rather than over HTTP: /api/platforms now
    # needs a session (see tests/test_endpoint_auth.py), and logging in needs
    # a database, which this module deliberately does without.
    keys = {cls.connect_schema()["key"] for cls in PLATFORMS.values()}
    assert keys == set(PLATFORMS.keys())


async def test_platforms_endpoint_needs_a_session(client):
    resp = await client.get("/api/platforms")
    assert resp.status_code == 401


async def test_spa_fallback_serves_html(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_unknown_route_falls_back_to_spa_not_404(client):
    # Client-side routes (e.g. a future deep link) should get the SPA shell,
    # not a raw 404, so the React router can take over.
    resp = await client.get("/some/client/route")
    assert resp.status_code == 200
