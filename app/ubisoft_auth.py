"""
Ubisoft Connect authentication via email/password + 2FA (TOTP or email code).

Setup (one-time):
  1. Hit POST /api/ubisoft-setup with {"email": "...", "password": "..."}
  2. If 2FA required, you get a two_factor_ticket back
  3. Hit POST /api/ubisoft-setup/verify with {"ticket": "...", "code": "..."}
  4. Done — rememberMeTicket is saved automatically for future syncs
"""

import json
import logging
import os
from base64 import urlsafe_b64decode
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_BASE = "https://public-ubiservices.ubi.com"
# Ubisoft Connect web-client App ID — the one the browser uses and that the
# public API accepts for session tickets grabbed from localStorage.
_APP_ID = "74e71609-1ddf-47da-9073-71ac3aa8c90c"

# The "club" (achievements/actions) service lives on a separate host + App ID.
CLUB_BASE = "https://msr-public-ubiservices.ubi.com"
CLUB_APP_ID = "86263886-327a-4328-ac69-527f0d20a237"


def club_headers(ticket: str) -> dict:
    """Headers for the msr- club (achievements) service."""
    headers = {**_base_headers(CLUB_APP_ID), "Authorization": f"Ubi_v1 t={ticket}"}
    sid = _sid_from_ticket(ticket)
    if sid:
        headers["Ubi-SessionId"] = sid
    return headers
_TOKEN_FILE = Path("/data/ubisoft_remember_me.txt")
_SESSION_FILE = Path("/data/ubisoft_session.txt")


def _base_headers(app_id: str = _APP_ID) -> dict:
    return {
        "Ubi-AppId": app_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "UbiServices_SDK_2019.Release.27_PC64_ansi_static",
    }


def _sid_from_ticket(ticket: str) -> str:
    """Extract the session id (sid) embedded in a JWE session ticket's header."""
    try:
        header_b64 = ticket.split(".", 1)[0]
        pad = "=" * (-len(header_b64) % 4)
        header = json.loads(urlsafe_b64decode(header_b64 + pad))
        return header.get("sid", "")
    except Exception:
        return ""


def session_headers(ticket: str) -> dict:
    """Build authenticated headers for API calls using a session ticket."""
    headers = {**_base_headers(), "Authorization": f"Ubi_v1 t={ticket}"}
    sid = _sid_from_ticket(ticket)
    if sid:
        headers["Ubi-SessionId"] = sid
    return headers


