import logging
import re

import httpx

from app import config

log = logging.getLogger(__name__)

_BASE = "https://www.steamgriddb.com/api/v2"
_CLEAN_RE = re.compile(r'[®™©]')


def _headers() -> dict | None:
    if not config.SGDB_API_KEY:
        return None
    return {"Authorization": f"Bearer {config.SGDB_API_KEY}"}


async def search_grid(name: str) -> str | None:
    """Return a wide backdrop art URL for the best matching game, or None."""
    headers = _headers()
    if not headers:
        return None
    clean_name = _CLEAN_RE.sub('', name).strip()
    async with httpx.AsyncClient(timeout=15) as client:
        # Search for game
        resp = await client.get(
            f"{_BASE}/search/autocomplete/{clean_name}",
            headers=headers,
        )
        if resp.status_code != 200:
            log.warning("SGDB search failed for '%s': %s", name, resp.text)
            return None
        data = resp.json()
        if not data.get("success") or not data.get("data"):
            return None
        game_id = data["data"][0]["id"]
        return await _best_backdrop(client, headers, game_id)


async def _best_backdrop(client: httpx.AsyncClient, headers: dict, game_id: int) -> str | None:
    """
    Prefer SteamGridDB "Heroes" — wide banner art designed to sit behind a
    client's own overlaid text, so it doesn't come with a logo baked in.
    "Grids" (the old source here) are built for Steam's logo-less grid view,
    so they're usually just the box art/logo itself, which clashes with our
    own title text drawn on top. Fall back to logo-free ("no_logo") grids,
    then any grid, only if no hero art exists.
    """
    resp = await client.get(f"{_BASE}/heroes/game/{game_id}", headers=headers, params={"limit": 5})
    if resp.status_code == 200:
        hero_data = resp.json()
        if hero_data.get("success") and hero_data.get("data"):
            return hero_data["data"][0]["url"]

    for styles in ("no_logo", None):
        for dimensions in ("460x215", "920x430"):
            params = {"dimensions": dimensions, "limit": 5}
            if styles:
                params["styles"] = styles
            resp = await client.get(
                f"{_BASE}/grids/game/{game_id}",
                headers=headers,
                params=params,
            )
            if resp.status_code != 200:
                continue
            grid_data = resp.json()
            if grid_data.get("success") and grid_data.get("data"):
                return grid_data["data"][0]["url"]
    return None
