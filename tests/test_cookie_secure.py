"""
The Secure flag on the session cookie.

Without it the browser will send the session over plain http — including on a
link an attacker downgrades — which for an https deployment throws away most
of what TLS was protecting.

The tricky part is auto-detection. uvicorn runs without --proxy-headers, so
behind a TLS-terminating proxy the app only ever sees http on the socket:
trusting request.url.scheme alone would leave Secure off on precisely the
deployments that need it. X-Forwarded-Proto is what actually carries the
answer, and these pin that down.
"""

import httpx
import pytest

from app import auth, config, db
from app.main import app
from tests.conftest import requires_db


@pytest.fixture
def restore_setting():
    original = config.COOKIE_SECURE
    yield
    config.COOKIE_SECURE = original


class _Req:
    """Just enough of a Request for the helper: headers and a URL scheme."""

    def __init__(self, headers=None, scheme="http"):
        self.headers = headers or {}
        self.url = type("U", (), {"scheme": scheme})()


def test_forwarded_proto_wins_over_the_socket_scheme(restore_setting):
    config.COOKIE_SECURE = "auto"
    # The case that matters: TLS terminated at the proxy, http on the socket.
    assert auth.cookie_secure(_Req({"x-forwarded-proto": "https"}, scheme="http")) is True


def test_plain_http_with_no_proxy_stays_insecure(restore_setting):
    config.COOKIE_SECURE = "auto"
    assert auth.cookie_secure(_Req(scheme="http")) is False


def test_direct_https_with_no_proxy_header(restore_setting):
    config.COOKIE_SECURE = "auto"
    assert auth.cookie_secure(_Req(scheme="https")) is True


def test_a_chain_of_proxies_uses_the_scheme_the_browser_spoke(restore_setting):
    config.COOKIE_SECURE = "auto"
    # Proxies append, so the first entry is the original client's scheme.
    assert auth.cookie_secure(_Req({"x-forwarded-proto": "https, http"})) is True
    assert auth.cookie_secure(_Req({"x-forwarded-proto": "http, https"})) is False


def test_explicit_settings_override_detection(restore_setting):
    config.COOKIE_SECURE = "true"
    assert auth.cookie_secure(_Req(scheme="http")) is True
    config.COOKIE_SECURE = "false"
    assert auth.cookie_secure(_Req({"x-forwarded-proto": "https"})) is False


@requires_db
async def test_login_over_a_forwarded_https_request_sets_secure(db_conn, restore_setting):
    config.COOKIE_SECURE = "auto"
    await db.create_user(db_conn, "dad", auth.hash_password("correctpassword1"), is_admin=True)
    await db_conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/auth/login",
            json={"username": "dad", "password": "correctpassword1"},
            headers={"x-forwarded-proto": "https"},
        )
        assert r.status_code == 200
        assert "secure" in r.headers["set-cookie"].lower()


@requires_db
async def test_login_over_plain_http_does_not_set_secure(db_conn, restore_setting):
    """A LAN deployment on http must keep working: a Secure cookie there is
    accepted by the browser and then never sent back, which reads as being
    logged out immediately."""
    config.COOKIE_SECURE = "auto"
    await db.create_user(db_conn, "dad", auth.hash_password("correctpassword1"), is_admin=True)
    await db_conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/login", json={"username": "dad", "password": "correctpassword1"})
        assert r.status_code == 200
        assert "secure" not in r.headers["set-cookie"].lower()
        # still a real session cookie, just without the flag
        assert auth.SESSION_COOKIE in r.headers["set-cookie"]
