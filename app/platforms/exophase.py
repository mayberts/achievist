import asyncio
import re
import logging

import httpx

log = logging.getLogger(__name__)

_API = "https://api.exophase.com"
_IMG_BASE = "https://m.exophase.com"
_BASE_HEADERS = {
    "Origin": "https://www.exophase.com",
    "Referer": "https://www.exophase.com/",
    "Accept": "application/json, text/plain, */*",
    "x-requested-with": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
}
_PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": _BASE_HEADERS["User-Agent"],
}

_IMG_TAG = re.compile(r'<img[^>]+class="[^"]*award-image[^"]*"[^>]*>', re.DOTALL)
_TIPPY_NAME = re.compile(r'data-tippy-content=".*?&lt;strong&gt;(.*?)&lt;/strong&gt;', re.DOTALL)
_SRC = re.compile(r'\bsrc="(https://m\.exophase\.com/[^"?]+)')


def _to_slug(name: str) -> str:
    s = name.lower()
    s = s.replace("'", "").replace("’", "")  # strip apostrophes before hyphenating
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


async def fetch_games_list(
    client: httpx.AsyncClient, player_id: str, access_token: str, environment: str = "xbox"
) -> list[dict]:
    """Return all games in the given Exophase environment for the player."""
    all_games: list[dict] = []
    page = 1
    headers = dict(_BASE_HEADERS)
    headers["Cookie"] = f"ACCESS_TOKEN={access_token}"

    while True:
        resp = await client.get(
            f"{_API}/public/player/{player_id}/games",
            params={"page": page, "environment": environment, "sort": 1, "showHidden": 0, "query": ""},
            headers=headers,
        )
        if resp.status_code != 200:
            log.warning("Exophase games list HTTP %d (page %d)", resp.status_code, page)
            break
        data = resp.json()
        batch = data.get("games") or []
        if not batch:
            break
        for g in batch:
            meta = g.get("meta") or {}
            platforms = meta.get("platforms") or []
            is_360 = any(p.get("slug") == "xbox-360" for p in platforms)
            title = meta.get("title", "")
            # Derive the game page slug: {title-slug}-{platform-slug}
            platform_tag = "xbox-360" if is_360 else "xbox-one"
            exo_slug = f"{_to_slug(title)}-{platform_tag}"
            all_games.append({
                "master_id": g["master_id"],
                "master_playerid": g["master_playerid"],
                "title": title,
                "is_360": is_360,
                "exo_slug": exo_slug,
            })
        if len(batch) < 25:
            break
        page += 1
    return all_games


_ENDPOINT_RE = re.compile(r"/game/([^/]+)/(achievements|challenges|trophies)/")


def _slug_and_page_type_from_endpoint(endpoint_awards: str) -> tuple[str | None, str | None]:
    """
    '/game/battlefield-v-deluxe-edition-origin/achievements/#123' -> ('battlefield-v-deluxe-edition-origin', 'achievements')
    '/game/trials-rising-uplay/challenges/#123' -> ('trials-rising-uplay', 'challenges')
    The page path segment (achievements/challenges/trophies) varies by
    environment — Ubisoft's are called "challenges" on Exophase, not
    "achievements" — so it must be read from the real URL, not assumed.
    """
    m = _ENDPOINT_RE.search(endpoint_awards or "")
    if not m:
        return None, None
    return m.group(1), m.group(2)


