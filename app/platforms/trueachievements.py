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

from app import config

log = logging.getLogger(__name__)

# How many achievements to look up per refresh when using the Google Custom
# Search API — bounds quota usage (free tier is 100 queries/day) per call;
# a game with more locked achievements than this just fills in gradually
# over multiple views, since results are cached permanently once found.
GUIDE_SEARCH_MAX_PER_REFRESH = 8

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Upgrade-Insecure-Requests": "1",
}

_GAME_URL_TEMPLATE = {
    "steam": "https://truesteamachievements.com/game/{slug}/achievements",
    "xbox": "https://www.trueachievements.com/game/{slug}/achievements",
}
_BASE_URL = {
    "steam": "https://truesteamachievements.com",
    "xbox": "https://www.trueachievements.com",
}
_SEARCH_DOMAIN = {
    "steam": "truesteamachievements.com",
    "xbox": "trueachievements.com",
}

# A real achievement permalink on either site, e.g.
# https://truesteamachievements.com/a2453/and-theyll-tell-two-friends-achievement
_ACH_PERMALINK_RE = re.compile(
    r"^https://(?:www\.)?(?:truesteamachievements|trueachievements)\.com/a\d+/[a-z0-9-]+-achievement/?$",
    re.IGNORECASE,
)

# An achievement permalink, e.g.
# /a2453/and-theyll-tell-two-friends-achievement
_ACH_LINK_RE = re.compile(
    r'href="(/a\d+/[a-z0-9-]+-achievement)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)

# TSA/TA spell out edition abbreviations that platform store names often
# shorten (e.g. Steam calls it "Borderlands GOTY Enhanced", TSA lists it as
# "Borderlands: Game of the Year Enhanced") — word-boundary substitutions,
# applied before slugifying.
_ABBREVIATION_EXPANSIONS = {
    r"\bGOTY\b": "Game of the Year",
    r"\bGOTYE\b": "Game of the Year Edition",
    r"\bDE\b": "Definitive Edition",
}

# Known-correct slug for a specific (platform, our-own-stored-name) pair,
# for cases the abbreviation expansion above doesn't catch. Add an entry
# here whenever a real mismatch is reported — see app/platforms/
# trueachievements.py's module docstring for why guessing can't be 100%.
_SLUG_OVERRIDES: dict[tuple[str, str], str] = {
    ("steam", "borderlandsgotyenhanced"): "Borderlands-Game-of-the-Year-Enhanced",
    # Xbox's own name for this is just "Guitar Hero III" — missing the
    # "Legends of Rock" subtitle TA's slug includes, which no amount of
    # slug-massaging can recover since the data simply isn't in our stored
    # name at all.
    ("xbox", "guitarheroiii"): "Guitar-Hero-3-Legends-of-Rock",
}


def slugify(name: str) -> str:
    """'Borderlands' -> 'Borderlands'; strips trademark/punctuation, spaces to dashes."""
    expanded = name
    for pattern, replacement in _ABBREVIATION_EXPANSIONS.items():
        expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
    # Strip trademark/copyright symbols *before* NFKD — NFKD's compatibility
    # decomposition expands "™" into the literal letters "TM", which would
    # otherwise survive as visible text instead of being removed.
    stripped = re.sub(r"[™®©'’]", "", expanded)
    normalized = unicodedata.normalize("NFKD", stripped)
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-")
    return normalized


def normalize_name(name: str) -> str:
    """Loose match key for an achievement (or game) name: lowercase, alnum only."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def game_url(platform: str, game_name: str) -> str | None:
    template = _GAME_URL_TEMPLATE.get(platform)
    if not template:
        return None
    override = _SLUG_OVERRIDES.get((platform, normalize_name(game_name)))
    slug = override or slugify(game_name)
    return template.format(slug=slug)


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


def search_api_configured() -> bool:
    return bool(config.GOOGLE_SEARCH_API_KEY and config.GOOGLE_SEARCH_ENGINE_ID)


async def search_achievement_url(platform: str, game_name: str, achievement_name: str) -> str | None:
    """
    Find a specific achievement's real TSA/TA permalink via the Google
    Custom Search JSON API, since their site blocks scraping the page
    directly (see fetch_achievement_links's docstring above) but Google
    already has it indexed. Returns None on any failure, missing config,
    unsupported platform, or if nothing in the results actually looks like
    a real achievement permalink (never trust a result blindly).
    """
    if not search_api_configured():
        return None
    domain = _SEARCH_DOMAIN.get(platform)
    if not domain:
        return None

    query = f'site:{domain} "{game_name}" "{achievement_name}"'
    params = {
        "key": config.GOOGLE_SEARCH_API_KEY,
        "cx": config.GOOGLE_SEARCH_ENGINE_ID,
        "q": query,
        "num": 3,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://www.googleapis.com/customsearch/v1", params=params)
    except httpx.HTTPError as e:
        log.warning("Guide search failed for %r / %r: %s", game_name, achievement_name, e)
        return None

    if resp.status_code != 200:
        log.warning(
            "Guide search HTTP %d for %r / %r: %s", resp.status_code, game_name, achievement_name, resp.text[:300],
        )
        return None

    for item in resp.json().get("items", []):
        link = item.get("link", "")
        if _ACH_PERMALINK_RE.match(link):
            return link
    return None
