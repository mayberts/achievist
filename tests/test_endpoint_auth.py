"""
Every API endpoint must be behind a login.

This is a whole-surface check rather than a handful of spot tests on purpose.
The hole it closes was not one careless endpoint: /api/sgdb-refresh,
/api/hltb-refresh, /api/igdb-refresh and a row of debug routes had no auth
dependency at all, so anyone who could reach the server could wipe every
cover in the install. Endpoints get added often; a test that enumerates the
router catches the next one, and a test of three named routes does not.
"""

import httpx
import pytest
from fastapi.routing import APIRoute

from app import auth, db
from app.main import app, require_admin, require_user
from tests.conftest import requires_db

# The only routes that may be reached without a session, and why. Anything
# else needs require_user or require_admin. Think hard before adding to this.
PUBLIC = {
    "/api/auth/status",  # the SPA asks this to decide whether to show login
    "/api/auth/setup",   # first-run: creates the admin, self-disables after
    "/api/auth/login",
    "/api/auth/logout",
    "/{full_path:path}",  # the SPA itself; the API it calls is still gated
}


def _auth_dep(route: APIRoute) -> str | None:
    """Which auth dependency guards this route, if any."""
    seen, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call in (require_admin,):
            return "admin"
        if dep.call in (require_user,):
            seen.add("user")
        stack.extend(dep.dependencies)
    return "user" if seen else None


def test_no_endpoint_is_reachable_without_a_session():
    unguarded = sorted(
        f"{sorted(r.methods)[0]} {r.path}"
        for r in app.routes
        if isinstance(r, APIRoute) and r.path not in PUBLIC and _auth_dep(r) is None
    )
    assert not unguarded, "endpoints with no auth dependency:\n  " + "\n  ".join(unguarded)


def test_install_wide_jobs_are_admin_only():
    """These rewrite rows in every account's library — the cover job says in
    its own UI copy that it overwrites manually chosen art."""
    want_admin = {
        "/api/sgdb-refresh",
        "/api/hltb-refresh",
        "/api/igdb-refresh",
        "/api/exophase-refresh",
        "/api/exophase-import-icons",
        "/api/xbox-dedup-games",
    }
    by_path = {r.path: _auth_dep(r) for r in app.routes if isinstance(r, APIRoute)}
    for path in want_admin:
        assert path in by_path, f"{path} no longer exists — update this test"
        assert by_path[path] == "admin", f"{path} is guarded by {by_path[path]}, not admin"


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@requires_db
async def test_cover_refresh_rejects_anonymous_and_non_admin(db_conn, client):
    resp = await client.post("/api/sgdb-refresh?force=true")
    assert resp.status_code == 401

    await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await db_conn.commit()
    await client.post("/api/auth/login", json={"username": "kid", "password": "kidpassword1"})

    resp = await client.post("/api/sgdb-refresh?force=true")
    assert resp.status_code == 403


@requires_db
async def test_export_stays_open_to_every_signed_in_user(db_conn, client):
    """It moved out of the admin-only Maintenance page and into the profile
    modal; it must not have picked up an admin gate on the way."""
    await db.create_user(db_conn, "kid", auth.hash_password("kidpassword1"), is_admin=False)
    await db_conn.commit()
    await client.post("/api/auth/login", json={"username": "kid", "password": "kidpassword1"})

    resp = await client.get("/api/export")
    assert resp.status_code == 200
    assert resp.json()["username"] == "kid"
