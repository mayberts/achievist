"""
PlayStation Network authentication via an `npsso` token.

Setup (one-time):
  1. Log into https://www.playstation.com in a browser.
  2. Visit https://ca.account.sony.com/api/v1/ssocookie — it returns
     {"npsso": "<64-char token>"}.
  3. POST that token to /api/psn-service-ticket. It's exchanged for an
     access/refresh token pair; the refresh token is stored and reused
     (refreshed automatically) so npsso itself is only needed once.
"""

import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# Well-known public PSN "PlayStation App" OAuth client, used by the PSN API
# community (psn-api, PSNAWP) — not a per-user secret.
_CLIENT_ID = "09515159-7237-4370-9b40-3806e67c0891"
_CLIENT_SECRET = "ur18Wd9kup1a3AoZgTM6dqAtVo3T7RiHo6D9Zwg"
_REDIRECT_URI = "com.scee.psxandroid.scecompcall://redirect"

_AUTH_URL = "https://ca.account.sony.com/api/authz/v3/oauth/authorize"
_TOKEN_URL = "https://ca.account.sony.com/api/authz/v3/oauth/token"

_TOKEN_FILE = Path("/data/psn_refresh_token.txt")


async def exchange_npsso(npsso: str) -> None:
    """Validate an npsso token and store the resulting refresh token."""
    npsso = (npsso or "").strip()
    if not npsso:
        raise RuntimeError("No npsso token provided.")

    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        resp = await client.get(
            _AUTH_URL,
            params={
                "access_type": "offline",
                "client_id": _CLIENT_ID,
                "response_type": "code",
                "scope": "psn:mobile.v2.core psn:clientapp",
                "redirect_uri": _REDIRECT_URI,
            },
            cookies={"npsso": npsso},
        )
        if resp.status_code not in (302, 303):
            raise RuntimeError(
                f"npsso token rejected (HTTP {resp.status_code}). It may be expired — "
                "get a fresh one from ca.account.sony.com/api/v1/ssocookie while logged in."
            )
        location = resp.headers.get("location", "")
        code = _extract_query_param(location, "code")
        if not code:
            raise RuntimeError("PlayStation login did not return an authorization code.")

        token_resp = await client.post(
            _TOKEN_URL,
            data={
                "code": code,
                "redirect_uri": _REDIRECT_URI,
                "grant_type": "authorization_code",
                "token_format": "jwt",
            },
            auth=(_CLIENT_ID, _CLIENT_SECRET),
        )
        if token_resp.status_code != 200:
            raise RuntimeError(f"PlayStation token exchange failed: HTTP {token_resp.status_code} — {token_resp.text[:200]}")
        data = token_resp.json()

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("PlayStation login succeeded but no refresh_token was returned.")
    _save_refresh_token(refresh_token)


def _extract_query_param(url: str, key: str) -> str | None:
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(url).query)
    vals = qs.get(key)
    return vals[0] if vals else None


async def get_access_token() -> str:
    """Refresh the stored PSN refresh token and return a live access token."""
    refresh_token = _load_refresh_token()
    if not refresh_token:
        raise RuntimeError(
            "PlayStation not signed in. Paste an npsso token in the Accounts tab to connect."
        )
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "psn:mobile.v2.core psn:clientapp",
                "token_format": "jwt",
            },
            auth=(_CLIENT_ID, _CLIENT_SECRET),
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"PlayStation session expired (HTTP {resp.status_code}). Paste a fresh npsso token in the Accounts tab."
        )
    data = resp.json()
    new_refresh = data.get("refresh_token")
    if new_refresh:
        _save_refresh_token(new_refresh)
    return data["access_token"]


async def service_ticket_valid() -> bool:
    try:
        await get_access_token()
        return True
    except Exception:
        return False


def auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _load_refresh_token() -> str | None:
    try:
        return _TOKEN_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


def _save_refresh_token(token: str) -> None:
    try:
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(token)
    except Exception as e:
        log.warning("Could not persist PSN refresh token: %s", e)
