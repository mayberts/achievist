import asyncio
import re
import logging
from html.parser import HTMLParser

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
                # "slug" collides for secret/hidden achievements — EA has
                # several distinct ones all literally named "hidden-achievement"
                # in the public API, which silently overwrote each other when
                # used as the dict key. The id-prefixed segment of "endpoint"
                # (e.g. "2840-hidden-achievement") is the actual unique id, and
                # matches what the page scraper's href-derived key uses.
                key = _id_segment(item.get("endpoint")) or item.get("slug")
                icon_path = (item.get("icons") or {}).get("m") or (item.get("icons") or {}).get("s")
                if key:
                    earned[key] = {
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


def _id_segment(path: str | None) -> str | None:
    """
    Last path segment of an achievement URL/endpoint, e.g.
    '/achievement/battlefield-1-origin/108-operations' -> '108-operations'.
    Kept with its numeric id prefix intact (not stripped) — it's the only
    part guaranteed unique, since the human-readable slug/name collides for
    secret achievements (several distinct ones are all literally named
    "hidden-achievement" in EA's public data).
    """
    if not path:
        return None
    seg = path.rstrip("/").rsplit("/", 1)[-1]
    return seg or None


class _AwardsPageParser(HTMLParser):
    """
    Parses an Exophase game achievements/challenges page. Each award is a
    <li class="... [locked] ... award ..." data-master="" data-award-id=""
    data-earned="" data-average="" data-points="">, containing a nested
    <img class="award-image" src="">, a title <a href=".../{id}-{slug}">Name</a>
    inside a div.award-title, and a description <p> inside div.award-description.

    A regex was tried first but EA's tooltip attribute contains *unescaped*
    inner HTML (e.g. data-tippy-content="<strong>Name</strong> <p>desc</p>"),
    which breaks any `[^>]*` character class before it ever reaches the real
    attributes — a real HTML parser sidesteps that entirely.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.awards: list[dict] = []
        self._cur: dict | None = None
        self._div_depth = 0
        self._title_depth: int | None = None
        self._desc_depth: int | None = None
        self._title_buf: list[str] = []
        self._desc_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        classes = (d.get("class") or "").split()

        if tag == "li" and "award" in classes:
            self._cur = {
                "award_id": d.get("data-award-id"),
                "master_id": d.get("data-master"),
                "locked": "locked" in classes,
                "earned_raw": d.get("data-earned"),
                "rarity_pct": d.get("data-average"),
                "points": d.get("data-points"),
                "icon": None,
                "name": None,
                "description": None,
                "slug": None,
            }
            return
        if self._cur is None:
            return

        if tag == "div":
            self._div_depth += 1
            if "award-title" in classes:
                self._title_depth = self._div_depth
            elif "award-description" in classes:
                self._desc_depth = self._div_depth
        elif tag == "img" and "award-image" in classes:
            self._cur["icon"] = d.get("src")
        elif tag == "a" and self._title_depth is not None:
            seg = _id_segment(d.get("href"))
            if seg:
                self._cur["slug"] = seg

    def handle_endtag(self, tag):
        if tag == "div" and self._cur is not None:
            if self._title_depth == self._div_depth:
                self._cur["name"] = "".join(self._title_buf).strip()
                self._title_buf = []
                self._title_depth = None
            if self._desc_depth == self._div_depth:
                self._cur["description"] = "".join(self._desc_buf).strip()
                self._desc_buf = []
                self._desc_depth = None
            self._div_depth -= 1
        elif tag == "li" and self._cur is not None:
            if self._cur.get("slug") and self._cur.get("name"):
                self.awards.append(self._cur)
            self._cur = None
            self._div_depth = 0
            self._title_depth = None
            self._desc_depth = None
            self._title_buf = []
            self._desc_buf = []

    def handle_data(self, data):
        if self._title_depth is not None:
            self._title_buf.append(data)
        if self._desc_depth is not None:
            self._desc_buf.append(data)


async def fetch_game_page_awards(exo_slug: str, page_type: str = "achievements") -> list[dict]:
    """
    Scrape the Exophase game achievements/challenges page for every award
    (locked and unlocked), with name/description/points/rarity_pct/icon —
    much richer than fetch_game_page_icons(), which only recovers icons and
    silently returns nothing at all on pages like EA's (see _AwardsPageParser).
    """
    url = f"https://www.exophase.com/game/{exo_slug}/{page_type}/"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers=_PAGE_HEADERS)
    if resp.status_code != 200:
        log.warning("Exophase game page HTTP %d for %s", resp.status_code, exo_slug)
        return []

    parser = _AwardsPageParser()
    parser.feed(resp.text)
    log.info("Exophase page scrape %s: %d awards", exo_slug, len(parser.awards))
    return parser.awards


def _dedupe_awards(awards: list[dict]) -> list[dict]:
    """
    Some platforms (EA, Ubisoft) list the same underlying achievement twice
    under different numeric ids — e.g. one copy sourced per source platform
    bundled into a single listing — which otherwise shows as literal
    duplicate rows in the UI. The duplicate copies don't always match
    exactly: Ubisoft's differ in capitalization/punctuation ("DIY" vs "Diy",
    "Escape From..." vs "Escape from...", "Amunet's Gift" vs "Amunets Gift")
    and one copy sometimes lacks the description the other has. Group by
    normalized name alone (case/punctuation-insensitive via _to_slug) rather
    than requiring an exact (name, description) match, keeping every
    id-variant's slug under "alt_slugs" so unlock status can still be
    checked against any of them, and preferring whichever copy actually has
    a description.
    """
    merged: dict[str, dict] = {}
    for a in awards:
        if not a.get("slug") or not a.get("name"):
            continue
        key = _to_slug(a["name"])
        if key not in merged:
            m = dict(a)
            m["alt_slugs"] = [a["slug"]]
            merged[key] = m
        else:
            existing = merged[key]
            existing["alt_slugs"].append(a["slug"])
            if not existing.get("description") and a.get("description"):
                existing["description"] = a["description"]
            if not existing.get("icon") and a.get("icon"):
                existing["icon"] = a["icon"]
            if not existing.get("rarity_pct") and a.get("rarity_pct"):
                existing["rarity_pct"] = a["rarity_pct"]
            if not existing.get("points") and a.get("points"):
                existing["points"] = a["points"]
    return list(merged.values())


def _humanize(slug: str) -> str:
    return slug.replace("-", " ").title()


def _to_int(val) -> int | None:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _to_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


async def _dedupe_stored_achievements(conn, platform_game_id: int) -> None:
    """
    Collapse achievement rows for a platform_game that represent the same
    achievement under slightly different text — leftover from before
    _dedupe_awards() existed, so already-synced games would otherwise keep
    their stale duplicates forever (the incremental-sync cache skips
    re-scraping once counts already match, so fixed-forward dedupe logic
    never runs for them). Grouped by normalized name (case/punctuation
    stripped), matching _dedupe_awards()'s key — an exact-text match missed
    Ubisoft's duplicates, which differ in capitalization/punctuation (e.g.
    "DIY" vs "Diy", "Escape From..." vs "Escape from...").
    Keeps whichever duplicate has an unlocked record (if any), else
    whichever has a description, else the lowest id; deletes the rest
    (user_achievements cascade-deletes with them).
    """
    await conn.execute(
        """
        WITH ranked AS (
            SELECT a.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY a.platform_game_id, regexp_replace(lower(a.name), '[^a-z0-9]+', '', 'g')
                       ORDER BY
                           EXISTS (
                               SELECT 1 FROM user_achievements ua
                               WHERE ua.achievement_id = a.id AND ua.unlocked
                           ) DESC,
                           (a.description IS NOT NULL) DESC,
                           a.id ASC
                   ) AS rn
            FROM achievements a
            WHERE a.platform_game_id = %s
        )
        DELETE FROM achievements WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """,
        (platform_game_id,),
    )


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

    linked_id = await db.upsert_linked_account(conn, account["user_id"], platform_key, account["external_id"])
    # Collapse any stray duplicate row left behind by a previous, differently
    # keyed version of this platform (e.g. Ubisoft used to be keyed by the
    # user's real username; this always uses the fixed connect-time id).
    await db.delete_other_accounts_for_platform(conn, account["user_id"], platform_key, account["external_id"])
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

        # One-time cleanup for rows stored before _dedupe_awards() existed —
        # runs unconditionally (cheap, no network) even when the cache below
        # would otherwise skip this game entirely, since a skipped game never
        # reaches the dedupe logic and would keep its stale duplicates forever.
        await _dedupe_stored_achievements(conn, pg_id)

        cached = earned_cache.get(exo_slug)
        if cached and cached["earned"] == g["earned_awards"] and cached["stored"] >= total > 0:
            continue

        await asyncio.sleep(delay)
        awards = _dedupe_awards(await fetch_game_page_awards(exo_slug, g["page_type"] or "achievements"))
        awards_by_slug = {a["slug"]: a for a in awards}
        await asyncio.sleep(delay)
        earned = await fetch_earned(g["master_playerid"], g["master_id"])  # {slug: {timestamp, icon}}

        # Union both slug sets: the page scrape may in principle miss a
        # secret achievement, and vice versa the earned feed's own slug is
        # Exophase's canonical one (should match the page's href-derived
        # slug, but don't assume every achievement shows up in both).
        all_slugs = set(awards_by_slug) | set(earned)
        if not all_slugs:
            continue

        for slug in all_slugs:
            worker._inc("achievements_synced")
            a = awards_by_slug.get(slug) or {}
            # Unlock status must be checked against every id-variant of a
            # deduped achievement (e.g. its Xbox-sourced and PS-sourced
            # copies), not just the canonical slug picked to represent it.
            earned_info = None
            for alt in a.get("alt_slugs") or [slug]:
                cand = earned.get(alt)
                if cand and (earned_info is None or (cand.get("timestamp") or 0) < (earned_info.get("timestamp") or float("inf"))):
                    earned_info = cand
            is_unlocked = earned_info is not None or a.get("locked") is False
            icon = (earned_info or {}).get("icon") or a.get("icon")
            db_ach_id = await db.upsert_achievement(
                conn, pg_id, slug, a.get("name") or _humanize(slug), a.get("description"),
                icon, _to_int(a.get("points")), _to_float(a.get("rarity_pct")),
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