async def refresh_session(stored: str | None = None) -> tuple[str, str]:
    """
    Return (session_ticket, profile_id) for API calls.

    `stored` may be passed in from an account's saved credentials; if omitted it
    falls back to the token file. The token may be either:
      - a rememberMeTicket (from the setup flow) → renew it with `rm` auth,
        which yields a fresh session ticket + profileId directly
      - a session ticket (JWE grabbed from the browser's localStorage,
        starts with "ewog") → use it directly as `Ubi_v1 t=`; the profileId
        is encrypted inside the JWE so we look it up via the /profiles/me API
    """
    stored = (stored or "").strip() or _load_remember_me()
    if not stored:
        raise RuntimeError("Ubisoft not configured — run the setup flow at /api/ubisoft-setup")

    is_session_ticket = stored.startswith("ewog")

    async with httpx.AsyncClient(timeout=20) as client:
        if not is_session_ticket:
            # rememberMeTicket → renew to get a session ticket + profileId
            headers = {**_base_headers(), "Authorization": f"rm {stored}"}
            resp = await client.post(
                f"{_BASE}/v3/profiles/sessions",
                json={"rememberMe": True},
                headers=headers,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Ubisoft session refresh failed: HTTP {resp.status_code} — {resp.text[:200]}")
            data = resp.json()
            new_rm = data.get("rememberMeTicket", "")
            ticket = data.get("ticket", "")
            if new_rm:
                _save_session(ticket, new_rm)
            return ticket, data.get("profileId", "")

        # Session ticket → use directly; fetch profileId from /v3/profiles/me
        headers = session_headers(stored)
        profile_id = await _lookup_profile_id(client, headers)
        return stored, profile_id


async def _lookup_profile_id(client: httpx.AsyncClient, headers: dict) -> str:
    """Resolve the current account's profileId using a valid session ticket."""
    resp = await client.get(f"{_BASE}/v3/profiles/me", headers=headers)
    if resp.status_code == 200:
        pid = resp.json().get("profileId")
        if pid:
            return pid
    if resp.status_code == 401:
        raise RuntimeError(
            "Ubisoft session ticket expired or invalid (401). Grab a fresh ticket from "
            "connect.ubisoft.com → DevTools → Local storage and re-save it."
        )
    raise RuntimeError(f"Could not resolve Ubisoft profileId: HTTP {resp.status_code} — {resp.text[:200]}")


async def save_service_ticket(ticket: str) -> str:
    """
    Validate a browser session ticket and store it as the backend service
    credential. Returns the service account's profileId. Raises if invalid.
    """
    ticket = (ticket or "").strip()
    if not ticket:
        raise RuntimeError("No session ticket provided.")
    # refresh_session validates the ticket (calls /profiles/me for session tickets)
    validated, profile_id = await refresh_session(ticket)
    _save_session(validated, ticket)
    return profile_id


async def service_ticket_valid() -> bool:
    """Live check: is the stored service ticket present and still usable?"""
    try:
        await get_service_ticket()
        return True
    except Exception:
        return False


async def get_service_ticket() -> str:
    """
    Get a live session ticket for the app's backend Ubisoft service account.
    Uses the stored rememberMeTicket (from the one-time email/password login)
    and refreshes it. Raises if the service account isn't configured.
    """
    ticket, _ = await refresh_session()
    if not ticket:
        raise RuntimeError(
            "Ubisoft service account not signed in. Complete the one-time login at "
            "/api/ubisoft-setup (email + password, then 2FA) so the app can look up "
            "public profiles by username."
        )
    return ticket


async def resolve_username(client: httpx.AsyncClient, headers: dict, username: str) -> str:
    """
    Resolve a Ubisoft username to its profileId via the public profiles lookup.
    The target profile must be public for this to succeed.
    """
    resp = await client.get(
        f"{_BASE}/v3/profiles",
        params={"nameOnPlatform": username, "platformType": "uplay"},
        headers=headers,
    )
    if resp.status_code == 401:
        raise RuntimeError("Ubisoft service session expired (401). Re-run /api/ubisoft-setup.")
    if resp.status_code != 200:
        raise RuntimeError(f"Ubisoft username lookup failed: HTTP {resp.status_code} — {resp.text[:200]}")
    profiles = resp.json().get("profiles") or []
    if not profiles:
        raise RuntimeError(f"No Ubisoft profile found for username '{username}' (is it spelled correctly?)")
    pid = profiles[0].get("profileId")
    if not pid:
        raise RuntimeError(f"Ubisoft profile for '{username}' has no profileId")
    return pid


def service_configured() -> bool:
    """
    True if a durable backend service login exists — i.e. a rememberMeTicket
    from the email/password flow. A leftover browser session ticket ("ewog…")
    is short-lived and doesn't count, so the UI still prompts for a real login.
    """
    tok = _load_remember_me()
    return bool(tok) and not tok.startswith("ewog")


def load_remember_me() -> str | None:
    return _load_remember_me()


def _load_remember_me() -> str | None:
    try:
        return _TOKEN_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


def _save_session(ticket: str, remember_me: str) -> None:
    try:
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        if remember_me:
            _TOKEN_FILE.write_text(remember_me)
        if ticket:
            _SESSION_FILE.write_text(ticket)
    except Exception as e:
        log.warning("Could not persist Ubisoft tokens: %s", e)
