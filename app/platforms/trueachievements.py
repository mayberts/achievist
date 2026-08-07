"""
Best-effort scraper for per-achievement links on TrueSteamAchievements
(Steam) and TrueAchievements (Xbox) — same company, same URL/markup scheme.
Neither site has a documented public API, so this parses their game
achievement-list page instead, the same approach already used for Exophase
icons in app/platforms/exophase.py.

This is inherently fragile: if their HTML changes, matching just silently
returns fewer (or no) links rather than erroring — callers should treat an
empty/partial result as "not available yet", not a hard failure.
"""

import logging
import re
import unicodedata

import httpx

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

_GAME_URL_TEMPLATE = {
    "steam": "https://truesteamachievements.com/game/{slug}/achievements",
    "xbox": "https://www.trueachievements.com/game/{slug}/achievements",
}
_BASE_URL = {
    "steam": "https://truesteamachievements.com",
    "xbox": "https://www.trueachievements.com",
}

# An achievement permalink, e.g.
# /a2453/and-theyll-tell-two-friends-achievement
_ACH_LINK_RE = re.compile(
    r'href="(/a\d+/[a-z0-9-]+-achievement)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)


def slugify(name: str) -> str:
    """'Borderlands' -> 'Borderlands'; strips trademark/punctuation, spaces to dashes."""
    # Strip trademark/copyright symbols *before* NFKD — NFKD's compatibility
    # decomposition expands "™" into the literal letters "TM", which would
    # otherwise survive as visible text instead of being removed.
    stripped = re.sub(r"[™®©'’]", "", name)
    normalized = unicodedata.normalize("NFKD", stripped)
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-")
    return normalized


def normalize_name(name: str) -> str:
    """Loose match key for an achievement name: lowercase, alnum only."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def game_url(platform: str, game_name: str) -> str | None:
    template = _GAME_URL_TEMPLATE.get(platform)
    if not template:
        return None
    return template.format(slug=slugify(game_name))


async def fetch_achievement_links(platform: str, game_name: str) -> dict[str, str]:
    """Return {normalized_achievement_name: full_url} scraped from the game's page."""
    url = game_url(platform, game_name)
    if not url:
        return {}

    try:
        async with httpx.AsyncClient(timeout=20, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        log.warning("TrueAchievements fetch failed for %r: %s", game_name, e)
        return {}

    if resp.status_code != 200:
        log.warning("TrueAchievements HTTP %d for %r (%s)", resp.status_code, game_name, url)
        return {}

    base = _BASE_URL[platform]
    links: dict[str, str] = {}
    for m in _ACH_LINK_RE.finditer(resp.text):
        href, display_name = m.group(1), m.group(2)
        key = normalize_name(display_name)
        if key and key not in links:
            links[key] = base + href

    log.info("TrueAchievements scrape %r: %d links found", game_name, len(links))
    return links