async def fetch_environment_games(
    client: httpx.AsyncClient, player_id: str, access_token: str, environment: str
) -> list[dict]:
    """
    Return all games in the given Exophase environment for the player, with
    the fields needed for a full sync (not just the Xbox-specific icon
    enrichment that fetch_games_list() was originally built for).
    """
    all_games: list[dict] = []
    page = 1
    headers = dict(_BASE_HEADERS)
    headers["Cookie"] = f"ACCESS_TOKEN={access_token}"

    while True:
        resp = await client.get(
            f"{_API}/public/player/{player_id}/games",
            params={"page": page, "environment": environment, "sort": 1, "showHidden": 0, "query": ""},
            headers=headers,
        )
        if resp.status_code != 200:
            log.warning("Exophase games list HTTP %d (page %d, env %s)", resp.status_code, page, environment)
            break
        data = resp.json()
        batch = data.get("games") or []
        if not batch:
            break
        for g in batch:
            meta = g.get("meta") or {}
            exo_slug, page_type = _slug_and_page_type_from_endpoint(meta.get("endpoint_awards") or "")
            if not exo_slug:
                continue
            all_games.append({
                "master_id": g["master_id"],
                "master_playerid": g["master_playerid"],
                "title": meta.get("title", ""),
                "total_awards": g.get("total_awards") or 0,
                "earned_awards": g.get("earned_awards") or 0,
                "cover": g.get("resource_standard"),
                "exo_slug": exo_slug,
                "page_type": page_type,
            })
        if len(batch) < 25:
            break
        page += 1
    return all_games


async def fetch_earned(master_playerid: int, game_id: int) -> dict[str, dict]:
    """Return {achievement_slug: {"timestamp": int, "icon": str}} for earned achievements."""
    earned: dict[str, dict] = {}
    last = 9999999999999
    seen: set[int] = set()

    async with httpx.AsyncClient(timeout=30, headers=_BASE_HEADERS) as client:
        while True:
            resp = await client.get(
                f"{_API}/public/player/{master_playerid}/game/{game_id}/earned",
                params={"last": last},
            )
            if resp.status_code != 200:
                log.warning("Exophase earned HTTP %d (game %s)", resp.status_code, game_id)
                break
            data = resp.json()
            items = data.get("list") or []
            if not items:
                break

            for item in items:
                slug = item.get("slug")
                icon_path = (item.get("icons") or {}).get("m") or (item.get("icons") or {}).get("s")
                if slug:
                    earned[slug] = {
                        "timestamp": item.get("timestamp"),
                        "icon": f"{_IMG_BASE}{icon_path}" if icon_path else None,
                    }

            timestamps = [item.get("timestamp") for item in items if item.get("timestamp")]
            if not timestamps:
                break
            oldest = min(timestamps)
            if oldest in seen:
                break
            seen.add(oldest)
            if len(items) < 12:
                break
            last = oldest

    return earned


async def fetch_game_page_icons(exo_slug: str, page_type: str = "achievements") -> dict[str, str]:
    """Scrape the Exophase game achievements/challenges page for all icons (earned + locked)."""
    url = f"https://www.exophase.com/game/{exo_slug}/{page_type}/"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers=_PAGE_HEADERS)
    if resp.status_code != 200:
        log.warning("Exophase game page HTTP %d for %s", resp.status_code, exo_slug)
        return {}

    icons: dict[str, str] = {}
    for m in _IMG_TAG.finditer(resp.text):
        tag = m.group(0)
        name_m = _TIPPY_NAME.search(tag)
        src_m = _SRC.search(tag)
        if name_m and src_m:
            icons[_to_slug(name_m.group(1))] = src_m.group(1)

    log.info("Exophase page scrape %s: %d icons", exo_slug, len(icons))
    return icons


def _humanize(slug: str) -> str:
    return slug.replace("-", " ").title()


async def sync_environment(worker, conn, platform_key: str, environment: str, account: dict) -> None:
    """
    Shared sync body for any platform whose real data comes from Exophase's
    public per-player API rather than its own (EA and Ubisoft both landed
    here after their own unofficial APIs proved unreliable/low-value —
    see each platform module's docstring for specifics). `worker` is the
    calling Platform instance, used for its `_inc` progress counter.
    """
    from datetime import datetime
    from app import config, db

    if not config.EXOPHASE_PLAYER_ID or not config.EXOPHASE_ACCESS_TOKEN:
        raise RuntimeError(
            f"EXOPHASE_PLAYER_ID / EXOPHASE_ACCESS_TOKEN not configured — {platform_key} sync "
            "rides on the app's Exophase login, same as Xbox 360 icon enrichment."
        )
    delay = config.REQUEST_DELAY_SECONDS

    linked_id = await db.upsert_linked_account(conn, platform_key, account["external_id"])
    # Collapse any stray duplicate row left behind by a previous, differently
    # keyed version of this platform (e.g. Ubisoft used to be keyed by the
    # user's real username; this always uses the fixed connect-time id).
    await db.delete_other_accounts_for_platform(conn, platform_key, account["external_id"])
    earned_cache = await db.get_earned_counts(conn, linked_id)

    async with httpx.AsyncClient(timeout=30) as client:
        games = await fetch_environment_games(
            client, config.EXOPHASE_PLAYER_ID, config.EXOPHASE_ACCESS_TOKEN, environment,
        )
    log.info("%s (via Exophase): %d games", platform_key, len(games))

    def _parse_ts(ts):
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(int(ts))
        except Exception:
            return None

    for g in games:
        total = g["total_awards"]
        if not total:
            continue
        exo_slug = g["exo_slug"]

        worker._inc("games_seen")
        pg_id = await db.upsert_platform_game(conn, platform_key, exo_slug, g["title"], g["cover"], total)
        await db.upsert_user_game(conn, linked_id, pg_id, 0, g["earned_awards"], total, None)

        cached = earned_cache.get(exo_slug)
        if cached and cached["earned"] == g["earned_awards"] and cached["stored"] >= total > 0:
            continue

        await asyncio.sleep(delay)
        icons = await fetch_game_page_icons(exo_slug, g["page_type"] or "achievements")  # {name_slug: icon_url}
        await asyncio.sleep(delay)
        earned = await fetch_earned(g["master_playerid"], g["master_id"])  # {slug: {timestamp, icon}}

        # Union both slug sets: the page scrape may miss secret/hidden
        # achievements that only appear once earned, and vice versa the
        # earned feed's own slug is Exophase's canonical one (may differ
        # slightly from our re-slugified tooltip name).
        all_slugs = set(icons) | set(earned)
        if not all_slugs:
            continue

        for slug in all_slugs:
            worker._inc("achievements_synced")
            earned_info = earned.get(slug)
            is_unlocked = earned_info is not None
            icon = (earned_info or {}).get("icon") or icons.get(slug)
            db_ach_id = await db.upsert_achievement(
                conn, pg_id, slug, _humanize(slug), None, icon, None, None,
            )
            await db.upsert_user_achievement(
                conn, linked_id, db_ach_id, is_unlocked,
                _parse_ts((earned_info or {}).get("timestamp")),
            )


async def fetch_earned_icons(
    master_playerid: int, game_id: int
) -> dict[str, str]:
    """Return {achievement_slug: icon_url} for all earned achievements in a game."""
    icons: dict[str, str] = {}
    last = 9999999999999
    seen: set[int] = set()

    async with httpx.AsyncClient(timeout=30, headers=_BASE_HEADERS) as client:
        while True:
            resp = await client.get(
                f"{_API}/public/player/{master_playerid}/game/{game_id}/earned",
                params={"last": last},
            )
            if resp.status_code != 200:
                log.warning("Exophase earned HTTP %d (game %s)", resp.status_code, game_id)
                break
            data = resp.json()
            items = data.get("list") or []
            if not items:
                break

            for item in items:
                slug = item.get("slug")
                icon_path = (item.get("icons") or {}).get("m") or (item.get("icons") or {}).get("s")
                if slug and icon_path:
                    icons[slug] = f"{_IMG_BASE}{icon_path}"

            timestamps = [item.get("timestamp") for item in items if item.get("timestamp")]
            if not timestamps:
                break
            oldest = min(timestamps)
            if oldest in seen:
                break
            seen.add(oldest)
            if len(items) < 12:
                break
            last = oldest

    return icons
